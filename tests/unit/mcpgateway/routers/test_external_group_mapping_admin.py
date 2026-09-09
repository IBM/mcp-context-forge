# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_external_group_mapping_admin.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the external group mappings admin CRUD router (issue #5976).

The endpoints are decorated with @require_permission("admin.system_config"),
which calls PermissionService(db).check_permission(...). We patch the
PermissionService class in mcpgateway.middleware.rbac to return the desired
allow/deny outcome and exercise the endpoint functions directly, the same
pattern used by test_runtime_admin_router.py.
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


@pytest.fixture
def db():
    """In-memory SQLite session seeded with an owner user, two teams, and two roles."""
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
    session.add(EmailTeam(id="team-b", name="Team B", slug="team-b", created_by=user.email, is_personal=False, visibility="private"))
    session.add(Role(name="developer", scope="team", permissions=["a2a.invoke"], created_by=user.email, is_system_role=True, is_active=True))
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
def non_admin_user():
    return {"email": "user@example.com", "is_admin": False, "ip_address": "127.0.0.1", "user_agent": "tests"}


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


@pytest.fixture
def deny_all(monkeypatch: pytest.MonkeyPatch):
    """Patch PermissionService so check_permission always returns False."""

    class DenyAll:
        def __init__(self, _db):
            pass

        async def check_permission(self, **_kwargs):
            return False

    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", DenyAll)


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


class TestDenyPaths:
    """401 / 403 / 400 deny paths."""

    @pytest.mark.asyncio
    async def test_create_unauthenticated_401(self, db, request_stub):
        with pytest.raises(HTTPException) as exc:
            await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=None, db=db)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_create_insufficient_permissions_403(self, deny_all, db, non_admin_user, request_stub):
        with pytest.raises(HTTPException) as exc:
            await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=non_admin_user, db=db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_insufficient_permissions_403(self, deny_all, db, non_admin_user, request_stub):
        with pytest.raises(HTTPException) as exc:
            await router_module.list_external_group_mappings(request=request_stub, user=non_admin_user, db=db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_create_invalid_cf_team_id_400(self, allow_admin, db, admin_user, request_stub):
        with pytest.raises(HTTPException) as exc:
            await router_module.create_external_group_mapping(_create_body(cf_team_id="missing-team"), request=request_stub, user=admin_user, db=db)
        assert exc.value.status_code == 400
        assert "missing-team" in exc.value.detail

    @pytest.mark.asyncio
    async def test_create_invalid_cf_role_400(self, allow_admin, db, admin_user, request_stub):
        with pytest.raises(HTTPException) as exc:
            await router_module.create_external_group_mapping(_create_body(cf_role="no-such-role"), request=request_stub, user=admin_user, db=db)
        assert exc.value.status_code == 400
        assert "Role not found" in exc.value.detail

    @pytest.mark.asyncio
    async def test_update_invalid_cf_team_id_400(self, allow_admin, db, admin_user, request_stub):
        created = await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        body = router_module.ExternalGroupMappingUpdate(cf_team_id="missing-team")
        with pytest.raises(HTTPException) as exc:
            await router_module.update_external_group_mapping(created.id, body, request=request_stub, user=admin_user, db=db)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_missing_404(self, allow_admin, db, admin_user, request_stub):
        with pytest.raises(HTTPException) as exc:
            await router_module.delete_external_group_mapping(9999, request=request_stub, user=admin_user, db=db)
        assert exc.value.status_code == 404


class TestCrudHappyPaths:
    """Valid create, list, update, and delete flows."""

    @pytest.mark.asyncio
    async def test_create_valid_200(self, allow_admin, db, admin_user, request_stub):
        created = await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        assert created.id is not None
        assert created.issuer == "https://issuer.example.com"
        assert created.tenant == "tenant-1"
        assert created.external_group_id == "guid-1"
        assert created.cf_team_id == "team-a"
        assert created.cf_role == "developer"
        assert created.validation_status == "valid"

    @pytest.mark.asyncio
    async def test_list_200(self, allow_admin, db, admin_user, request_stub):
        await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        await router_module.create_external_group_mapping(_create_body(external_group_id="guid-2", cf_team_id="team-b", cf_role=None), request=request_stub, user=admin_user, db=db)
        rows = await router_module.list_external_group_mappings(request=request_stub, user=admin_user, db=db)
        assert len(rows) == 2
        assert {row.external_group_id for row in rows} == {"guid-1", "guid-2"}

    @pytest.mark.asyncio
    async def test_update_valid_200(self, allow_admin, db, admin_user, request_stub):
        created = await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        body = router_module.ExternalGroupMappingUpdate(cf_team_id="team-b", cf_role="viewer")
        updated = await router_module.update_external_group_mapping(created.id, body, request=request_stub, user=admin_user, db=db)
        assert updated.cf_team_id == "team-b"
        assert updated.cf_role == "viewer"

    @pytest.mark.asyncio
    async def test_delete_valid_200(self, allow_admin, db, admin_user, request_stub):
        created = await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        await router_module.delete_external_group_mapping(created.id, request=request_stub, user=admin_user, db=db)
        assert db.query(ExternalGroupMapping).count() == 0

    @pytest.mark.asyncio
    async def test_create_duplicate_409(self, allow_admin, db, admin_user, request_stub):
        await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        with pytest.raises(HTTPException) as exc:
            await router_module.create_external_group_mapping(_create_body(cf_team_id="team-b"), request=request_stub, user=admin_user, db=db)
        assert exc.value.status_code == 409


class TestGraphValidatorSeam:
    """The injectable group-existence validator seam (Graph client lands in #5977)."""

    @pytest.mark.asyncio
    async def test_default_validator_returns_valid(self, allow_admin, db, admin_user, request_stub):
        created = await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        assert created.validation_status == "valid"

    @pytest.mark.asyncio
    async def test_unknown_status_warns_and_allows(self, allow_admin, db, admin_user, request_stub, monkeypatch: pytest.MonkeyPatch):
        # Graph unreachable -> validation_status "unknown" -> row is still
        # stored (warn-and-allow). The denial of a missing group never comes
        # from this seam; fail-closed happens in the resolver at read time.
        monkeypatch.setattr(router_module, "group_exists_validator", lambda issuer, tenant, group_id: "unknown")
        created = await router_module.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        assert created.validation_status == "unknown"
        assert created.last_validated_at is not None
