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
def client_with_teams(tmp_path):
    """FastAPI TestClient with a real database and platform-admin user.

    Mirrors the pattern in test_admin_teams_ui.py: a temp SQLite file, real schema, a seeded
    platform_admin user, and an active team whose slug we will collide with.
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

    admin_user = EmailUser(
        email="admin@test.com",
        password_hash="$2b$12$dummy",
        is_admin=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(admin_user)
    db.flush()

    from mcpgateway.db import Role, UserRole

    pa_role = Role(
        id=str(uuid4()),
        name="platform_admin",
        description="Platform Administrator",
        scope="global",
        permissions=["*"],
        created_by="admin@test.com",
        is_system_role=True,
        is_active=True,
    )
    db.add(pa_role)
    db.flush()
    db.add(
        UserRole(
            user_email="admin@test.com",
            role_id=pa_role.id,
            scope="global",
            scope_id=None,
            granted_by="admin@test.com",
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
            return db_session.query(EmailUser).filter(EmailUser.email == "admin@test.com").first()
        finally:
            db_session.close()

    async def mock_user_with_permissions():
        db_session = TestSessionLocal()
        try:
            yield {
                "email": "admin@test.com",
                "full_name": "Admin User",
                "is_admin": True,
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
    app.dependency_overrides[require_auth] = lambda: "admin@test.com"

    client = TestClient(app)

    try:
        yield client, TestSessionLocal
    finally:
        db.close()
        client.close()
        app.dependency_overrides = old_overrides
        mp.undo()


@pytest.mark.integration
def test_second_post_same_name_returns_400_not_500(client_with_teams):
    """ICA20-1559 contract: a POST colliding with an EXISTING ACTIVE team returns 400, never 500."""
    client, _ = client_with_teams

    payload = {"name": "Existing Active Team", "visibility": "private"}

    response = client.post("/teams/", json=payload)

    assert response.status_code == 400, (
        f"Expected 400 on active-slug collision, got {response.status_code}: {response.text}"
    )
    assert "already exists" in response.text


@pytest.mark.integration
def test_create_team_success_still_returns_201(client_with_teams):
    """Guard: creating a genuinely NEW team still returns 201 (no regression)."""
    client, _ = client_with_teams

    payload = {"name": "Brand New Team", "visibility": "private"}

    response = client.post("/teams/", json=payload)

    assert response.status_code == 201, (
        f"Expected 201 on fresh team creation, got {response.status_code}: {response.text}"
    )
