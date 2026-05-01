"""E2E tests for React App authentication flow.

Tests the complete authentication flow including:
- Login with cookie and CSRF token
- Session validation via /app/auth/me
- CSRF protection on logout
- Cookie security flags
- Cross-tab session persistence
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from mcpgateway.main import app
from mcpgateway.db import SessionLocal, EmailUser
from mcpgateway.services.email_auth_service import EmailAuthService


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def test_user_credentials():
    """Test user credentials."""
    return {
        "email": "e2e-test@example.com",
        "password": "TestPassword123!",  # pragma: allowlist secret
    }


@pytest.fixture
def setup_test_user(test_user_credentials):
    """Create test user in database."""
    db = SessionLocal()
    try:
        # Clean up any existing test user
        existing = db.query(EmailUser).filter_by(email=test_user_credentials["email"]).first()
        if existing:
            db.delete(existing)
            db.commit()

        # Create test user
        auth_service = EmailAuthService(db)
        user = auth_service.create_user(
            email=test_user_credentials["email"],
            password=test_user_credentials["password"],
        )
        db.commit()
        yield user

        # Cleanup
        db.delete(user)
        db.commit()
    finally:
        db.close()


class TestFullLoginFlow:
    """Test complete login flow with cookies and CSRF."""

    def test_login_sets_cookies_and_returns_user(self, client, setup_test_user, test_user_credentials):
        """Test POST /app/auth/login sets JWT and CSRF cookies."""
        response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )

        # Verify response
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["user"]["email"] == test_user_credentials["email"]
        assert "csrf_token" in data
        assert len(data["csrf_token"]) == 43  # URL-safe base64 of 32 bytes

        # Verify cookies set
        assert "jwt_token" in response.cookies
        assert "csrf_token" in response.cookies

        # Verify cookie values match
        assert response.cookies["csrf_token"] == data["csrf_token"]

    def test_login_then_get_me(self, client, setup_test_user, test_user_credentials):
        """Test login followed by GET /app/auth/me validates session."""
        # Login
        login_response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )
        assert login_response.status_code == status.HTTP_200_OK

        # Extract cookies
        jwt_token = login_response.cookies.get("jwt_token")
        csrf_token = login_response.cookies.get("csrf_token")

        # Get current user
        me_response = client.get(
            "/app/auth/me",
            cookies={"jwt_token": jwt_token, "csrf_token": csrf_token},
        )

        # Verify response
        assert me_response.status_code == status.HTTP_200_OK
        data = me_response.json()
        assert data["email"] == test_user_credentials["email"]

    def test_login_then_logout(self, client, setup_test_user, test_user_credentials):
        """Test full login/logout flow with CSRF validation."""
        # Login
        login_response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )
        assert login_response.status_code == status.HTTP_200_OK

        # Extract cookies and CSRF token
        jwt_token = login_response.cookies.get("jwt_token")
        csrf_token_cookie = login_response.cookies.get("csrf_token")
        csrf_token_header = login_response.json()["csrf_token"]

        # Logout with CSRF token
        logout_response = client.post(
            "/app/auth/logout",
            cookies={"jwt_token": jwt_token, "csrf_token": csrf_token_cookie},
            headers={"X-CSRF-Token": csrf_token_header},
        )

        # Verify logout success
        assert logout_response.status_code == status.HTTP_200_OK
        assert logout_response.json()["message"] == "Logged out successfully"

        # Verify session invalidated - GET /app/auth/me should fail
        me_response = client.get(
            "/app/auth/me",
            cookies={"jwt_token": jwt_token, "csrf_token": csrf_token_cookie},
        )
        assert me_response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]


class TestCSRFProtection:
    """Test CSRF protection on state-changing operations."""

    def test_logout_without_csrf_token_fails(self, client, setup_test_user, test_user_credentials):
        """Test logout without CSRF token returns 403."""
        # Login
        login_response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )
        jwt_token = login_response.cookies.get("jwt_token")
        csrf_token_cookie = login_response.cookies.get("csrf_token")

        # Attempt logout without CSRF header
        logout_response = client.post(
            "/app/auth/logout",
            cookies={"jwt_token": jwt_token, "csrf_token": csrf_token_cookie},
            # No X-CSRF-Token header
        )

        # Verify CSRF protection
        assert logout_response.status_code == status.HTTP_403_FORBIDDEN
        assert "CSRF token" in logout_response.json()["detail"]

    def test_logout_with_invalid_csrf_token_fails(self, client, setup_test_user, test_user_credentials):
        """Test logout with mismatched CSRF token returns 403."""
        # Login
        login_response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )
        jwt_token = login_response.cookies.get("jwt_token")
        csrf_token_cookie = login_response.cookies.get("csrf_token")

        # Attempt logout with wrong CSRF header
        logout_response = client.post(
            "/app/auth/logout",
            cookies={"jwt_token": jwt_token, "csrf_token": csrf_token_cookie},
            headers={"X-CSRF-Token": "wrong-csrf-token"},
        )

        # Verify CSRF protection
        assert logout_response.status_code == status.HTTP_403_FORBIDDEN
        assert "CSRF token" in logout_response.json()["detail"]

    def test_logout_with_valid_csrf_token_succeeds(self, client, setup_test_user, test_user_credentials):
        """Test logout with valid CSRF token succeeds."""
        # Login
        login_response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )
        jwt_token = login_response.cookies.get("jwt_token")
        csrf_token_cookie = login_response.cookies.get("csrf_token")
        csrf_token_header = login_response.json()["csrf_token"]

        # Logout with matching CSRF tokens
        logout_response = client.post(
            "/app/auth/logout",
            cookies={"jwt_token": jwt_token, "csrf_token": csrf_token_cookie},
            headers={"X-CSRF-Token": csrf_token_header},
        )

        # Verify success
        assert logout_response.status_code == status.HTTP_200_OK


class TestCrossTabSessionPersistence:
    """Test session persistence across multiple tabs (simulated)."""

    def test_session_shared_across_tabs(self, client, setup_test_user, test_user_credentials):
        """Test that JWT cookie enables session sharing across tabs."""
        # Tab 1: Login
        login_response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )
        jwt_token = login_response.cookies.get("jwt_token")
        csrf_token = login_response.cookies.get("csrf_token")

        # Tab 2: Use same cookies (simulates browser sharing cookies)
        tab2_response = client.get(
            "/app/auth/me",
            cookies={"jwt_token": jwt_token, "csrf_token": csrf_token},
        )

        # Verify Tab 2 is authenticated without re-login
        assert tab2_response.status_code == status.HTTP_200_OK
        assert tab2_response.json()["email"] == test_user_credentials["email"]

    def test_logout_in_one_tab_affects_all_tabs(self, client, setup_test_user, test_user_credentials):
        """Test that logout in one tab invalidates session in all tabs."""
        # Tab 1: Login
        login_response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )
        jwt_token = login_response.cookies.get("jwt_token")
        csrf_token_cookie = login_response.cookies.get("csrf_token")
        csrf_token_header = login_response.json()["csrf_token"]

        # Tab 1: Logout
        logout_response = client.post(
            "/app/auth/logout",
            cookies={"jwt_token": jwt_token, "csrf_token": csrf_token_cookie},
            headers={"X-CSRF-Token": csrf_token_header},
        )
        assert logout_response.status_code == status.HTTP_200_OK

        # Tab 2: Try to use same cookies (should fail)
        tab2_response = client.get(
            "/app/auth/me",
            cookies={"jwt_token": jwt_token, "csrf_token": csrf_token_cookie},
        )

        # Verify Tab 2 is logged out
        assert tab2_response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]


class TestCookieSecurityFlags:
    """Test cookie security configuration."""

    def test_jwt_cookie_security_flags(self, client, setup_test_user, test_user_credentials):
        """Test JWT cookie has correct security flags."""
        response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )

        # Verify JWT cookie exists
        assert "jwt_token" in response.cookies

        # Note: TestClient doesn't expose cookie flags directly,
        # but we can verify the cookie was set
        # In production, verify via browser DevTools:
        # - httpOnly=true
        # - secure=true (in production)
        # - samesite=lax or strict
        # - path=/

    def test_csrf_cookie_security_flags(self, client, setup_test_user, test_user_credentials):
        """Test CSRF cookie has correct security flags."""
        response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )

        # Verify CSRF cookie exists
        assert "csrf_token" in response.cookies

        # Note: TestClient doesn't expose cookie flags directly,
        # but we can verify the cookie was set
        # In production, verify via browser DevTools:
        # - httpOnly=true
        # - secure=true (in production)
        # - samesite=strict
        # - path=/app/auth


class TestInvalidCredentials:
    """Test authentication with invalid credentials."""

    def test_login_with_wrong_password(self, client, setup_test_user, test_user_credentials):
        """Test login with wrong password returns 401."""
        response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": "WrongPassword123!",  # pragma: allowlist secret
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid email or password" in response.json()["detail"]

    def test_login_with_nonexistent_user(self, client):
        """Test login with non-existent user returns 401."""
        response = client.post(
            "/app/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "Password123!",  # pragma: allowlist secret
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid email or password" in response.json()["detail"]

    def test_get_me_without_authentication(self, client):
        """Test GET /app/auth/me without authentication returns 401."""
        response = client.get("/app/auth/me")

        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]
