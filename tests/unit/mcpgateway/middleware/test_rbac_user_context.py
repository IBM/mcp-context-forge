# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_rbac_user_context.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests that the RBAC user context carries the canonical user_id and the
claims-derived identity.

The authenticated context built by get_current_user_with_permissions must
expose the canonical user_id (resolving user_id -> email -> sub -> "unknown"
via mcpgateway.auth_context.get_user_id), not only the e-mail attribute, so
live RBAC checks can key on the stable identity. On the JWT-trust path it
must additionally carry the VirtualPrincipal's claims-derived roles, the
claims-derived admin flag (token_is_admin), and the claims-derived teams;
non-trust authenticated paths expose the same keys with neutral defaults so
downstream consumers can rely on key presence.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.middleware.rbac import _resolve_team_and_check_mode, get_current_user_with_permissions
from mcpgateway.utils.trusted_claims import VirtualPrincipal


def _mock_request():
    """Build a minimal browser-style request for the JWT auth path."""

    class MockState:
        pass

    mock_request = MagicMock()
    mock_request.state = MockState()
    mock_request.state.auth_method = "simple_token"
    mock_request.state.request_id = "test-request-id"
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"user-agent": "TestAgent", "accept": "text/html"}  # Browser request allows cookie auth
    mock_request.cookies = {"jwt_token": "test-token"}
    return mock_request


@pytest.mark.asyncio
async def test_user_context_carries_canonical_user_id():
    """The authenticated context must expose the canonical user_id, not only email."""
    # Minimal principal whose user_id diverges from email — the F8 case.
    principal = SimpleNamespace(
        email="alice@example.com",
        user_id="entra-sub-123",
        full_name="Alice",
        is_admin=False,
        teams=[],
    )

    with patch("mcpgateway.auth.validate_token_user", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = principal

        ctx = await get_current_user_with_permissions(
            request=_mock_request(),
            credentials=None,
            jwt_token="test-token",
        )

    assert ctx["email"] == "alice@example.com"
    assert ctx["user_id"] == "entra-sub-123"


@pytest.mark.asyncio
async def test_user_context_user_id_falls_back_to_email():
    """A principal without an explicit user_id resolves user_id to its email."""
    principal = SimpleNamespace(
        email="bob@example.com",
        full_name="Bob",
        is_admin=False,
    )

    with patch("mcpgateway.auth.validate_token_user", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = principal

        ctx = await get_current_user_with_permissions(
            request=_mock_request(),
            credentials=None,
            jwt_token="test-token",
        )

    assert ctx["user_id"] == "bob@example.com"


@pytest.mark.asyncio
async def test_trust_principal_claims_reach_user_context():
    """The trust-path context must carry the principal's claims-derived identity."""
    principal = VirtualPrincipal(
        user_id="entra-sub-123",
        email="alice@example.com",
        full_name="Alice",
        teams=["team-a"],
        roles=["developer"],
        is_admin=False,
    )
    request = _mock_request()
    request.state.token_use = "trusted"  # Set by get_current_user on the trust branch

    with patch("mcpgateway.auth.validate_token_user", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = principal

        ctx = await get_current_user_with_permissions(
            request=request,
            credentials=None,
            jwt_token="test-token",
        )

    assert ctx["user_id"] == "entra-sub-123"
    assert ctx["roles"] == ["developer"]
    assert ctx["token_is_admin"] is False
    assert ctx["token_teams"] == ["team-a"]


@pytest.mark.asyncio
async def test_internal_jwt_context_has_neutral_claims_defaults():
    """A non-trust authenticated context exposes the claims keys with neutral defaults."""
    principal = SimpleNamespace(
        email="carol@example.com",
        user_id="carol-uuid-456",
        full_name="Carol",
        is_admin=True,  # DB-derived admin must NOT leak into token_is_admin
        teams=["team-x"],
    )

    with patch("mcpgateway.auth.validate_token_user", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = principal

        ctx = await get_current_user_with_permissions(
            request=_mock_request(),
            credentials=None,
            jwt_token="test-token",
        )

    assert ctx["roles"] == []
    assert ctx["token_is_admin"] is False
    assert ctx["is_admin"] is True
    assert "token_teams" in ctx


@pytest.mark.asyncio
async def test_trust_principal_admin_flag_reaches_user_context():
    """A trust principal with the mapped admin claim sets token_is_admin True."""
    principal = VirtualPrincipal(
        user_id="entra-sub-admin",
        email="root@example.com",
        full_name="Root",
        teams=[],
        roles=["platform_admin"],
        is_admin=True,
    )
    request = _mock_request()
    request.state.token_use = "trusted"

    with patch("mcpgateway.auth.validate_token_user", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = principal

        ctx = await get_current_user_with_permissions(
            request=request,
            credentials=None,
            jwt_token="test-token",
        )

    assert ctx["token_is_admin"] is True
    assert ctx["roles"] == ["platform_admin"]


@pytest.mark.asyncio
async def test_session_context_carries_token_use_and_neutral_claims():
    """A session-type authenticated context must keep token_use for RBAC team derivation."""
    principal = SimpleNamespace(
        email="dave@example.com",
        user_id="dave-uuid-789",
        full_name="Dave",
        is_admin=False,
        teams=["team-a"],
    )
    request = _mock_request()
    request.state.token_use = "session"
    request.state.token_teams = ["team-a"]

    with patch("mcpgateway.auth.validate_token_user", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = principal

        ctx = await get_current_user_with_permissions(
            request=request,
            credentials=None,
            jwt_token="test-token",
        )

    assert ctx["token_use"] == "session"
    assert ctx["roles"] == []
    assert ctx["token_is_admin"] is False
    assert ctx["token_teams"] == ["team-a"]


@pytest.mark.asyncio
async def test_resolve_team_and_check_mode_relies_on_context_token_use():
    """_resolve_team_and_check_mode derives the accessed resource's team only when the
    context carries a session/api token_use; without it the check broadens to any-team."""
    with patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value="team-b") as mock_derive:
        team_id, check_any_team = await _resolve_team_and_check_mode({"token_use": "session"}, {"db": MagicMock()})

    assert team_id == "team-b"
    assert check_any_team is False
    mock_derive.assert_called_once()

    with patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value="team-b") as mock_derive:
        team_id, check_any_team = await _resolve_team_and_check_mode({}, {"db": MagicMock()})

    assert team_id is None
    assert check_any_team is True
    mock_derive.assert_not_called()
