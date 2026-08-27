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
import ssl
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import Base, Gateway as DbGateway
from mcpgateway.routers.mcp_servers_router import _validated_team_id, check_mcp_server_connectivity, check_mcp_server_handshake
from mcpgateway.schemas import GatewayHandshakeRequest, GatewayHandshakeResponse, GatewayTestRequest, GatewayTestResponse
from mcpgateway.services.gateway_service import (
    _classify_handshake_error,
    _gateway_test_visibility_filters,
    _HANDSHAKE_AUTH_COPY,
    _HANDSHAKE_INVALID_COPY,
    _HANDSHAKE_PROTOCOL_COPY,
    _HANDSHAKE_TRANSPORT_COPY,
    _SniPinningTransport,
)

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


def _outbound_header(mock_client: AsyncMock, header_name: str) -> str:
    """Return one case-insensitive outbound request header value."""
    sent_headers = mock_client.request.call_args.kwargs["headers"]
    matching_headers = [value for key, value in sent_headers.items() if key.lower() == header_name.lower()]
    assert len(matching_headers) == 1
    return matching_headers[0]


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


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
@pytest.mark.parametrize(
    ("method", "headers", "expected_accept"),
    [
        ("GET", None, "text/event-stream"),
        ("POST", None, "application/json, text/event-stream"),
        ("GET", {"accept": "application/custom"}, "application/custom"),
    ],
    ids=["get-default", "post-default", "caller-override"],
)
async def test_test_endpoint_uses_mcp_safe_accept_header(method, headers, expected_accept, user_ctx, db_session):
    """Connectivity checks default Accept for MCP while preserving caller overrides."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None
    request = GatewayTestRequest(base_url="http://example.com", path="/mcp", method=method, headers=headers, body={"jsonrpc": "2.0"} if method == "POST" else None)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.get_structured_logger", return_value=MagicMock(log=MagicMock())):
            result = await check_mcp_server_connectivity(request=request, team_id=None, user=user_ctx, db=db_session)

    assert result.status_code == 200
    assert _outbound_header(mock_client, "Accept") == expected_accept


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

    tools_list = _json_response(200, {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{}, {}, {}]}})
    mock_client = _mock_resilient_client(_discover_success(capabilities={"tools": {}}), tools_list)

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
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm) as mock_streamable:
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.negotiation_path == "initialize"
    assert result.protocol_version == "2025-11-25"
    assert result.server_name == "legacy-srv"
    assert result.component_counts == {"tools": 2}
    # The SDK keeps the validated hostname; _SniPinningTransport dials the pinned address.
    assert mock_streamable.call_args.kwargs["url"] == "http://example.com/mcp"

    with patch("mcpgateway.services.gateway_service._SniPinningTransport", wraps=_SniPinningTransport) as mock_transport:
        factory_client = mock_streamable.call_args.kwargs["httpx_client_factory"]()
        await factory_client.aclose()

    assert mock_transport.call_args.kwargs["sni_hostname"] == "example.com"
    assert mock_transport.call_args.kwargs["pinned_host"] == "8.8.8.8"


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


# ---------------------------------------------------------------------------
# Tests: handshake failure classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("root_cause", "expected"),
    [
        (httpx.HTTPStatusError("unauthorized", request=MagicMock(), response=MagicMock(status_code=401)), ("auth", _HANDSHAKE_AUTH_COPY)),
        (httpx.HTTPStatusError("forbidden", request=MagicMock(), response=MagicMock(status_code=403)), ("auth", _HANDSHAKE_AUTH_COPY)),
        (httpx.HTTPStatusError("teapot", request=MagicMock(), response=MagicMock(status_code=418)), ("invalid_response", _HANDSHAKE_INVALID_COPY)),
        (httpx.ConnectError("connection refused"), ("transport", _HANDSHAKE_TRANSPORT_COPY)),
        (httpx.ReadError("stream closed"), ("transport", _HANDSHAKE_TRANSPORT_COPY)),
        (httpx.PoolTimeout("no free connection"), ("transport", _HANDSHAKE_TRANSPORT_COPY)),
        (httpx.RemoteProtocolError("peer closed connection"), ("transport", _HANDSHAKE_TRANSPORT_COPY)),
        (OSError("network unreachable"), ("transport", _HANDSHAKE_TRANSPORT_COPY)),
        (McpError(ErrorData(code=-32000, message="server error")), ("protocol", _HANDSHAKE_PROTOCOL_COPY)),
        (RuntimeError("protocol version mismatch"), ("protocol", _HANDSHAKE_PROTOCOL_COPY)),
        (RuntimeError("something else"), ("invalid_response", _HANDSHAKE_INVALID_COPY)),
        (ValueError("junk"), ("invalid_response", _HANDSHAKE_INVALID_COPY)),
    ],
)
def test_classify_handshake_error_classification(root_cause, expected):
    """Each handshake root cause maps to its failure class and actionable copy."""
    assert _classify_handshake_error(root_cause) == expected


# ---------------------------------------------------------------------------
# Tests: handshake credential resolution
# ---------------------------------------------------------------------------


def _mock_gateway(**attributes):
    """Build a registered-gateway row stand-in for credential-resolution tests."""
    gateway = MagicMock()
    gateway.id = "gateway-1"
    gateway.name = "Test Server"
    gateway.auth_type = None
    gateway.auth_value = None
    gateway.oauth_config = None
    gateway.ca_certificate = None
    for key, value in attributes.items():
        setattr(gateway, key, value)
    return gateway


def _discover_success(capabilities=None):
    """Build a spec-shaped server/discover response, optionally advertising capabilities."""
    result = {
        "resultType": "complete",
        "supportedVersions": ["2026-07-28"],
        "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "srv", "version": "1.0"}},
    }
    if capabilities is not None:
        result["capabilities"] = capabilities
    return _json_response(200, {"jsonrpc": "2.0", "id": 1, "result": result})


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_gateway_lookup_error_degrades_to_no_credentials(handshake_request, user_ctx, db_session):
    """A failing registered-gateway lookup probes unauthenticated instead of failing the handshake."""
    db_session.execute.side_effect = Exception("db down")

    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.credential_source == "none"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_team_scoped_lookup_filters_by_team(handshake_request, db_session):
    """A supplied team_id narrows the registered-gateway credential lookup to that team."""
    import uuid

    team_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb").hex
    admin_user = {"email": "admin@example.com", "full_name": "Admin User", "is_admin": True, "token_teams": None, "db": db_session}
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=team_id, user=admin_user, db=db_session)

    assert result.success is True
    assert "team_id" in str(db_session.execute.call_args[0][0])


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_stored_authcode_without_token_is_auth_failure(handshake_request, user_ctx, db_session):
    """An authorization_code gateway with no stored user token asks the caller to authorize first."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(auth_type="oauth", oauth_config={"grant_type": "authorization_code"})

    mock_client = _mock_resilient_client()
    token_storage = MagicMock()
    token_storage.get_user_token = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.token_storage_service.TokenStorageService", return_value=token_storage):
            result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is False
    assert result.failure_class == "auth"
    assert "Please authorize Test Server" in result.error
    mock_client.request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_stored_authcode_token_sets_bearer_header(handshake_request, user_ctx, db_session):
    """A stored authorization_code token is sent as a bearer header and reported as a stored credential."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(auth_type="oauth", oauth_config={"grant_type": "authorization_code"})

    mock_client = _mock_resilient_client(_discover_success())
    token_storage = MagicMock()
    token_storage.get_user_token = AsyncMock(return_value="stored-token")

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.token_storage_service.TokenStorageService", return_value=token_storage):
            result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.credential_source == "stored"
    assert mock_client.request.call_args.kwargs["headers"]["Authorization"] == "Bearer stored-token"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_stored_client_credentials_token_used(handshake_request, user_ctx, db_session):
    """A client_credentials gateway mints a token through OAuthManager and sends it."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(auth_type="oauth", oauth_config={"grant_type": "client_credentials"})

    mock_client = _mock_resilient_client(_discover_success())
    oauth_manager = MagicMock()
    oauth_manager.get_access_token = AsyncMock(return_value="minted-token")

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.OAuthManager", return_value=oauth_manager):
            result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.credential_source == "stored"
    assert mock_client.request.call_args.kwargs["headers"]["Authorization"] == "Bearer minted-token"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_stored_token_retrieval_failure_is_auth(handshake_request, user_ctx, db_session):
    """A token-minting failure surfaces as an auth failure naming the server, with no outbound probe."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(auth_type="oauth", oauth_config={"grant_type": "client_credentials"})

    mock_client = _mock_resilient_client()
    oauth_manager = MagicMock()
    oauth_manager.get_access_token = AsyncMock(side_effect=Exception("token endpoint down"))

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.OAuthManager", return_value=oauth_manager):
            result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is False
    assert result.failure_class == "auth"
    assert result.error.startswith("Token retrieval failed for MCP server 'Test Server'")
    mock_client.request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_stored_basic_auth_dict_is_sent(handshake_request, user_ctx, db_session):
    """A stored basic-auth header dict is forwarded verbatim on the probe."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(auth_type="basic", auth_value={"Authorization": "Basic abc"})

    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.credential_source == "stored"
    assert mock_client.request.call_args.kwargs["headers"]["Authorization"] == "Basic abc"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_stored_basic_auth_string_is_decoded(handshake_request, user_ctx, db_session):
    """An encoded stored auth value is decoded into headers before the probe."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(auth_type="bearer", auth_value="encoded-value")

    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.decode_auth", return_value={"Authorization": "Bearer decoded"}) as mock_decode:
            result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    mock_decode.assert_called_once_with("encoded-value")
    assert result.credential_source == "stored"
    assert mock_client.request.call_args.kwargs["headers"]["Authorization"] == "Bearer decoded"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_form_headers_win_over_stored(user_ctx, db_session):
    """Headers supplied on the request override stored credentials and are reported as form-sourced."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(auth_type="basic", auth_value={"Authorization": "Basic stored"})

    request = GatewayHandshakeRequest(base_url="http://example.com", path="/mcp", headers={"Authorization": "Bearer typed"})
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=request, team_id=None, user=user_ctx, db=db_session)

    assert result.credential_source == "form"
    assert mock_client.request.call_args.kwargs["headers"]["Authorization"] == "Bearer typed"


# ---------------------------------------------------------------------------
# Tests: handshake negotiation fallbacks and transports
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_discover_non_json_falls_back_to_initialize(handshake_request, user_ctx, db_session):
    """A 200 server/discover response that is not JSON falls back to the SDK initialize path."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    discover = MagicMock()
    discover.status_code = 200
    discover.json.side_effect = ValueError("not json")
    mock_client = _mock_resilient_client(discover)
    transport_cm, session = _mock_sdk_session()

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.negotiation_path == "initialize"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_discover_list_failure_keeps_success(handshake_request, user_ctx, db_session):
    """A failing component listing on the discover path still reports a successful handshake."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_client = _mock_resilient_client(_discover_success(capabilities={"tools": {}}), httpx.ReadError("stream closed"))

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.negotiation_path == "server_discover"
    assert result.component_counts is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_initialize_list_failure_keeps_success(handshake_request, user_ctx, db_session):
    """A failing component listing on the initialize path still reports a successful handshake."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_client = _mock_resilient_client(_json_response(404, {"error": "not found"}))
    transport_cm, session = _mock_sdk_session()
    session.list_tools = AsyncMock(side_effect=Exception("list failed"))

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.negotiation_path == "initialize"
    assert result.component_counts is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_sse_gateway_uses_sse_client(handshake_request, user_ctx, db_session):
    """A registered SSE gateway negotiates over the SSE transport with a TLS-verifying client factory."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(transport="sse")

    mock_client = _mock_resilient_client(_json_response(404, {"error": "not found"}))
    _unused_cm, session = _mock_sdk_session()
    sse_cm = MagicMock()
    sse_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
    sse_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.sse_client", return_value=sse_cm) as mock_sse:
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.negotiation_path == "initialize"
    mock_sse.assert_called_once()
    # The SDK must see the validated hostname: it rejects an endpoint event whose origin
    # differs from the URL it connected to. Pinning happens in the transport instead.
    assert mock_sse.call_args.kwargs["url"] == "http://example.com/mcp"

    factory = mock_sse.call_args.kwargs["httpx_client_factory"]
    with patch("mcpgateway.services.gateway_service._SniPinningTransport", wraps=_SniPinningTransport) as mock_transport:
        factory_client = factory()
        try:
            assert isinstance(factory_client, httpx.AsyncClient)
            assert factory_client.follow_redirects is False
        finally:
            await factory_client.aclose()

    assert mock_transport.call_args.kwargs["sni_hostname"] == "example.com"
    assert mock_transport.call_args.kwargs["pinned_host"] == "8.8.8.8"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_initialize_timeout_is_transport(handshake_request, user_ctx, db_session):
    """An initialize timeout reports the generic transport copy without exception detail."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_client = _mock_resilient_client(_json_response(404, {"error": "not found"}))
    transport_cm, session = _mock_sdk_session(init_side_effect=TimeoutError())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is False
    assert result.failure_class == "transport"
    assert result.error == _HANDSHAKE_TRANSPORT_COPY


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_exception_group_unwraps_root_cause(handshake_request, user_ctx, db_session):
    """A grouped initialize failure is classified from its root cause and keeps the detail suffix."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_client = _mock_resilient_client(_json_response(404, {"error": "not found"}))
    transport_cm, session = _mock_sdk_session(init_side_effect=ExceptionGroup("handshake failed", [httpx.ConnectError("connection refused")]))

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is False
    assert result.failure_class == "transport"
    assert result.error == f"{_HANDSHAKE_TRANSPORT_COPY}: connection refused"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_discover_paginated_counts_are_partial(handshake_request, user_ctx, db_session):
    """A paginated component listing on the discover path flags the counts as partial."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    tools_page = _json_response(200, {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{}, {}], "nextCursor": "page-2"}})
    mock_client = _mock_resilient_client(_discover_success(capabilities={"tools": {}}), tools_page)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.component_counts == {"tools": 2}
    assert result.counts_partial is True


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_initialize_paginated_counts_are_partial(handshake_request, user_ctx, db_session):
    """A paginated component listing on the initialize path flags the counts as partial."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_client = _mock_resilient_client(_json_response(404, {"error": "not found"}))
    transport_cm, session = _mock_sdk_session()
    tools_result = MagicMock()
    tools_result.tools = [MagicMock()]
    tools_result.nextCursor = "page-2"
    session.list_tools = AsyncMock(return_value=tools_result)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.component_counts == {"tools": 1}
    assert result.counts_partial is True


# ---------------------------------------------------------------------------
# Tests: handshake credential-source accuracy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_non_credential_form_header_keeps_stored_source(user_ctx, db_session):
    """A form header carrying no credential leaves the stored credential and its reported source intact."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(auth_type="basic", auth_value={"Authorization": "Basic stored"})

    request = GatewayHandshakeRequest(base_url="http://example.com", path="/mcp", headers={"X-Trace-Id": "abc"})
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=request, team_id=None, user=user_ctx, db=db_session)

    assert result.credential_source == "stored"
    sent_headers = mock_client.request.call_args.kwargs["headers"]
    assert sent_headers["Authorization"] == "Basic stored"
    assert sent_headers["X-Trace-Id"] == "abc"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_non_credential_form_header_without_gateway_stays_none(user_ctx, db_session):
    """A form header carrying no credential does not claim a credential when nothing is stored."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    request = GatewayHandshakeRequest(base_url="http://example.com", path="/mcp", headers={"X-Trace-Id": "abc"})
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=request, team_id=None, user=user_ctx, db=db_session)

    assert result.credential_source == "none"
    assert mock_client.request.call_args.kwargs["headers"]["X-Trace-Id"] == "abc"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_form_header_replaces_stored_header_of_different_case(user_ctx, db_session):
    """A form header overriding a stored credential header replaces it outright and is reported as form-sourced."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(auth_type="authheaders", auth_value={"X-API-Key": "stored-key"})  # pragma: allowlist secret

    request = GatewayHandshakeRequest(base_url="http://example.com", path="/mcp", headers={"x-api-key": "typed-key"})  # pragma: allowlist secret
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=request, team_id=None, user=user_ctx, db=db_session)

    assert result.credential_source == "form"
    sent_headers = mock_client.request.call_args.kwargs["headers"]
    assert sent_headers["x-api-key"] == "typed-key"
    assert "X-API-Key" not in sent_headers


# ---------------------------------------------------------------------------
# Tests: handshake Layer-1 team scoping
# ---------------------------------------------------------------------------


def _mock_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """Resolve every hostname to a public address so URL validation stays deterministic."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port or 80))]


@pytest.fixture
def team_b_gateway_db():
    """Build in-memory sessions holding one enabled team-B gateway with stored basic auth."""
    engines = []
    sessions = []

    def _build(visibility="team", owner_email="owner@example.com", url="http://example.com"):
        engine = create_engine("sqlite:///:memory:")
        session_factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
        Base.metadata.create_all(bind=engine)
        engines.append(engine)
        with session_factory() as setup_session:
            setup_session.add(
                DbGateway(
                    id="gw-team-b",
                    name="Team B Server",
                    slug="team-b-server",
                    url=url,
                    transport="STREAMABLEHTTP",
                    capabilities={},
                    enabled=True,
                    auth_type="basic",
                    auth_value={"Authorization": "Basic teamb"},
                    visibility=visibility,
                    team_id="team-b",
                    owner_email=owner_email,
                )
            )
            setup_session.commit()
        session = session_factory()
        sessions.append(session)
        return session

    yield _build

    for session in sessions:
        session.close()
    for engine in engines:
        engine.dispose()


@pytest.fixture
def narrowed_user() -> dict[str, Any]:
    """Non-admin user context narrowed to team-a only."""
    return {
        "email": "user@example.com",
        "full_name": "Narrowed User",
        "is_admin": False,
        "token_teams": ["team-a"],
        "permissions": ["gateways.read"],
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_narrowed_token_cannot_borrow_other_teams_credentials(handshake_request, narrowed_user, team_b_gateway_db):
    """A token scoped to team-a probes without team-b's stored credentials even when no team_id is supplied."""
    db = team_b_gateway_db()
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=narrowed_user, db=db)

    assert result.success is True
    assert result.credential_source == "none"
    assert "Authorization" not in mock_client.request.call_args.kwargs["headers"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_token_scoped_to_owning_team_uses_stored_credentials(handshake_request, team_b_gateway_db):
    """A token scoped to the owning team still resolves that team's stored credentials."""
    db = team_b_gateway_db()
    team_b_user = {"email": "user@example.com", "is_admin": False, "token_teams": ["team-b"], "permissions": ["gateways.read"]}
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=team_b_user, db=db)

    assert result.success is True
    assert result.credential_source == "stored"
    assert mock_client.request.call_args.kwargs["headers"]["Authorization"] == "Basic teamb"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_admin_token_uses_stored_credentials_across_teams(handshake_request, user_ctx, team_b_gateway_db, monkeypatch):
    """An admin recognised by the platform keeps visibility over team-scoped gateways."""
    from mcpgateway import config

    monkeypatch.setattr(config.settings, "platform_admin_email", "admin@example.com")
    db = team_b_gateway_db()
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db)

    assert result.success is True
    assert result.credential_source == "stored"
    assert mock_client.request.call_args.kwargs["headers"]["Authorization"] == "Basic teamb"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_admin_bypass_excludes_other_users_private_gateways(handshake_request, user_ctx, team_b_gateway_db, monkeypatch):
    """Admin bypass covers public and team rows but never another user's private gateway."""
    from mcpgateway import config

    monkeypatch.setattr(config.settings, "platform_admin_email", "admin@example.com")
    db = team_b_gateway_db(visibility="private", owner_email="someone-else@example.com")
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db)

    assert result.success is True
    assert result.credential_source == "none"
    assert "Authorization" not in mock_client.request.call_args.kwargs["headers"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_context_without_token_scope_is_not_treated_as_admin(handshake_request, team_b_gateway_db):
    """A non-admin context carrying no token_teams key gets public-only scope, not an admin bypass."""
    db = team_b_gateway_db()
    unscoped_user = {"email": "anonymous", "is_admin": False, "permissions": ["gateways.read"]}
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=unscoped_user, db=db)

    assert result.success is True
    assert result.credential_source == "none"
    assert "Authorization" not in mock_client.request.call_args.kwargs["headers"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_public_only_token_sees_no_private_gateway(handshake_request, team_b_gateway_db):
    """A public-only token (token_teams == []) gets no private row, not even its own."""
    db = team_b_gateway_db(visibility="private", owner_email="user@example.com")
    public_only_user = {"email": "user@example.com", "is_admin": False, "token_teams": [], "permissions": ["gateways.read"]}
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=public_only_user, db=db)

    assert result.success is True
    assert result.credential_source == "none"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_owner_reaches_own_private_gateway(handshake_request, narrowed_user, team_b_gateway_db):
    """A team-scoped token still resolves credentials for a private gateway it owns."""
    db = team_b_gateway_db(visibility="private", owner_email="user@example.com")
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=narrowed_user, db=db)

    assert result.success is True
    assert result.credential_source == "stored"
    assert mock_client.request.call_args.kwargs["headers"]["Authorization"] == "Basic teamb"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_connectivity_narrowed_token_does_not_forward_other_teams_credentials(narrowed_user, team_b_gateway_db):
    """POST /test applies the same Layer-1 scope, so team-b's stored header is not forwarded."""
    db = team_b_gateway_db()
    request = GatewayTestRequest(base_url="http://example.com", path="/mcp", method="GET", headers={}, body=None)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.get_structured_logger", return_value=MagicMock(log=MagicMock())):
            result = await check_mcp_server_connectivity(request=request, team_id=None, user=narrowed_user, db=db)

    assert result.status_code == 200
    assert "Authorization" not in mock_client.request.call_args.kwargs["headers"]


@pytest.mark.asyncio
async def test_handshake_registered_only_allowlist_excludes_other_teams_gateways(handshake_request, narrowed_user, team_b_gateway_db, monkeypatch):
    """registered_only=True: a team-b gateway is invisible to a team-a token, so its host is not probeable."""
    from mcpgateway import config

    monkeypatch.setattr(config.settings, "gateway_test_allow_registered_only", True)
    monkeypatch.setattr("mcpgateway.common.validators.socket.getaddrinfo", _mock_getaddrinfo)

    db = team_b_gateway_db()
    # A response is queued so a regression reports the explicit assertions below, not a drained-mock error.
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=narrowed_user, db=db)

    assert result.success is False
    assert result.failure_class == "transport"
    assert "not allowed" in result.error
    mock_client.request.assert_not_called()


@pytest.mark.asyncio
async def test_handshake_registered_only_allowlist_keeps_public_gateways_probeable(handshake_request, narrowed_user, team_b_gateway_db, monkeypatch):
    """registered_only=True: a public gateway stays probeable by a narrowed token, since public is platform-wide scope."""
    from mcpgateway import config

    monkeypatch.setattr(config.settings, "gateway_test_allow_registered_only", True)
    monkeypatch.setattr("mcpgateway.common.validators.socket.getaddrinfo", _mock_getaddrinfo)

    db = team_b_gateway_db(visibility="public")
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=narrowed_user, db=db)

    assert result.success is True
    assert result.credential_source == "stored"


# ---------------------------------------------------------------------------
# Tests: handshake SDK fallback address pinning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sni_pinning_transport_dials_pinned_host_with_hostname_identity():
    """The transport rewrites the request onto the pinned address while keeping Host and TLS identity."""
    transport = _SniPinningTransport(sni_hostname="example.com", pinned_host="8.8.8.8")
    request = httpx.Request("GET", "http://example.com/mcp")

    with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(return_value=httpx.Response(200))):
        await transport.handle_async_request(request)

    assert str(request.url) == "http://8.8.8.8/mcp"
    assert request.headers["Host"] == "example.com"
    assert request.extensions["sni_hostname"] == "example.com"
    await transport.aclose()


@pytest.mark.asyncio
async def test_sni_pinning_transport_refuses_unvalidated_host():
    """The transport refuses to send anywhere but the validated hostname."""
    transport = _SniPinningTransport(sni_hostname="example.com", pinned_host="8.8.8.8")
    request = httpx.Request("GET", "http://attacker.example.net/mcp")

    with pytest.raises(httpx.UnsupportedProtocol):
        await transport.handle_async_request(request)

    await transport.aclose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_form_authorization_skips_unobtainable_stored_oauth_token(user_ctx, db_session):
    """A form Authorization header is used instead of failing on a stored OAuth token the caller overrode."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(auth_type="oauth", oauth_config={"grant_type": "authorization_code"})

    request = GatewayHandshakeRequest(base_url="http://example.com", path="/mcp", headers={"Authorization": "Bearer typed"})
    mock_client = _mock_resilient_client(_discover_success())
    token_storage = MagicMock()
    token_storage.get_user_token = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.token_storage_service.TokenStorageService", return_value=token_storage):
            result = await check_mcp_server_handshake(request=request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.credential_source == "form"
    assert mock_client.request.call_args.kwargs["headers"]["Authorization"] == "Bearer typed"
    token_storage.get_user_token.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_uses_gateway_custom_ca_for_tls(user_ctx, db_session):
    """A registered gateway's private CA and client certificate are used for the SDK connection."""
    gateway = _mock_gateway(transport="STREAMABLEHTTP", ca_certificate="ca-pem", client_cert="client-pem", client_key="key-pem")
    db_session.execute.return_value.scalars.return_value.first.return_value = gateway

    request = GatewayHandshakeRequest(base_url="https://example.com", path="/mcp", headers={})
    mock_client = _mock_resilient_client(_json_response(404, {"error": "not found"}))
    transport_cm, session = _mock_sdk_session()
    ssl_context = ssl.create_default_context()

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client) as mock_resilient:
        with patch("mcpgateway.services.gateway_service.get_cached_ssl_context", return_value=ssl_context) as mock_ssl:
            with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm) as mock_streamable:
                with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                    result = await check_mcp_server_handshake(request=request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    mock_ssl.assert_called_once_with("ca-pem", client_cert="client-pem", client_key="key-pem")

    with patch("mcpgateway.services.gateway_service._SniPinningTransport", wraps=_SniPinningTransport) as mock_transport:
        factory_client = mock_streamable.call_args.kwargs["httpx_client_factory"]()
        await factory_client.aclose()

    assert mock_transport.call_args.kwargs["verify"] is ssl_context
    # The stateless discover probe runs first, so it needs the same TLS settings or it fails
    # the handshake before the SDK client is ever built.
    assert mock_resilient.call_args.kwargs["client_args"]["verify"] is ssl_context


@pytest.mark.asyncio
async def test_sni_pinning_transport_accepts_punycode_host():
    """An internationalized hostname is matched in its IDNA-encoded form, not rejected."""
    transport = _SniPinningTransport(sni_hostname="xn--nicode-2ya.com", pinned_host="8.8.8.8")
    request = httpx.Request("GET", "http://xn--nicode-2ya.com/mcp")

    with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(return_value=httpx.Response(200))):
        await transport.handle_async_request(request)

    assert str(request.url) == "http://8.8.8.8/mcp"
    await transport.aclose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_ignores_caller_supplied_host_header(user_ctx, db_session):
    """A form Host header cannot re-aim stored credentials at another virtual host."""
    db_session.execute.return_value.scalars.return_value.first.return_value = _mock_gateway(auth_type="authheaders", auth_value={"X-API-Key": "stored-key"})  # pragma: allowlist secret

    request = GatewayHandshakeRequest(base_url="http://example.com", path="/mcp", headers={"host": "internal-vhost.corp"})
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.credential_source == "stored"
    sent_headers = mock_client.request.call_args.kwargs["headers"]
    assert sent_headers["Host"] == "example.com"
    assert "host" not in sent_headers


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_connectivity_ignores_caller_supplied_host_header(user_ctx, db_session):
    """POST /test also derives the authority from the validated URL, not from a form header."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    request = GatewayTestRequest(base_url="http://example.com", path="/api/test", method="GET", headers={"host": "internal-vhost.corp"}, body=None)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.get_structured_logger", return_value=MagicMock(log=MagicMock())):
            result = await check_mcp_server_connectivity(request=request, team_id=None, user=user_ctx, db=db_session)

    assert result.status_code == 200
    sent_headers = mock_client.request.call_args.kwargs["headers"]
    assert sent_headers["Host"] == "example.com"
    assert "host" not in sent_headers


def test_gateway_test_visibility_filters_treat_unknown_owner_as_no_identity(team_b_gateway_db):
    """The "unknown" email sentinel is not an identity, so it must not own-match private rows."""
    db = team_b_gateway_db(visibility="private", owner_email="unknown")

    for context in ({"is_admin": False, "token_teams": ["team-a"]}, {"email": "unknown", "is_admin": False, "token_teams": ["team-a"]}):
        visible = db.execute(select(DbGateway.id).where(or_(*_gateway_test_visibility_filters(db, context)))).scalars().all()
        assert visible == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_discover_sends_required_request_metadata(handshake_request, user_ctx, db_session):
    """Both the discover call and the component listings carry the per-request protocol metadata."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    tools_list = _json_response(200, {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}})
    mock_client = _mock_resilient_client(_discover_success(capabilities={"tools": {}}), tools_list)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    for call in mock_client.request.call_args_list:
        sent_meta = call.kwargs["json"]["params"]["_meta"]
        assert sent_meta["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
        assert sent_meta["io.modelcontextprotocol/clientCapabilities"] == {}
        assert sent_meta["io.modelcontextprotocol/clientInfo"]["name"] == "contextforge"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_discover_reads_top_level_server_info_as_fallback(handshake_request, user_ctx, db_session):
    """A server reporting identity at the top level of the result is still named in the response."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    legacy = _json_response(200, {"jsonrpc": "2.0", "id": 1, "result": {"supportedVersions": ["2026-07-28"], "serverInfo": {"name": "legacy-shape", "version": "0.9"}}})
    mock_client = _mock_resilient_client(legacy)

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.negotiation_path == "server_discover"
    assert result.server_name == "legacy-shape"
    assert result.server_version == "0.9"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_shapeless_discover_result_falls_back_to_initialize(handshake_request, user_ctx, db_session):
    """An empty JSON-RPC result is not evidence of discovery support, so the SDK probe runs."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    mock_client = _mock_resilient_client(_json_response(200, {"jsonrpc": "2.0", "id": 1, "result": {}}))
    transport_cm, session = _mock_sdk_session()

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        with patch("mcpgateway.services.gateway_service.streamablehttp_client", return_value=transport_cm):
            with patch("mcpgateway.services.gateway_service.ClientSession", return_value=session):
                result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert result.negotiation_path == "initialize"
    assert result.server_name == "legacy-srv"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_appends_path_before_base_url_query(user_ctx, db_session):
    """A base URL carrying a query string keeps it after the handshake path is appended."""
    db_session.execute.return_value.scalars.return_value.first.return_value = None

    request = GatewayHandshakeRequest(base_url="http://example.com/api?tenant=one", path="/mcp", headers={})
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=request, team_id=None, user=user_ctx, db=db_session)

    assert result.success is True
    assert mock_client.request.call_args.kwargs["url"] == "http://8.8.8.8/api/mcp?tenant=one"


def test_handshake_request_rejects_control_characters_in_path():
    """A control character in the path is rejected at the boundary instead of failing mid-request."""
    with pytest.raises(ValidationError):
        GatewayHandshakeRequest(base_url="http://example.com", path="/mcp\r\nX-Injected: 1")


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
@pytest.mark.parametrize("registered_url", ["http://example.com", "http://example.com/"])
async def test_handshake_matches_registered_root_url_either_spelling(handshake_request, team_b_gateway_db, registered_url):
    """A root gateway resolves its stored credentials whether or not it was registered with a trailing slash."""
    db = team_b_gateway_db(url=registered_url)
    team_b_user = {"email": "user@example.com", "is_admin": False, "token_teams": ["team-b"], "permissions": ["gateways.read"]}
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=handshake_request, team_id=None, user=team_b_user, db=db)

    assert result.success is True
    assert result.credential_source == "stored"
    assert mock_client.request.call_args.kwargs["headers"]["Authorization"] == "Basic teamb"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_does_not_alias_non_root_registered_paths(team_b_gateway_db):
    """Only the root path is trailing-slash ambiguous: /mcp must not borrow /mcp/'s credentials."""
    db = team_b_gateway_db(url="http://example.com/mcp/")
    team_b_user = {"email": "user@example.com", "is_admin": False, "token_teams": ["team-b"], "permissions": ["gateways.read"]}
    request = GatewayHandshakeRequest(base_url="http://example.com/mcp", path="", headers={})
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=request, team_id=None, user=team_b_user, db=db)

    assert result.success is True
    assert result.credential_source == "none"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configure_allowlist")
async def test_handshake_matches_registered_root_url_with_query_string(team_b_gateway_db):
    """A root URL carrying a query keeps the query in both candidate spellings."""
    db = team_b_gateway_db(url="http://example.com?tenant=one")
    team_b_user = {"email": "user@example.com", "is_admin": False, "token_teams": ["team-b"], "permissions": ["gateways.read"]}
    request = GatewayHandshakeRequest(base_url="http://example.com?tenant=one", path="/mcp", headers={})
    mock_client = _mock_resilient_client(_discover_success())

    with patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=mock_client):
        result = await check_mcp_server_handshake(request=request, team_id=None, user=team_b_user, db=db)

    assert result.success is True
    assert result.credential_source == "stored"
