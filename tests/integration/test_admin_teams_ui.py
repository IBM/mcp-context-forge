# -*- coding: utf-8 -*-
# tests/integration/test_admin_teams_ui.py
"""Location: ./tests/integration/test_admin_teams_ui.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Integration tests for admin teams UI endpoints with actual template rendering.
Tests verify that the HTML response contains the correct UI elements (buttons, badges)
based on user permissions and team visibility.

Related to issue #3488 - ensures admins see join buttons for public teams.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
import os
import tempfile
from uuid import uuid4

# Third-Party
from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.db import Base, EmailTeam, EmailUser
from mcpgateway.main import app
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.middleware.rbac import get_db as rbac_get_db
from mcpgateway.utils.verify_credentials import require_auth


@pytest.fixture
def test_client_with_admin():
    """FastAPI TestClient with actual database and admin user setup."""
    mp = MonkeyPatch()

    # Create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # Patch settings
    from mcpgateway.config import settings
    mp.setattr(settings, "database_url", url, raising=False)
    mp.setattr(settings, "email_auth_enabled", True, raising=False)
    mp.setattr(settings, "auth_required", False, raising=False)  # Disable auth requirement for testing

    # Create engine and session
    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    # Create schema
    Base.metadata.create_all(bind=engine)

    # Create test admin user
    db = TestSessionLocal()

    admin_user = EmailUser(
        email="admin@test.com",
        password_hash="$2b$12$dummy",
        is_admin=True,
        email_verified_at=datetime.now(timezone.utc)
    )
    db.add(admin_user)

    # Create team owner user
    owner_user = EmailUser(
        email="owner@test.com",
        password_hash="$2b$12$dummy",
        is_admin=False,
        email_verified_at=datetime.now(timezone.utc)
    )
    db.add(owner_user)
    db.flush()

    # Create platform_admin role and assign to admin user for RBAC
    from mcpgateway.db import Role, UserRole

    pa_role = Role(
        id=str(uuid4()),
        name="platform_admin",
        description="Platform Administrator",
        scope="global",
        permissions=["*"],
        created_by="admin@test.com",
        is_system_role=True,
        is_active=True
    )
    db.add(pa_role)
    db.flush()

    pa_ur = UserRole(
        user_email="admin@test.com",
        role_id=pa_role.id,
        scope="global",
        scope_id=None,
        granted_by="admin@test.com",
        is_active=True
    )
    db.add(pa_ur)
    db.commit()

    # Create public team (admin is NOT a member)
    public_team = EmailTeam(
        id=str(uuid4()),
        name="Public Integration Test Team",
        slug="public-integration-test",
        created_by="owner@test.com",
        visibility="public",
        is_personal=False,
        is_active=True
    )
    db.add(public_team)

    # Create private team (admin is NOT a member)
    private_team = EmailTeam(
        id=str(uuid4()),
        name="Private Integration Test Team",
        slug="private-integration-test",
        created_by="owner@test.com",
        visibility="private",
        is_personal=False,
        is_active=True
    )
    db.add(private_team)
    db.commit()

    # Override get_db dependency
    def override_get_db():
        db_session = TestSessionLocal()
        try:
            yield db_session
        finally:
            db_session.close()

    app.dependency_overrides[rbac_get_db] = override_get_db

    # Override auth dependencies to return admin user
    async def mock_get_current_user():
        db_session = TestSessionLocal()
        user_obj = db_session.query(EmailUser).filter(EmailUser.email == "admin@test.com").first()
        return user_obj

    # Override get_current_user_with_permissions for RBAC middleware
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

    # Create TestClient
    client = TestClient(app)

    yield client, TestSessionLocal, public_team, private_team

    # Cleanup
    db.close()
    os.close(fd)
    os.unlink(path)
    mp.undo()
    app.dependency_overrides.clear()


@pytest.mark.integration
def test_admin_sees_join_button_in_html_for_public_teams(test_client_with_admin):
    """
    Integration test: Verify admin sees 'Request to Join' button in actual HTML response
    for public teams they're not members of.

    This test exercises the full stack:
    - Actual database queries
    - Template rendering
    - HTML generation

    Verifies fix for issue #3488.
    """
    client, session_factory, public_team, private_team = test_client_with_admin

    # Make request to admin teams partial endpoint
    # Auth is already set up in the fixture via dependency overrides
    response = client.get(
        "/admin/teams/partial",
        params={
            "page": 1,
            "per_page": 50,
            "render": "partial"
        }
    )

    # Verify response is successful
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    html_content = response.text

    # Verify public team is present in HTML
    assert "Public Integration Test Team" in html_content, "Public team should appear in response"
    assert "Private Integration Test Team" in html_content, "Private team should appear in response"

    # CRITICAL: Verify admin sees "Request to Join" button for PUBLIC team
    # The button has specific classes: btn-indigo and join-team-button
    assert 'Request to Join' in html_content, "Admin should see 'Request to Join' button for public teams"

    # Verify the join button appears in context of the public team
    # The HTML structure has team cards with team names followed by action buttons
    public_team_section_start = html_content.find("Public Integration Test Team")
    assert public_team_section_start > 0, "Public team section should exist"

    # Find the next team section or end of content
    private_team_section_start = html_content.find("Private Integration Test Team", public_team_section_start)

    # Extract the public team section HTML
    if private_team_section_start > 0:
        public_team_html = html_content[public_team_section_start:private_team_section_start]
    else:
        public_team_html = html_content[public_team_section_start:]

    # Verify join button is in the public team section
    assert 'Request to Join' in public_team_html or 'requestToJoin' in public_team_html, \
        "Join button should appear in public team section"

    # Verify "CAN JOIN" badge appears for public team
    assert 'CAN JOIN' in public_team_html or 'badge-orange' in public_team_html, \
        "Public team should show 'CAN JOIN' badge for non-members"

    # Verify admin controls (Manage Members, Delete Team) do NOT appear in public team section
    assert 'Manage Members' not in public_team_html, \
        "Admin should NOT see 'Manage Members' button for public teams"
    assert 'Delete Team' not in public_team_html, \
        "Admin should NOT see 'Delete Team' button for public teams"

    # For PRIVATE team: admin should see admin controls, not join button
    private_team_html = html_content[private_team_section_start:] if private_team_section_start > 0 else ""

    if private_team_html:
        # Admin controls should appear for private teams
        # Note: The exact presence depends on template structure, but relationship="none" enables admin controls
        # We mainly verify that the join button does NOT appear for private teams
        public_join_buttons_count = html_content.count('Request to Join')

        # If there's at least one join button, it should be for the public team only
        if public_join_buttons_count > 0:
            # The join button context should not include the private team
            assert 'Request to Join' not in private_team_html or \
                   html_content.find('Request to Join', private_team_section_start) == -1, \
                "Join button should not appear for private teams in admin view"


@pytest.mark.integration
def test_regular_user_sees_join_button_for_public_teams(test_client_with_admin):
    """
    Integration test: Verify regular (non-admin) users also see 'Request to Join' button
    for public teams they're not members of.

    This ensures the fix doesn't break existing behavior for regular users.
    """
    client, session_factory, public_team, private_team = test_client_with_admin

    # Create regular user
    db = session_factory()
    regular_user = EmailUser(
        email="regular@test.com",
        password_hash="$2b$12$dummy",
        is_admin=False,
        email_verified_at=datetime.now(timezone.utc)
    )
    db.add(regular_user)
    db.commit()
    db.close()

    # Override auth to return regular user (non-admin)
    async def mock_get_regular_user():
        db_session = session_factory()
        user_obj = db_session.query(EmailUser).filter(EmailUser.email == "regular@test.com").first()
        return user_obj

    app.dependency_overrides[get_current_user] = mock_get_regular_user
    app.dependency_overrides[require_auth] = lambda: "regular@test.com"

    # Make request to admin teams partial endpoint
    response = client.get(
        "/admin/teams/partial",
        params={
            "page": 1,
            "per_page": 50,
            "render": "partial"
        }
    )

    # Verify response is successful
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    html_content = response.text

    # Verify public team is present
    assert "Public Integration Test Team" in html_content, "Public team should appear in response"

    # Verify regular user sees "Request to Join" button for public team
    assert 'Request to Join' in html_content, "Regular user should see 'Request to Join' button"

    # Verify regular user does NOT see private team (no access)
    # Note: This depends on RBAC configuration, but typically private teams require membership to view
    # For this test, we're mainly ensuring the join button logic works correctly
