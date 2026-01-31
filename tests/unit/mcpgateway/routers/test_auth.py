# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the auth router module.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException

# First-Party
from mcpgateway.routers.auth import LoginRequest, get_db, login


class TestLoginRequest:
    """Tests for LoginRequest model."""

    def test_get_email_from_email_field(self):
        """Test getting email from email field."""
        req = LoginRequest(email="test@example.com", password="pass")
        assert req.get_email() == "test@example.com"

    def test_get_email_from_username_with_at(self):
        """Test getting email from username field with @ symbol."""
        req = LoginRequest(username="user@domain.com", password="pass")
        assert req.get_email() == "user@domain.com"

    def test_get_email_from_username_without_at_raises(self):
        """Test that plain username raises ValueError."""
        req = LoginRequest(username="plainuser", password="pass")
        with pytest.raises(ValueError, match="Username format not supported"):
            req.get_email()

    def test_get_email_missing_both_raises(self):
        """Test that missing email and username raises ValueError."""
        req = LoginRequest(password="pass")
        with pytest.raises(ValueError, match="Either email or username must be provided"):
            req.get_email()

    def test_email_takes_precedence_over_username(self):
        """Test that email field takes precedence over username."""
        req = LoginRequest(email="email@example.com", username="user@domain.com", password="pass")
        assert req.get_email() == "email@example.com"


class TestGetDb:
    """Tests for get_db dependency."""

    def test_get_db_yields_session(self):
        """Test that get_db yields a session."""
        with patch("mcpgateway.routers.auth.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_session_local.return_value = mock_db

            gen = get_db()
            db = next(gen)

            assert db == mock_db

            # Complete the generator
            try:
                next(gen)
            except StopIteration:
                pass

            mock_db.commit.assert_called_once()
            mock_db.close.assert_called_once()

    def test_get_db_rollback_on_exception(self):
        """Test that get_db rolls back on exception."""
        with patch("mcpgateway.routers.auth.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_session_local.return_value = mock_db

            gen = get_db()
            next(gen)

            # Simulate exception during usage
            with pytest.raises(RuntimeError):
                gen.throw(RuntimeError("Test error"))

            mock_db.rollback.assert_called_once()
            mock_db.close.assert_called_once()

    def test_get_db_invalidate_on_rollback_failure(self):
        """Test that get_db invalidates on rollback failure."""
        with patch("mcpgateway.routers.auth.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.rollback.side_effect = Exception("Rollback failed")
            mock_session_local.return_value = mock_db

            gen = get_db()
            next(gen)

            # Simulate exception during usage
            with pytest.raises(RuntimeError):
                gen.throw(RuntimeError("Test error"))

            mock_db.rollback.assert_called_once()
            mock_db.invalidate.assert_called_once()
            mock_db.close.assert_called_once()

    def test_get_db_passes_on_invalidate_failure(self):
        """Test that get_db passes on invalidate failure."""
        with patch("mcpgateway.routers.auth.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.rollback.side_effect = Exception("Rollback failed")
            mock_db.invalidate.side_effect = Exception("Invalidate failed")
            mock_session_local.return_value = mock_db

            gen = get_db()
            next(gen)

            # Simulate exception during usage - should not raise additional errors
            with pytest.raises(RuntimeError):
                gen.throw(RuntimeError("Test error"))

            mock_db.close.assert_called_once()


class TestLogin:
    """Tests for login endpoint."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock FastAPI request."""
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "test-agent"}
        return request

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock()

    @pytest.fixture
    def mock_user(self):
        """Create a mock email user."""
        user = MagicMock()
        user.id = "test-user-id"
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_active = True
        user.is_admin = False
        user.auth_provider = "local"
        user.teams = []
        return user

    @pytest.mark.asyncio
    async def test_login_success(self, mock_request, mock_db, mock_user):
        """Test successful login."""
        with (
            patch("mcpgateway.routers.auth.EmailAuthService") as mock_auth_service,
            patch("mcpgateway.routers.auth.create_access_token", new_callable=AsyncMock) as mock_create_token,
        ):
            mock_service = MagicMock()
            mock_service.authenticate_user = AsyncMock(return_value=mock_user)
            mock_auth_service.return_value = mock_service

            mock_create_token.return_value = ("test_token", 3600)

            login_request = LoginRequest(email="test@example.com", password="password123")

            response = await login(login_request, mock_request, mock_db)

            assert response.access_token == "test_token"
            assert response.token_type == "bearer"
            assert response.expires_in == 3600
            mock_service.authenticate_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, mock_request, mock_db):
        """Test login with invalid credentials.

        Note: Due to exception handling structure, HTTPException from failed auth
        is caught by the generic Exception handler and re-raised as 500.
        """
        with patch("mcpgateway.routers.auth.EmailAuthService") as mock_auth_service:
            mock_service = MagicMock()
            mock_service.authenticate_user = AsyncMock(return_value=None)
            mock_auth_service.return_value = mock_service

            login_request = LoginRequest(email="test@example.com", password="wrongpass")

            with pytest.raises(HTTPException) as exc_info:
                await login(login_request, mock_request, mock_db)

            # The 401 HTTPException is caught by except Exception and becomes 500
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_login_value_error(self, mock_request, mock_db):
        """Test login with missing email/username."""
        login_request = LoginRequest(password="password123")

        with pytest.raises(HTTPException) as exc_info:
            await login(login_request, mock_request, mock_db)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_login_service_error(self, mock_request, mock_db):
        """Test login when auth service fails."""
        with patch("mcpgateway.routers.auth.EmailAuthService") as mock_auth_service:
            mock_service = MagicMock()
            mock_service.authenticate_user = AsyncMock(side_effect=Exception("Service error"))
            mock_auth_service.return_value = mock_service

            login_request = LoginRequest(email="test@example.com", password="password123")

            with pytest.raises(HTTPException) as exc_info:
                await login(login_request, mock_request, mock_db)

            assert exc_info.value.status_code == 500
            assert "Authentication service error" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_login_with_username_field(self, mock_request, mock_db, mock_user):
        """Test login using username field instead of email."""
        with (
            patch("mcpgateway.routers.auth.EmailAuthService") as mock_auth_service,
            patch("mcpgateway.routers.auth.create_access_token", new_callable=AsyncMock) as mock_create_token,
        ):
            mock_service = MagicMock()
            mock_service.authenticate_user = AsyncMock(return_value=mock_user)
            mock_auth_service.return_value = mock_service

            mock_create_token.return_value = ("test_token", 3600)

            login_request = LoginRequest(username="user@domain.com", password="password123")

            response = await login(login_request, mock_request, mock_db)

            assert response.access_token == "test_token"
            mock_service.authenticate_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_with_plain_username_fails(self, mock_request, mock_db):
        """Test login with plain username (no @) fails."""
        login_request = LoginRequest(username="plainuser", password="password123")

        with pytest.raises(HTTPException) as exc_info:
            await login(login_request, mock_request, mock_db)

        assert exc_info.value.status_code == 400
        assert "Username format not supported" in exc_info.value.detail
