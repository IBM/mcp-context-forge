# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_rbac_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope behavior in the RBAC role handler bodies.

Imported WITHOUT patch_rbac_decorators so handler-body logic runs for real.
Decorator behaviour itself is covered by
tests/unit/mcpgateway/middleware/test_global_scope_helpers.py, and the fact that
specific routes carry the guard is covered by
tests/unit/mcpgateway/test_global_record_scope.py.
"""

# Standard
from datetime import datetime, timezone
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest

# `test_rbac_router.py` (and any other suite using patch_rbac_decorators) imports
# this same module while `mcpgateway.middleware.rbac.require_global_admin_permission`
# is monkeypatched to a no-op. Because Python caches modules in sys.modules, if that
# import happens first in the test session (e.g. collected alphabetically ahead of
# this file), `create_role`/`update_role`/`delete_role` end up permanently decorated
# with the mock — restoring the patched attribute afterwards can't retroactively
# re-decorate functions already bound at import time. Drop any cached entry and
# re-import so this file always exercises freshly-applied, real decorators,
# regardless of collection order. This intentionally does NOT reuse
# `importlib.reload`, which would mutate the *same* module object other test
# files (e.g. test_rbac_router.py) already hold a reference to and corrupt their
# mocked state; popping + re-importing rebinds `sys.modules` to a brand new
# module object instead, leaving any existing references untouched.
sys.modules.pop("mcpgateway.routers.rbac", None)

# First-Party
rbac_router = importlib.import_module("mcpgateway.routers.rbac")
from mcpgateway.db import UserRole  # noqa: E402
from tests.helpers.scope import admin_user_context, scoped_request  # noqa: E402


def test_module_imports_with_real_decorators():
    """Guard against this file accidentally being imported under the mocks."""
    assert rbac_router.create_role.__mcpgateway_scope_class__ == "global_only"
    assert rbac_router.update_role.__mcpgateway_scope_class__ == "global_only"
    assert rbac_router.delete_role.__mcpgateway_scope_class__ == "global_only"


_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _jwt_scoped_request(token_teams, path):
    """Build a ``scoped_request`` that also carries a verified JWT payload.

    ``list_roles``/``get_role`` call ``get_scoped_resource_access_context``
    (unlike the decorator-gated handlers, which read ``request.state.token_teams``
    directly via ``get_token_teams_from_request``). Without a verified JWT payload
    cached on ``request.state``, ``get_scoped_resource_access_context`` treats the
    caller as a non-JWT dev-mode/basic-auth admin and grants unconditional bypass
    (see ``_has_verified_jwt_payload`` / the fallback-admin branch in
    ``mcpgateway.auth_context.get_scoped_resource_access_context``) regardless of
    ``token_teams`` — that carve-out is intentional for dev-mode callers but wrong
    for simulating a real narrowed admin session token here. Setting
    ``_jwt_verified_payload`` makes this fixture exercise the same verified-token
    code path a real narrowed admin session hits in production.

    Args:
        token_teams: ``None`` for unrestricted, ``[]`` for public-only, or a list of team IDs.
        path: Route path passed through to ``scoped_request``.

    Returns:
        MagicMock: Request stub with a verified JWT payload in addition to ``scoped_request``'s state.
    """
    request = scoped_request(token_teams, path=path)
    request.state._jwt_verified_payload = ("token", {"is_admin": True, "teams": token_teams})
    return request


def _role_row(role_id, name, scope):
    """Build a row satisfying every RoleResponse field."""
    return SimpleNamespace(
        id=role_id,
        name=name,
        description="d",
        scope=scope,
        permissions=[],
        effective_permissions=[],
        inherits_from=None,
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.mark.asyncio
async def test_list_roles_hides_global_roles_from_narrowed_admin(monkeypatch):
    """Narrowed admins see non-global roles only — a 403 here would break the UI role picker."""
    rows = [_role_row("1", "platform_admin", "global"), _role_row("2", "team_admin", "team")]
    monkeypatch.setattr("mcpgateway.services.role_service.RoleService.list_roles", AsyncMock(return_value=rows))

    result = await rbac_router.list_roles(
        request=_jwt_scoped_request(["team-a"], path="/rbac/roles"),
        user=admin_user_context(["team-a"]),
        db=MagicMock(),
    )

    assert {r.scope for r in result} == {"team"}


@pytest.mark.asyncio
async def test_list_roles_shows_everything_to_unrestricted_admin(monkeypatch):
    rows = [_role_row("1", "platform_admin", "global"), _role_row("2", "team_admin", "team")]
    monkeypatch.setattr("mcpgateway.services.role_service.RoleService.list_roles", AsyncMock(return_value=rows))

    result = await rbac_router.list_roles(
        request=_jwt_scoped_request(None, path="/rbac/roles"),
        user=admin_user_context(None),
        db=MagicMock(),
    )

    assert len(result) == 2


def _user_role_row(role_id, scope, scope_id=None):
    """Build a row satisfying every UserRoleResponse field."""
    return SimpleNamespace(
        id=f"ur-{role_id}",
        user_email="member@example.com",
        role_id=role_id,
        role_name=role_id,
        scope=scope,
        scope_id=scope_id,
        granted_by="admin@example.com",
        granted_at=_NOW,
        expires_at=None,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_get_user_roles_hides_global_assignment_from_narrowed_admin(monkeypatch):
    """A narrowed admin must not enumerate who holds a global role assignment (e.g. platform_admin)."""
    rows = [_user_role_row("platform_admin", "global"), _user_role_row("team_admin", "team", "team-a")]
    permission_service = MagicMock()
    permission_service.get_user_roles = AsyncMock(return_value=rows)
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: permission_service)

    result = await rbac_router.get_user_roles(
        "member@example.com",
        scope=None,
        active_only=True,
        user=admin_user_context(["team-a"]),
        db=MagicMock(),
        request=_jwt_scoped_request(["team-a"], path="/rbac/users/member@example.com/roles"),
    )

    assert {r.scope for r in result} == {"team"}


@pytest.mark.asyncio
async def test_get_user_roles_shows_everything_to_unrestricted_admin(monkeypatch):
    rows = [_user_role_row("platform_admin", "global"), _user_role_row("team_admin", "team", "team-a")]
    permission_service = MagicMock()
    permission_service.get_user_roles = AsyncMock(return_value=rows)
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: permission_service)

    result = await rbac_router.get_user_roles(
        "member@example.com",
        scope=None,
        active_only=True,
        user=admin_user_context(None),
        db=MagicMock(),
        request=_jwt_scoped_request(None, path="/rbac/users/member@example.com/roles"),
    )

    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_global_role_returns_404_for_narrowed_admin(monkeypatch):
    """404, not 403 — do not confirm the existence of a role the caller may not enumerate."""
    monkeypatch.setattr(
        "mcpgateway.services.role_service.RoleService.get_role_by_id",
        AsyncMock(return_value=_role_row("1", "platform_admin", "global")),
    )

    with pytest.raises(HTTPException) as exc:
        await rbac_router.get_role(
            request=_jwt_scoped_request(["team-a"], path="/rbac/roles/1"),
            role_id="1",
            user=admin_user_context(["team-a"]),
            db=MagicMock(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Role not found"


@pytest.mark.asyncio
async def test_narrowed_admin_cannot_authorize_global_assignment(monkeypatch):
    """The escalation path: a narrowed admin minting themselves a global '*' role."""
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as exc:
        await rbac_router._authorize_assignment_scope(scoped_request(["team-a"]), admin_user_context(["team-a"]), MagicMock(), "global", None, "victim@example.com")

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unrestricted_admin_may_authorize_global_assignment(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=True))

    assert await rbac_router._authorize_assignment_scope(scoped_request(None), admin_user_context(None), MagicMock(), "global", None, "victim@example.com") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,scope_id,target,expected_denied",
    [
        ("team", "team-b", "victim@example.com", True),  # team not covered by the token
        ("team", None, "victim@example.com", True),  # team scope with no scope_id fails closed
        ("team", "team-a", "member@example.com", False),  # covered team
        ("personal", None, "victim@example.com", True),  # someone else's personal scope
        ("personal", None, "admin@example.com", False),  # self
        ("nonsense", None, "victim@example.com", True),  # unknown scope fails closed
    ],
)
async def test_assignment_scope_matrix(scope, scope_id, target, expected_denied):
    # `_authorize_assignment_scope`'s team/personal branches call
    # `get_scoped_resource_access_context`, which — unlike
    # `require_unrestricted_platform_admin` — falls back to unconditional
    # non-JWT admin bypass unless a verified JWT payload is cached on
    # `request.state`. A bare `scoped_request()` doesn't set that, so every
    # "should be denied" case below would silently bypass narrowing and the
    # test would falsely pass by never raising. Use `_jwt_scoped_request` so
    # this exercises the real verified-token narrowing path. See the
    # docstring on `_jwt_scoped_request` above for the full explanation.
    request = _jwt_scoped_request(["team-a"], path="/rbac/users/x/roles")
    user = admin_user_context(["team-a"])

    if expected_denied:
        with pytest.raises(HTTPException) as exc:
            await rbac_router._authorize_assignment_scope(request, user, MagicMock(), scope, scope_id, target)
        assert exc.value.status_code == 403
    else:
        assert await rbac_router._authorize_assignment_scope(request, user, MagicMock(), scope, scope_id, target) is None


def _role_with_permissions(permissions, effective_permissions=None):
    """Build a minimal role row with the ``permissions``/``get_effective_permissions()`` used by containment checks.

    ``effective_permissions`` defaults to ``permissions`` (mirroring the real
    ``Role.get_effective_permissions()`` when the role has no parent), but can be
    set separately to simulate a role that inherits additional permissions from
    a parent via ``inherits_from``.
    """
    role = SimpleNamespace(id="r1", permissions=permissions)
    role.get_effective_permissions = lambda: effective_permissions if effective_permissions is not None else permissions
    return role


def _db_with_member(is_member: bool):
    """Build a MagicMock db whose EmailTeamMember query resolves to present/absent."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id="m1") if is_member else None
    return db


@pytest.mark.asyncio
async def test_team_assignment_denies_role_exceeding_callers_own_permissions(monkeypatch):
    """A team_admin holding only admin.user_management must not grant a role carrying '*'.

    RoleCreateRequest.permissions is an unvalidated List[str], so a scope="team"
    role definition can legally carry a wildcard. Without delegation-containment,
    granting such a role is the self-escalation path this closes.
    """
    role_service = MagicMock()
    role_service.get_role_by_id = AsyncMock(return_value=_role_with_permissions(["*"]))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: role_service)

    permission_service = MagicMock()
    permission_service.get_user_permissions = AsyncMock(return_value={"admin.user_management"})
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: permission_service)

    request = _jwt_scoped_request(["team-a"], path="/rbac/users/x/roles")
    user = admin_user_context(["team-a"])

    with pytest.raises(HTTPException) as exc:
        await rbac_router._authorize_assignment_scope(request, user, _db_with_member(True), "team", "team-a", "member@example.com", role_id="r1")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_team_assignment_allows_role_covered_by_callers_own_permissions(monkeypatch):
    """A team_admin may grant a role whose permissions are a subset of their own."""
    role_service = MagicMock()
    role_service.get_role_by_id = AsyncMock(return_value=_role_with_permissions(["tools.read"]))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: role_service)

    permission_service = MagicMock()
    permission_service.get_user_permissions = AsyncMock(return_value={"admin.user_management", "tools.read"})
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: permission_service)

    request = _jwt_scoped_request(["team-a"], path="/rbac/users/x/roles")
    user = admin_user_context(["team-a"])

    result = await rbac_router._authorize_assignment_scope(request, user, _db_with_member(True), "team", "team-a", "member@example.com", role_id="r1")
    assert result is None


@pytest.mark.asyncio
async def test_team_assignment_denies_role_escalating_via_inherited_permissions(monkeypatch):
    """A role's direct permissions can look harmless while it inherits '*' via inherits_from.

    Containment must check Role.get_effective_permissions() (direct + inherited),
    not just the direct `permissions` column, or a narrowed team_admin could grant
    a role whose parent carries platform-admin/wildcard authority.
    """
    role_service = MagicMock()
    role_service.get_role_by_id = AsyncMock(return_value=_role_with_permissions(["tools.read"], effective_permissions=["tools.read", "*"]))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: role_service)

    permission_service = MagicMock()
    permission_service.get_user_permissions = AsyncMock(return_value={"admin.user_management", "tools.read"})
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: permission_service)

    request = _jwt_scoped_request(["team-a"], path="/rbac/users/x/roles")
    user = admin_user_context(["team-a"])

    with pytest.raises(HTTPException) as exc:
        await rbac_router._authorize_assignment_scope(request, user, _db_with_member(True), "team", "team-a", "member@example.com", role_id="r1")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_team_assignment_denies_target_not_an_active_team_member(monkeypatch):
    """UserRole.scope_id is not a team foreign key; membership must be checked explicitly."""
    role_service = MagicMock()
    role_service.get_role_by_id = AsyncMock(return_value=_role_with_permissions(["tools.read"]))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: role_service)

    permission_service = MagicMock()
    permission_service.get_user_permissions = AsyncMock(return_value={"tools.read"})
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: permission_service)

    request = _jwt_scoped_request(["team-a"], path="/rbac/users/x/roles")
    user = admin_user_context(["team-a"])

    with pytest.raises(HTTPException) as exc:
        await rbac_router._authorize_assignment_scope(request, user, _db_with_member(False), "team", "team-a", "outsider@example.com", role_id="r1")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_personal_assignment_denies_role_exceeding_callers_own_permissions(monkeypatch):
    """Unconditional self-assignment must not bypass containment for a wildcard role."""
    role_service = MagicMock()
    role_service.get_role_by_id = AsyncMock(return_value=_role_with_permissions(["admin.system_config"]))
    monkeypatch.setattr(rbac_router, "RoleService", lambda db: role_service)

    permission_service = MagicMock()
    permission_service.get_user_permissions = AsyncMock(return_value={"tools.read"})
    monkeypatch.setattr(rbac_router, "PermissionService", lambda db: permission_service)

    request = _jwt_scoped_request(["team-a"], path="/rbac/users/x/roles")
    user = admin_user_context(["team-a"])

    with pytest.raises(HTTPException) as exc:
        await rbac_router._authorize_assignment_scope(request, user, MagicMock(), "personal", None, "admin@example.com", role_id="r1")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_revoke_does_not_run_delegation_containment():
    """Revocation only reduces privilege; it must not be gated by role_id containment.

    _authorize_assignment_scope's role_id parameter defaults to None precisely so
    the revoke call site (which never passes it) skips the assign-only checks —
    otherwise a team_admin could be blocked from revoking a wildcard-carrying
    assignment they don't personally hold.
    """
    request = _jwt_scoped_request(["team-a"], path="/rbac/users/x/roles/r1")
    user = admin_user_context(["team-a"])

    assert await rbac_router._authorize_assignment_scope(request, user, MagicMock(), "team", "team-a", "member@example.com") is None


@pytest.mark.asyncio
async def test_revoke_reads_scope_from_the_stored_row_not_the_request(monkeypatch):
    """A client must not be able to relabel a global assignment to get it revoked."""
    monkeypatch.setattr("mcpgateway.auth_context.is_unrestricted_platform_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(rbac_router, "_load_assignment", lambda db, email, role_id, scope=None, scope_id=None: SimpleNamespace(scope="global", scope_id=None))

    with pytest.raises(HTTPException) as exc:
        # Caller claims team scope; the stored row says global, so this must be denied.
        await rbac_router.revoke_user_role(
            request=scoped_request(["team-a"]),
            user_email="victim@example.com",
            role_id="r",
            scope="team",
            scope_id="team-a",
            user=admin_user_context(["team-a"]),
            db=MagicMock(),
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_revoke_returns_404_when_assignment_absent(monkeypatch):
    monkeypatch.setattr(rbac_router, "_load_assignment", lambda db, email, role_id, scope=None, scope_id=None: None)

    with pytest.raises(HTTPException) as exc:
        await rbac_router.revoke_user_role(
            request=scoped_request(None),
            user_email="nobody@example.com",
            role_id="r",
            scope="team",
            scope_id="team-a",
            user=admin_user_context(None),
            db=MagicMock(),
        )

    assert exc.value.status_code == 404


def _active_team_role(user_email, role_id, scope_id):
    """Build an active, team-scoped ``UserRole`` row for the disambiguation tests below.

    Args:
        user_email: Email the assignment belongs to.
        role_id: Role identifier held under the given team.
        scope_id: Team the role is scoped to.

    Returns:
        UserRole: An unsaved ORM instance, ready to be added to a session.
    """
    return UserRole(user_email=user_email, role_id=role_id, scope="team", scope_id=scope_id, granted_by="admin@example.com", is_active=True)


def test_load_assignment_disambiguates_by_scope_id_when_role_held_in_multiple_teams(test_db):
    """The bug this closes: a user can hold the SAME role active under different
    teams at once (the user_roles unique index explicitly permits this per
    (user, role, scope, scope_id)). Without a scope/scope_id filter, ``.first()``
    would return whichever row the DB happens to return first — potentially
    revoking (or authorizing against) a team the caller never targeted. This
    exercises the real SQLAlchemy query, not a mock, so it would have caught the
    original ``.first()``-with-no-filter bug.

    Uses per-test-unique (user_email, role_id) identifiers because ``test_db``'s
    underlying engine is session-scoped (shared across tests in this module,
    not rolled back between them) while ``user_roles`` enforces a real DB unique
    constraint on (user_email, role_id, scope, scope_id) for active rows —
    reusing the same identifiers across test functions would collide.
    """
    team_a = _active_team_role("bob-disambiguate@example.com", "developer", "team-a")
    team_b = _active_team_role("bob-disambiguate@example.com", "developer", "team-b")
    test_db.add_all([team_a, team_b])
    test_db.commit()

    result_a = rbac_router._load_assignment(test_db, "bob-disambiguate@example.com", "developer", scope="team", scope_id="team-a")
    result_b = rbac_router._load_assignment(test_db, "bob-disambiguate@example.com", "developer", scope="team", scope_id="team-b")

    assert result_a is not None and result_a.scope_id == "team-a"
    assert result_b is not None and result_b.scope_id == "team-b"
    assert result_a.id != result_b.id


def test_load_assignment_omitted_scope_is_ambiguous_and_fails_closed(test_db):
    """Mirrors ``RoleService.get_user_role_assignment``: when the caller doesn't
    supply ``scope`` to disambiguate and multiple active assignments exist, the
    query must match nothing (fail closed to a 404 upstream) rather than
    arbitrarily picking one of the caller's teams.
    """
    team_a = _active_team_role("bob-ambiguous@example.com", "developer", "team-a")
    team_b = _active_team_role("bob-ambiguous@example.com", "developer", "team-b")
    test_db.add_all([team_a, team_b])
    test_db.commit()

    assert rbac_router._load_assignment(test_db, "bob-ambiguous@example.com", "developer") is None


def test_load_assignment_scope_id_mismatch_returns_none(test_db):
    """A scope_id that doesn't match any active row must not fall back to an
    unrelated row for the same (user, role, scope).
    """
    team_a = _active_team_role("bob-mismatch@example.com", "developer", "team-a")
    test_db.add(team_a)
    test_db.commit()

    assert rbac_router._load_assignment(test_db, "bob-mismatch@example.com", "developer", scope="team", scope_id="team-c") is None


@pytest.mark.asyncio
async def test_revoke_disambiguates_via_query_params_when_role_held_in_multiple_teams(test_db):
    """End-to-end: revoke on team-b must not touch the team-a grant, and must
    authorize (and act) against the row it actually loaded — never the raw
    request scope — even though in this case they happen to agree.

    Uses ``_jwt_scoped_request`` (not a bare ``scoped_request``) so the caller is
    a genuinely narrowed admin whose token only covers team-b, exercising real
    Layer-1 narrowing together with the disambiguation fix, rather than the
    non-JWT admin-bypass path described on ``_jwt_scoped_request`` above.
    """
    team_a = _active_team_role("bob-revoke@example.com", "developer", "team-a")
    team_b = _active_team_role("bob-revoke@example.com", "developer", "team-b")
    test_db.add_all([team_a, team_b])
    test_db.commit()
    # `revoke_user_role` commits and closes `db` on success, detaching (and
    # expiring the attributes of) `team_a`/`team_b` — capture the ids up front
    # rather than reading them off the detached instances afterward.
    team_a_id, team_b_id = team_a.id, team_b.id

    result = await rbac_router.revoke_user_role(
        request=_jwt_scoped_request(["team-b"], path="/rbac/users/bob-revoke@example.com/roles/developer"),
        user_email="bob-revoke@example.com",
        role_id="developer",
        scope="team",
        scope_id="team-b",
        user=admin_user_context(["team-b"]),
        db=test_db,
    )

    assert result["message"] == "Role revoked successfully"
    after_a = test_db.query(UserRole).filter(UserRole.id == team_a_id).one()
    after_b = test_db.query(UserRole).filter(UserRole.id == team_b_id).one()
    assert after_a.is_active is True
    assert after_b.is_active is False
