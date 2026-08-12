# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_vault_router.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for vault_router — deny-path security regression tests.

Per AGENTS.md: "Security-sensitive changes must include deny-path regression
tests (unauthenticated, wrong team, insufficient permissions, feature disabled)."
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.routers.vault_router import _resolve_oauth_gateway, vault_authorize


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server(server_id: str = "srv-123") -> MagicMock:
    """Return a minimal mock Server ORM object."""
    server = MagicMock()
    server.id = server_id
    return server


def _make_gateway(
    gateway_id: str = "gw-456",
    visibility: str = "team",
    team_id: str = "engineering",
    owner_email: str = "alice@corp.com",
    oauth_config: dict | None = None,
) -> MagicMock:
    """Return a minimal mock Gateway ORM object."""
    gw = MagicMock()
    gw.id = gateway_id
    gw.visibility = visibility
    gw.team_id = team_id
    gw.owner_email = owner_email
    gw.oauth_config = oauth_config or {"grant_type": "authorization_code"}
    gw.auth_type = "oauth"
    return gw


def _make_request() -> MagicMock:
    """Return a minimal mock FastAPI Request."""
    req = MagicMock()
    req.url.scheme = "https"
    req.url.netloc = "gateway.example.com"
    req.state = MagicMock()
    req.state.token_teams = None
    req.state.jwt_teams_claim = None
    return req


def _make_user(
    email: str = "alice@corp.com",
    is_admin: bool = False,
    token_teams: list | None = None,
) -> dict:
    """Return a minimal current_user dict as produced by get_current_user_with_permissions."""
    return {
        "email": email,
        "is_admin": is_admin,
        "token_teams": token_teams,
        "token_use": "session",
    }


# ---------------------------------------------------------------------------
# _resolve_oauth_gateway tests
# ---------------------------------------------------------------------------


class TestResolveOAuthGateway:
    """Unit tests for the internal gateway resolver."""

    def test_returns_none_when_no_tools(self):
        """Returns None when the server has no tool associations."""
        db = MagicMock()
        server = _make_server()
        db.execute.return_value.all.return_value = []
        result = _resolve_oauth_gateway(server, db)
        assert result is None

    def test_returns_none_when_no_oauth_gateways(self):
        """Returns None when associated gateways don't have auth_type=oauth."""
        db = MagicMock()
        server = _make_server()
        # First query returns some gateway_ids; second returns no oauth gateways
        db.execute.return_value.all.return_value = [("gw-1",)]
        db.execute.return_value.scalars.return_value.all.return_value = []
        result = _resolve_oauth_gateway(server, db)
        assert result is None

    def test_returns_first_gateway_when_no_preferred_url(self):
        """Returns the first OAuth gateway when no preferred URL specified."""
        db = MagicMock()
        server = _make_server()
        gw = _make_gateway()

        execute_mock = MagicMock()
        execute_mock.all.return_value = [("gw-456",)]
        execute_mock.scalars.return_value.all.return_value = [gw]
        db.execute.return_value = execute_mock

        result = _resolve_oauth_gateway(server, db)
        assert result is gw

    def test_returns_none_when_preferred_url_not_found(self):
        """Returns None when preferred_url is specified but doesn't match any gateway."""
        db = MagicMock()
        server = _make_server()
        gw = _make_gateway()
        gw.url = "https://gw1.example.com/mcp"

        execute_mock = MagicMock()
        execute_mock.all.return_value = [("gw-456",)]
        execute_mock.scalars.return_value.all.return_value = [gw]
        db.execute.return_value = execute_mock

        result = _resolve_oauth_gateway(server, db, preferred_url="https://other.example.com/mcp")
        assert result is None


# ---------------------------------------------------------------------------
# vault_authorize — deny-path security tests (AGENTS.md requirement)
# ---------------------------------------------------------------------------


class TestVaultAuthorizeDenyPaths:
    """Security regression tests: deny-path scenarios per AGENTS.md.

    These tests verify that _enforce_gateway_access() is correctly wired into
    vault_authorize, so that callers without gateway access are rejected before
    any OAuth flow is initiated.
    """

    @pytest.mark.asyncio
    async def test_server_not_found_returns_404(self):
        """Unknown server_id must return 404 before any gateway resolution."""
        db = MagicMock()
        db.get.return_value = None  # Server not found

        with pytest.raises(HTTPException) as exc_info:
            await vault_authorize(
                request=_make_request(),
                server_id="nonexistent-server",
                gateway_url=None,
                db=db,
                current_user=_make_user(),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_oauth_gateways_returns_400(self):
        """Server with no OAuth-enabled gateways returns 400."""
        db = MagicMock()
        db.get.return_value = _make_server()

        with patch("mcpgateway.routers.vault_router._resolve_oauth_gateway", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await vault_authorize(
                    request=_make_request(),
                    server_id="srv-123",
                    gateway_url=None,
                    db=db,
                    current_user=_make_user(),
                )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_wrong_team_caller_returns_403(self):
        """Non-member of gateway team must be denied with 403.

        mallory@corp.com (teams=['marketing']) attempts to authorize against
        a private gateway owned by team='engineering'. Without the
        _enforce_gateway_access() call this would have returned 302; with it
        it must return 403.
        """
        db = MagicMock()
        db.get.return_value = _make_server()
        gateway = _make_gateway(visibility="team", team_id="engineering")

        mallory = _make_user(email="mallory@corp.com", is_admin=False, token_teams=["marketing"])

        with patch("mcpgateway.routers.vault_router._resolve_oauth_gateway", return_value=gateway):
            with patch(
                "mcpgateway.routers.vault_router._enforce_gateway_access",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=403, detail="You don't have access to this gateway"),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await vault_authorize(
                        request=_make_request(),
                        server_id="srv-123",
                        gateway_url=None,
                        db=db,
                        current_user=mallory,
                    )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_public_only_token_returns_403(self):
        """A public-only token (token_teams=[]) must not gain OAuth credentials."""
        db = MagicMock()
        db.get.return_value = _make_server()
        gateway = _make_gateway(visibility="team", team_id="engineering")

        public_user = _make_user(email="bob@corp.com", is_admin=False, token_teams=[])

        with patch("mcpgateway.routers.vault_router._resolve_oauth_gateway", return_value=gateway):
            with patch(
                "mcpgateway.routers.vault_router._enforce_gateway_access",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=403, detail="You don't have access to this gateway"),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await vault_authorize(
                        request=_make_request(),
                        server_id="srv-123",
                        gateway_url=None,
                        db=db,
                        current_user=public_user,
                    )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_valid_team_member_initiates_flow(self):
        """A valid team member receives a 302 redirect to the IdP."""
        db = MagicMock()
        db.get.return_value = _make_server()
        gateway = _make_gateway(visibility="team", team_id="engineering")

        alice = _make_user(email="alice@corp.com", is_admin=False, token_teams=["engineering"])

        with patch("mcpgateway.routers.vault_router._resolve_oauth_gateway", return_value=gateway):
            with patch(
                "mcpgateway.routers.vault_router._enforce_gateway_access",
                new_callable=AsyncMock,
                return_value=None,  # Access granted — no exception
            ):
                with patch("mcpgateway.routers.vault_router.OAuthManager") as mock_oauth_cls:
                    mock_oauth = AsyncMock()
                    mock_oauth.initiate_authorization_code_flow.return_value = {
                        "authorization_url": "https://idp.example.com/authorize?state=xyz"
                    }
                    mock_oauth_cls.return_value = mock_oauth

                    from fastapi.responses import RedirectResponse

                    response = await vault_authorize(
                        request=_make_request(),
                        server_id="srv-123",
                        gateway_url=None,
                        db=db,
                        current_user=alice,
                    )

        assert isinstance(response, RedirectResponse)
        assert response.status_code == 302

    @pytest.mark.asyncio
    async def test_admin_user_can_authorize(self):
        """Platform admin can authorize against any gateway."""
        db = MagicMock()
        db.get.return_value = _make_server()
        gateway = _make_gateway(visibility="private", owner_email="other@corp.com")

        admin = _make_user(email="admin@corp.com", is_admin=True, token_teams=None)

        with patch("mcpgateway.routers.vault_router._resolve_oauth_gateway", return_value=gateway):
            with patch(
                "mcpgateway.routers.vault_router._enforce_gateway_access",
                new_callable=AsyncMock,
                return_value=None,  # Admin bypass — no exception
            ):
                with patch("mcpgateway.routers.vault_router.OAuthManager") as mock_oauth_cls:
                    mock_oauth = AsyncMock()
                    mock_oauth.initiate_authorization_code_flow.return_value = {
                        "authorization_url": "https://idp.example.com/authorize?state=abc"
                    }
                    mock_oauth_cls.return_value = mock_oauth

                    from fastapi.responses import RedirectResponse

                    response = await vault_authorize(
                        request=_make_request(),
                        server_id="srv-123",
                        gateway_url=None,
                        db=db,
                        current_user=admin,
                    )

        assert isinstance(response, RedirectResponse)
        assert response.status_code == 302
