# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Location: ./tests/unit/mcpgateway/middleware/test_rbac_decorator_forwards_token_roles.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for #5902 (finding F2, second half): the RBAC decorator path must
forward the claims-derived identity carried on every authenticated user
context — role names (``roles``) and the admin flag (``token_is_admin``) —
into ``PermissionService.check_permission`` as ``token_roles`` /
``token_is_admin``. Without the forwarding, trust-only principals (no local
``EmailUser``/``UserRole`` rows) fall back to empty local lookups and are
denied everything, including permissions their claims-derived roles hold.

Two layers are covered:

1. Recording-service tests: a ``PermissionService`` subclass captures the
   kwargs each decorator-path call site forwards.
2. Real-service tests: a seeded roles table with ZERO local ``UserRole``
   rows proves a trust principal with ``roles=["developer"]`` passes
   ``@require_permission`` for a permission the developer role holds, and
   that the deny paths (empty roles, non-granting role, public-only
   suppression, no admin claim) still deny.
"""

# Future
from __future__ import annotations

# Standard
import contextlib
from datetime import datetime, timezone
from typing import List
from unittest.mock import AsyncMock, MagicMock
import uuid

# Third-Party
from fastapi import HTTPException
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, EmailUser, Permissions, Role, UserRole
from mcpgateway.middleware import rbac
from mcpgateway.services.permission_service import PermissionService

TRUST_USER_ID = "entra-sub-123"
TRUST_EMAIL = "alice@example.com"
SEEDER_EMAIL = "seeder@example.com"


@pytest.fixture(autouse=True)
def _no_plugin_manager(monkeypatch):
    """Disable plugin permission hooks so the RBAC fallback path runs."""
    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))


def _trust_ctx(**overrides) -> dict:
    """User context as built by get_current_user_with_permissions for a trust principal."""
    ctx = {
        "email": TRUST_EMAIL,
        "user_id": TRUST_USER_ID,
        "is_admin": False,
        "roles": ["developer"],
        "token_is_admin": False,
        "token_teams": ["team-a"],
        "token_use": "trusted",
    }
    ctx.update(overrides)
    return ctx


def _install_recording_service(monkeypatch, captured: List[dict]) -> None:
    """Replace rbac.PermissionService with a subclass recording check_permission kwargs."""

    class RecordingPermissionService(PermissionService):
        """Captures every check_permission call's kwargs; always grants."""

        def __init__(self, db):
            self.db = db

        async def check_permission(self, user_email, permission, **kwargs):
            captured.append({"user_email": user_email, "permission": permission, **kwargs})
            return True

    monkeypatch.setattr(rbac, "PermissionService", RecordingPermissionService)


@contextlib.contextmanager
def _fresh_db(db):
    """Stand-in for rbac.fresh_db_session yielding a fixed session."""
    yield db


# ---------------------------------------------------------------------------
# Recording-service tests: every decorator-path call site forwards the claims
# ---------------------------------------------------------------------------


class TestDecoratorForwardsClaimsKwargs:
    """check_permission_inline, require_permission, require_any_permission, and
    PermissionChecker must forward token_roles/token_is_admin from the context."""

    @pytest.mark.asyncio
    async def test_check_permission_inline_forwards_claims_db_branch(self, monkeypatch):
        captured: List[dict] = []
        _install_recording_service(monkeypatch, captured)

        ok = await rbac.check_permission_inline(_trust_ctx(), Permissions.A2A_INVOKE, db=MagicMock())

        assert ok is True
        assert len(captured) == 1
        assert captured[0]["token_roles"] == ["developer"]
        assert captured[0]["token_is_admin"] is False

    @pytest.mark.asyncio
    async def test_check_permission_inline_forwards_claims_fresh_db_branch(self, monkeypatch):
        captured: List[dict] = []
        _install_recording_service(monkeypatch, captured)
        monkeypatch.setattr(rbac, "fresh_db_session", lambda: _fresh_db(MagicMock()))

        ok = await rbac.check_permission_inline(_trust_ctx(), Permissions.A2A_INVOKE)

        assert ok is True
        assert len(captured) == 1
        assert captured[0]["token_roles"] == ["developer"]
        assert captured[0]["token_is_admin"] is False

    @pytest.mark.asyncio
    async def test_require_permission_forwards_claims(self, monkeypatch):
        captured: List[dict] = []
        _install_recording_service(monkeypatch, captured)

        @rbac.require_permission(Permissions.A2A_INVOKE)
        async def endpoint(user=None, db=None):
            return "ok"

        result = await endpoint(user=_trust_ctx(), db=MagicMock())

        assert result == "ok"
        assert len(captured) == 1
        assert captured[0]["user_email"] == TRUST_USER_ID
        assert captured[0]["token_roles"] == ["developer"]
        assert captured[0]["token_is_admin"] is False

    @pytest.mark.asyncio
    async def test_require_permission_forwards_admin_claim(self, monkeypatch):
        captured: List[dict] = []
        _install_recording_service(monkeypatch, captured)

        @rbac.require_permission(Permissions.ADMIN_USER_MANAGEMENT)
        async def endpoint(user=None, db=None):
            return "ok"

        result = await endpoint(user=_trust_ctx(roles=["platform_admin"], token_is_admin=True), db=MagicMock())

        assert result == "ok"
        assert captured[0]["token_roles"] == ["platform_admin"]
        assert captured[0]["token_is_admin"] is True

    @pytest.mark.asyncio
    async def test_require_any_permission_forwards_claims(self, monkeypatch):
        captured: List[dict] = []
        _install_recording_service(monkeypatch, captured)

        @rbac.require_any_permission([Permissions.A2A_INVOKE, Permissions.TOOLS_EXECUTE])
        async def endpoint(user=None, db=None):
            return "ok"

        result = await endpoint(user=_trust_ctx(), db=MagicMock())

        assert result == "ok"
        assert captured, "require_any_permission never consulted PermissionService"
        for call in captured:
            assert call["token_roles"] == ["developer"]
            assert call["token_is_admin"] is False

    @pytest.mark.asyncio
    async def test_permission_checker_has_permission_forwards_claims(self, monkeypatch):
        captured: List[dict] = []
        _install_recording_service(monkeypatch, captured)

        checker = rbac.PermissionChecker(_trust_ctx(db=MagicMock()))
        assert await checker.has_permission(Permissions.A2A_INVOKE) is True

        assert captured[0]["token_roles"] == ["developer"]
        assert captured[0]["token_is_admin"] is False

    @pytest.mark.asyncio
    async def test_permission_checker_has_permission_forwards_claims_fresh_db(self, monkeypatch):
        captured: List[dict] = []
        _install_recording_service(monkeypatch, captured)
        monkeypatch.setattr(rbac, "fresh_db_session", lambda: _fresh_db(MagicMock()))

        checker = rbac.PermissionChecker(_trust_ctx())  # no 'db' key -> fresh session path
        assert await checker.has_permission(Permissions.A2A_INVOKE) is True

        assert captured[0]["token_roles"] == ["developer"]
        assert captured[0]["token_is_admin"] is False

    @pytest.mark.asyncio
    async def test_permission_checker_has_any_permission_forwards_claims(self, monkeypatch):
        captured: List[dict] = []
        _install_recording_service(monkeypatch, captured)

        checker = rbac.PermissionChecker(_trust_ctx(db=MagicMock()))
        assert await checker.has_any_permission([Permissions.A2A_INVOKE, Permissions.TOOLS_EXECUTE]) is True

        assert captured, "has_any_permission never consulted PermissionService"
        for call in captured:
            assert call["token_roles"] == ["developer"]
            assert call["token_is_admin"] is False

    @pytest.mark.asyncio
    async def test_neutral_defaults_forwarded_when_keys_absent(self, monkeypatch):
        """A context without the claims keys forwards neutral defaults, never None-ish gaps."""
        captured: List[dict] = []
        _install_recording_service(monkeypatch, captured)

        ok = await rbac.check_permission_inline({"email": TRUST_EMAIL}, Permissions.TOOLS_READ, db=MagicMock())

        assert ok is True
        assert captured[0]["token_roles"] == []
        assert captured[0]["token_is_admin"] is False


# ---------------------------------------------------------------------------
# Real-service tests: seeded roles, ZERO local UserRole rows for the principal
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_db():
    """In-memory DB with developer/viewer role rows and no UserRole rows at all."""
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    now = datetime.now(timezone.utc)
    session.add(
        EmailUser(
            email=SEEDER_EMAIL,
            password_hash="hash",  # pragma: allowlist secret
            full_name="Seeder",
            is_admin=True,
            is_active=True,
            email_verified_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()
    session.add(
        Role(
            id=str(uuid.uuid4()),
            name="developer",
            description="Developer",
            scope="global",
            permissions=[Permissions.A2A_INVOKE, Permissions.TOOLS_READ],
            created_by=SEEDER_EMAIL,
            is_system_role=True,
            is_active=True,
        )
    )
    session.add(
        Role(
            id=str(uuid.uuid4()),
            name="viewer",
            description="Viewer",
            scope="global",
            permissions=[Permissions.TOOLS_READ],
            created_by=SEEDER_EMAIL,
            is_system_role=True,
            is_active=True,
        )
    )
    session.commit()
    assert session.query(UserRole).count() == 0  # the trust principal has zero local rows
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def real_service(monkeypatch):
    """Use the real PermissionService (auditing off) on the decorator path."""
    monkeypatch.setattr(rbac, "PermissionService", lambda db: PermissionService(db, audit_enabled=False))


async def _invoke(permission: str, ctx: dict, db) -> str:
    """Run a @require_permission-decorated endpoint for ctx against db."""

    @rbac.require_permission(permission)
    async def endpoint(user=None, db=None):  # noqa: A002 - signature mirrors route handlers
        return "ok"

    return await endpoint(user=ctx, db=db)


class TestTrustPrincipalRealService:
    """End-to-end through the decorator with the real PermissionService."""

    @pytest.mark.asyncio
    async def test_developer_role_grants_a2a_invoke_without_local_rows(self, seeded_db, real_service):
        """Acceptance: roles=['developer'] passes @require_permission('a2a.invoke'), zero local rows."""
        result = await _invoke(Permissions.A2A_INVOKE, _trust_ctx(), seeded_db)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_admin_claim_grants_admin_permission_without_local_rows(self, seeded_db, real_service):
        """token_is_admin=True authorizes via admin parity with no DB admin rows."""
        result = await _invoke(Permissions.ADMIN_USER_MANAGEMENT, _trust_ctx(roles=[], token_is_admin=True), seeded_db)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_empty_roles_denied(self, seeded_db, real_service):
        """roles=[] + token_is_admin=False + no local rows -> denied."""
        with pytest.raises(HTTPException) as exc_info:
            await _invoke(Permissions.A2A_INVOKE, _trust_ctx(roles=[]), seeded_db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_non_granting_role_denied(self, seeded_db, real_service):
        """token_roles naming a role that does NOT grant the permission -> denied."""
        with pytest.raises(HTTPException) as exc_info:
            await _invoke(Permissions.A2A_INVOKE, _trust_ctx(roles=["viewer"]), seeded_db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_unknown_role_denied(self, seeded_db, real_service):
        """token_roles naming a role absent from the roles table grants nothing."""
        with pytest.raises(HTTPException) as exc_info:
            await _invoke(Permissions.A2A_INVOKE, _trust_ctx(roles=["no-such-role"]), seeded_db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_public_only_token_suppresses_claims_roles(self, seeded_db, real_service):
        """token_teams=[] (public-only) suppresses claims-derived roles -> denied."""
        with pytest.raises(HTTPException) as exc_info:
            await _invoke(Permissions.A2A_INVOKE, _trust_ctx(token_teams=[]), seeded_db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_public_only_token_suppresses_admin_claim(self, seeded_db, real_service):
        """token_teams=[] suppresses the claims-derived admin bypass -> denied."""
        with pytest.raises(HTTPException) as exc_info:
            await _invoke(Permissions.ADMIN_USER_MANAGEMENT, _trust_ctx(roles=[], token_is_admin=True, token_teams=[]), seeded_db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_developer_role_does_not_grant_admin_permission(self, seeded_db, real_service):
        """token_is_admin=False with no local admin rows -> admin permission denied."""
        with pytest.raises(HTTPException) as exc_info:
            await _invoke(Permissions.ADMIN_USER_MANAGEMENT, _trust_ctx(), seeded_db)
        assert exc_info.value.status_code == 403
