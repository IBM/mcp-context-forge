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


@pytest.fixture(params=["admin", "non_admin"])
def client_with_teams(tmp_path, request):
    """FastAPI TestClient with a real database and a seeded user.

    Mirrors the pattern in test_admin_teams_ui.py: a temp SQLite file, real schema, a seeded
    user, and an active team whose slug we will collide with.

    The ``request.param`` controls the identity under which the collision POST is issued:

    * ``admin`` - a platform_admin user (is_admin=True, ``*`` role). The router's tiered
      disclosure returns a specific 400 with the perfectly-named team in the body.
    * ``non_admin`` - a user with only ``teams.create``/``teams.read`` but no ``*`` role. The
      router must NOT leak the purposefully-named team, returning a generic 409 instead.
    """
    is_admin = request.param == "admin"
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
def test_second_post_same_name_returns_400_not_500(client_with_teams):
    """ICA20-1559 contract: a POST colliding with an EXISTING ACTIVE team returns 400, never 500."""
    client, _, is_admin = client_with_teams
    if not is_admin:
        pytest.skip("admin-specific tiered disclosure")

    payload = {"name": "Existing Active Team", "visibility": "private"}

    response = client.post("/teams/", json=payload)

    assert response.status_code == 400, (
        f"Expected 400 on active-slug collision, got {response.status_code}: {response.text}"
    )
    assert "already exists" in response.text


@pytest.mark.integration
def test_second_post_same_name_non_admin_returns_409(client_with_teams):
    """ICA20-1559: a non-admin colliding with an active team gets a generic 409, never a 500
    and never a leak of the purposefully-named team (identity is derivable from it)."""
    client, _, is_admin = client_with_teams
    if is_admin:
        pytest.skip("non-admin 409 path")

    payload = {"name": "Existing Active Team", "visibility": "private"}

    response = client.post("/teams/", json=payload)

    assert response.status_code == 409, (
        f"Expected 409 for non-admin on active-slug collision, got {response.status_code}: {response.text}"
    )
    assert "already exists" not in response.text.lower()


@pytest.mark.integration
def test_create_team_success_still_returns_201(client_with_teams):
    """Guard: creating a genuinely NEW team still returns 201 (no regression)."""
    client, _, is_admin = client_with_teams
    if not is_admin:
        pytest.skip("admin-only guard")

    payload = {"name": "Brand New Team", "visibility": "private"}

    response = client.post("/teams/", json=payload)

    assert response.status_code == 201, (
        f"Expected 201 on fresh team creation, got {response.status_code}: {response.text}"
    )
