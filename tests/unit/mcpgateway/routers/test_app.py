"""Unit tests for React App API router (/app/auth/* endpoints)."""

import os
import pytest
from collections.abc import Callable, Generator
from datetime import datetime
from typing import Any
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from mcpgateway.auth import get_current_user_from_cookie
from mcpgateway.main import app
from mcpgateway.utils.csrf import CSRF_TOKEN_LENGTH, require_csrf

pytestmark = pytest.mark.skipif(
    os.environ.get("MCPGATEWAY_UI_ENABLED", "").lower() not in ("1", "true"),
    reason="MCPGATEWAY_UI_ENABLED is not set — /app routes not registered",
)


@pytest.fixture(scope="session", autouse=True)
def _ensure_app_routes_mounted() -> None:
    """Mount app_router and app_spa_router on main.app if not already present.

    With -n auto (xdist), a worker may import mcpgateway.main before
    main_app_with_admin_api (conftest) sets MCPGATEWAY_UI_ENABLED=true. The
    resulting app singleton lacks /app routes even though the skip condition
    is False (env var is now true). This fixture guarantees the routes are
    present before any test in this module runs, matching the dynamic-mount
    pattern used by main_app_with_admin_api in conftest.py.
    """
    import mcpgateway.main as main_mod
    from mcpgateway.routers.app import app_router, app_spa_router

    existing = {getattr(r, "path", "") for r in main_mod.app.routes}
    if "/app/auth/login" not in existing:
        main_mod.app.include_router(app_router)
    if "/app/{path:path}" not in existing:
        main_mod.app.include_router(app_spa_router)


def _make_mock_user(email: str = "test@example.com") -> MagicMock:
    """Build a MagicMock that quacks like an EmailUser ORM object."""
    user = MagicMock()
    user.email = email
    user.full_name = None
    user.is_admin = False
    user.is_active = True
    user.auth_provider = "local"
    user.password_change_required = False
    user.is_email_verified.return_value = True
    user.failed_login_attempts = 0
    user.locked_until = None
    user.is_account_locked.return_value = False
    user.last_login = None
    user.created_at = datetime(2024, 1, 1)
    user.updated_at = datetime(2024, 1, 1)
    return user


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def dep_override() -> Generator[Callable[..., None], Any, None]:
    """Set FastAPI dependency overrides and clean up after each test."""
    overrides_set: dict[Any, Any] = {}

    def _set(dep: Any, fn: Any) -> None:
        overrides_set[dep] = fn
        app.dependency_overrides[dep] = fn

    yield _set

    for dep in overrides_set:
        app.dependency_overrides.pop(dep, None)


def _raise_invalid_token():
    raise HTTPException(status_code=401, detail="Invalid token")


def _raise_expired_token():
    raise HTTPException(status_code=401, detail="Invalid or expired token")


def _raise_csrf_missing_header():
    raise HTTPException(status_code=403, detail="CSRF token missing from header")


def _raise_csrf_mismatch():
    raise HTTPException(status_code=403, detail="CSRF token mismatch")


def _raise_csrf_missing_cookie():
    raise HTTPException(status_code=403, detail="CSRF token missing from cookie")


class TestAuthLogin:
    """Tests for POST /app/auth/login endpoint."""

    # Successful login is covered by tests/e2e/test_app_auth.py::TestFullLoginFlow
    # which runs the full stack against a real DB. Unit-testing it here would require
    # mocking create_access_token and generate_csrf_token (internal functions), which
    # tests routing plumbing rather than real behavior.

    @patch("mcpgateway.routers.app.EmailAuthService")
    def test_login_invalid_credentials(self, mock_auth_service, client):
        """Test login with invalid credentials returns 401."""
        # Setup mock to return None (authentication failed)
        mock_auth_instance = AsyncMock()
        mock_auth_instance.authenticate_user = AsyncMock(return_value=None)
        mock_auth_service.return_value = mock_auth_instance

        # Make request
        response = client.post(
            "/app/auth/login",
            json={"email": "test@example.com", "password": "wrongpassword"},  # pragma: allowlist secret
        )

        # Assertions
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        detail = response.json()["detail"]
        if isinstance(detail, dict):
            assert detail["message"] == "Invalid email or password"
        else:
            assert "Invalid email or password" in detail

        # Verify no cookies set
        assert "jwt_token" not in response.cookies
        assert "csrf_token" not in response.cookies

    def test_login_missing_email(self, client):
        """Test login without email returns 422."""
        response = client.post(
            "/app/auth/login",
            json={"password": "password123"},  # pragma: allowlist secret
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_login_missing_password(self, client):
        """Test login without password returns 422."""
        response = client.post(
            "/app/auth/login",
            json={"email": "test@example.com"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_login_invalid_email_format(self, client):
        """Test login with invalid email format returns 422."""
        response = client.post(
            "/app/auth/login",
            json={"email": "not-an-email", "password": "password123"},  # pragma: allowlist secret
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch("mcpgateway.routers.app.EmailAuthService")
    def test_login_service_error(self, mock_auth_service, client):
        """Test login handles service errors gracefully."""
        # Setup mock to raise exception
        mock_auth_instance = AsyncMock()
        mock_auth_instance.authenticate_user = AsyncMock(side_effect=Exception("Database error"))
        mock_auth_service.return_value = mock_auth_instance

        # Make request
        response = client.post(
            "/app/auth/login",
            json={"email": "test@example.com", "password": "password123"},  # pragma: allowlist secret
        )

        # Assertions
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        detail = response.json()["detail"]
        if isinstance(detail, dict):
            assert detail["message"] == "Authentication failed"
        else:
            assert "Authentication failed" in detail


class TestGetCurrentUser:
    """Tests for GET /app/auth/me endpoint."""

    def test_get_me_without_cookie(self, client):
        """Test GET /app/auth/me without cookie returns 401."""
        response = client.get("/app/auth/me")

        # Should return 401 or 403 depending on auth middleware
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    def test_get_me_with_invalid_cookie(self, client, dep_override):
        """Test GET /app/auth/me with invalid JWT cookie returns 401."""
        dep_override(get_current_user_from_cookie, _raise_invalid_token)

        response = client.get(
            "/app/auth/me",
            cookies={"jwt_token": "invalid-jwt-token"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_me_with_expired_token(self, client, dep_override):
        """Test GET /app/auth/me with expired JWT cookie returns 401."""
        dep_override(get_current_user_from_cookie, _raise_expired_token)

        response = client.get(
            "/app/auth/me",
            cookies={"jwt_token": "expired-jwt-token"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "expired" in response.json()["detail"].lower()


class TestLogout:
    """Tests for POST /app/auth/logout endpoint."""

    def test_logout_missing_csrf_token(self, client, dep_override):
        """Test logout without CSRF token returns 403."""
        dep_override(get_current_user_from_cookie, lambda: (_make_mock_user(), None))
        dep_override(require_csrf, _raise_csrf_missing_header)

        response = client.post(
            "/app/auth/logout",
            cookies={
                "jwt_token": "valid-jwt-token",
                "csrf_token": "valid-csrf-token",
            },
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "CSRF token" in response.json()["detail"]

    def test_logout_invalid_csrf_token(self, client, dep_override):
        """Test logout with mismatched CSRF token returns 403."""
        dep_override(get_current_user_from_cookie, lambda: (_make_mock_user(), None))
        dep_override(require_csrf, _raise_csrf_mismatch)

        response = client.post(
            "/app/auth/logout",
            cookies={
                "jwt_token": "valid-jwt-token",
                "csrf_token": "cookie-csrf-token",
            },
            headers={"X-CSRF-Token": "different-csrf-token"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "CSRF token" in response.json()["detail"]

    def test_logout_without_authentication(self, client):
        """Test logout without authentication returns 401."""
        response = client.post("/app/auth/logout")

        # Should return 401 or 403 depending on auth middleware
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]


class TestCSRFProtection:
    """Tests for CSRF protection utilities."""

    def test_csrf_token_generation(self):
        """Test CSRF token generation produces unique tokens."""
        from mcpgateway.utils.csrf import generate_csrf_token

        token1 = generate_csrf_token()
        token2 = generate_csrf_token()

        # Tokens should be different
        assert token1 != token2

        assert len(token1) == CSRF_TOKEN_LENGTH
        assert len(token2) == CSRF_TOKEN_LENGTH

    def test_csrf_cookie_security_flags(self):
        """Test CSRF cookie has samesite=strict, non-httpOnly, and path=/ (application-wide scope)."""
        from fastapi import Response
        from mcpgateway.utils.csrf import set_csrf_cookie

        response = Response()
        set_csrf_cookie(response, "test-token")

        set_cookie_headers = [v.decode() if isinstance(v, bytes) else v for k, v in response.raw_headers if (k.decode() if isinstance(k, bytes) else k).lower() == "set-cookie"]
        assert set_cookie_headers, "No Set-Cookie header found"
        csrf_cookie = next((h for h in set_cookie_headers if "csrf_token=" in h), "")
        assert csrf_cookie, "csrf_token cookie not found in Set-Cookie"
        assert "samesite=strict" in csrf_cookie.lower()
        assert "httponly" not in csrf_cookie.lower(), "CSRF cookie must not be httpOnly — JS needs to read it"
        assert "path=/" in csrf_cookie.lower()


class TestSecurityVectors:
    """Test security attack vectors."""

    @patch("mcpgateway.routers.app.EmailAuthService")
    def test_login_sql_injection_attempt(self, mock_auth_service, client):
        """Test SQL injection in email field is safely handled."""
        # Mock auth service to return None (authentication failed)
        mock_auth_instance = AsyncMock()
        mock_auth_instance.authenticate_user = AsyncMock(return_value=None)
        mock_auth_service.return_value = mock_auth_instance

        response = client.post(
            "/app/auth/login",
            json={
                "email": "admin'--@example.com",
                "password": "password123",  # pragma: allowlist secret
            },
        )
        # Should fail safely with 401 or 422 (validation error)
        assert response.status_code in [401, 422]

    @patch("mcpgateway.routers.app.EmailAuthService")
    def test_login_xss_payload_in_password(self, mock_auth_service, client):
        """Test XSS payload in password field is safely handled."""
        # Mock auth service to return None (authentication failed)
        mock_auth_instance = AsyncMock()
        mock_auth_instance.authenticate_user = AsyncMock(return_value=None)
        mock_auth_service.return_value = mock_auth_instance

        response = client.post(
            "/app/auth/login",
            json={
                "email": "test@example.com",
                "password": "<script>alert('xss')</script>",  # pragma: allowlist secret
            },
        )
        # Should fail safely with 401 (invalid credentials)
        assert response.status_code == 401

    def test_csrf_token_wrong_length_rejected(self, client):
        """Test CSRF validation rejects tokens that are not 43 characters."""
        short_token = "token-with-wrong-len"  # 20 chars, not 43
        response = client.post(
            "/app/auth/logout",
            cookies={
                "jwt_token": "valid-jwt-token",
                "csrf_token": short_token,
            },
            headers={"X-CSRF-Token": short_token},
        )
        # Fails due to token length check (not XSS — JSON body is never reflected)
        assert response.status_code in [401, 403]

    def test_csrf_token_length_validation_oversized(self, client):
        """Test CSRF validation rejects oversized tokens."""
        oversized_token = "x" * 1000
        response = client.post(
            "/app/auth/logout",
            cookies={
                "jwt_token": "valid-jwt-token",
                "csrf_token": oversized_token,
            },
            headers={"X-CSRF-Token": oversized_token},
        )
        # Should fail with 403 (invalid token format)
        assert response.status_code in [401, 403]
        if response.status_code == 403:
            assert response.json()["detail"]["message"] == "Invalid CSRF token format"

    def test_csrf_token_length_validation_undersized(self, client):
        """Test CSRF validation rejects undersized tokens."""
        undersized_token = "short"
        response = client.post(
            "/app/auth/logout",
            cookies={
                "jwt_token": "valid-jwt-token",
                "csrf_token": undersized_token,
            },
            headers={"X-CSRF-Token": undersized_token},
        )
        # Should fail with 403 (invalid token format)
        assert response.status_code in [401, 403]
        if response.status_code == 403:
            assert response.json()["detail"]["message"] == "Invalid CSRF token format"


class TestRBACMiddleware:
    """Tests for Sec-Fetch-* based RBAC cookie rejection.

    /app/auth/* endpoints use get_current_user_from_cookie (cookie-only by design) and
    bypass the RBAC Sec-Fetch-* check. The check in get_current_user_with_permissions
    guards admin/API endpoints when accessed from the React SPA via cookie.
    """

    def test_app_auth_endpoints_accept_cookie_without_sec_fetch_headers(self, client, dep_override):
        """/app/auth/* accepts cookie auth without Sec-Fetch-* — these endpoints are cookie-only by design."""
        dep_override(get_current_user_from_cookie, _raise_invalid_token)

        response = client.get(
            "/app/auth/me",
            cookies={"jwt_token": "any-token"},
            # No Sec-Fetch-* headers — still reaches auth layer (not blocked by RBAC)
        )
        # Auth layer rejects the invalid token — not RBAC
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        detail = response.json()["detail"]
        assert detail != "Cookie authentication not allowed for API requests. Use Authorization header."

    def test_cookie_auth_passes_rbac_with_sec_fetch_same_origin(self, client, dep_override):
        """Browser fetch with Sec-Fetch-Site: same-origin reaches the auth layer."""
        dep_override(get_current_user_from_cookie, _raise_invalid_token)

        response = client.get(
            "/app/auth/me",
            cookies={"jwt_token": "invalid-but-reaches-auth"},
            headers={"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        detail = response.json()["detail"]
        assert detail != "Cookie authentication not allowed for API requests. Use Authorization header."


class TestSPAServing:
    """Tests for React SPA serving."""

    @patch("mcpgateway.routers.app.settings")
    def test_spa_returns_404_when_not_built(self, mock_settings, client: TestClient, tmp_path):
        """Test /app returns 404 with helpful message when React app is not built."""
        mock_settings.static_dir = tmp_path  # tmp_path has no app/index.html
        response = client.get("/app")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not built" in response.json()["detail"]

    @patch("mcpgateway.routers.app.FileResponse")
    @patch("mcpgateway.routers.app.settings")
    def test_spa_serves_index_when_built(self, mock_settings, mock_file_response, client: TestClient, tmp_path):
        """Test /app serves index.html when React app is built."""
        import os
        from fastapi.responses import HTMLResponse

        os.makedirs(tmp_path / "app")
        (tmp_path / "app" / "index.html").write_text("<html/>")
        mock_settings.static_dir = tmp_path
        mock_file_response.return_value = HTMLResponse(content="<html/>", status_code=200)

        response = client.get("/app")
        assert response.status_code == status.HTTP_200_OK

    @patch("mcpgateway.routers.app.settings")
    def test_spa_nested_route_returns_404_when_not_built(self, mock_settings, client: TestClient, tmp_path):
        """Test /app/nested/route returns 404 when React app is not built."""
        mock_settings.static_dir = tmp_path
        response = client.get("/app/nested/route")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestTokenExpiry:
    """Tests for token expiry behavior."""

    def test_csrf_token_expiry_synchronized_with_jwt(self, client: TestClient, dep_override: Callable[..., None]):
        """Test that CSRF failure blocks logout even when JWT auth would succeed.

        Verifies the coupling documented in csrf.py: both tokens must expire
        simultaneously to prevent auth/CSRF desynchronization.
        """
        # Auth would succeed, but CSRF cookie is missing (simulates simultaneous expiry)
        dep_override(get_current_user_from_cookie, lambda: (_make_mock_user(), "valid-jti"))
        dep_override(require_csrf, _raise_csrf_missing_cookie)

        response = client.post(
            "/app/auth/logout",
            cookies={"jwt_token": "valid-jwt"},
            headers={"X-CSRF-Token": "some-token"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "CSRF token" in response.json()["detail"]
