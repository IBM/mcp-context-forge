# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_permission_service_token_narrowing.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for session-token team narrowing in PermissionService.

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
async def test_check_permission_public_only_token_blocks_team_perms(svc):
    """Public-only token (token_teams=[]) blocks ALL team permissions (Option A strict isolation).

    With Option A, token_teams=[] enforces strict isolation at BOTH layers:
    - Layer 1 (token scoping): filters visibility to public resources only
    - Layer 2 (RBAC): excludes ALL team-scoped roles, only global/personal remain

    This is defense-in-depth: even if Layer 1 has gaps, Layer 2 still blocks.
    """
    role = SimpleNamespace(
        name="team_admin",
        permissions=["teams.read", "teams.create"],
        get_effective_permissions=lambda: ["teams.read", "teams.create"],
    )
    user_role = SimpleNamespace(role=role, role_id="r1", scope="team", scope_id="team-a")

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_roles", return_value=[]):  # Empty because token_teams=[] filters out team roles
            # Public-only token blocks team permissions at Layer 2 (strict isolation)
            result = await svc.check_permission(
                "user@test.com",
                "teams.read",
                check_any_team=True,
                token_teams=[],
            )
            assert result is False, "Public-only token must block team permissions (Option A strict isolation)"


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
async def test_check_permission_public_only_token_retains_global_scope_perms(svc):
    """Public-only token (token_teams=[]) retains global-scope permissions.

    With Option A strict isolation, token_teams=[] excludes ALL team-scoped
    roles at Layer 2, but global-scope and personal-scope roles are preserved.
    A user with a global-scope role should still have those permissions.
    """
    role = SimpleNamespace(
        name="platform_admin",
        permissions=["tools.read"],
        get_effective_permissions=lambda: ["tools.read"],
    )
    user_role = SimpleNamespace(role=role, role_id="r1", scope="global", scope_id=None)

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_roles", return_value=[user_role]):
            # Public-only token retains global-scope permissions
            result = await svc.check_permission(
                "user@test.com",
                "tools.read",
                check_any_team=True,
                token_teams=[],
            )
            assert result is True, "Public-only token retains global-scope permissions"


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
async def test_check_permission_specific_team_id_validated_against_token_teams(svc):
    """check_permission with specific team_id validates it against token_teams."""
    role_a = SimpleNamespace(name="developer", permissions=["tools.read"], get_effective_permissions=lambda: ["tools.read"])

    def mock_get_roles(user_email, team_id, include_all_teams=False, token_teams=None):
        # Real _get_user_roles validates team_id against token_teams
        if token_teams is not None and (len(token_teams) == 0 or team_id not in token_teams):
            return []
        if team_id == "team-a":
            return [SimpleNamespace(role=role_a, role_id="r1", scope="team", scope_id="team-a")]
        return []

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_roles", side_effect=mock_get_roles):
            # Specific team_id=team-a but token narrowed to team-b: denied
            result_denied = await svc.check_permission("user@test.com", "tools.read", team_id="team-a", check_any_team=False, token_teams=["team-b"])
            assert result_denied is False, "team_id outside token_teams must be denied"

            # Clear cache before second check (different token_teams = different scenario)
            svc.clear_cache()

            # Specific team_id=team-a and token includes team-a: allowed
            result_allowed = await svc.check_permission("user@test.com", "tools.read", team_id="team-a", check_any_team=False, token_teams=["team-a", "team-b"])
            assert result_allowed is True, "team_id within token_teams should be allowed"


# ---------- Security Gap Fixes: Regression Tests ----------


@pytest.mark.asyncio
async def test_explicit_team_id_rejects_out_of_scope_team(svc, mock_db):
    """_get_user_roles rejects explicit team_id not in token_teams.

    Verifies that when a specific team_id is provided (e.g., from route path),
    the permission service validates it against token_teams and denies access
    if the team is not in scope.
    """
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

    # Request roles for team-b, but token is narrowed to team-a only
    result = await svc._get_user_roles("user@test.com", team_id="team-b", include_all_teams=False, token_teams=["team-a"])  # Explicit team_id from route  # Narrowed to team-a only

    # Should return empty list (access denied)
    assert result == [], "Should reject access to team-b when token is narrowed to team-a"


@pytest.mark.asyncio
async def test_explicit_team_id_allows_in_scope_team(svc, mock_db):
    """_get_user_roles allows explicit team_id when in token_teams."""
    role = SimpleNamespace(name="developer", permissions=["tools.read"], get_effective_permissions=lambda: ["tools.read"])
    user_role = SimpleNamespace(role=role, role_id="r1", scope="team", scope_id="team-a")
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = [user_role]

    # Request roles for team-a, token is narrowed to team-a
    result = await svc._get_user_roles("user@test.com", team_id="team-a", include_all_teams=False, token_teams=["team-a", "team-b"])  # Explicit team_id  # team-a is in scope

    # Should return roles (access allowed)
    assert len(result) > 0, "Should allow access to team-a when it's in token_teams"


@pytest.mark.asyncio
async def test_admin_bypass_suppressed_for_public_only_non_admin_perm(svc):
    """Admin bypass suppressed for token_teams=[] on non-admin.* permissions.

    With Option A strict isolation, a public-only token (token_teams=[]) should
    suppress admin bypass even for non-admin.* permissions like teams.read.
    """
    with patch.object(svc, "_is_user_admin", return_value=True):
        with patch.object(svc, "get_user_permissions", return_value=set()):
            # Admin user with public-only token trying to access teams.read
            result = await svc.check_permission("admin@test.com", "teams.read", token_teams=[], allow_admin_bypass=True)  # Non-admin.* permission  # Public-only token

            # Should be denied (admin bypass suppressed)
            assert result is False, "Admin bypass should be suppressed for token_teams=[] on non-admin.* perms"


@pytest.mark.asyncio
async def test_admin_bypass_works_for_narrowed_token(svc):
    """Admin bypass still works for narrowed (non-empty) tokens."""
    with patch.object(svc, "_is_user_admin", return_value=True):
        # Admin with narrowed token should still get admin bypass
        result = await svc.check_permission("admin@test.com", "teams.read", token_teams=["team-a"], allow_admin_bypass=True)  # Narrowed, not public-only

        # Should be allowed (admin bypass works)
        assert result is True, "Admin bypass should work for narrowed tokens"


@pytest.mark.asyncio
async def test_admin_bypass_works_for_unnarrowed_token(svc):
    """Admin bypass still works for un-narrowed tokens."""
    with patch.object(svc, "_is_user_admin", return_value=True):
        # Admin with un-narrowed token should get admin bypass
        result = await svc.check_permission("admin@test.com", "teams.read", token_teams=None, allow_admin_bypass=True)  # Un-narrowed

        # Should be allowed (admin bypass works)
        assert result is True, "Admin bypass should work for un-narrowed tokens"


@pytest.mark.asyncio
async def test_check_admin_permission_respects_token_teams(svc):
    """check_admin_permission respects token_teams parameter.

    Verifies that admin permission checks now accept and forward token_teams,
    preventing narrowed/public-only tokens from bypassing RBAC on admin routes.
    """
    admin_perms = ["admin.system_config", "admin.user_management"]

    # Mock get_user_permissions to return empty set when token_teams=[]
    # (simulating that team roles are filtered out for public-only tokens)
    async def mock_get_user_permissions(user_email, team_id=None, token_teams=None):
        if token_teams is not None and len(token_teams) == 0:
            return set()  # Public-only token: no team permissions
        return set(admin_perms)  # Otherwise return admin permissions

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", side_effect=mock_get_user_permissions):
            # Non-admin user with admin permissions via roles, but public-only token
            result = await svc.check_admin_permission("user@test.com", token_teams=[])  # Public-only token

            # Should be denied (token_teams=[] filters out team roles)
            assert result is False, "check_admin_permission should respect token_teams=[]"


@pytest.mark.asyncio
async def test_check_admin_permission_allows_with_proper_scope(svc):
    """check_admin_permission allows when token_teams is properly scoped."""
    admin_perms = ["admin.system_config"]

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value=set(admin_perms)):
            # User with admin permissions and properly scoped token
            result = await svc.check_admin_permission("user@test.com", token_teams=["team-a"])  # Narrowed token

            # Should be allowed
            assert result is True, "check_admin_permission should allow with proper token scope"


@pytest.mark.asyncio
async def test_public_only_token_excludes_all_team_roles(svc, mock_db):
    """token_teams=[] excludes ALL team-scoped roles at Layer 2.

    With Option A strict isolation, token_teams=[] should filter out all
    team-scoped roles, leaving only global and personal roles.
    """
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

    await svc._get_user_roles("user@test.com", team_id=None, include_all_teams=True, token_teams=[])

    # Verify query was executed
    assert mock_db.execute.called

    # Verify team-scoped roles are NOT included
    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))

    # Should NOT have is_personal check (which indicates team filtering)
    assert "is_personal" not in compiled, "token_teams=[] should exclude all team roles"

    # Should only have global and personal scopes
    assert "user_roles.scope = 'global'" in compiled, "Should include global scope"
    assert "user_roles.scope = 'personal'" in compiled, "Should include personal scope"


@pytest.mark.asyncio
async def test_narrowed_token_includes_specified_teams(svc, mock_db):
    """Non-empty token_teams includes only specified teams."""
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

    await svc._get_user_roles("user@test.com", team_id=None, include_all_teams=True, token_teams=["team-a"])

    # Verify query includes team filtering
    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))

    # Should have team filtering (is_personal check present)
    assert "is_personal" in compiled or "scope_id IN" in compiled, "Narrowed token should filter teams"


# ---------- Security Gap Fixes: Additional Regression Tests ----------


@pytest.mark.asyncio
async def test_explicit_team_id_rejects_public_only_token(svc, mock_db):
    """_get_user_roles excludes team-scoped roles when token_teams=[] (public-only).

    Public-only tokens must never access team-specific roles, even when an explicit
    team_id is provided.  Global and personal roles are still queried so that
    platform-wide permissions (e.g. teams.join via platform_viewer) remain available
    without granting membership-derived rights in the target team.
    """
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

    result = await svc._get_user_roles(
        "user@test.com",
        team_id="team-a",
        include_all_teams=False,
        token_teams=[],  # Public-only
    )

    assert result == [], "Public-only token must not return team-specific roles"

    # Global/personal roles are still queried — verify no team-scoped condition
    # for the out-of-scope team appears in the compiled query.
    assert mock_db.execute.called, "DB should be queried for global/personal roles"
    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))
    assert "team-a" not in compiled, "team-scoped roles for the out-of-scope team must not be queried"


@pytest.mark.asyncio
async def test_explicit_team_id_excludes_out_of_scope_narrowed_token(svc, mock_db):
    """_get_user_roles excludes team-scoped roles when team_id is outside narrowed token_teams.

    When token_teams=["team-a"] but team_id="team-b", team-scoped roles for
    team-b must not appear in the query.  Global and personal roles are still
    queried so that platform-wide permissions (e.g. teams.join) remain available.
    """
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

    result = await svc._get_user_roles(
        "user@test.com",
        team_id="team-b",
        include_all_teams=False,
        token_teams=["team-a"],  # Narrowed — team-b is out of scope
    )

    assert result == [], "Out-of-scope team must not return team-specific roles"

    # Global/personal roles are still queried — verify no team-scoped condition
    # for the out-of-scope team appears in the compiled query.
    assert mock_db.execute.called, "DB should be queried for global/personal roles"
    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))
    assert "team-b" not in compiled, "team-scoped roles for the out-of-scope team must not be queried"


@pytest.mark.asyncio
async def test_explicit_team_id_includes_team_roles_when_token_unrestricted(svc, mock_db):
    """_get_user_roles includes team-scoped roles when token_teams is None (unrestricted).

    Unrestricted tokens (token_teams=None) skip the narrowing guard entirely,
    so team-scoped roles for the explicit team_id must appear in the query.
    """
    role = SimpleNamespace(name="developer", permissions=["tools.read"], get_effective_permissions=lambda: ["tools.read"])
    team_user_role = SimpleNamespace(role=role, role_id="r1", scope="team", scope_id="team-a")
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = [team_user_role]

    result = await svc._get_user_roles(
        "user@test.com",
        team_id="team-a",
        include_all_teams=False,
        token_teams=None,  # Unrestricted
    )

    assert len(result) == 1
    assert result[0].scope == "team"
    assert result[0].scope_id == "team-a"

    # Verify the compiled query includes team-scoped condition for team-a
    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))
    assert "team-a" in compiled, "Unrestricted token must include team-scoped roles for the requested team"


@pytest.mark.asyncio
async def test_has_admin_permission_suppresses_bypass_for_public_only(svc):
    """has_admin_permission suppresses admin bypass for token_teams=[].

    This covers the AdminAuthMiddleware path through has_admin_permission
    (distinct from check_admin_permission).
    """
    with patch.object(svc, "_is_user_admin", return_value=True):
        with patch.object(svc, "get_user_permissions", return_value=set()):
            result = await svc.has_admin_permission(
                "admin@test.com",
                token_teams=[],  # Public-only
            )
            assert result is False, "has_admin_permission should suppress bypass for public-only tokens"


@pytest.mark.asyncio
async def test_has_admin_permission_works_for_narrowed_token(svc):
    """has_admin_permission works normally for narrowed tokens."""
    with patch.object(svc, "_is_user_admin", return_value=True):
        result = await svc.has_admin_permission(
            "admin@test.com",
            token_teams=["team-a"],  # Narrowed, not public-only
        )
        assert result is True, "has_admin_permission should work for narrowed tokens"


@pytest.mark.asyncio
async def test_has_admin_permission_forwards_token_teams(svc):
    """has_admin_permission forwards token_teams to get_user_permissions."""
    admin_perms = {"admin.dashboard"}

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value=admin_perms) as mock_get_perms:
            await svc.has_admin_permission("user@test.com", token_teams=["team-a"])
            mock_get_perms.assert_called_once_with("user@test.com", team_id=None, token_teams=["team-a"])


# ---------- Codex Review Findings: Regression Tests ----------


@pytest.mark.asyncio
async def test_cache_key_isolation_none_vs_empty(svc):
    """Cache keys must differ for token_teams=None vs token_teams=[] (Finding 4).

    Without proper isolation, a cached result for an un-narrowed request
    (token_teams=None) could be returned for a public-only request
    (token_teams=[]), leaking broader permissions.
    """
    broad_perms = {"admin.dashboard", "tools.read", "teams.manage"}
    public_perms = set()  # Public-only should get nothing from team roles

    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_roles", return_value=[]) as mock_roles:
            # First call: un-narrowed (token_teams=None)
            mock_roles.return_value = [
                SimpleNamespace(
                    role=SimpleNamespace(name="admin", permissions=list(broad_perms), get_effective_permissions=lambda: list(broad_perms)),
                    role_id="r1",
                    scope="team",
                    scope_id="team-a",
                )
            ]
            result_none = await svc.get_user_permissions("user@test.com", include_all_teams=True, token_teams=None)

            # Second call: public-only (token_teams=[]) — must NOT reuse first cache entry
            mock_roles.return_value = []
            result_empty = await svc.get_user_permissions("user@test.com", include_all_teams=True, token_teams=[])

            assert result_none != result_empty or result_empty == set(), "Cache must isolate token_teams=None from token_teams=[]"
            assert mock_roles.call_count == 2, "Both calls must query (not share cache)"


@pytest.mark.asyncio
async def test_cache_key_isolation_team_id_with_different_token_teams(svc):
    """Cache keys for team_id lookups must differ across token_teams values (Finding 4)."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_roles", return_value=[]) as mock_roles:
            await svc.get_user_permissions("user@test.com", team_id="team-a", token_teams=None)
            await svc.get_user_permissions("user@test.com", team_id="team-a", token_teams=[])
            await svc.get_user_permissions("user@test.com", team_id="team-a", token_teams=["team-a"])

            assert mock_roles.call_count == 3, "Each token_teams variant must produce a distinct cache key"


@pytest.mark.asyncio
async def test_public_only_excludes_scope_id_null_team_roles(svc, mock_db):
    """token_teams=[] must exclude team roles with scope_id=NULL (Finding 2).

    Roles with scope='team', scope_id=NULL apply to all teams. Public-only
    tokens must not access these under strict isolation.
    """
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

    await svc._get_user_roles("user@test.com", team_id=None, include_all_teams=False, token_teams=[])

    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))

    # The compiled query must NOT include scope='team' conditions when token_teams=[]
    assert "scope = 'team'" not in compiled.lower().replace('"', "'"), "Public-only token must exclude all team-scoped roles including scope_id=NULL"
