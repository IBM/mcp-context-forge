# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_team_creation_slug_collision.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for ICA20-1559.

Callers (e.g. ICA's ContextForgeMcpGatewayImpl.createMcpTeam) that retry team creation for a team
whose ICA->CF mapping was lost hit an active same-slug collision in ContextForge. Previously this
leaked an IntegrityError and surfaced as an opaque 500 {"detail":"Failed to create team"}, which
ICA could not recover from. After the fix, the colliding POST is rejected with a clean, catchable
400 instead of 500. These tests lock that HTTP contract end-to-end through the real router and a
real database.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
from uuid import uuid4

# Third-Party
from fastapi.testclient import TestClient
import pytest
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.db import Base, EmailTeam, EmailUser
from mcpgateway.db import get_db as main_get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.middleware.rbac import get_db as rbac_get_db
from mcpgateway.utils.verify_credentials import require_auth


@pytest.fixture
def admin_client_with_teams(tmp_path):
    """TestClient with a real DB and a platform_admin (``*`` role) identity.

    The router's tiered disclosure returns a specific 400 (with the colliding team's name in the
    body) when this identity collides with an active team's slug.
    """
    yield from _make_team_client(tmp_path, is_admin=True)


@pytest.fixture
def non_admin_client_with_teams(tmp_path):
    """TestClient with a real DB and a non-admin (``teams.create``/``teams.read`` only) identity.

    The router must NOT leak the colliding team's existence, returning a generic 409 instead.
    """
    yield from _make_team_client(tmp_path, is_admin=False)


def _make_team_client(tmp_path, is_admin):
    """Build a FastAPI TestClient with a real database and a seeded user.

    Mirrors the pattern in test_admin_teams_ui.py: a temp SQLite file, real schema, a seeded
    user, and an active team whose slug we will collide with.

    ``is_admin`` controls the identity under which the collision POST is issued (see
    ``admin_client_with_teams`` / ``non_admin_client_with_teams``).
    """
    mp = MonkeyPatch()

    db_path = tmp_path / "test.db"
    url = f"sqlite:///{db_path}"

    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)
    mp.setattr(settings, "email_auth_enabled", True, raising=False)
    mp.setattr(settings, "auth_required", False, raising=False)
    mp.setattr(settings, "mcpgateway_admin_api_enabled", True, raising=True)

    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    mp.setattr(main_mod, "ADMIN_API_ENABLED", True, raising=True)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    from mcpgateway.main import app

    old_overrides = app.dependency_overrides.copy()
    Base.metadata.create_all(bind=engine)

    db = TestSessionLocal()

    user_email = "admin@test.com" if is_admin else "dev@test.com"

    seed_user = EmailUser(
        email=user_email,
        password_hash="$2b$12$dummy",
        is_admin=is_admin,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(seed_user)
    db.flush()

    from mcpgateway.db import Role, UserRole

    if is_admin:
        role_permissions = ["*"]
        role_name = "platform_admin"
    else:
        role_permissions = ["teams.create", "teams.read"]
        role_name = "team_creator"

    seed_role = Role(
        id=str(uuid4()),
        name=role_name,
        description=role_name.replace("_", " ").title(),
        scope="global",
        permissions=role_permissions,
        created_by=user_email,
        is_system_role=is_admin,
        is_active=True,
    )
    db.add(seed_role)
    db.flush()
    db.add(
        UserRole(
            user_email=user_email,
            role_id=seed_role.id,
            scope="global",
            scope_id=None,
            granted_by=user_email,
            is_active=True,
        )
    )

    # Seed an ACTIVE team whose slug we will later collide with.
    colliding_team = EmailTeam(
        id=str(uuid4()),
        name="Existing Active Team",
        slug="existing-active-team",
        created_by="admin@test.com",
        visibility="private",
        is_personal=False,
        is_active=True,
    )
    db.add(colliding_team)
    db.commit()

    def override_get_db():
        db_session = TestSessionLocal()
        try:
            yield db_session
        finally:
            db_session.close()

    app.dependency_overrides[rbac_get_db] = override_get_db
    app.dependency_overrides[main_get_db] = override_get_db

    async def mock_get_current_user():
        db_session = TestSessionLocal()
        try:
            return db_session.query(EmailUser).filter(EmailUser.email == user_email).first()
        finally:
            db_session.close()

    async def mock_user_with_permissions():
        db_session = TestSessionLocal()
        try:
            yield {
                "email": user_email,
                "full_name": user_email,
                "is_admin": is_admin,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "auth_method": "jwt",
                "db": db_session,
                "token_use": "session",
                "team_id": None,
                "token_teams": None,
            }
        finally:
            db_session.close()

    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
    app.dependency_overrides[require_auth] = lambda: user_email

    client = TestClient(app)

    try:
        yield client, TestSessionLocal, is_admin
    finally:
        db.close()
        client.close()
        app.dependency_overrides = old_overrides
        mp.undo()


@pytest.mark.integration
def test_second_post_same_name_returns_400_not_500(admin_client_with_teams):
    """ICA20-1559 contract: an admin POST colliding with an EXISTING ACTIVE team returns 400, never
    500, and discloses the specific conflicting team (the caller is authorized to see it)."""
    client, _, _ = admin_client_with_teams

    payload = {"name": "Existing Active Team", "visibility": "private"}

    response = client.post("/teams/", json=payload)

    assert response.status_code == 400, (
        f"Expected 400 on active-slug collision, got {response.status_code}: {response.text}"
    )
    assert "already exists" in response.text


@pytest.mark.integration
def test_second_post_same_name_non_admin_returns_409(non_admin_client_with_teams):
    """ICA20-1559: a non-admin colliding with an active team gets a generic 409, never a 500
    and never a leak of the purposefully-named team (identity is derivable from it)."""
    client, _, _ = non_admin_client_with_teams

    payload = {"name": "Existing Active Team", "visibility": "private"}

    response = client.post("/teams/", json=payload)

    assert response.status_code == 409, (
        f"Expected 409 for non-admin on active-slug collision, got {response.status_code}: {response.text}"
    )
    assert "already exists" not in response.text.lower()


@pytest.mark.integration
@pytest.mark.parametrize("client_fixture", ["admin_client_with_teams", "non_admin_client_with_teams"])
def test_create_team_success_still_returns_201(client_fixture, request):
    """Guard: creating a genuinely NEW team still returns 201 for BOTH admin and non-admin (no
    regression on the collision fix, and the non-admin creation path is covered too)."""
    client, _, _ = request.getfixturevalue(client_fixture)

    payload = {"name": "Brand New Team", "visibility": "private"}

    response = client.post("/teams/", json=payload)

    assert response.status_code == 201, (
        f"Expected 201 on fresh team creation, got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# Waiver: concurrent-race (flush IntegrityError) backstop is NOT covered at the
# integration level — by design, not omission.
#
# The backstop (team_management_service.create_team_with_members, the
# `except IntegrityError` around `self.db.flush()`) can only fire when two fully
# concurrent in-flight transactions BOTH pass the active-slug pre-check before
# either commits. `email_teams.slug` is globally unique across active and
# inactive rows, so a single sequential request can never make the pre-check
# miss a row that the later insert collides with — the two statements observe
# the same rows absent real concurrency.
#
# Reproducing that true race here would require real multi-worker/threaded
# concurrency against the SQLite + StaticPool + single-TestClient harness this
# file uses; SQLite write-locking makes such a test inherently non-deterministic
# and flaky, which would be worse than no test.
#
# The backstop is therefore covered deterministically at the unit level by
# `test_team_management_service.py::test_create_team_flush_integrity_error_becomes_conflict`,
# which forces the flush IntegrityError and asserts it surfaces as a clean
# TeamNameConflictError (routed to 400/409). The race is closed by the same DB
# unique constraint the sequential 400/409 tests above already prove end-to-end.
# ---------------------------------------------------------------------------
