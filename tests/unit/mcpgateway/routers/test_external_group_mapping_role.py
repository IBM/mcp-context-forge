# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_external_group_mapping_role.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for cf_role validation on the external group mappings admin CRUD
router (issue #6272).

cf_role names a row in the roles table. It is a plain String with no foreign
key (roles.name has only a partial unique index), so existence is validated
at the application level, the same pattern as cf_team_id against email_teams.
The endpoints are exercised directly with a patched PermissionService, the
same pattern as test_external_group_mapping_admin.py.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Third-Party
from fastapi import HTTPException
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, EmailTeam, EmailUser, ExternalGroupMapping, Role
from mcpgateway.routers import admin_external_group_mappings as router_module
from mcpgateway.services.role_resolution import resolve_mapping_role


@pytest.fixture
def db():
    """In-memory SQLite session seeded with an owner user, one team, and three roles."""
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    user = EmailUser(
        email="admin@example.com",
        password_hash="hash",  # pragma: allowlist secret
        full_name="Admin",
        is_admin=True,
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.add(EmailTeam(id="team-a", name="Team A", slug="team-a", created_by=user.email, is_personal=False, visibility="private"))
    session.add(Role(name="developer", scope="team", permissions=["a2a.invoke"], created_by=user.email, is_system_role=True, is_active=True))
    session.add(Role(name="team_admin", scope="team", permissions=["a2a.invoke"], created_by=user.email, is_system_role=True, is_active=True))
    session.add(Role(name="viewer", scope="team", permissions=[], created_by=user.email, is_system_role=True, is_active=True))
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def admin_user():
    return {"email": "admin@example.com", "is_admin": True, "ip_address": "127.0.0.1", "user_agent": "tests"}


@pytest.fixture
def request_stub():
    req = MagicMock()
    req.headers = {}
    return req


@pytest.fixture
def allow_admin(monkeypatch: pytest.MonkeyPatch):
    """Patch PermissionService so check_permission always returns True."""

    class AllowAll:
        def __init__(self, _db):
            pass

        async def check_permission(self, **_kwargs):
            return True

    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", AllowAll)


def _create_body(**overrides) -> router_module.ExternalGroupMappingCreate:
    values = {
        "issuer": "https://issuer.example.com",
        "tenant": "tenant-1",
        "external_group_id": "guid-1",
        "cf_team_id": "team-a",
        "cf_role": "developer",
    }
    values.update(overrides)
    return router_module.ExternalGroupMappingCreate(**values)


class TestGroupRoleCrudValidation:
    """cf_role is validated against the roles table on create and update."""

    @pytest.mark.asyncio
    async def test_group_role_create_valid_200(self, allow_admin, db, admin_user, request_stub):
        """POST with cf_role="developer" creates the row."""
        created = await router_module.create_external_group_mapping(_create_body(cf_role="developer"), request=request_stub, user=admin_user, db=db)
        assert created.id is not None
        assert created.cf_role == "developer"

    @pytest.mark.asyncio
    async def test_group_role_create_unknown_role_400(self, allow_admin, db, admin_user, request_stub):
        """POST with cf_role="nonexistent" answers 400 Role not found."""
        with pytest.raises(HTTPException) as exc:
            await router_module.create_external_group_mapping(_create_body(cf_role="nonexistent"), request=request_stub, user=admin_user, db=db)
        assert exc.value.status_code == 400
        assert exc.value.detail == "Role not found: nonexistent"
        assert db.query(ExternalGroupMapping).count() == 0

    @pytest.mark.asyncio
    async def test_group_role_update_valid_200(self, allow_admin, db, admin_user, request_stub):
        """PUT with cf_role="team_admin" updates the row."""
        created = await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        body = router_module.ExternalGroupMappingUpdate(cf_role="team_admin")
        updated = await router_module.update_external_group_mapping(created.id, body, request=request_stub, user=admin_user, db=db)
        assert updated.cf_role == "team_admin"

    @pytest.mark.asyncio
    async def test_group_role_update_unknown_role_400(self, allow_admin, db, admin_user, request_stub):
        """PUT with cf_role="nonexistent" answers 400 and leaves the row unchanged."""
        created = await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        body = router_module.ExternalGroupMappingUpdate(cf_role="nonexistent")
        with pytest.raises(HTTPException) as exc:
            await router_module.update_external_group_mapping(created.id, body, request=request_stub, user=admin_user, db=db)
        assert exc.value.status_code == 400
        assert exc.value.detail == "Role not found: nonexistent"
        assert db.query(ExternalGroupMapping).filter(ExternalGroupMapping.id == created.id).one().cf_role == "developer"


class TestScopeExactRoleResolution:
    """cf_role resolves to exactly one active Role row, scope-exact (NB6).

    roles.name is unique only per (name, scope) among active rows
    (partial unique index uq_roles_name_scope_active), so two active roles
    can share a name across scopes. Resolution prefers the team-scoped row
    (the mapping's context is a team), falls back to the global-scoped row
    only when no team-scoped row exists, and never unions multiple rows.
    """

    def test_team_scoped_role_wins_over_global_same_name(self, db):
        """A team-scoped row beats a global row of the same name; permissions are not unioned."""
        db.add(Role(name="developer", scope="global", permissions=["admin.system_config"], created_by="admin@example.com", is_system_role=True, is_active=True))
        db.commit()

        resolved = resolve_mapping_role(db, "developer", cf_team_id="team-a")

        assert isinstance(resolved, Role)
        assert resolved.scope == "team"
        assert resolved.permissions == ["a2a.invoke"]

    def test_global_role_resolves_when_no_team_scoped_row(self, db):
        """The global row is the fallback when the name exists only in global scope."""
        db.add(Role(name="ops", scope="global", permissions=["a2a.invoke"], created_by="admin@example.com", is_system_role=True, is_active=True))
        db.commit()

        resolved = resolve_mapping_role(db, "ops", cf_team_id="team-a")

        assert isinstance(resolved, Role)
        assert resolved.scope == "global"

    def test_duplicate_team_scoped_rows_resolve_by_lowest_id(self):
        """Two active rows with the same (name, scope) are impossible via the partial unique index.

        If a query ever returns both, resolution stays deterministic: the
        row with the lowest role id wins regardless of result order; the
        rows are never unioned.
        """
        row_low = Role(id="00000000-0000-0000-0000-000000000001", name="developer", scope="team", permissions=["a2a.invoke"], created_by="admin@example.com", is_active=True)
        row_high = Role(id="00000000-0000-0000-0000-000000000002", name="developer", scope="team", permissions=["admin.system_config"], created_by="admin@example.com", is_active=True)

        for rows in ([row_high, row_low], [row_low, row_high]):
            stub_db = MagicMock()
            stub_db.query.return_value.filter.return_value.all.return_value = rows
            resolved = resolve_mapping_role(stub_db, "developer", cf_team_id="team-a")
            assert resolved is row_low

    def test_inactive_team_scoped_row_ignored_active_global_resolves(self, db):
        """An inactive team-scoped row is filtered out; the active global row resolves."""
        db.add(Role(name="ops", scope="team", permissions=["admin.system_config"], created_by="admin@example.com", is_system_role=True, is_active=False))
        db.add(Role(name="ops", scope="global", permissions=["a2a.invoke"], created_by="admin@example.com", is_system_role=True, is_active=True))
        db.commit()

        resolved = resolve_mapping_role(db, "ops", cf_team_id="team-a")

        assert isinstance(resolved, Role)
        assert resolved.scope == "global"
        assert resolved.permissions == ["a2a.invoke"]

    def test_unknown_role_resolves_none(self, db):
        """A name with no active row resolves to None (fail-closed)."""
        assert resolve_mapping_role(db, "nonexistent", cf_team_id="team-a") is None

    @pytest.mark.asyncio
    async def test_group_role_create_inactive_role_400(self, allow_admin, db, admin_user, request_stub):
        """POST with a cf_role that exists only as an inactive row answers 400."""
        db.add(Role(name="retired", scope="team", permissions=[], created_by="admin@example.com", is_system_role=True, is_active=False))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            await router_module.create_external_group_mapping(_create_body(cf_role="retired"), request=request_stub, user=admin_user, db=db)
        assert exc.value.status_code == 400
        assert exc.value.detail == "Role not found: retired"
        assert db.query(ExternalGroupMapping).count() == 0
