# -*- coding: utf-8 -*-
"""Unit tests for PermissionService."""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.permission_service import PermissionService


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []
    db.execute.return_value.scalars.return_value.all.return_value = []
    return db


@pytest.fixture
def svc(mock_db):
    return PermissionService(mock_db, audit_enabled=False)


# ---------- Construction ----------


def test_init_defaults(mock_db):
    """PermissionService initializes with audit from settings."""
    with patch("mcpgateway.services.permission_service.settings") as m:
        m.permission_audit_enabled = True
        s = PermissionService(mock_db)
    assert s.audit_enabled is True


def test_init_explicit_audit(mock_db):
    """PermissionService accepts explicit audit_enabled."""
    s = PermissionService(mock_db, audit_enabled=False)
    assert s.audit_enabled is False


# ---------- Cache ----------


def test_clear_user_cache(svc):
    """clear_user_cache removes only matching keys."""
    svc._permission_cache = {"alice:global": {"tools.read"}, "bob:team1": {"*"}}
    svc._roles_cache = {"alice:global": [], "bob:team1": []}
    svc._cache_timestamps = {"alice:global": datetime.now(tz=timezone.utc), "bob:team1": datetime.now(tz=timezone.utc)}

    svc.clear_user_cache("alice")

    assert "alice:global" not in svc._permission_cache
    assert "bob:team1" in svc._permission_cache


def test_clear_cache(svc):
    """clear_cache removes everything."""
    svc._permission_cache = {"a:b": {"p"}}
    svc._roles_cache = {"a:b": []}
    svc._cache_timestamps = {"a:b": datetime.now(tz=timezone.utc)}

    svc.clear_cache()

    assert svc._permission_cache == {}
    assert svc._roles_cache == {}
    assert svc._cache_timestamps == {}


def test_is_cache_valid_missing(svc):
    """Cache miss returns False."""
    assert svc._is_cache_valid("nonexistent") is False


def test_is_cache_valid_no_timestamp(svc):
    """Cache present but no timestamp returns False."""
    svc._permission_cache = {"key": {"perm"}}
    assert svc._is_cache_valid("key") is False


def test_is_cache_valid_expired(svc):
    """Expired cache returns False."""
    svc._permission_cache = {"key": {"perm"}}
    svc._cache_timestamps = {"key": datetime.now(tz=timezone.utc) - timedelta(seconds=9999)}
    assert svc._is_cache_valid("key") is False


def test_is_cache_valid_fresh(svc):
    """Fresh cache returns True."""
    svc._permission_cache = {"key": {"perm"}}
    svc._cache_timestamps = {"key": datetime.now(tz=timezone.utc)}
    assert svc._is_cache_valid("key") is True


# ---------- _is_user_admin ----------


@pytest.mark.asyncio
async def test_is_user_admin_platform_admin(svc):
    """Platform admin email is recognized as admin."""
    # is_user_admin is read from mcpgateway.utils.admin_check now (shared
    # helper unifying Layer 1 and Layer 2 admin detection).
    with patch("mcpgateway.config.settings") as m:
        m.platform_admin_email = "admin@system.com"
        result = await svc._is_user_admin("admin@system.com")
    assert result is True


@pytest.mark.asyncio
async def test_is_user_admin_db_admin(svc, mock_db):
    """DB user with is_admin=True is admin."""
    user = SimpleNamespace(is_admin=True)
    mock_db.execute.return_value.scalar_one_or_none.return_value = user
    with patch("mcpgateway.config.settings") as m:
        m.platform_admin_email = ""
        result = await svc._is_user_admin("admin@test.com")
    assert result is True


@pytest.mark.asyncio
async def test_is_user_admin_regular_user(svc, mock_db):
    """Regular user is not admin."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(is_admin=False)
    with patch("mcpgateway.config.settings") as m:
        m.platform_admin_email = ""
        result = await svc._is_user_admin("user@test.com")
    assert result is False


@pytest.mark.asyncio
async def test_is_user_admin_no_user(svc, mock_db):
    """Non-existent user is not admin."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    with patch("mcpgateway.config.settings") as m:
        m.platform_admin_email = ""
        result = await svc._is_user_admin("nobody@test.com")
    assert result is False


# ---------- check_permission ----------


@pytest.mark.asyncio
async def test_check_permission_admin_bypass(svc):
    """Admin user bypasses all permission checks."""
    with patch.object(svc, "_is_user_admin", return_value=True):
        result = await svc.check_permission("admin@test.com", "tools.create")
    assert result is True


@pytest.mark.asyncio
async def test_check_permission_public_only_token_blocks_admin_permissions(svc):
    """Public-only token scope must deny admin.* permissions even for admin identities."""
    with patch.object(svc, "_is_user_admin", return_value=True):
        result = await svc.check_permission("admin@test.com", "admin.system_config", token_teams=[])
    assert result is False


@pytest.mark.asyncio
async def test_check_permission_has_exact_perm(svc):
    """User with exact permission gets access."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value={"tools.create", "tools.read"}):
            result = await svc.check_permission("user@test.com", "tools.create")
    assert result is True


@pytest.mark.asyncio
async def test_check_permission_has_wildcard(svc):
    """User with wildcard permission gets access."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value={"*"}):
            result = await svc.check_permission("user@test.com", "tools.create")
    assert result is True


@pytest.mark.asyncio
async def test_check_permission_denied(svc):
    """User without permission is denied."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value={"tools.read"}):
            result = await svc.check_permission("user@test.com", "tools.create")
    assert result is False


@pytest.mark.asyncio
async def test_check_permission_team_fallback(svc):
    """teams.* permissions require explicit RBAC grants."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value=set()):
            with patch.object(svc, "_check_team_fallback_permissions") as mock_fallback:
                result = await svc.check_permission("user@test.com", "teams.read")
    assert result is False
    mock_fallback.assert_not_called()


@pytest.mark.asyncio
async def test_check_permission_token_fallback(svc):
    """tokens.* permissions require explicit RBAC grants."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value=set()):
            with patch.object(svc, "_check_token_fallback_permissions") as mock_fallback:
                result = await svc.check_permission("user@test.com", "tokens.create")
    assert result is False
    mock_fallback.assert_not_called()


@pytest.mark.asyncio
async def test_check_permission_with_audit(mock_db):
    """Permission check with audit logging enabled."""
    svc = PermissionService(mock_db, audit_enabled=True)
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value={"tools.read"}):
            with patch.object(svc, "_get_roles_for_audit", return_value={"roles": []}):
                with patch.object(svc, "_log_permission_check") as mock_log:
                    result = await svc.check_permission("user@test.com", "tools.read")
    assert result is True
    mock_log.assert_called_once()


@pytest.mark.asyncio
async def test_check_permission_no_admin_bypass(svc):
    """allow_admin_bypass=False forces explicit permission check."""
    with patch.object(svc, "_is_user_admin", return_value=True):
        with patch.object(svc, "get_user_permissions", return_value=set()):
            result = await svc.check_permission("admin@test.com", "tools.create", allow_admin_bypass=False)
    assert result is False


@pytest.mark.asyncio
async def test_check_permission_exception_denies(svc):
    """Exception during permission check defaults to deny."""
    with patch.object(svc, "_is_user_admin", side_effect=RuntimeError("db error")):
        result = await svc.check_permission("user@test.com", "tools.create")
    assert result is False


# ---------- has_admin_permission ----------


@pytest.mark.asyncio
async def test_has_admin_permission_db_admin(svc):
    """DB admin is detected."""
    with patch.object(svc, "_is_user_admin", return_value=True):
        assert await svc.has_admin_permission("admin@test.com") is True


@pytest.mark.asyncio
async def test_has_admin_permission_wildcard(svc):
    """Wildcard permission grants admin."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value={"*"}):
            assert await svc.has_admin_permission("user@test.com") is True


@pytest.mark.asyncio
async def test_has_admin_permission_admin_perm(svc):
    """admin.* permission grants admin."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value={"admin.system_config", "tools.read"}):
            assert await svc.has_admin_permission("user@test.com") is True


@pytest.mark.asyncio
async def test_has_admin_permission_none(svc):
    """No admin permissions → not admin."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value={"tools.read"}):
            assert await svc.has_admin_permission("user@test.com") is False


@pytest.mark.asyncio
async def test_has_admin_permission_exception(svc):
    """Exception defaults to not admin."""
    with patch.object(svc, "_is_user_admin", side_effect=RuntimeError("err")):
        assert await svc.has_admin_permission("user@test.com") is False


@pytest.mark.asyncio
async def test_has_admin_permission_with_team_id(svc):
    """Team-scoped admin.dashboard grants admin when team_id is provided."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value={"admin.dashboard", "tools.read"}) as mock_get_perms:
            assert await svc.has_admin_permission("user@test.com", team_id="team-123") is True
            mock_get_perms.assert_awaited_once_with("user@test.com", team_id="team-123", token_teams=None)


@pytest.mark.asyncio
async def test_has_admin_permission_no_team_id_no_admin_perm(svc):
    """Without team_id, team-scoped permissions are not checked (global only)."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value={"tools.read"}) as mock_get_perms:
            assert await svc.has_admin_permission("user@test.com") is False
            mock_get_perms.assert_awaited_once_with("user@test.com", team_id=None, token_teams=None)


# ---------- get_user_permissions ----------


@pytest.mark.asyncio
async def test_get_user_permissions_cached(svc):
    """Cached permissions are returned without DB query."""
    svc._permission_cache = {"user@test.com:global": {"tools.read"}}
    svc._cache_timestamps = {"user@test.com:global": datetime.now(tz=timezone.utc)}
    result = await svc.get_user_permissions("user@test.com")
    assert result == {"tools.read"}


@pytest.mark.asyncio
async def test_get_user_permissions_from_roles(svc):
    """Permissions are collected from user roles."""
    role = SimpleNamespace(name="test_role", permissions=["tools.read", "tools.create"], get_effective_permissions=lambda: ["tools.read", "tools.create"])
    user_role = SimpleNamespace(role=role, role_id="r1", scope="global", scope_id=None)
    with patch.object(svc, "_get_user_roles", return_value=[user_role]):
        result = await svc.get_user_permissions("user@test.com")
    assert "tools.read" in result
    assert "tools.create" in result


@pytest.mark.asyncio
async def test_get_user_permissions_any_team_cache_key(svc):
    """include_all_teams uses separate cache key."""
    role = SimpleNamespace(name="team_role", permissions=["teams.read"], get_effective_permissions=lambda: ["teams.read"])
    user_role = SimpleNamespace(role=role, role_id="r1", scope="team", scope_id="t1")
    with patch.object(svc, "_get_user_roles", return_value=[user_role]):
        result = await svc.get_user_permissions("user@test.com", include_all_teams=True)
    assert "user@test.com:__anyteam__" in svc._permission_cache


# ---------- get_user_roles ----------


@pytest.mark.asyncio
async def test_get_user_roles_basic(svc, mock_db):
    """get_user_roles returns DB results."""
    mock_db.execute.return_value.scalars.return_value.all.return_value = ["role1"]
    roles = await svc.get_user_roles("user@test.com")
    assert roles == ["role1"]


@pytest.mark.asyncio
async def test_get_user_roles_with_scope(svc, mock_db):
    """get_user_roles with scope filter."""
    mock_db.execute.return_value.scalars.return_value.all.return_value = []
    roles = await svc.get_user_roles("user@test.com", scope="team", team_id="t1")
    assert roles == []


@pytest.mark.asyncio
async def test_get_user_roles_include_all_teams(svc, mock_db):
    """_get_user_roles with include_all_teams=True."""
    mock_db.execute.return_value.scalars.return_value.all.return_value = []
    roles = await svc._get_user_roles("user@test.com", team_id=None, include_all_teams=True)
    assert roles == []


@pytest.mark.asyncio
async def test_get_user_roles_include_all_teams_excludes_personal_teams(svc, mock_db):
    """_get_user_roles with include_all_teams=True excludes personal team roles.

    Every user gets a personal team with team_admin role auto-assigned.
    When aggregating permissions via check_any_team=True, personal team
    roles must be excluded to prevent all users from inheriting team_admin
    permissions (servers.create, tools.create, etc.).
    """

    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []
    await svc._get_user_roles("user@test.com", team_id=None, include_all_teams=True)

    # Verify the query was executed (the important thing is it doesn't crash)
    assert mock_db.execute.called

    # Verify the SQL contains a subquery filtering personal teams
    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))
    # The query should reference email_teams.is_personal to exclude personal teams
    assert "is_personal" in compiled, f"Query should filter personal teams: {compiled}"


@pytest.mark.asyncio
async def test_get_user_roles_specific_team_does_not_exclude_personal(svc, mock_db):
    """_get_user_roles with specific team_id does NOT exclude personal teams.

    When a specific team_id is provided (direct team context), the query
    should include that team's roles even if it's a personal team.
    """
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []
    await svc._get_user_roles("user@test.com", team_id="personal-team-123", include_all_teams=False)

    query_arg = mock_db.execute.call_args[0][0]
    compiled = str(query_arg.compile(compile_kwargs={"literal_binds": True}))
    # When a specific team_id is provided, personal teams should NOT be filtered
    assert "is_personal" not in compiled, f"Specific team query should not filter personal teams: {compiled}"


@pytest.mark.asyncio
async def test_check_permission_check_any_team_excludes_personal_team_roles(svc, mock_db):
    """check_permission with check_any_team=True denies viewer despite personal team_admin.

    This is the core regression test for the RBAC bypass where viewers could
    create servers because their personal team's team_admin role granted
    servers.create via check_any_team aggregation.
    """
    # Simulate: viewer has only platform_viewer (global) + viewer (team-scoped on real team)
    # The personal team's team_admin role should be excluded by the fix
    viewer_role = SimpleNamespace(
        name="viewer",
        permissions=["servers.read", "tools.read"],
        get_effective_permissions=lambda: ["servers.read", "tools.read"],
    )
    user_role = SimpleNamespace(role=viewer_role, role_id="r1", scope="team", scope_id="real-team-123")

    with patch.object(svc, "_is_user_admin", return_value=False), patch.object(svc, "_get_user_roles", return_value=[user_role]):
        granted = await svc.check_permission(
            user_email="viewer@test.com",
            permission="servers.create",
            check_any_team=True,
            allow_admin_bypass=True,
        )
    assert granted is False, "Viewer should NOT be able to create servers even with check_any_team=True"


@pytest.mark.asyncio
async def test_get_user_roles_include_expired(svc, mock_db):
    """get_user_roles with include_expired."""
    mock_db.execute.return_value.scalars.return_value.all.return_value = []
    roles = await svc.get_user_roles("user@test.com", include_expired=True)
    assert roles == []


# ---------- has_permission_on_resource ----------


@pytest.mark.asyncio
async def test_has_permission_on_resource_granted(svc):
    """Resource permission check delegates to check_permission."""
    with patch.object(svc, "check_permission", return_value=True):
        result = await svc.has_permission_on_resource("user@test.com", "tools.read", "tool", "t1")
    assert result is True


@pytest.mark.asyncio
async def test_has_permission_on_resource_denied(svc):
    """Resource permission denied."""
    with patch.object(svc, "check_permission", return_value=False):
        result = await svc.has_permission_on_resource("user@test.com", "tools.create", "tool", "t1")
    assert result is False


# ---------- check_resource_ownership ----------


@pytest.mark.asyncio
async def test_check_resource_ownership_admin(svc):
    """Admin bypasses ownership check."""
    with patch.object(svc, "_is_user_admin", return_value=True):
        result = await svc.check_resource_ownership("admin@test.com", SimpleNamespace())
    assert result is True


@pytest.mark.asyncio
async def test_check_resource_ownership_owner(svc):
    """Direct owner matches."""
    resource = SimpleNamespace(owner_email="user@test.com")
    with patch.object(svc, "_is_user_admin", return_value=False):
        result = await svc.check_resource_ownership("user@test.com", resource)
    assert result is True


@pytest.mark.asyncio
async def test_check_resource_ownership_team_admin(svc):
    """Team owner gets ownership on team resources."""
    resource = SimpleNamespace(owner_email="other@test.com", visibility="team", team_id="t1")
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_team_role", return_value="owner"):
            result = await svc.check_resource_ownership("user@test.com", resource)
    assert result is True


@pytest.mark.asyncio
async def test_check_resource_ownership_team_member_denied(svc):
    """Team member (not owner) is denied."""
    resource = SimpleNamespace(owner_email="other@test.com", visibility="team", team_id="t1")
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "_get_user_team_role", return_value="member"):
            result = await svc.check_resource_ownership("user@test.com", resource)
    assert result is False


@pytest.mark.asyncio
async def test_check_resource_ownership_no_team_admin_flag(svc):
    """allow_team_admin=False skips team check."""
    resource = SimpleNamespace(owner_email="other@test.com", visibility="team", team_id="t1")
    with patch.object(svc, "_is_user_admin", return_value=False):
        result = await svc.check_resource_ownership("user@test.com", resource, allow_team_admin=False)
    assert result is False


# ---------- check_admin_permission ----------


@pytest.mark.asyncio
async def test_check_admin_permission_is_admin(svc):
    """DB admin returns True."""
    with patch.object(svc, "_is_user_admin", return_value=True):
        assert await svc.check_admin_permission("admin@test.com") is True


@pytest.mark.asyncio
async def test_check_admin_permission_has_system_config(svc):
    """admin.system_config grants admin."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value={"admin.system_config"}):
            assert await svc.check_admin_permission("user@test.com") is True


@pytest.mark.asyncio
async def test_check_admin_permission_no_admin_perms(svc):
    """No admin permissions → False."""
    with patch.object(svc, "_is_user_admin", return_value=False):
        with patch.object(svc, "get_user_permissions", return_value={"tools.read"}):
            assert await svc.check_admin_permission("user@test.com") is False


# ---------- Team fallback permissions ----------


@pytest.mark.asyncio
async def test_team_fallback_no_team_create(svc):
    """Without team_id, teams.create is allowed."""
    result = await svc._check_team_fallback_permissions("user@test.com", "teams.create", None)
    assert result is True


@pytest.mark.asyncio
async def test_team_fallback_no_team_read(svc):
    """Without team_id, teams.read is allowed."""
    result = await svc._check_team_fallback_permissions("user@test.com", "teams.read", None)
    assert result is True


@pytest.mark.asyncio
async def test_team_fallback_no_team_delete_denied(svc):
    """Without team_id, teams.delete is denied."""
    result = await svc._check_team_fallback_permissions("user@test.com", "teams.delete", None)
    assert result is False


@pytest.mark.asyncio
async def test_team_fallback_owner(svc):
    """Team owner gets full permissions."""
    with patch.object(svc, "_get_user_team_role", return_value="owner"):
        for perm in ["teams.read", "teams.update", "teams.delete", "teams.manage_members"]:
            result = await svc._check_team_fallback_permissions("user@test.com", perm, "t1")
            assert result is True, f"Owner should have {perm}"


@pytest.mark.asyncio
async def test_team_fallback_member(svc):
    """Team member gets only read."""
    with patch.object(svc, "_get_user_team_role", return_value="member"):
        assert await svc._check_team_fallback_permissions("user@test.com", "teams.read", "t1") is True
        assert await svc._check_team_fallback_permissions("user@test.com", "teams.update", "t1") is False


@pytest.mark.asyncio
async def test_team_fallback_not_member(svc):
    """Non-member is denied."""
    with patch.object(svc, "_get_user_team_role", return_value=None):
        result = await svc._check_team_fallback_permissions("user@test.com", "teams.read", "t1")
    assert result is False


# ---------- Token fallback permissions ----------


@pytest.mark.asyncio
async def test_token_fallback_allowed(svc):
    """Token self-management permissions are allowed."""
    for perm in ["tokens.create", "tokens.read", "tokens.update", "tokens.revoke"]:
        result = await svc._check_token_fallback_permissions("user@test.com", perm)
        assert result is True


@pytest.mark.asyncio
async def test_token_fallback_denied(svc):
    """Non-token permissions are denied."""
    result = await svc._check_token_fallback_permissions("user@test.com", "tokens.admin")
    assert result is False


# ---------- _get_user_team_role ----------


@pytest.mark.asyncio
async def test_get_user_team_role_found(svc, mock_db):
    """Team member role returned."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(role="owner")
    result = await svc._get_user_team_role("user@test.com", "t1")
    assert result == "owner"


@pytest.mark.asyncio
async def test_get_user_team_role_not_found(svc, mock_db):
    """Non-member returns None."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    result = await svc._get_user_team_role("user@test.com", "t1")
    assert result is None


# ---------- _is_team_member ----------


@pytest.mark.asyncio
async def test_is_team_member_yes(svc):
    """Member is detected."""
    with patch.object(svc, "_get_user_team_role", return_value="member"):
        assert await svc._is_team_member("user@test.com", "t1") is True


@pytest.mark.asyncio
async def test_is_team_member_no(svc):
    """Non-member is detected."""
    with patch.object(svc, "_get_user_team_role", return_value=None):
        assert await svc._is_team_member("user@test.com", "t1") is False


# ---------- _log_permission_check ----------


@pytest.mark.asyncio
async def test_log_permission_check(svc, mock_db):
    """Audit log is created and committed."""
    await svc._log_permission_check(
        user_email="user@test.com",
        permission="tools.read",
        resource_type="tool",
        resource_id="t1",
        team_id="team1",
        granted=True,
        roles_checked={"roles": []},
        ip_address="1.2.3.4",
        user_agent="test",
    )
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


# ---------- Token narrowing regression tests (PR #3932 fix) ----------


@pytest.mark.asyncio
async def test_get_user_roles_out_of_scope_team_preserves_global_roles(svc, mock_db):
    """Out-of-scope team_id should still return global roles (regression test for PR #3932)."""
    global_role = SimpleNamespace(
        name="platform_viewer",
        permissions=["servers.read", "tools.read"],
        get_effective_permissions=lambda: ["servers.read", "tools.read"],
    )
    global_user_role = SimpleNamespace(role=global_role, role_id="r1", scope="global", scope_id=None)

    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = [global_user_role]

    # User has token scoped to team-a, but requests roles for team-b (out of scope)
    roles = await svc._get_user_roles("user@test.com", team_id="team-b", token_teams=["team-a"])

    # Team-scoped roles for team-b are excluded, but global roles are preserved
    assert len(roles) == 1
    assert roles[0].scope == "global"


@pytest.mark.asyncio
async def test_get_user_roles_out_of_scope_team_preserves_personal_roles(svc, mock_db):
    """Out-of-scope team_id should still return personal roles (regression test for PR #3932)."""
    personal_role = SimpleNamespace(
        name="personal_role",
        permissions=["tools.read"],
        get_effective_permissions=lambda: ["tools.read"],
    )
    personal_user_role = SimpleNamespace(role=personal_role, role_id="r2", scope="personal", scope_id="user@test.com")

    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = [personal_user_role]

    # User has token scoped to team-a, but requests roles for team-b (out of scope)
    roles = await svc._get_user_roles("user@test.com", team_id="team-b", token_teams=["team-a"])

    # Should still return personal roles
    assert len(roles) == 1
    assert roles[0].scope == "personal"


@pytest.mark.asyncio
async def test_get_user_roles_out_of_scope_team_excludes_team_roles(svc, mock_db):
    """Out-of-scope team_id should exclude team-scoped roles (security invariant)."""
    # Mock returns no roles because team-scoped roles are filtered out
    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []

    # User has token scoped to team-a, but requests roles for team-b (out of scope)
    roles = await svc._get_user_roles("user@test.com", team_id="team-b", token_teams=["team-a"])

    # Should return empty because no global/personal roles exist and team roles are excluded
    assert len(roles) == 0


@pytest.mark.asyncio
async def test_get_user_roles_public_only_token_with_team_id_returns_global_personal_only(svc, mock_db):
    """Public-only token (token_teams=[]) with team_id should return only global/personal roles."""
    global_role = SimpleNamespace(
        name="platform_viewer",
        permissions=["servers.read"],
        get_effective_permissions=lambda: ["servers.read"],
    )
    global_user_role = SimpleNamespace(role=global_role, role_id="r1", scope="global", scope_id=None)

    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = [global_user_role]

    # Public-only token with team_id should exclude team roles but keep global/personal
    roles = await svc._get_user_roles("user@test.com", team_id="team-a", token_teams=[])

    # Team-scoped roles are excluded, but global/personal roles are still returned
    assert len(roles) == 1
    assert roles[0].scope == "global"


@pytest.mark.asyncio
async def test_get_user_roles_in_scope_team_includes_team_roles(svc, mock_db):
    """In-scope team_id should include team-scoped roles."""
    team_role = SimpleNamespace(
        name="team_admin",
        permissions=["servers.create", "tools.create"],
        get_effective_permissions=lambda: ["servers.create", "tools.create"],
    )
    team_user_role = SimpleNamespace(role=team_role, role_id="r3", scope="team", scope_id="team-a")

    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = [team_user_role]

    # User has token scoped to team-a and requests roles for team-a (in scope)
    roles = await svc._get_user_roles("user@test.com", team_id="team-a", token_teams=["team-a"])

    # Should include team-scoped roles
    assert len(roles) == 1
    assert roles[0].scope == "team"
    assert roles[0].scope_id == "team-a"


@pytest.mark.asyncio
async def test_check_permission_join_endpoint_with_global_role(svc, mock_db):
    """Join endpoint should work with global roles even when team_id is out of scope (regression test)."""
    global_role = SimpleNamespace(
        name="platform_viewer",
        permissions=["teams.join"],
        get_effective_permissions=lambda: ["teams.join"],
    )
    global_user_role = SimpleNamespace(role=global_role, role_id="r1", scope="global", scope_id=None)

    mock_db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = [global_user_role]

    with patch.object(svc, "_is_user_admin", return_value=False):
        # User with API token (token_teams=[]) tries to join team-a
        # Before fix: _get_user_roles returned [], so no permissions
        # After fix: _get_user_roles returns global roles, so teams.join is granted
        granted = await svc.check_permission(
            user_email="user@test.com",
            permission="teams.join",
            team_id="team-a",
            token_teams=[],  # Public-only token
        )

    assert granted is True, "User with global teams.join permission should be able to join teams"


# ---------- _get_roles_for_audit ----------


def test_get_roles_for_audit_cached(svc):
    """Uses cached roles for audit."""
    role = SimpleNamespace(name="viewer", permissions=["tools.read"])
    user_role = SimpleNamespace(role_id="r1", role=role, scope="global")
    svc._roles_cache = {"user@test.com:global": [user_role]}

    result = svc._get_roles_for_audit("user@test.com", None)
    assert len(result["roles"]) == 1
    assert result["roles"][0]["name"] == "viewer"


def test_get_roles_for_audit_empty(svc):
    """Empty cache returns empty roles."""
    result = svc._get_roles_for_audit("user@test.com", None)
    assert result == {"roles": []}
