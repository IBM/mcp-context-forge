# -*- coding: utf-8 -*-
"""Unit tests for session-token team narrowing in PermissionService.

Tests the fix for Layer 2 RBAC enforcement of Layer 1 token scoping.
When a session token is narrowed to specific teams via JWT claims,
permission checks should only aggregate permissions from roles in those teams.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.permission_service import PermissionService


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []
    db.execute.return_value.scalars.return_value.all.return_value = []
    return db


@pytest.fixture
def svc(mock_db):
    """PermissionService instance with audit disabled."""
    return PermissionService(mock_db, audit_enabled=False)


# ---------- Token Narrowing: Cache Key Generation ----------


@pytest.mark.asyncio
async def test_cache_key_includes_token_teams_when_narrowed(svc):
    """Cache key includes token_teams to prevent cross-contamination."""
    role = SimpleNamespace(name="developer", permissions=["tools.read", "tools.execute"], get_effective_permissions=lambda: ["tools.read", "tools.execute"])
    user_role = SimpleNamespace(role=role, role_id="r1", scope="team", scope_id="team-a")

    with patch.object(svc, "_get_user_roles", return_value=[user_role]):
        # First call with narrowing to team-a
        result1 = await svc.get_user_permissions("user@test.com", include_all_teams=True, token_teams=["team-a"])

        # Verify cache key includes team-a
        assert "user@test.com:__anyteam__:team-a" in svc._permission_cache
        assert result1 == {"tools.read", "tools.execute"}


@pytest.mark.asyncio
async def test_cache_key_different_for_different_narrowing(svc):
    """Different token_teams produce different cache keys."""
    role_a = SimpleNamespace(name="developer", permissions=["tools.read"], get_effective_permissions=lambda: ["tools.read"])
    role_b = SimpleNamespace(name="team_admin", permissions=["teams.*", "tools.create"], get_effective_permissions=lambda: ["teams.*", "tools.create"])

    # Mock different roles for different calls
    with patch.object(svc, "_get_user_roles") as mock_get_roles:
        # First call: narrowed to team-a (developer role)
        mock_get_roles.return_value = [SimpleNamespace(role=role_a, role_id="r1", scope="team", scope_id="team-a")]
        result1 = await svc.get_user_permissions("user@test.com", include_all_teams=True, token_teams=["team-a"])

        # Second call: narrowed to team-b (team_admin role)
        mock_get_roles.return_value = [SimpleNamespace(role=role_b, role_id="r2", scope="team", scope_id="team-b")]
        result2 = await svc.get_user_permissions("user@test.com", include_all_teams=True, token_teams=["team-b"])

        # Verify different cache keys
        assert "user@test.com:__anyteam__:team-a" in svc._permission_cache
        assert "user@test.com:__anyteam__:team-b" in svc._permission_cache

        # Verify different permissions
        assert result1 == {"tools.read"}
        assert result2 == {"teams.*", "tools.create"}


@pytest.mark.asyncio
async def test_cache_key_sorted_teams_for_consistency(svc):
    """Token teams are sorted in cache key for consistency."""
    role = SimpleNamespace(name="developer", permissions=["tools.read"], get_effective_permissions=lambda: ["tools.read"])
    user_role = SimpleNamespace(role=role, role_id="r1", scope="team", scope_id="team-a")

    with patch.object(svc, "_get_user_roles", return_value=[user_role]):
        # Call with unsorted teams
        await svc.get_user_permissions("user@test.com", include_all_teams=True, token_teams=["team-c", "team-a", "team-b"])

        # Verify cache key has sorted teams
        assert "user@test.com:__anyteam__:team-a,team-b,team-c" in svc._permission_cache


@pytest.mark.asyncio
async def test_cache_key_deduplicates_token_teams(svc):
    """Duplicate team IDs in token_teams produce the same cache key as deduplicated."""
    role = SimpleNamespace(name="developer", permissions=["tools.read"], get_effective_permissions=lambda: ["tools.read"])
    user_role = SimpleNamespace(role=role, role_id="r1", scope="team", scope_id="team-a")

    with patch.object(svc, "_get_user_roles", return_value=[user_role]):
        await svc.get_user_permissions("user@test.com", include_all_teams=True, token_teams=["team-a", "team-a"])

        # Deduplicated: should be same key as single "team-a"
        assert "user@test.com:__anyteam__:team-a" in svc._permission_cache
        assert "user@test.com:__anyteam__:team-a,team-a" not in svc._permission_cache


@pytest.mark.asyncio
async def test_cache_key_no_suffix_when_token_teams_none(svc):
    """Un-narrowed sessions (token_teams=None) use base cache key."""
    role = SimpleNamespace(name="developer", permissions=["tools.read"], get_effective_permissions=lambda: ["tools.read"])
    user_role = SimpleNamespace(role=role, role_id="r1", scope="team", scope_id="team-a")

    with patch.object(svc, "_get_user_roles", return_value=[user_role]):
        await svc.get_user_permissions("user@test.com", include_all_teams=True, token_teams=None)

        # Verify cache key has no team suffix
        assert "user@test.com:__anyteam__" in svc._permission_cache
        assert "user@test.com:__anyteam__:" not in svc._permission_cache


# ---------- Token Narrowing: Role Filtering ----------


@pytest.mark.asyncio
async def test_get_user_roles_filters_by_token_teams_when_narrowed(svc, mock_db):
    """_get_user_roles filters team-scoped roles to token_teams when narrowed."""
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

    await svc._get_user_roles("user@test.com", team_id=None, include_all_teams=True, token_teams=["team-a", "team-b"])

    # Verify query was executed
    assert mock_db.execute.called

    # Verify the SQL includes token_teams filtering
    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))

    # Should include team-a and team-b in the query
    assert "team-a" in compiled or "scope_id IN" in compiled, f"Query should filter by token_teams: {compiled}"


@pytest.mark.asyncio
async def test_get_user_roles_no_filter_when_token_teams_none(svc, mock_db):
    """_get_user_roles does not filter when token_teams is None (un-narrowed)."""
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

    await svc._get_user_roles("user@test.com", team_id=None, include_all_teams=True, token_teams=None)

    # Verify query was executed
    assert mock_db.execute.called

    # Query should still exclude personal teams but not filter by specific teams
    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))
    assert "is_personal" in compiled


@pytest.mark.asyncio
async def test_get_user_roles_no_filter_when_token_teams_empty(svc, mock_db):
    """_get_user_roles does not filter when token_teams is empty list (public-only)."""
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

    await svc._get_user_roles("user@test.com", team_id=None, include_all_teams=True, token_teams=[])

    # Verify query was executed
    assert mock_db.execute.called

    # Empty token_teams means public-only scope, no team filtering applied at this level
    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))
    assert "is_personal" in compiled


@pytest.mark.asyncio
async def test_get_user_roles_preserves_global_team_roles_when_narrowed(svc, mock_db):
    """_get_user_roles preserves roles with scope_id=None when narrowed."""
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

    await svc._get_user_roles("user@test.com", team_id=None, include_all_teams=True, token_teams=["team-a"])

    # Verify query was executed
    assert mock_db.execute.called

    # Query should include OR condition for scope_id IS NULL (global team roles)
    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))
    assert "IS NULL" in compiled or "scope_id IS NULL" in compiled, f"Query should preserve global team roles: {compiled}"


# ---------- Token Narrowing: End-to-End Permission Checks ----------


@pytest.mark.asyncio
async def test_check_permission_narrowed_session_restricts_to_token_teams(svc):
    """check_permission with narrowed session only uses permissions from token_teams.

    Uses realistic explicit permissions (matching bootstrap_db.py built-in roles)
    so the negative assertion actually detects a role leak — if team-B's role
    leaked into the result, 'teams.create' would be present via exact match.
    """
    # team-a: developer with read/execute only
    role_a = SimpleNamespace(name="developer", permissions=["tools.read", "tools.execute"], get_effective_permissions=lambda: ["tools.read", "tools.execute"])
    # team-b: team_admin with explicit team management permissions (realistic, not wildcard)
    role_b = SimpleNamespace(
        name="team_admin",
        permissions=["teams.create", "teams.read", "teams.update", "teams.delete", "tools.create"],
        get_effective_permissions=lambda: ["teams.create", "teams.read", "teams.update", "teams.delete", "tools.create"],
    )

    # Mock _get_user_roles to return only team-a role when narrowed
    def mock_get_roles(user_email, team_id, include_all_teams=False, token_teams=None):
        if token_teams == ["team-a"]:
            return [SimpleNamespace(role=role_a, role_id="r1", scope="team", scope_id="team-a")]
        else:
            return [SimpleNamespace(role=role_a, role_id="r1", scope="team", scope_id="team-a"), SimpleNamespace(role=role_b, role_id="r2", scope="team", scope_id="team-b")]

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_roles", side_effect=mock_get_roles):
            # Narrowed to team-a: must NOT have teams.create from team-b
            result_narrowed = await svc.check_permission("user@test.com", "teams.create", check_any_team=True, token_teams=["team-a"])
            assert result_narrowed is False, "Narrowed session must not have teams.create from team-b"

            # Should have tools.read from team-a
            result_allowed = await svc.check_permission("user@test.com", "tools.read", check_any_team=True, token_teams=["team-a"])
            assert result_allowed is True, "Narrowed session should have tools.read from team-a"


@pytest.mark.asyncio
async def test_check_permission_unnarrowed_session_uses_all_teams(svc):
    """check_permission with un-narrowed session (token_teams=None) uses all team roles."""
    role_a = SimpleNamespace(name="developer", permissions=["tools.read"], get_effective_permissions=lambda: ["tools.read"])
    role_b = SimpleNamespace(name="team_admin", permissions=["teams.create", "teams.read"], get_effective_permissions=lambda: ["teams.create", "teams.read"])

    user_roles = [SimpleNamespace(role=role_a, role_id="r1", scope="team", scope_id="team-a"), SimpleNamespace(role=role_b, role_id="r2", scope="team", scope_id="team-b")]

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_roles", return_value=user_roles):
            # Un-narrowed session: should have teams.create from team-b
            result = await svc.check_permission("user@test.com", "teams.create", check_any_team=True, token_teams=None)
            assert result is True, "Un-narrowed session should have teams.create from team-b"


@pytest.mark.asyncio
async def test_check_permission_public_only_token_retains_non_admin_team_perms(svc):
    """Public-only token (token_teams=[]) retains non-admin team permissions.

    Layer 1 (token scoping) handles public-only visibility filtering.
    Layer 2 (RBAC) still grants non-admin permissions from team roles
    because token_teams=[] does not trigger role filtering — only
    non-empty token_teams narrows the role set.  The admin.* block
    (tested separately) is the only Layer 2 restriction for public-only.
    """
    role = SimpleNamespace(
        name="team_admin",
        permissions=["teams.read", "teams.create"],
        get_effective_permissions=lambda: ["teams.read", "teams.create"],
    )
    user_role = SimpleNamespace(role=role, role_id="r1", scope="team", scope_id="team-a")

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_roles", return_value=[user_role]):
            # Public-only token retains non-admin team permissions at Layer 2;
            # Layer 1 handles visibility restriction to public resources only.
            result = await svc.check_permission(
                "user@test.com",
                "teams.read",
                check_any_team=True,
                token_teams=[],
            )
            assert result is True, "Public-only token retains non-admin team permissions (Layer 1 handles visibility)"


@pytest.mark.asyncio
async def test_check_permission_admin_bypass_unaffected_by_narrowing(svc):
    """Admin bypass works regardless of token_teams narrowing."""
    with patch.object(svc, "_is_user_admin", return_value=True):
        # Admin with narrowed token still bypasses
        result = await svc.check_permission("admin@test.com", "teams.create", check_any_team=True, token_teams=["team-a"], allow_admin_bypass=True)
        assert result is True, "Admin bypass should work with narrowed token"


@pytest.mark.asyncio
async def test_check_permission_public_only_blocks_admin_permissions_even_for_admin(svc):
    """Public-only token blocks admin.* permissions even for admin users."""
    with patch.object(svc, "_is_user_admin", return_value=True):
        result = await svc.check_permission("admin@test.com", "admin.system_config", token_teams=[], allow_admin_bypass=True)  # Public-only
        assert result is False, "Public-only token must block admin.* even for admin users"


# ---------- Token Narrowing: Multiple Teams ----------


@pytest.mark.asyncio
async def test_check_permission_narrowed_to_multiple_teams(svc):
    """check_permission with multiple teams in token_teams aggregates from all specified teams."""
    role_a = SimpleNamespace(name="developer", permissions=["tools.read"], get_effective_permissions=lambda: ["tools.read"])
    role_b = SimpleNamespace(name="developer", permissions=["tools.execute"], get_effective_permissions=lambda: ["tools.execute"])

    def mock_get_roles(user_email, team_id, include_all_teams=False, token_teams=None):
        if token_teams == ["team-a", "team-b"]:
            # Narrowed to team-a and team-b: return both roles
            return [SimpleNamespace(role=role_a, role_id="r1", scope="team", scope_id="team-a"), SimpleNamespace(role=role_b, role_id="r2", scope="team", scope_id="team-b")]
        return []

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_roles", side_effect=mock_get_roles):
            # Should have tools.read from team-a
            result_read = await svc.check_permission("user@test.com", "tools.read", check_any_team=True, token_teams=["team-a", "team-b"])
            assert result_read is True

            # Should have tools.execute from team-b
            result_execute = await svc.check_permission("user@test.com", "tools.execute", check_any_team=True, token_teams=["team-a", "team-b"])
            assert result_execute is True

            # Should NOT have teams.* from team-c (not in token_teams)
            result_teams = await svc.check_permission("user@test.com", "teams.create", check_any_team=True, token_teams=["team-a", "team-b"])
            assert result_teams is False


# ---------- Token Narrowing: Specific Team Context ----------


@pytest.mark.asyncio
async def test_check_permission_specific_team_id_ignores_token_teams(svc):
    """check_permission with specific team_id uses that team, not token_teams."""
    role_a = SimpleNamespace(name="developer", permissions=["tools.read"], get_effective_permissions=lambda: ["tools.read"])

    def mock_get_roles(user_email, team_id, include_all_teams=False, token_teams=None):
        if team_id == "team-a":
            return [SimpleNamespace(role=role_a, role_id="r1", scope="team", scope_id="team-a")]
        return []

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_roles", side_effect=mock_get_roles):
            # Specific team_id provided: should use team-a regardless of token_teams
            result = await svc.check_permission("user@test.com", "tools.read", team_id="team-a", check_any_team=False, token_teams=["team-b"])  # Different from team_id
            assert result is True, "Specific team_id should override token_teams"
