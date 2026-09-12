# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_external_group_mapping_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Mapping uniqueness and external-identity cache invalidation tests (#5976).

This branch has no separate service module: the mapping CRUD lives in
mcpgateway/routers/admin_external_group_mappings.py, which is the mapping
service layer exercised here.

Defects under test:
1. The unique constraint on (issuer, tenant, external_group_id) has a
   nullable tenant; SQLite and PostgreSQL both permit duplicate rows when
   tenant IS NULL. The service must reject a second create/update that
   collides on (issuer, external_group_id) with tenant NULL, using the same
   409 conflict error as the non-null-tenant duplicate path.
2. _external_identity_cache in mcpgateway/utils/verify_credentials.py caches
   synthesized external identities keyed by token hash. Every successful
   mapping create/update/delete must call invalidate_external_identity_cache()
   so a deleted mapping stops contributing teams to a cached token identity.
"""

# Standard
from datetime import datetime, timezone
from time import monotonic
from unittest.mock import MagicMock

# Third-Party
from fastapi import HTTPException
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, EmailTeam, EmailUser, ExternalGroupMapping, Role
from mcpgateway.routers import admin_external_group_mappings as mapping_service
from mcpgateway.utils import verify_credentials as vc


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
def request_stub():
    req = MagicMock()
    req.headers = {}
    return req


@pytest.fixture
def allow_admin(monkeypatch: pytest.MonkeyPatch):
    """Patch PermissionService so check_permission always returns True."""

    class AllowAll:
        def __init__(self, db):
            pass

        async def check_permission(self, *args, **kwargs):
            return True

    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", AllowAll)


@pytest.fixture
def seeded_identity_cache():
    """Seed the real external-identity cache with one token entry; always clean up."""
    token_hash = vc._token_hash("raw-token")
    vc._external_identity_cache[token_hash] = ({"token_teams": ["team-a"]}, monotonic() + 60)
    try:
        yield token_hash
    finally:
        vc._external_identity_cache.clear()


def _create_body(**overrides) -> mapping_service.ExternalGroupMappingCreate:
    values = {
        "issuer": "https://issuer.example.com",
        "tenant": None,
        "external_group_id": "guid-1",
        "cf_team_id": "team-a",
        "cf_role": "developer",
    }
    values.update(overrides)
    return mapping_service.ExternalGroupMappingCreate(**values)


class TestNullTenantUniqueness:
    """Duplicate (issuer, external_group_id) rows with tenant NULL must be rejected."""

    @pytest.mark.asyncio
    async def test_duplicate_null_tenant_create_rejected(self, allow_admin, db, admin_user, request_stub):
        await mapping_service.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        with pytest.raises(HTTPException) as exc:
            await mapping_service.create_external_group_mapping(_create_body(cf_team_id="team-b", cf_role="viewer"), request=request_stub, user=admin_user, db=db)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_duplicate_non_null_tenant_create_still_rejected(self, allow_admin, db, admin_user, request_stub):
        await mapping_service.create_external_group_mapping(_create_body(tenant="tenant-1"), request=request_stub, user=admin_user, db=db)
        with pytest.raises(HTTPException) as exc:
            await mapping_service.create_external_group_mapping(_create_body(tenant="tenant-1", cf_team_id="team-b"), request=request_stub, user=admin_user, db=db)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_same_group_different_tenants_allowed(self, allow_admin, db, admin_user, request_stub):
        await mapping_service.create_external_group_mapping(_create_body(tenant=None), request=request_stub, user=admin_user, db=db)
        created = await mapping_service.create_external_group_mapping(_create_body(tenant="tenant-1"), request=request_stub, user=admin_user, db=db)
        assert created.id is not None

    @pytest.mark.asyncio
    async def test_update_colliding_null_tenant_rejected(self, allow_admin, db, admin_user, request_stub):
        await mapping_service.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        other = await mapping_service.create_external_group_mapping(_create_body(external_group_id="guid-2"), request=request_stub, user=admin_user, db=db)
        body = mapping_service.ExternalGroupMappingUpdate(external_group_id="guid-1")
        with pytest.raises(HTTPException) as exc:
            await mapping_service.update_external_group_mapping(other.id, body, request=request_stub, user=admin_user, db=db)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_own_null_tenant_identity_allowed(self, allow_admin, db, admin_user, request_stub):
        created = await mapping_service.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        body = mapping_service.ExternalGroupMappingUpdate(cf_role="viewer")
        updated = await mapping_service.update_external_group_mapping(created.id, body, request=request_stub, user=admin_user, db=db)
        assert updated.cf_role == "viewer"


class TestExternalIdentityCacheInvalidation:
    """Every successful mapping mutation clears the external identity cache."""

    @pytest.mark.asyncio
    async def test_create_invalidates_cache(self, allow_admin, db, admin_user, request_stub, seeded_identity_cache):
        await mapping_service.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        assert vc._external_identity_cache == {}

    @pytest.mark.asyncio
    async def test_update_invalidates_cache(self, allow_admin, db, admin_user, request_stub, seeded_identity_cache):
        created = await mapping_service.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        vc._external_identity_cache[seeded_identity_cache] = ({"token_teams": ["team-a"]}, monotonic() + 60)
        body = mapping_service.ExternalGroupMappingUpdate(cf_team_id="team-b")
        await mapping_service.update_external_group_mapping(created.id, body, request=request_stub, user=admin_user, db=db)
        assert vc._external_identity_cache == {}

    @pytest.mark.asyncio
    async def test_delete_invalidates_cache(self, allow_admin, db, admin_user, request_stub, seeded_identity_cache):
        created = await mapping_service.create_external_group_mapping(_create_body(), request=request_stub, user=admin_user, db=db)
        vc._external_identity_cache[seeded_identity_cache] = ({"token_teams": ["team-a"]}, monotonic() + 60)
        await mapping_service.delete_external_group_mapping(created.id, request=request_stub, user=admin_user, db=db)
        assert vc._external_identity_cache == {}
        assert db.query(ExternalGroupMapping).count() == 0
