# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_csrf_coverage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Coverage tests for CSRF token generation and JWT fallback paths.
Targets uncovered lines in admin.py and main.py related to CSRF token handling.
"""

import time
from unittest.mock import AsyncMock, Mock, patch

import jwt
import pytest
from fastapi import Request
from fastapi.responses import Response

from mcpgateway.config import settings


class TestAdminCSRFCookieFallback:
    """Test _set_admin_csrf_cookie fallback JWT extraction (admin.py:1529-1532)."""

    @pytest.mark.asyncio
    async def test_set_admin_csrf_cookie_extracts_user_from_jwt_sub(self):
        """Test fallback extraction of user_id from JWT 'sub' claim."""
        from mcpgateway.admin import _set_admin_csrf_cookie

        # Create mock request with JWT cookie containing 'sub' but no 'email'
        mock_request = Mock(spec=Request)
        mock_request.scope = {"root_path": ""}
        mock_request.cookies = {}
        mock_request.state = Mock()
        mock_request.state.user = None  # Force JWT fallback
        mock_request.state.jti = None  # Force JWT fallback

        # Create JWT with only 'sub' and 'jti'
        payload = {
            "sub": "user@example.com",
            "jti": "session-123",
            "exp": int(time.time()) + 3600,
        }
        secret = settings.jwt_secret_key
        if hasattr(secret, "get_secret_value"):
            secret = secret.get_secret_value()
        token = jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)
        mock_request.cookies["jwt_token"] = token

        mock_response = Mock(spec=Response)
        mock_response.set_cookie = Mock()

        with patch("mcpgateway.services.csrf_service.get_csrf_service") as mock_get_service:
            mock_service = Mock()
            mock_service.generate_csrf_token = Mock(return_value="csrf-token-123")
            mock_get_service.return_value = mock_service

            _set_admin_csrf_cookie(mock_request, mock_response)

            # Verify CSRF token was generated with user_id from 'sub'
            mock_service.generate_csrf_token.assert_called_once_with("user@example.com", "session-123")

    @pytest.mark.asyncio
    async def test_set_admin_csrf_cookie_extracts_user_from_nested_email(self):
        """Test fallback extraction of user_id from nested 'user.email' claim."""
        from mcpgateway.admin import _set_admin_csrf_cookie

        mock_request = Mock(spec=Request)
        mock_request.scope = {"root_path": ""}
        mock_request.cookies = {}
        mock_request.state = Mock()
        mock_request.state.user = None  # Force JWT fallback
        mock_request.state.jti = None  # Force JWT fallback

        # Create JWT with nested user.email structure
        payload = {
            "user": {"email": "nested@example.com"},
            "jti": "session-456",
            "exp": int(time.time()) + 3600,
        }
        secret = settings.jwt_secret_key
        if hasattr(secret, "get_secret_value"):
            secret = secret.get_secret_value()
        token = jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)
        mock_request.cookies["jwt_token"] = token

        mock_response = Mock(spec=Response)
        mock_response.set_cookie = Mock()

        with patch("mcpgateway.services.csrf_service.get_csrf_service") as mock_get_service:
            mock_service = Mock()
            mock_service.generate_csrf_token = Mock(return_value="csrf-token-456")
            mock_get_service.return_value = mock_service

            _set_admin_csrf_cookie(mock_request, mock_response)

            # Verify CSRF token was generated with user_id from nested email
            mock_service.generate_csrf_token.assert_called_once_with("nested@example.com", "session-456")

    @pytest.mark.asyncio
    async def test_set_admin_csrf_cookie_extracts_session_from_jti(self):
        """Test fallback extraction of session_id from JWT 'jti' claim (line 1532)."""
        from mcpgateway.admin import _set_admin_csrf_cookie

        mock_request = Mock(spec=Request)
        mock_request.scope = {"root_path": ""}
        mock_request.cookies = {}
        mock_request.state = Mock()
        mock_request.state.user = None  # Force JWT fallback
        mock_request.state.jti = None  # Force JWT fallback

        # Create JWT with email and jti
        payload = {
            "email": "user@example.com",
            "jti": "jti-session-789",
            "exp": int(time.time()) + 3600,
        }
        secret = settings.jwt_secret_key
        if hasattr(secret, "get_secret_value"):
            secret = secret.get_secret_value()
        token = jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)
        mock_request.cookies["jwt_token"] = token

        mock_response = Mock(spec=Response)
        mock_response.set_cookie = Mock()

        with patch("mcpgateway.services.csrf_service.get_csrf_service") as mock_get_service:
            mock_service = Mock()
            mock_service.generate_csrf_token = Mock(return_value="csrf-token-789")
            mock_get_service.return_value = mock_service

            _set_admin_csrf_cookie(mock_request, mock_response)

            # Verify session_id was extracted from jti
            mock_service.generate_csrf_token.assert_called_once_with("user@example.com", "jti-session-789")


class TestAdminLoginJWTCookieException:
    """Test exception handling when setting JWT cookie fails (admin.py:4063)."""

    @pytest.mark.asyncio
    async def test_login_handler_jwt_cookie_exception_still_sets_csrf(self):
        """Test that CSRF cookie is still set even when JWT cookie setting fails."""
        from mcpgateway.admin import admin_login_handler
        from mcpgateway.db import EmailUser
        from sqlalchemy.orm import Session

        mock_request = Mock(spec=Request)
        mock_request.scope = {"root_path": ""}

        # Mock form data
        mock_form = AsyncMock()
        mock_form.return_value = {
            "email": "test@example.com",
            "password": "password123",
        }
        mock_request.form = mock_form

        mock_db = Mock(spec=Session)

        # Mock user
        mock_user = Mock(spec=EmailUser)
        mock_user.email = "test@example.com"
        mock_user.is_admin = True
        mock_user.password_change_required = False

        # Mock email auth service to return success
        with patch("mcpgateway.admin.EmailAuthService") as mock_auth_class:
            mock_auth_service = Mock()
            mock_auth_service.authenticate_user = AsyncMock(return_value=mock_user)
            mock_auth_class.return_value = mock_auth_service

            # Mock JWT token creation to raise exception
            with patch("mcpgateway.admin.create_jwt_token") as mock_create_jwt:
                mock_create_jwt.side_effect = Exception("JWT creation failed")

                # Mock CSRF cookie setting
                with patch("mcpgateway.admin._set_admin_csrf_cookie") as mock_set_csrf:
                    with patch("mcpgateway.admin.utc_now"):
                        response = await admin_login_handler(mock_request, mock_db)

                        # Verify CSRF cookie was still set despite JWT failure (line 4063)
                        mock_set_csrf.assert_called_once()
                        assert response.status_code == 303




@pytest.fixture
def enable_admin_for_test(monkeypatch):
    """Temporarily enable admin API and reload main.py to mount admin routes."""
    import sys
    from mcpgateway.config import get_settings

    # Clear settings cache and set admin enabled
    get_settings.cache_clear()
    monkeypatch.setenv("MCPGATEWAY_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MCPGATEWAY_UI_ENABLED", "true")

    # Reload main to pick up new settings and mount admin routes
    if "mcpgateway.main" in sys.modules:
        del sys.modules["mcpgateway.main"]

    # Import fresh main with admin enabled
    from mcpgateway.main import app

    yield app

    # Cleanup: restore original state
    get_settings.cache_clear()
    if "mcpgateway.main" in sys.modules:
        del sys.modules["mcpgateway.main"]


# NOTE: TestMainAdminPageEndpoint class removed because the standalone /admin/ route
# in main.py (previously at line 12410) was unreachable dead code. The admin_router
# (included at main.py:12121) provides the /admin/ endpoint, making the standalone
# route unreachable. The dead code has been removed from main.py.
