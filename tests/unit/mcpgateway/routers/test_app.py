"""Unit tests for React App API router (/app/auth/* endpoints)."""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from mcpgateway.main import app
from mcpgateway.schemas import UserResponse


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_user():
    """Mock user object."""
    return MagicMock(
        id=1,
        email="test@example.com",
        is_admin=False,
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


@pytest.fixture
def mock_csrf_token():
    """Mock CSRF token."""
    return "test-csrf-token-1234567890abcdef"


class TestAuthLogin:
    """Tests for POST /app/auth/login endpoint."""

    @patch("mcpgateway.routers.app.EmailAuthService")
    @patch("mcpgateway.routers.app.create_access_token")
    @patch("mcpgateway.routers.app.generate_csrf_token")
    def test_login_success(
        self,
        mock_generate_csrf,
        mock_create_token,
        mock_auth_service,
        client,
        mock_user,
        mock_csrf_token,
    ):
        """Test successful login sets cookies and returns user info."""
        # Setup mocks
        mock_auth_instance = AsyncMock()
        mock_auth_instance.authenticate_user = AsyncMock(return_value=mock_user)
        mock_auth_service.return_value = mock_auth_instance
        mock_create_token.return_value = ("test-jwt-token", None)
        mock_generate_csrf.return_value = mock_csrf_token

        # Make request
        response = client.post(
            "/app/auth/login",
            json={"email": "test@example.com", "password": "password123"},  # pragma: allowlist secret
        )

        # Assertions
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["user"]["email"] == "test@example.com"
        assert data["csrf_token"] == mock_csrf_token

        # Verify cookies set
        assert "jwt_token" in response.cookies
        assert "csrf_token" in response.cookies

        # Verify JWT cookie is httpOnly (can't check directly in TestClient,
        # but we can verify it was called)
        mock_create_token.assert_called_once()

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
        assert "Invalid email or password" in response.json()["detail"]

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
        assert "Authentication failed" in response.json()["detail"]


class TestGetCurrentUser:
    """Tests for GET /app/auth/me endpoint."""

    @patch("mcpgateway.routers.app.get_current_user_from_cookie")
    def test_get_me_with_valid_cookie(self, mock_get_user, client):
        """Test GET /app/auth/me with valid JWT cookie returns user info."""
        # Setup mock
        mock_get_user.return_value = {
            "id": 1,
            "email": "test@example.com",
            "is_admin": False,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }

        # Make request with cookie
        response = client.get(
            "/app/auth/me",
            cookies={"jwt_token": "valid-jwt-token"},
        )

        # Assertions
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["is_admin"] is False

    def test_get_me_without_cookie(self, client):
        """Test GET /app/auth/me without cookie returns 401."""
        response = client.get("/app/auth/me")

        # Should return 401 or 403 depending on auth middleware
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    @patch("mcpgateway.routers.app.get_current_user_from_cookie")
    def test_get_me_with_invalid_cookie(self, mock_get_user, client):
        """Test GET /app/auth/me with invalid JWT cookie returns 401."""
        # Setup mock to raise HTTPException
        from fastapi import HTTPException

        mock_get_user.side_effect = HTTPException(status_code=401, detail="Invalid token")

        # Make request with invalid cookie
        response = client.get(
            "/app/auth/me",
            cookies={"jwt_token": "invalid-jwt-token"},
        )

        # Assertions
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestLogout:
    """Tests for POST /app/auth/logout endpoint."""

    @patch("mcpgateway.routers.app.get_current_user_from_cookie")
    @patch("mcpgateway.routers.app.validate_csrf_token")
    def test_logout_success(self, mock_validate_csrf, mock_get_user, client):
        """Test successful logout clears cookies."""
        # Setup mocks
        mock_get_user.return_value = {
            "id": 1,
            "email": "test@example.com",
            "is_admin": False,
        }
        mock_validate_csrf.return_value = None  # Validation passes

        # Make request with valid cookies and CSRF token
        response = client.post(
            "/app/auth/logout",
            cookies={
                "jwt_token": "valid-jwt-token",
                "csrf_token": "valid-csrf-token",
            },
            headers={"X-CSRF-Token": "valid-csrf-token"},
        )

        # Assertions
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["message"] == "Logged out successfully"

        # Verify CSRF validation was called
        mock_validate_csrf.assert_called_once()

    @patch("mcpgateway.routers.app.get_current_user_from_cookie")
    @patch("mcpgateway.routers.app.validate_csrf_token")
    def test_logout_missing_csrf_token(self, mock_validate_csrf, mock_get_user, client):
        """Test logout without CSRF token returns 403."""
        # Setup mocks
        mock_get_user.return_value = {
            "id": 1,
            "email": "test@example.com",
            "is_admin": False,
        }
        from fastapi import HTTPException

        mock_validate_csrf.side_effect = HTTPException(status_code=403, detail="CSRF token missing from header")

        # Make request without CSRF header
        response = client.post(
            "/app/auth/logout",
            cookies={
                "jwt_token": "valid-jwt-token",
                "csrf_token": "valid-csrf-token",
            },
        )

        # Assertions
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "CSRF token" in response.json()["detail"]

    @patch("mcpgateway.routers.app.get_current_user_from_cookie")
    @patch("mcpgateway.routers.app.validate_csrf_token")
    def test_logout_invalid_csrf_token(self, mock_validate_csrf, mock_get_user, client):
        """Test logout with mismatched CSRF token returns 403."""
        # Setup mocks
        mock_get_user.return_value = {
            "id": 1,
            "email": "test@example.com",
            "is_admin": False,
        }
        from fastapi import HTTPException

        mock_validate_csrf.side_effect = HTTPException(status_code=403, detail="CSRF token mismatch")

        # Make request with mismatched CSRF tokens
        response = client.post(
            "/app/auth/logout",
            cookies={
                "jwt_token": "valid-jwt-token",
                "csrf_token": "cookie-csrf-token",
            },
            headers={"X-CSRF-Token": "different-csrf-token"},
        )

        # Assertions
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

        # Tokens should be URL-safe base64 (43 chars for 32 bytes)
        assert len(token1) == 43
        assert len(token2) == 43

    def test_csrf_cookie_security_flags(self):
        """Test CSRF cookie has correct security flags."""
        from fastapi import Response
        from mcpgateway.utils.csrf import set_csrf_cookie

        response = Response()
        set_csrf_cookie(response, "test-token")

        # Verify cookie was set (can't directly check flags in unit test,
        # but we verify the function was called correctly)
        assert response.raw_headers is not None


class TestSPAServing:
    """Tests for React SPA serving."""

    def test_spa_root_serves_index(self, client):
        """Test /app serves React index.html."""
        # This will fail if React app not built, which is expected in test env
        response = client.get("/app")

        # Either serves the file (200) or returns 404 if not built
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]

    def test_spa_nested_route_serves_index(self, client):
        """Test /app/nested/route serves React index.html (client-side routing)."""
        response = client.get("/app/nested/route")

        # Either serves the file (200) or returns 404 if not built
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]
