# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_password_change_bypass.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for password change bypass vulnerability (Issue #4736).

This test suite verifies that the PasswordChangeEnforcementMiddleware
properly prevents users from bypassing the mandatory password change
requirement by directly navigating to admin routes.
"""

# Standard
from unittest.mock import patch

# Third-Party
import pytest
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.db import EmailUser, SessionLocal
from mcpgateway.main import app
from mcpgateway.services.email_auth_service import EmailAuthService


@pytest.fixture
def db_session():
    """Create a test database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_user(db_session):
    """Create a test user with password_change_required flag set."""
    auth_service = EmailAuthService(db_session)

    # Create user with password change required
    user = EmailUser(
        email="test@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",  # Dummy hash
        full_name="Test User",
        is_admin=True,
        is_active=True,
        password_change_required=True,
        auth_provider="local",
    )

    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    yield user

    # Cleanup
    db_session.delete(user)
    db_session.commit()


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def authenticated_client(client, test_user):
    """Create an authenticated test client with JWT token."""
    # Mock JWT token creation
    with patch("mcpgateway.routers.email_auth.create_access_token") as mock_create_token:
        mock_create_token.return_value = ("test_jwt_token", 3600)

        # Mock authentication
        with patch("mcpgateway.auth.get_current_user") as mock_get_user:
            mock_get_user.return_value = test_user

            # Set JWT cookie
            client.cookies.set("jwt_token", "test_jwt_token")

            yield client


def test_login_blocks_user_with_password_change_required(client, test_user, db_session):
    """Test that login returns 403 when password change is required."""
    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        with patch("mcpgateway.services.email_auth_service.EmailAuthService.authenticate_user") as mock_auth:
            mock_auth.return_value = test_user

            response = client.post(
                "/auth/email/login",
                json={"email": "test@example.com", "password": "test_password"},  # pragma: allowlist secret
            )

            assert response.status_code == 403
            assert "password change required" in response.json()["detail"].lower()
            assert response.headers.get("X-Password-Change-Required") == "true"


def test_direct_navigation_to_admin_redirects_to_password_change(authenticated_client, test_user):
    """Test that direct navigation to admin routes redirects to password change page.

    This is the core test for Issue #4736 - verifying that users cannot bypass
    the password change requirement by opening a new tab and navigating directly
    to admin routes.
    """
    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        # Simulate user opening new tab and navigating to admin overview
        response = authenticated_client.get("/admin/#overview", follow_redirects=False)

        # Should redirect to password change page
        assert response.status_code == 303
        assert "/admin/change-password-required" in response.headers["location"]


def test_multiple_admin_routes_blocked(authenticated_client, test_user):
    """Test that all admin routes are blocked when password change is required."""
    admin_routes = [
        "/admin/#overview",
        "/admin/#servers",
        "/admin/#tools",
        "/admin/#gateways",
        "/admin/#teams",
        "/admin/#users",
    ]

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        for route in admin_routes:
            response = authenticated_client.get(route, follow_redirects=False)
            assert response.status_code == 303, f"Route {route} should be blocked"
            assert "/admin/change-password-required" in response.headers["location"]


def test_password_change_page_accessible(authenticated_client, test_user):
    """Test that the password change page itself is accessible."""
    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        response = authenticated_client.get("/admin/change-password-required")

        # Should NOT redirect (allow access to password change page)
        assert response.status_code != 303


def test_password_change_api_endpoint_accessible(authenticated_client, test_user):
    """Test that the password change API endpoint is accessible."""
    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        # Mock password change
        with patch("mcpgateway.services.email_auth_service.EmailAuthService.change_password") as mock_change:
            mock_change.return_value = True

            response = authenticated_client.post(
                "/auth/email/change-password",
                json={"old_password": "old_pass", "new_password": "new_pass"},  # pragma: allowlist secret
            )

            # Should NOT redirect (allow password change)
            assert response.status_code != 303


def test_logout_accessible_when_password_change_required(authenticated_client, test_user):
    """Test that logout is accessible even when password change is required."""
    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        response = authenticated_client.get("/auth/email/logout")

        # Should NOT redirect (allow logout)
        assert response.status_code != 303


def test_api_token_not_blocked(client, test_user):
    """Test that API tokens are not blocked by password change enforcement."""
    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        with patch("mcpgateway.auth.get_current_user") as mock_get_user:
            mock_get_user.return_value = test_user

            # Mock API token authentication
            with patch.object(client, "state", create=True) as mock_state:
                mock_state.auth_method = "api_token"

                response = client.get(
                    "/admin/#overview",
                    headers={"Authorization": "Bearer api_token_here"},
                )

                # Should NOT redirect for API tokens
                assert response.status_code != 303


def test_non_admin_routes_not_affected(authenticated_client, test_user):
    """Test that non-admin routes are not affected by password change enforcement."""
    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        # MCP routes should not be blocked
        response = authenticated_client.get("/mcp/tools")

        # Should NOT redirect (only admin routes are enforced)
        assert response.status_code != 303


def test_user_without_password_change_required_not_blocked(client, db_session):
    """Test that users without password_change_required flag are not blocked."""
    # Create user without password change required
    user = EmailUser(
        email="normal@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        full_name="Normal User",
        is_admin=True,
        is_active=True,
        password_change_required=False,
        auth_provider="local",
    )

    db_session.add(user)
    db_session.commit()

    try:
        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            with patch("mcpgateway.auth.get_current_user") as mock_get_user:
                mock_get_user.return_value = user

                client.cookies.set("jwt_token", "test_jwt_token")
                response = client.get("/admin/#overview")

                # Should NOT redirect (password change not required)
                assert response.status_code != 303
    finally:
        db_session.delete(user)
        db_session.commit()


def test_feature_flag_disabled_allows_access(authenticated_client, test_user):
    """Test that disabling the feature flag allows access even with password_change_required."""
    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", False):
        response = authenticated_client.get("/admin/#overview")

        # Should NOT redirect when feature is disabled
        assert response.status_code != 303


def test_bypass_scenario_from_issue_4736(authenticated_client, test_user):
    """Test the exact bypass scenario described in Issue #4736.

    Steps:
    1. User logs in with default credentials
    2. Gets redirected to /admin/change-password-required
    3. Opens new browser tab
    4. Navigates directly to /admin/#overview
    5. Should be blocked and redirected back to password change page
    """
    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        # Step 1-2: Login attempt (would return 403 in real scenario)
        # Already authenticated via fixture

        # Step 3-4: User opens new tab and navigates to admin overview
        response = authenticated_client.get("/admin/#overview", follow_redirects=False)

        # Step 5: Should be blocked and redirected
        assert response.status_code == 303, "User should be redirected, not granted access"
        assert "/admin/change-password-required" in response.headers["location"], "Should redirect to password change page"

        # Verify user cannot access ANY admin route
        admin_routes = ["/admin/#servers", "/admin/#tools", "/admin/#users"]
        for route in admin_routes:
            response = authenticated_client.get(route, follow_redirects=False)
            assert response.status_code == 303, f"Route {route} should also be blocked"
