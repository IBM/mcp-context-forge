# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_mcp_servers_router.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the MCP Servers router.

Tests cover:
    - POST /v1/mcp-servers/test: success, SSRF blocked, no permission, bad UUID
    - _validated_team_id: valid UUID, None, and invalid UUID
"""

# Standard
import socket
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.routers.mcp_servers_router import _validated_team_id, check_mcp_server_connectivity, check_mcp_server_handshake
from mcpgateway.schemas import GatewayHandshakeRequest, GatewayHandshakeResponse, GatewayTestRequest, GatewayTestResponse

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def rbac_bypass():
    """Bypass RBAC decorators for unit tests."""
    originals = patch_rbac_decorators()
    yield
    restore_rbac_decorators(originals)


@pytest.fixture
def db_session() -> MagicMock:
    """Mock database session."""
    return MagicMock()


@pytest.fixture
def user_ctx(db_session: MagicMock) -> dict[str, Any]:
    """Authenticated admin user context."""
    return {
        "email": "admin@example.com",
        "full_name": "Admin User",
        "is_admin": True,
        "token_teams": None,
        "db": db_session,
        "permissions": ["gateways.read"],
    }


@pytest.fixture
def gateway_test_request() -> GatewayTestRequest:
    """A valid GatewayTestRequest pointing at a public test host."""
    return GatewayTestRequest(
        base_url="http://example.com",
        path="/api/test",
        method="GET",
        headers={},
        body=None,
    )


@pytest.fixture
def configure_allowlist(monkeypatch):
    """Configure gateway test allowlist to allow *.example.com and mock DNS."""
    from mcpgateway import config

    monkeypatch.setattr(config.settings, "gateway_test_allow_registered_only", False)
    monkeypatch.setattr(config.settings, "gateway_test_allowed_hosts", ["example.com", "*.example.com"])

    def mock_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port or 80))]

    monkeypatch.setattr("mcpgateway.common.validators.socket.getaddrinfo", mock_getaddrinfo)


# ---------------------------------------------------------------------------
# Tests: POST /test — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_test_endpoint_success(gateway_test_request, user_ctx, db_session):
    """Valid URL with allowed host returns GatewayTestResponse."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.get_structured_logger", return_value=MagicMock(log=MagicMock())):
            result = await check_mcp_server_connectivity(
                request=gateway_test_request,
                team_id=None,
                user=user_ctx,
                db=db_session,
            )

    assert isinstance(result, GatewayTestResponse)
    assert result.status_code == 200
    assert result.body == {"ok": True}
    assert result.latency_ms >= 0


# ---------------------------------------------------------------------------
# Tests: POST /test — SSRF blocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_endpoint_ssrf_blocked(user_ctx, db_session, monkeypatch):
    """URL pointing at a private IP or unlisted host returns 400."""
    from mcpgateway import config

    # No allowed hosts and SSRF protection enabled
    monkeypatch.setattr(config.settings, "gateway_test_allow_registered_only", False)
    monkeypatch.setattr(config.settings, "gateway_test_allowed_hosts", [])

    db_session.execute.return_value.scalars.return_value.all.return_value = []

    request = GatewayTestRequest(
        base_url="http://internal.private.host",
        path="/secret",
        method="GET",
        headers={},
        body=None,
    )

    result = await check_mcp_server_connectivity(
        request=request,
        team_id=None,
        user=user_ctx,
        db=db_session,
    )

    assert result.status_code == 400
    assert "error" in result.body


# ---------------------------------------------------------------------------
# Tests: POST /test — HTTP error (502)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_test_endpoint_request_error_returns_502(gateway_test_request, user_ctx, db_session):
    """httpx.RequestError during connection is returned as 502."""
    import httpx

    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.get_structured_logger", return_value=MagicMock(log=MagicMock())):
            result = await check_mcp_server_connectivity(
                request=gateway_test_request,
                team_id=None,
                user=user_ctx,
                db=db_session,
            )

    assert result.status_code == 502
    assert "error" in result.body


# ---------------------------------------------------------------------------
# Tests: _validated_team_id helper
# ---------------------------------------------------------------------------


def test_validated_team_id_none_returns_none():
    """None input returns None."""
    assert _validated_team_id(None) is None


def test_validated_team_id_valid_uuid_returns_hex():
    """Valid UUID is normalised to hex string."""
    import uuid

    raw = str(uuid.uuid4())
    result = _validated_team_id(raw)
    # hex form has no hyphens
    assert result is not None
    assert "-" not in result
    assert len(result) == 32


def test_validated_team_id_invalid_uuid_raises_400():
    """Non-UUID string raises HTTP 400."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _validated_team_id("not-a-valid-uuid-at-all")

    assert exc_info.value.status_code == 400
    assert "Invalid team ID" in exc_info.value.detail


def test_validated_team_id_empty_string_returns_none():
    """Empty string means "no filter" — matches admin _normalize_team_id."""
    assert _validated_team_id("") is None


# ---------------------------------------------------------------------------
# Tests: POST /test — non-JSON response body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_test_endpoint_non_json_response_returns_string_body(gateway_test_request, user_ctx, db_session):
    """Gateway returning non-JSON text → body is plain string, not dict."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("not json")
    mock_response.text = "plain text response"

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.get_structured_logger", return_value=MagicMock(log=MagicMock())):
            result = await check_mcp_server_connectivity(
                request=gateway_test_request,
                team_id=None,
                user=user_ctx,
                db=db_session,
            )

    assert result.status_code == 200
    assert result.body == {"details": "plain text response"}


# ---------------------------------------------------------------------------
# Tests: POST /test — non-200 status code pass-through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_test_endpoint_non_200_status_passes_through(user_ctx, db_session):
    """Gateway 404 → response carries status_code 404, not raised as exception."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    request = GatewayTestRequest(
        base_url="http://example.com",
        path="/missing",
        method="GET",
        headers={},
        body=None,
    )

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.json.return_value = {"error": "not found"}

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.get_structured_logger", return_value=MagicMock(log=MagicMock())):
            result = await check_mcp_server_connectivity(
                request=request,
                team_id=None,
                user=user_ctx,
                db=db_session,
            )

    assert result.status_code == 404
    assert result.body == {"error": "not found"}


# ---------------------------------------------------------------------------
# Tests: POST /test — gateway_test_allow_registered_only mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_endpoint_registered_only_allows_registered_host(user_ctx, db_session, monkeypatch):
    """registered_only=True: URL whose host is in registered DB gateways is allowed."""
    from mcpgateway import config

    monkeypatch.setattr(config.settings, "gateway_test_allow_registered_only", True)

    # DB returns the registered gateway URL matching the request host
    db_session.execute.return_value.scalars.return_value.all.return_value = ["http://example.com"]
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    def mock_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port or 80))]

    monkeypatch.setattr("mcpgateway.common.validators.socket.getaddrinfo", mock_getaddrinfo)

    request = GatewayTestRequest(
        base_url="http://example.com",
        path="/test",
        method="GET",
        headers={},
        body=None,
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.get_structured_logger", return_value=MagicMock(log=MagicMock())):
            result = await check_mcp_server_connectivity(
                request=request,
                team_id=None,
                user=user_ctx,
                db=db_session,
            )

    assert result.status_code == 200


@pytest.mark.asyncio
async def test_test_endpoint_registered_only_blocks_unregistered_host(user_ctx, db_session, monkeypatch):
    """registered_only=True: URL not in registered gateways returns 400."""
    from mcpgateway import config

    monkeypatch.setattr(config.settings, "gateway_test_allow_registered_only", True)
    # No registered gateways → empty allowlist
    db_session.execute.return_value.scalars.return_value.all.return_value = []

    request = GatewayTestRequest(
        base_url="http://internal.private.host",
        path="/secret",
        method="GET",
        headers={},
        body=None,
    )

    result = await check_mcp_server_connectivity(
        request=request,
        team_id=None,
        user=user_ctx,
        db=db_session,
    )

    assert result.status_code == 400
    assert "error" in result.body


# ---------------------------------------------------------------------------
# Tests: POST /test — POST method with body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_test_endpoint_post_method_with_body(user_ctx, db_session):
    """POST request with JSON body is forwarded and 201 response returned."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    request = GatewayTestRequest(
        base_url="http://example.com",
        path="/api/create",
        method="POST",
        headers={"X-Custom-Header": "value"},
        body={"key": "value"},
    )

    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"id": "abc123"}

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.get_structured_logger", return_value=MagicMock(log=MagicMock())):
            result = await check_mcp_server_connectivity(
                request=request,
                team_id=None,
                user=user_ctx,
                db=db_session,
            )

    assert result.status_code == 201
    assert result.body == {"id": "abc123"}
    # verify the upstream HTTP call used POST
    call_kwargs = mock_client.request.call_args
    assert call_kwargs.kwargs.get("method", "").upper() == "POST" or (call_kwargs.args and call_kwargs.args[0].upper() == "POST")


# ---------------------------------------------------------------------------
# Tests: POST /test — timeout error → 502
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_test_endpoint_timeout_returns_502(gateway_test_request, user_ctx, db_session):
    """httpx.TimeoutException during connection → 502 with error body."""
    import httpx

    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("request timed out"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.get_structured_logger", return_value=MagicMock(log=MagicMock())):
            result = await check_mcp_server_connectivity(
                request=gateway_test_request,
                team_id=None,
                user=user_ctx,
                db=db_session,
            )

    assert result.status_code == 502
    assert "error" in result.body


# ---------------------------------------------------------------------------
# Tests: Deny-path — 401 unauthenticated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401(gateway_test_request, db_session):
    """Request without authenticated user context raises 401."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await check_mcp_server_connectivity(
            request=gateway_test_request,
            team_id=None,
            user=None,
            db=db_session,
        )

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Tests: Deny-path — 403 insufficient permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insufficient_permission_returns_403(gateway_test_request, user_ctx, db_session):
    """User without gateways.read permission is denied with 403."""
    from fastapi import HTTPException

    with patch("mcpgateway.middleware.rbac.PermissionService") as mock_ps_class:
        mock_ps = MagicMock()
        mock_ps.check_permission = AsyncMock(return_value=False)
        mock_ps_class.return_value = mock_ps

        with pytest.raises(HTTPException) as exc_info:
            await check_mcp_server_connectivity(
                request=gateway_test_request,
                team_id=None,
                user=user_ctx,
                db=db_session,
            )

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Tests: Deny-path — 403 cross-team team_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_team_team_id_returns_403(gateway_test_request, db_session):
    """Non-admin user supplying a team_id outside their authorized teams raises 403."""
    import uuid
    from fastapi import HTTPException

    authorized_team = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa").hex
    foreign_team = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb").hex

    non_admin_user = {
        "email": "user@example.com",
        "full_name": "Regular User",
        "is_admin": False,
        "token_teams": [authorized_team],
        "db": db_session,
    }

    with pytest.raises(HTTPException) as exc_info:
        await check_mcp_server_connectivity(
            request=gateway_test_request,
            team_id=foreign_team,
            user=non_admin_user,
            db=db_session,
        )

    assert exc_info.value.status_code == 403
    assert "team" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_admin_bypass_cross_team_team_id_allowed(gateway_test_request, db_session, monkeypatch):
    """Admin user (token_teams=None) can supply any team_id without 403."""
    import uuid
    from mcpgateway import config

    monkeypatch.setattr(config.settings, "gateway_test_allow_registered_only", False)
    monkeypatch.setattr(config.settings, "gateway_test_allowed_hosts", ["example.com", "*.example.com"])

    def mock_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port or 80))]

    monkeypatch.setattr("mcpgateway.common.validators.socket.getaddrinfo", mock_getaddrinfo)

    foreign_team = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb").hex

    admin_user = {
        "email": "admin@example.com",
        "full_name": "Admin User",
        "is_admin": True,
        "token_teams": None,  # None = admin bypass
        "db": db_session,
    }

    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.get_structured_logger", return_value=MagicMock(log=MagicMock())):
            result = await check_mcp_server_connectivity(
                request=gateway_test_request,
                team_id=foreign_team,
                user=admin_user,
                db=db_session,
            )

    assert result.status_code == 200


# ---------------------------------------------------------------------------
# Tests: POST /test-handshake
# ---------------------------------------------------------------------------


@pytest.fixture
def handshake_request() -> GatewayHandshakeRequest:
    """A valid GatewayHandshakeRequest pointing at a public test host."""
    return GatewayHandshakeRequest(base_url="http://example.com", path="/mcp", headers={})


def _mock_resilient_client(*responses):
    """Build a mock ResilientHttpClient whose request() returns the given responses in order."""
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=list(responses))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


def _json_response(status_code: int, payload):
    """Build a mock httpx.Response with a JSON body."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


@pytest.mark.asyncio
async def test_handshake_allowlist_rejection(user_ctx, db_session, monkeypatch):
    """URL rejected by the test policy returns a generic transport failure with no outbound call."""
    from mcpgateway import config

    monkeypatch.setattr(config.settings, "gateway_test_allow_registered_only", False)
    monkeypatch.setattr(config.settings, "gateway_test_allowed_hosts", [])

    request = GatewayHandshakeRequest(base_url="http://internal.private.host", path="/mcp")

    mock_client = _mock_resilient_client()
    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=request, team_id=None, user=user_ctx, db=db_session)

    assert isinstance(result, GatewayHandshakeResponse)
    assert result.success is False
    assert result.failure_class == "transport"
    assert "not allowed" in result.error
    mock_client.request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_discover_success(handshake_request, user_ctx, db_session):
    """server/discover 200 with a JSON-RPC result yields the server_discover negotiation path."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    discover = _json_response(200, {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "srv", "version": "1.0"}, "capabilities": {"tools": {}}}})
    tools_list = _json_response(200, {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{}, {}, {}]}})
    mock_client = _mock_resilient_client(discover, tools_list)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.negotiation_path == "server_discover"
    assert result.protocol_version == "2026-07-28"
    assert result.server_name == "srv"
    assert result.server_version == "1.0"
    assert result.component_counts == {"tools": 3}
    assert result.counts_partial is False
    assert result.credential_source == "none"


def _mock_sdk_session(init_side_effect=None):
    """Build mocked streamablehttp_client / ClientSession context managers."""
    init_result = MagicMock()
    init_result.protocolVersion = "2025-11-25"
    init_result.serverInfo.name = "legacy-srv"
    init_result.serverInfo.version = "2.0"
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
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_discover_fallback_to_initialize(handshake_request, user_ctx, db_session):
    """A JSON-RPC -32601 from server/discover falls back to the SDK initialize path."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    discover = _json_response(200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}})
    mock_client = _mock_resilient_client(discover)
    transport_cm, session = _mock_sdk_session()

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.negotiation_path == "initialize"
    assert result.protocol_version == "2025-11-25"
    assert result.server_name == "legacy-srv"
    assert result.component_counts == {"tools": 2}


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_discover_401_is_auth_failure(handshake_request, user_ctx, db_session):
    """HTTP 401 from server/discover short-circuits as an auth failure with no initialize attempt."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_client = _mock_resilient_client(_json_response(401, {"error": "unauthorized"}))

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client") as mock_streamable:
            result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is False
    assert result.failure_class == "auth"
    mock_streamable.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_connect_error_is_transport_failure(handshake_request, user_ctx, db_session):
    """httpx.ConnectError during server/discover is a transport failure."""
    import httpx

    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is False
    assert result.failure_class == "transport"
    assert "Could not reach the MCP server" in result.error


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_initialize_garbage_is_invalid_response(handshake_request, user_ctx, db_session):
    """A decode error during initialize classifies as invalid_response."""
    import json as stdlib_json

    db_session.execute.return_value.scalars.return_value.first.return_value = None

    discover = _json_response(404, {"error": "not found"})
    mock_client = _mock_resilient_client(discover)
    transport_cm, session = _mock_sdk_session(init_side_effect=stdlib_json.JSONDecodeError("Expecting value", "doc", 0))

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is False
    assert result.failure_class == "invalid_response"
    assert "not valid MCP" in result.error


@pytest.mark.asyncio
async def test_handshake_unauthenticated_request_returns_401(handshake_request, db_session):
    """Request without authenticated user context raises 401."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await check_mcp_server_handshake(request=handshake_request, team_id=None, user=None, db=db_session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_handshake_insufficient_permission_returns_403(handshake_request, user_ctx, db_session):
    """User without gateways.read permission is denied with 403."""
    from fastapi import HTTPException

    with patch("mcpgateway.middleware.rbac.PermissionService") as mock_ps_class:
        mock_ps = MagicMock()
        mock_ps.check_permission = AsyncMock(return_value=False)
        mock_ps_class.return_value = mock_ps

        with pytest.raises(HTTPException) as exc_info:
            await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_handshake_cross_team_team_id_returns_403(handshake_request, db_session):
    """Non-admin user supplying a team_id outside their authorized teams raises 403."""
    import uuid
    from fastapi import HTTPException

    authorized_team = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa").hex
    foreign_team = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb").hex

    non_admin_user = {
        "email": "user@example.com",
        "full_name": "Regular User",
        "is_admin": False,
        "token_teams": [authorized_team],
        "db": db_session,
    }

    with pytest.raises(HTTPException) as exc_info:
        await check_mcp_server_handshake(request=handshake_request, team_id=foreign_team, user=non_admin_user, db=db_session)

    assert exc_info.value.status_code == 403
    assert "team" in exc_info.value.detail.lower()
