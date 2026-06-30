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
