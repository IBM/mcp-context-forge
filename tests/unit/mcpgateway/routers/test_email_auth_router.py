# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_email_auth_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for Email Auth router.
This module tests email authentication endpoints including login with password change required.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import status
import pytest

# First-Party
from mcpgateway.db import EmailUser


class TestEmailAuthLoginPasswordChangeRequired:
    """Test cases for login endpoint when password change is required."""

    @pytest.fixture
    def mock_user_needs_password_change(self):
        """Create mock user that needs password change."""
        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.password_hash = "hashed_password"
        user.full_name = "Test User"
        user.is_admin = False
        user.is_active = True
        user.password_change_required = True
        user.failed_login_attempts = 0
        user.account_locked_until = None
        user.is_account_locked = MagicMock(return_value=False)
        user.reset_failed_attempts = MagicMock()
        return user

    @pytest.fixture
    def mock_user_normal(self):
        """Create mock user that does not need password change."""
        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.password_hash = "hashed_password"
        user.full_name = "Test User"
        user.is_admin = False
        user.is_active = True
        user.password_change_required = False
        user.failed_login_attempts = 0
        user.account_locked_until = None
        user.auth_provider = "local"
        user.is_account_locked = MagicMock(return_value=False)
        user.reset_failed_attempts = MagicMock()
        user.get_teams = MagicMock(return_value=[])
        user.team_memberships = []
        return user

    @pytest.mark.asyncio
    async def test_login_returns_403_when_password_change_required(self, mock_user_needs_password_change):
        """Test that login returns 403 with X-Password-Change-Required header when password change is required."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import EmailLoginRequest

        # Create mock request
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"User-Agent": "TestAgent/1.0"}

        # Create mock db session
        mock_db = MagicMock()

        # Create login request
        login_request = EmailLoginRequest(email="test@example.com", password="password123")

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
            mock_service = MockAuthService.return_value
            mock_service.authenticate_user = AsyncMock(return_value=mock_user_needs_password_change)

            # Call the login function - user.password_change_required is True
            response = await login(login_request, mock_request, mock_db)

            # Verify response
            assert response.status_code == status.HTTP_403_FORBIDDEN
            assert response.headers.get("X-Password-Change-Required") == "true"

            # Verify response body
            import orjson

            body = orjson.loads(response.body)
            assert "detail" in body
            assert "password change required" in body["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_returns_403_when_using_default_password(self, mock_user_normal):
        """Test that login returns 403 when user is using default password."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import EmailLoginRequest

        # Create mock request
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"User-Agent": "TestAgent/1.0"}

        # Create mock db session
        mock_db = MagicMock()

        # Create login request
        login_request = EmailLoginRequest(email="test@example.com", password="password123")

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
            mock_service = MockAuthService.return_value
            mock_service.authenticate_user = AsyncMock(return_value=mock_user_normal)

            # Patch where Argon2PasswordService is imported (inside the function)
            with patch("mcpgateway.services.argon2_service.Argon2PasswordService") as MockPasswordService:
                mock_password_service = MockPasswordService.return_value
                # User IS using default password
                mock_password_service.verify_password.return_value = True

                with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
                    mock_settings.default_user_password.get_secret_value.return_value = "default_password"

                    # Call the login function
                    response = await login(login_request, mock_request, mock_db)

                    # Verify response
                    assert response.status_code == status.HTTP_403_FORBIDDEN
                    assert response.headers.get("X-Password-Change-Required") == "true"

    @pytest.mark.asyncio
    async def test_login_success_when_no_password_change_required(self, mock_user_normal):
        """Test that login succeeds when password change is not required."""
        # First-Party
        from mcpgateway.routers.email_auth import login
        from mcpgateway.schemas import AuthenticationResponse, EmailLoginRequest

        # Create mock request
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"User-Agent": "TestAgent/1.0"}

        # Create mock db session
        mock_db = MagicMock()

        # Create login request
        login_request = EmailLoginRequest(email="test@example.com", password="password123")

        with patch("mcpgateway.routers.email_auth.EmailAuthService") as MockAuthService:
            mock_service = MockAuthService.return_value
            mock_service.authenticate_user = AsyncMock(return_value=mock_user_normal)

            # Patch where Argon2PasswordService is imported (inside the function)
            with patch("mcpgateway.services.argon2_service.Argon2PasswordService") as MockPasswordService:
                mock_password_service = MockPasswordService.return_value
                # User is NOT using default password
                mock_password_service.verify_password.return_value = False

                with patch("mcpgateway.routers.email_auth.settings") as mock_settings:
                    mock_settings.default_user_password.get_secret_value.return_value = "default_password"
                    mock_settings.token_expiry = 60
                    mock_settings.jwt_issuer = "test-issuer"
                    mock_settings.jwt_audience = "test-audience"

                    with patch("mcpgateway.routers.email_auth.create_access_token") as mock_create_token:
                        mock_create_token.return_value = ("test_token_123", 3600)

                        # Call the login function
                        response = await login(login_request, mock_request, mock_db)

                        # Verify response is AuthenticationResponse (not ORJSONResponse)
                        assert isinstance(response, AuthenticationResponse)
                        assert response.access_token == "test_token_123"
                        assert response.token_type == "bearer"
