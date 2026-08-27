# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_server_handshake.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for gateway_service.test_server_handshake (issue #6370).

Unlike test_gateway_handshake, the target is the virtual server's own
/servers/{id}/mcp transport rather than a caller-supplied URL, so there is no
SSRF allowlist to clear: these tests focus on the disabled-server short
circuit, credential-source resolution (session/form/none), the in-process
ASGI dispatch, and failure classification passthrough.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import GatewayHandshakeResponse, ServerHandshakeRequest
from mcpgateway.services.gateway_service import test_server_handshake as run_server_handshake


def _mock_sdk_session(init_side_effect=None):
    """Build mocked streamablehttp_client / ClientSession context managers.

    Args:
        init_side_effect: Optional exception (or exception instance) for
            ``session.initialize()`` to raise instead of succeeding.

    Returns:
        Tuple of (transport context manager, session) mocks.
    """
    init_result = MagicMock()
    init_result.protocolVersion = "2025-11-25"
    init_result.serverInfo.name = "smoke-test-server"
    init_result.serverInfo.version = "1.0"
    init_result.capabilities.tools = MagicMock()
    init_result.capabilities.resources = None
    init_result.capabilities.prompts = None
    init_result.capabilities.model_dump.return_value = {"tools": {}}
    init_result.model_dump.return_value = {"protocolVersion": "2025-11-25"}

    tools_result = MagicMock()
    tools_result.tools = [MagicMock(), MagicMock()]
    tools_result.nextCursor = None

    session = MagicMock()
    session.initialize = AsyncMock(side_effect=init_side_effect, return_value=init_result) if init_side_effect else AsyncMock(return_value=init_result)
    session.list_tools = AsyncMock(return_value=tools_result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    transport_cm = MagicMock()
    transport_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    transport_cm.__aexit__ = AsyncMock(return_value=None)

    return transport_cm, session


@pytest.mark.asyncio
async def test_disabled_server_fails_without_attempting_a_handshake():
    """A disabled virtual server returns a graceful failure with no outbound dispatch."""
    with patch("mcpgateway.services.gateway_service.streamablehttp_client") as mock_streamable:
        result = await run_server_handshake("srv-1", "my-server", False, ServerHandshakeRequest(), {})

    assert isinstance(result, GatewayHandshakeResponse)
    assert result.success is False
    assert result.failure_class == "transport"
    assert "disabled" in result.error
    mock_streamable.assert_not_called()


@pytest.mark.asyncio
async def test_successful_handshake_reuses_forwarded_session_credentials():
    """A successful initialize round-trip reports credential_source='session' when only forwarded headers are present."""
    transport_cm, session = _mock_sdk_session()

    with patch("mcpgateway.main.app", MagicMock()):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm) as mock_streamable:
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await run_server_handshake("srv-1", "my-server", True, ServerHandshakeRequest(), {"Authorization": "Bearer caller-token"})

    assert result.success is True
    assert result.negotiation_path == "initialize"
    assert result.protocol_version == "2025-11-25"
    assert result.server_name == "smoke-test-server"
    assert result.component_counts == {"tools": 2}
    assert result.credential_source == "session"

    # Target is derived from the server ID via a loopback URL, never from caller input.
    called_url = mock_streamable.call_args.kwargs["url"]
    assert called_url.endswith("/servers/srv-1/mcp")
    called_headers = mock_streamable.call_args.kwargs["headers"]
    assert called_headers["Authorization"] == "Bearer caller-token"


@pytest.mark.asyncio
async def test_no_credentials_reports_none_source():
    """No forwarded headers and no body override reports credential_source='none'."""
    transport_cm, session = _mock_sdk_session()

    with patch("mcpgateway.main.app", MagicMock()):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await run_server_handshake("srv-1", "my-server", True, ServerHandshakeRequest(), {})

    assert result.success is True
    assert result.credential_source == "none"


@pytest.mark.asyncio
async def test_body_header_override_wins_over_forwarded_credentials():
    """An explicit header override in the request body replaces the forwarded Authorization and reports credential_source='form'."""
    transport_cm, session = _mock_sdk_session()

    with patch("mcpgateway.main.app", MagicMock()):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm) as mock_streamable:
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await run_server_handshake(
                    "srv-1",
                    "my-server",
                    True,
                    ServerHandshakeRequest(headers={"Authorization": "Bearer override-token"}),
                    {"Authorization": "Bearer caller-token"},
                )

    assert result.success is True
    assert result.credential_source == "form"
    called_headers = mock_streamable.call_args.kwargs["headers"]
    assert called_headers["Authorization"] == "Bearer override-token"


@pytest.mark.asyncio
async def test_body_header_override_ignores_host():
    """A caller-supplied Host in the body override is stripped, matching the gateway-handshake rule."""
    transport_cm, session = _mock_sdk_session()

    with patch("mcpgateway.main.app", MagicMock()):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm) as mock_streamable:
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                await run_server_handshake(
                    "srv-1",
                    "my-server",
                    True,
                    ServerHandshakeRequest(headers={"Host": "evil.example.com"}),
                    {},
                )

    called_headers = mock_streamable.call_args.kwargs["headers"]
    assert "Host" not in called_headers
    assert "host" not in {k.lower() for k in called_headers}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forbidden_header",
    [
        "X-Authenticated-User",  # default settings.proxy_user_header -- trusted-proxy identity spoofing
        "X-Forwarded-For",
        "X-Forwarded-Host",
        "X-Real-IP",
        "X-ContextForge-Internal",
        "Mcp-Session-Id",
        "Connection",
        "Transfer-Encoding",
    ],
)
async def test_body_header_override_drops_forbidden_headers(forbidden_header):
    """A caller-supplied proxy-identity/client-IP/session/hop-by-hop header in the body override never
    reaches the in-process probe -- only 'Authorization' is honored from arbitrary body JSON (CWE-287/CWE-807).
    """
    transport_cm, session = _mock_sdk_session()

    with patch("mcpgateway.main.app", MagicMock()):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm) as mock_streamable:
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await run_server_handshake(
                    "srv-1",
                    "my-server",
                    True,
                    ServerHandshakeRequest(headers={forbidden_header: "spoofed-value", "Authorization": "Bearer caller-own-token"}),
                    {},
                )

    called_headers = mock_streamable.call_args.kwargs["headers"]
    assert forbidden_header.lower() not in {k.lower() for k in called_headers}
    assert called_headers["Authorization"] == "Bearer caller-own-token"
    assert result.credential_source == "form"


@pytest.mark.asyncio
async def test_forwarded_proxy_identity_header_is_not_overridable_by_body():
    """Even when the caller's own forwarded credentials legitimately carry the trusted-proxy identity
    header (TRUST_PROXY_AUTH_DANGEROUSLY), a body override cannot replace it with a different identity --
    the override key is dropped, not merged in, so the session-derived value stands.
    """
    transport_cm, session = _mock_sdk_session()

    with patch("mcpgateway.main.app", MagicMock()):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm) as mock_streamable:
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await run_server_handshake(
                    "srv-1",
                    "my-server",
                    True,
                    ServerHandshakeRequest(headers={"X-Authenticated-User": "victim@example.com"}),
                    {"X-Authenticated-User": "caller@example.com"},
                )

    called_headers = {k.lower(): v for k, v in mock_streamable.call_args.kwargs["headers"].items()}
    assert called_headers.get("x-authenticated-user") == "caller@example.com"
    assert result.credential_source == "session"


@pytest.mark.asyncio
async def test_body_header_override_honors_custom_auth_header_name(monkeypatch):
    """When AUTH_HEADER_NAME is customized, a body override under that configured header name is
    honored (not just the literal 'Authorization'), matching the nested request's own auth extraction.
    """
    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "auth_header_name", "X-MCP-Gateway-Auth")

    transport_cm, session = _mock_sdk_session()

    with patch("mcpgateway.main.app", MagicMock()):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm) as mock_streamable:
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await run_server_handshake(
                    "srv-1",
                    "my-server",
                    True,
                    ServerHandshakeRequest(headers={"X-MCP-Gateway-Auth": "Bearer custom-header-token"}),
                    {},
                )

    called_headers = {k.lower(): v for k, v in mock_streamable.call_args.kwargs["headers"].items()}
    assert called_headers.get("x-mcp-gateway-auth") == "Bearer custom-header-token"
    assert result.credential_source == "form"


@pytest.mark.asyncio
async def test_body_header_override_still_drops_spoofed_headers_with_custom_auth_header_name(monkeypatch):
    """Customizing AUTH_HEADER_NAME widens the allowlist by exactly one entry -- proxy-identity and
    other spoofed headers in a body override remain dropped.
    """
    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "auth_header_name", "X-MCP-Gateway-Auth")

    transport_cm, session = _mock_sdk_session()

    with patch("mcpgateway.main.app", MagicMock()):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm) as mock_streamable:
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                await run_server_handshake(
                    "srv-1",
                    "my-server",
                    True,
                    ServerHandshakeRequest(headers={"X-MCP-Gateway-Auth": "Bearer custom-header-token", "X-Authenticated-User": "spoofed@example.com"}),
                    {},
                )

    called_headers = {k.lower(): v for k, v in mock_streamable.call_args.kwargs["headers"].items()}
    assert called_headers.get("x-mcp-gateway-auth") == "Bearer custom-header-token"
    assert "x-authenticated-user" not in called_headers


@pytest.mark.asyncio
async def test_connect_error_is_classified_as_transport_failure():
    """A connection error from the in-process transport is classified the same way as a real gateway handshake."""
    # Third-Party
    import httpx

    with patch("mcpgateway.main.app", MagicMock()):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", side_effect=httpx.ConnectError("boom")):
            result = await run_server_handshake("srv-1", "my-server", True, ServerHandshakeRequest(), {})

    assert result.success is False
    assert result.failure_class == "transport"


@pytest.mark.asyncio
async def test_initialize_timeout_is_transport_failure():
    """A TimeoutError from the SDK session re-raises past the inner handler and is caught as a transport failure."""
    # First-Party
    from mcpgateway.services.gateway_service import _HANDSHAKE_TRANSPORT_COPY

    transport_cm, session = _mock_sdk_session(init_side_effect=TimeoutError())

    with patch("mcpgateway.main.app", MagicMock()):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await run_server_handshake("srv-1", "my-server", True, ServerHandshakeRequest(), {})

    assert result.success is False
    assert result.failure_class == "transport"
    assert result.error == _HANDSHAKE_TRANSPORT_COPY


@pytest.mark.asyncio
async def test_exception_group_unwraps_root_cause():
    """A grouped initialize failure is classified from its root cause and keeps the detail suffix."""
    # Third-Party
    import httpx

    # First-Party
    from mcpgateway.services.gateway_service import _HANDSHAKE_TRANSPORT_COPY

    transport_cm, session = _mock_sdk_session(init_side_effect=ExceptionGroup("handshake failed", [httpx.ConnectError("connection refused")]))

    with patch("mcpgateway.main.app", MagicMock()):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await run_server_handshake("srv-1", "my-server", True, ServerHandshakeRequest(), {})

    assert result.success is False
    assert result.failure_class == "transport"
    assert result.error == f"{_HANDSHAKE_TRANSPORT_COPY}: connection refused"


@pytest.mark.asyncio
async def test_httpx_client_factory_builds_asgi_transport_client():
    """The httpx_client_factory passed to the SDK builds a client wired to the ASGI transport."""
    # Third-Party
    import httpx

    transport_cm, session = _mock_sdk_session()
    fake_app = MagicMock()

    with patch("mcpgateway.main.app", fake_app):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm) as mock_streamable:
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                await run_server_handshake("srv-1", "my-server", True, ServerHandshakeRequest(), {})

    factory = mock_streamable.call_args.kwargs["httpx_client_factory"]
    client = factory()
    try:
        assert isinstance(client, httpx.AsyncClient)
        assert isinstance(client._transport, httpx.ASGITransport)
    finally:
        await client.aclose()
