# -*- coding: utf-8 -*-
"""Unit tests for logout endpoint in auth router."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from mcpgateway.config import get_settings
from mcpgateway.main import app
from mcpgateway.routers.auth import get_db
from mcpgateway.auth import get_current_user


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = MagicMock()
    return db


@pytest.fixture
def mock_current_user():
    """Mock current user."""
    user = MagicMock()
    user.email = "test@example.com"
    return user


@pytest.fixture
def valid_token():
    """Create a valid JWT token with JTI."""
    settings = get_settings()

    # Handle both SecretStr and string types
    secret_key = settings.jwt_secret_key
    if hasattr(secret_key, 'get_secret_value'):
        secret_key = secret_key.get_secret_value()

    now = datetime.now(timezone.utc)
    payload = {
        "sub": "test@example.com",
        "exp": int((now + timedelta(minutes=20)).timestamp()),
        "iat": int(now.timestamp()),
        "jti": "test-jti-123",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "email": "test@example.com",
        "is_admin": False,
        "teams": [],
        "last_activity": int(now.timestamp())
    }
    return jwt.encode(
        payload,
        secret_key,
        algorithm=settings.jwt_algorithm
    )


class TestLogoutEndpoint:
    """Tests for /auth/logout endpoint."""

    def test_logout_success(self, mock_db, mock_current_user, valid_token):
        """Test successful logout."""
        # Override FastAPI dependencies
        app.dependency_overrides[get_current_user] = lambda: mock_current_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with patch('mcpgateway.services.token_blocklist_service.get_token_blocklist_service') as mock_service:
                mock_blocklist = MagicMock()
                mock_blocklist.revoke_token.return_value = True
                mock_service.return_value = mock_blocklist

                client = TestClient(app)
                response = client.post(
                    "/auth/logout",
                    headers={"Authorization": f"Bearer {valid_token}"}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["message"] == "Logged out successfully"
                assert data["revoked_token"] == "test-jti-123"

                # Verify revoke_token was called
                mock_blocklist.revoke_token.assert_called_once()
                call_args = mock_blocklist.revoke_token.call_args
                assert call_args.kwargs["jti"] == "test-jti-123"
                assert call_args.kwargs["revoked_by"] == "test@example.com"
                assert call_args.kwargs["reason"] == "logout"
        finally:
            # Clean up overrides
            app.dependency_overrides.clear()

    def test_logout_missing_authorization_header(self, mock_db):
        """Test logout without Authorization header."""
        def mock_auth_fail():
            raise HTTPException(status_code=401, detail="Authentication required")

        app.dependency_overrides[get_current_user] = mock_auth_fail
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.post("/auth/logout")

            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_logout_invalid_bearer_format(self, mock_db, mock_current_user):
        """Test logout with invalid Bearer format."""
        app.dependency_overrides[get_current_user] = lambda: mock_current_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.post(
                "/auth/logout",
                headers={"Authorization": "InvalidFormat token"}
            )

            assert response.status_code == 401
            detail = response.json()["detail"]
            # Accept various auth-related error messages
            assert any(word in detail.lower() for word in ["authorization", "token", "authentication", "bearer"])
        finally:
            app.dependency_overrides.clear()

    def test_logout_token_without_jti(self, mock_db, mock_current_user):
        """Test logout with token missing JTI."""
        settings = get_settings()

        # Handle both SecretStr and string types
        secret_key = settings.jwt_secret_key
        if hasattr(secret_key, 'get_secret_value'):
            secret_key = secret_key.get_secret_value()

        # Create token without JTI
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "test@example.com",
            "exp": int((now + timedelta(minutes=20)).timestamp()),
            "iat": int(now.timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience
            # Missing JTI
        }
        token = jwt.encode(
            payload,
            secret_key,
            algorithm=settings.jwt_algorithm
        )

        app.dependency_overrides[get_current_user] = lambda: mock_current_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.post(
                "/auth/logout",
                headers={"Authorization": f"Bearer {token}"}
            )

            assert response.status_code == 400
            assert "does not support revocation" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_logout_invalid_token_format(self, mock_db, mock_current_user):
        """Test logout with malformed token."""
        app.dependency_overrides[get_current_user] = lambda: mock_current_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.post(
                "/auth/logout",
                headers={"Authorization": "Bearer invalid.token.format"}
            )

            assert response.status_code == 401
            detail = response.json()["detail"]
            assert "invalid" in detail.lower() or "token" in detail.lower()
        finally:
            app.dependency_overrides.clear()

    def test_logout_revocation_failure(self, mock_db, mock_current_user, valid_token):
        """Test logout when token revocation fails."""
        app.dependency_overrides[get_current_user] = lambda: mock_current_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with patch('mcpgateway.services.token_blocklist_service.get_token_blocklist_service') as mock_service:
                mock_blocklist = MagicMock()
                mock_blocklist.revoke_token.return_value = False
                mock_service.return_value = mock_blocklist

                client = TestClient(app)
                response = client.post(
                    "/auth/logout",
                    headers={"Authorization": f"Bearer {valid_token}"}
                )

                assert response.status_code == 500
                assert "Failed to revoke token" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_logout_unexpected_error(self, mock_db, mock_current_user, valid_token):
        """Test logout with unexpected error."""
        app.dependency_overrides[get_current_user] = lambda: mock_current_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with patch('mcpgateway.services.token_blocklist_service.get_token_blocklist_service') as mock_service:
                mock_service.side_effect = Exception("Database error")

                client = TestClient(app)
                response = client.post(
                    "/auth/logout",
                    headers={"Authorization": f"Bearer {valid_token}"}
                )

                assert response.status_code == 500
                assert "error" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_logout_with_secretstr_jwt_key(self, mock_db, mock_current_user, valid_token):
        """Test logout with SecretStr jwt_secret_key (covers line 244 in routers/auth.py)."""
        from pydantic import SecretStr

        app.dependency_overrides[get_current_user] = lambda: mock_current_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            # Mock settings to return SecretStr
            with patch('mcpgateway.routers.auth.settings') as mock_settings:
                from mcpgateway.config import get_settings
                real_settings = get_settings()

                # Create a SecretStr version of the key
                mock_settings.jwt_secret_key = SecretStr(
                    real_settings.jwt_secret_key.get_secret_value()
                    if hasattr(real_settings.jwt_secret_key, 'get_secret_value')
                    else real_settings.jwt_secret_key
                )
                mock_settings.jwt_algorithm = real_settings.jwt_algorithm

                with patch('mcpgateway.services.token_blocklist_service.get_token_blocklist_service') as mock_service:
                    mock_blocklist = MagicMock()
                    mock_blocklist.revoke_token.return_value = True
                    mock_service.return_value = mock_blocklist

                    client = TestClient(app)
                    response = client.post(
                        "/auth/logout",
                        headers={"Authorization": f"Bearer {valid_token}"}
                    )

                    # Should succeed - this covers the get_secret_value() path on line 244
                    assert response.status_code == 200
                    data = response.json()
                    assert data["message"] == "Logged out successfully"
        finally:
            app.dependency_overrides.clear()
