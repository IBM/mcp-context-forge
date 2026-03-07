# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_rpc_permission_team_fallback.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Regression tests for session-token team-permission fallback in _ensure_rpc_permission.
Ref: https://github.com/IBM/mcp-context-forge/issues/3515

The bug: _ensure_rpc_permission calls PermissionChecker.has_permission without
check_any_team=True, so _get_user_roles only returns global roles + team roles with
scope_id=NULL, missing the user's actual team assignments.  Users with tools.execute
only in a team-scoped RBAC role get -32003 on /rpc and /mcp while the same user
succeeds on REST endpoints.

These tests are written against the *expected* fixed behaviour and therefore FAIL
before the fix is applied (Task 3).
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.main import _ensure_rpc_permission
from mcpgateway.validation.jsonrpc import JSONRPCError


def _make_session_user(email: str = "user@example.com", is_admin: bool = False) -> dict:
    """Build a minimal user context that mimics a session token (token_use='session')."""
    return {
        "email": email,
        "is_admin": is_admin,
        "token_use": "session",
        "token_teams": None,
    }


def _make_mock_checker(grants: bool):
    """Return a mock PermissionChecker instance whose has_permission returns `grants`."""
    instance = MagicMock()
    instance.has_permission = AsyncMock(return_value=grants)
    return instance


@pytest.mark.asyncio
async def test_ensure_rpc_permission_grants_session_token_with_team_role():
    """Session token user with tools.execute only in team-scoped role must be granted.

    Before the fix, check_any_team=False caused _get_user_roles to skip
    team-specific assignments, returning only global roles which lack tools.execute.

    After the fix, _ensure_rpc_permission must call has_permission with
    check_any_team=True when token_use=='session'.

    This test FAILS before the fix because has_permission is called without
    check_any_team=True.
    """
    user = _make_session_user()
    db = MagicMock(spec=Session)
    mock_checker = _make_mock_checker(grants=True)

    with patch("mcpgateway.main.PermissionChecker", return_value=mock_checker):
        # Must NOT raise
        await _ensure_rpc_permission(user, db, "tools.execute", "tools/call")

    # Verify has_permission was called with check_any_team=True
    mock_checker.has_permission.assert_called_once()
    call_kwargs = mock_checker.has_permission.call_args.kwargs
    assert call_kwargs.get("check_any_team") is True, (
        "Expected check_any_team=True for session token without explicit team_id; "
        "got call_kwargs=%r" % call_kwargs
    )


@pytest.mark.asyncio
async def test_ensure_rpc_permission_denies_when_rbac_denies():
    """Even with check_any_team=True, RBAC denial must still raise JSONRPCError."""
    user = _make_session_user()
    db = MagicMock(spec=Session)
    mock_checker = _make_mock_checker(grants=False)

    with patch("mcpgateway.main.PermissionChecker", return_value=mock_checker):
        with pytest.raises(JSONRPCError) as exc_info:
            await _ensure_rpc_permission(user, db, "tools.execute", "tools/call")

    assert exc_info.value.code == -32003
    assert "Access denied" in exc_info.value.message


@pytest.mark.asyncio
async def test_ensure_rpc_permission_non_session_token_uses_check_any_team_false():
    """Non-session (API) tokens must NOT use check_any_team — preserves existing behaviour.

    This test verifies that the fix is scoped only to session tokens and does not
    change the behaviour for API tokens that carry explicit team scoping via
    token_teams.

    This test may PASS before the fix if the current code happens to omit the kwarg
    (defaulting to False) or FAIL if check_any_team is added unconditionally.
    """
    user = {
        "email": "user@example.com",
        "is_admin": False,
        "token_use": "access",  # API token, not session
        "token_teams": ["team-abc"],
    }
    db = MagicMock(spec=Session)
    mock_checker = _make_mock_checker(grants=True)

    with patch("mcpgateway.main.PermissionChecker", return_value=mock_checker):
        await _ensure_rpc_permission(user, db, "tools.execute", "tools/call")

    call_kwargs = mock_checker.has_permission.call_args.kwargs
    assert call_kwargs.get("check_any_team", False) is False, (
        "Non-session tokens must not use check_any_team=True; "
        "got call_kwargs=%r" % call_kwargs
    )


@pytest.mark.asyncio
async def test_ensure_rpc_permission_unauthenticated_raises():
    """Missing user email must raise JSONRPCError -32003 (fail-closed)."""
    user = {"email": "", "is_admin": False, "token_use": "session"}
    db = MagicMock(spec=Session)
    mock_checker = _make_mock_checker(grants=False)

    with patch("mcpgateway.main.PermissionChecker", return_value=mock_checker):
        with pytest.raises(JSONRPCError) as exc_info:
            await _ensure_rpc_permission(user, db, "tools.execute", "tools/call")

    assert exc_info.value.code == -32003


# ---------------------------------------------------------------------------
# Deny-path regression tests (Task 6)
# Guard against the fix accidentally granting access it shouldn't.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_rpc_permission_denies_user_with_no_qualifying_role():
    """User whose team roles don't include tools.execute must still be denied."""
    user = _make_session_user()
    db = MagicMock(spec=Session)
    mock_checker = _make_mock_checker(grants=False)  # RBAC returns False

    with patch("mcpgateway.main.PermissionChecker", return_value=mock_checker):
        with pytest.raises(JSONRPCError) as exc_info:
            await _ensure_rpc_permission(user, db, "tools.execute", "tools/call")

    assert exc_info.value.code == -32003


@pytest.mark.asyncio
async def test_ensure_rpc_permission_admin_session_token_calls_has_permission():
    """Admin session-token users still go through has_permission in _ensure_rpc_permission.

    The admin bypass lives inside PermissionService, not in _ensure_rpc_permission itself.
    This test verifies:
    - has_permission IS called (no early exit at this layer for admin users)
    - check_any_team=True because the user carries a session token
    """
    user = _make_session_user(is_admin=True)
    db = MagicMock(spec=Session)
    mock_checker = _make_mock_checker(grants=True)

    with patch("mcpgateway.main.PermissionChecker", return_value=mock_checker):
        await _ensure_rpc_permission(user, db, "tools.execute", "tools/call")

    mock_checker.has_permission.assert_called_once()
    call_kwargs = mock_checker.has_permission.call_args.kwargs
    assert call_kwargs.get("check_any_team") is True, (
        "Admin session tokens are still session tokens — expected check_any_team=True; "
        "got call_kwargs=%r" % call_kwargs
    )


@pytest.mark.asyncio
async def test_ensure_rpc_permission_token_scope_cap_blocks_at_layer1():
    """Explicit scopes.permissions=['tools.read'] blocks tools.execute at Layer 1."""
    user = _make_session_user()
    db = MagicMock(spec=Session)
    mock_checker = _make_mock_checker(grants=True)  # RBAC would grant

    mock_request = MagicMock()
    mock_request.state._jwt_verified_payload = (
        None,
        {"scopes": {"permissions": ["tools.read"]}},
    )

    with patch("mcpgateway.main.PermissionChecker", return_value=mock_checker):
        with pytest.raises(JSONRPCError) as exc_info:
            await _ensure_rpc_permission(
                user, db, "tools.execute", "tools/call", request=mock_request
            )

    assert exc_info.value.code == -32003
    assert "Access denied" in exc_info.value.message
