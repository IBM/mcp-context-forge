# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_mcp_servers_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

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
from mcpgateway.routers.mcp_servers_router import _validated_team_id, check_mcp_server_connectivity
from mcpgateway.schemas import GatewayTestRequest, GatewayTestResponse

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
