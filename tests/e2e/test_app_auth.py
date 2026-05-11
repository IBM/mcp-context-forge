"""E2E tests for React App authentication flow.

Tests the complete authentication flow including:
- Login with cookie and CSRF token
- Session validation via /app/auth/me
- CSRF protection on logout
- Cookie security flags
- Cross-tab session persistence
"""

import asyncio
from datetime import datetime, timedelta, timezone
import os
import re
import time
import uuid
from typing import Dict, Generator

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from mcpgateway import db as db_mod
from mcpgateway.admin import rate_limit_storage
from mcpgateway.db import EmailUser
from mcpgateway.services.email_auth_service import EmailAuthService

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("MCPGATEWAY_UI_ENABLED", "").lower() not in ("1", "true"),
        reason="MCPGATEWAY_UI_ENABLED is not set — /app routes not registered",
    ),
]


@pytest.fixture(autouse=True)
def clear_auth_rate_limits() -> Generator[None, None, None]:
    """Keep auth rate limiting isolated between tests."""
    rate_limit_storage.clear()
    yield
    rate_limit_storage.clear()


def _set_cookie_headers(response) -> list[str]:
    """Return separate Set-Cookie headers from an httpx response."""
    return response.headers.get_list("set-cookie")


@pytest.fixture
def client(app_with_temp_db) -> TestClient:
    """Create test client."""
    return TestClient(app_with_temp_db)


@pytest.fixture
def test_user_credentials() -> Dict[str, str]:
    """Test user credentials."""
    return {
        "email": f"e2e-test-{uuid.uuid4().hex[:8]}@example.com",
        "password": "TestPassword123!",  # pragma: allowlist secret
    }


@pytest.fixture
def setup_test_user(test_user_credentials: Dict[str, str]) -> Generator[EmailUser, None, None]:
    """Create test user in database."""
    db = db_mod.SessionLocal()
    try:
        # Clean up any existing test user
        existing = db.query(EmailUser).filter_by(email=test_user_credentials["email"]).first()
        if existing:
            db.delete(existing)
            db.commit()

        # Create test user
        auth_service = EmailAuthService(db)
        user = asyncio.run(
            auth_service.create_user(
                email=test_user_credentials["email"],
                password=test_user_credentials["password"],
            )
        )
        db.commit()
        yield user
    finally:
        # Cleanup — separate try/except so a test failure inside yield doesn't
        # skip the delete and leave orphaned rows in the test database.
        try:
            user_to_delete = db.query(EmailUser).filter_by(email=test_user_credentials["email"]).first()
            if user_to_delete:
                db.delete(user_to_delete)
                db.commit()
        except Exception:
            db.rollback()
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

        # Verify cookies are cleared in the HTTP response
        set_cookie_headers = _set_cookie_headers(logout_response)
        jwt_clear = next((c for c in set_cookie_headers if "jwt_token=" in c), "")
        csrf_clear = next((c for c in set_cookie_headers if "csrf_token=" in c), "")
        assert jwt_clear, "jwt_token Set-Cookie header missing from logout response"
        assert csrf_clear, "csrf_token Set-Cookie header missing from logout response"
        assert "max-age=0" in jwt_clear.lower(), "jwt_token cookie not cleared (max-age=0 missing)"
        assert "max-age=0" in csrf_clear.lower(), "csrf_token cookie not cleared (max-age=0 missing)"

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
        assert "CSRF token" in logout_response.json()["detail"]["message"]

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
        assert "CSRF token" in logout_response.json()["detail"]["message"]

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
        """Test JWT cookie has httpOnly and samesite flags set."""
        response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )
        assert response.status_code == status.HTTP_200_OK

        set_cookies = _set_cookie_headers(response)
        jwt_cookie = next((c for c in set_cookies if "jwt_token=" in c), "")

        assert jwt_cookie, "jwt_token cookie not found in Set-Cookie headers"
        assert "httponly" in jwt_cookie.lower()
        assert "samesite=lax" in jwt_cookie.lower()
        assert "path=/app" in jwt_cookie.lower()

    def test_csrf_cookie_security_flags(self, client, setup_test_user, test_user_credentials):
        """Test CSRF cookie has samesite=strict and is scoped to /app."""
        response = client.post(
            "/app/auth/login",
            json={
                "email": test_user_credentials["email"],
                "password": test_user_credentials["password"],
            },
        )
        assert response.status_code == status.HTTP_200_OK

        set_cookies = _set_cookie_headers(response)
        csrf_cookie = next((c for c in set_cookies if "csrf_token=" in c), "")

        assert csrf_cookie, "csrf_token cookie not found in Set-Cookie headers"
        assert "samesite=strict" in csrf_cookie.lower()
        assert "path=/app" in csrf_cookie.lower()
        assert "httponly" not in csrf_cookie.lower(), "CSRF cookie must not be httpOnly — JS needs to read it"


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
        assert "Invalid email or password" in response.json()["detail"]["message"]

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
        assert "Invalid email or password" in response.json()["detail"]["message"]

    def test_get_me_without_authentication(self, client):
        """Test GET /app/auth/me without authentication returns 401."""
        response = client.get("/app/auth/me")

        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]


class TestLockedAccount:
    """Test that locked accounts cannot authenticate."""

    def test_login_with_locked_account_fails(self, client, setup_test_user, test_user_credentials):
        """Locked account login returns 401."""
        db = db_mod.SessionLocal()
        try:
            user = db.query(EmailUser).filter_by(email=test_user_credentials["email"]).first()
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=30)
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/app/auth/login",
            json=test_user_credentials,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_after_lock_expires_succeeds(self, client, setup_test_user, test_user_credentials):
        """Login succeeds once lock expiry has passed."""
        db = db_mod.SessionLocal()
        try:
            user = db.query(EmailUser).filter_by(email=test_user_credentials["email"]).first()
            user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=5)
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/app/auth/login",
            json=test_user_credentials,
        )

        assert response.status_code == status.HTTP_200_OK
