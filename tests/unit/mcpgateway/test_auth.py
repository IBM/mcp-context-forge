# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test authentication utilities module.

This module provides comprehensive unit tests for the auth.py module,
covering JWT authentication, API token authentication, user validation,
and error handling scenarios.
"""

# Standard
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user, get_db
from mcpgateway.db import EmailApiToken, EmailUser


class TestGetDb:
    """Test cases for the get_db dependency function."""

    def test_get_db_yields_session(self):
        """Test that get_db yields a database session."""
        with patch("mcpgateway.auth.SessionLocal") as mock_session_local:
            mock_session = MagicMock(spec=Session)
            mock_session_local.return_value = mock_session

            db = next(get_db())

            assert db == mock_session
            mock_session_local.assert_called_once()

    def test_get_db_closes_session_on_exit(self):
        """Test that get_db closes the session after use."""
        with patch("mcpgateway.auth.SessionLocal") as mock_session_local:
            mock_session = MagicMock(spec=Session)
            mock_session_local.return_value = mock_session

            db_gen = get_db()
            _ = next(db_gen)

            # Finish the generator
            try:
                next(db_gen)
            except StopIteration:
                pass

            mock_session.close.assert_called_once()

    def test_get_db_closes_session_on_exception(self):
        """Test that get_db closes the session even if an exception occurs."""
        with patch("mcpgateway.auth.SessionLocal") as mock_session_local:
            mock_session = MagicMock(spec=Session)
            mock_session_local.return_value = mock_session

            db_gen = get_db()
            _ = next(db_gen)

            # Simulate an exception by closing the generator
            try:
                db_gen.throw(Exception("Test exception"))
            except Exception:
                pass

            mock_session.close.assert_called_once()


class TestGetCurrentUser:
    """Test cases for the get_current_user authentication function."""

    @pytest.mark.asyncio
    async def test_no_credentials_raises_401(self):
        """Test that missing credentials raises 401 Unauthorized."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=None)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Authentication required"
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}

    @pytest.mark.asyncio
    async def test_valid_jwt_token_returns_user(self):
        """Test successful authentication with valid JWT token."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt_token")

        # Mock JWT verification
        jwt_payload = {"sub": "test@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        # Mock user object
        mock_user = EmailUser(
            email="test@example.com",
            password_hash="hash",
            full_name="Test User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value="team_123"):
                    user = await get_current_user(credentials=credentials)

                    assert user.email == mock_user.email
                    assert user.full_name == mock_user.full_name

    @pytest.mark.asyncio
    async def test_jwt_with_legacy_email_format(self):
        """Test JWT token with legacy 'email' field instead of 'sub'."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="legacy_jwt_token")

        # Mock JWT verification with legacy format
        jwt_payload = {"email": "legacy@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        mock_user = EmailUser(
            email="legacy@example.com",
            password_hash="hash",
            full_name="Legacy User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    user = await get_current_user(credentials=credentials)

                    assert user.email == mock_user.email

    @pytest.mark.asyncio
    async def test_jwt_without_email_or_sub_raises_401(self):
        """Test JWT token without email or sub field raises 401."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid_jwt")

        # Mock JWT verification without email/sub
        jwt_payload = {"exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials)

            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert exc_info.value.detail == "Invalid token"

    @pytest.mark.asyncio
    async def test_revoked_jwt_token_raises_401(self):
        """Test that revoked JWT token raises 401."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="revoked_jwt")

        jwt_payload = {"sub": "test@example.com", "jti": "token_id_123", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._check_token_revoked_sync", return_value=True):
                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "Token has been revoked"

    @pytest.mark.asyncio
    async def test_token_revocation_check_failure_logs_warning(self, caplog):
        """Test that token revocation check failure logs warning but doesn't fail auth."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt_with_jti")

        jwt_payload = {"sub": "test@example.com", "jti": "token_id_456", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        mock_user = EmailUser(
            email="test@example.com",
            password_hash="hash",
            full_name="Test User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        caplog.set_level(logging.WARNING)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._check_token_revoked_sync", side_effect=Exception("Database error")):
                with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        user = await get_current_user(credentials=credentials)

                        assert user.email == mock_user.email
                        assert "Token revocation check failed for JTI token_id_456" in caplog.text

    @pytest.mark.asyncio
    async def test_expired_jwt_token_raises_401(self):
        """Test that expired JWT token raises 401."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="expired_jwt")

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"))):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials)

            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert exc_info.value.detail == "Token expired"

    @pytest.mark.asyncio
    async def test_api_token_authentication_success(self):
        """Test successful authentication with API token."""
        api_token_value = "api_token_123456"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=api_token_value)

        mock_user = EmailUser(
            email="api_user@example.com",
            password_hash="hash",
            full_name="API User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # JWT fails, fallback to API token
        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.auth._lookup_api_token_sync", return_value={"user_email": "api_user@example.com", "jti": "api_token_jti"}):
                with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                    user = await get_current_user(credentials=credentials)

                    assert user.email == mock_user.email

    @pytest.mark.asyncio
    async def test_expired_api_token_raises_401(self):
        """Test that expired API token raises 401."""
        api_token_value = "expired_api_token"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=api_token_value)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.auth._lookup_api_token_sync", return_value={"expired": True}):
                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "API token expired"

    @pytest.mark.asyncio
    async def test_revoked_api_token_raises_401(self):
        """Test that revoked API token raises 401."""
        api_token_value = "revoked_api_token"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=api_token_value)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.auth._lookup_api_token_sync", return_value={"revoked": True}):
                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "API token has been revoked"

    @pytest.mark.asyncio
    async def test_api_token_not_found_raises_401(self):
        """Test that non-existent API token raises 401."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="nonexistent_token")

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.auth._lookup_api_token_sync", return_value=None):
                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "Invalid authentication credentials"

    @pytest.mark.asyncio
    async def test_api_token_database_error_raises_401(self):
        """Test that database error during API token lookup raises 401."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token_causing_db_error")

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.auth._lookup_api_token_sync", side_effect=Exception("Database connection error")):
                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "Invalid authentication credentials"

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self):
        """Test that non-existent user raises 401."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt")

        jwt_payload = {"sub": "nonexistent@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    with pytest.raises(HTTPException) as exc_info:
                        await get_current_user(credentials=credentials)

                    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                    assert exc_info.value.detail == "User not found"

    @pytest.mark.asyncio
    async def test_platform_admin_virtual_user_creation(self):
        """Test that platform admin gets a virtual user object if not in database."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="admin_jwt")

        jwt_payload = {"sub": "admin@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):  # User not in DB
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    with patch("mcpgateway.config.settings.platform_admin_email", "admin@example.com"):
                        with patch("mcpgateway.config.settings.platform_admin_full_name", "Platform Administrator"):
                            user = await get_current_user(credentials=credentials)

                            assert user.email == "admin@example.com"
                            assert user.full_name == "Platform Administrator"
                            assert user.is_admin is True
                            assert user.is_active is True

    @pytest.mark.asyncio
    async def test_inactive_user_raises_401(self):
        """Test that inactive user account raises 401."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt")

        jwt_payload = {"sub": "inactive@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        mock_user = EmailUser(
            email="inactive@example.com",
            password_hash="hash",
            full_name="Inactive User",
            is_admin=False,
            is_active=False,  # Inactive account
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    with pytest.raises(HTTPException) as exc_info:
                        await get_current_user(credentials=credentials)

                    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                    assert exc_info.value.detail == "Account disabled"

    @pytest.mark.asyncio
    async def test_logging_debug_messages(self, caplog):
        """Test that appropriate debug messages are logged during authentication."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test_token_for_logging")

        jwt_payload = {"sub": "test@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        mock_user = EmailUser(
            email="test@example.com",
            password_hash="hash",
            full_name="Test User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        caplog.set_level(logging.DEBUG)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    await get_current_user(credentials=credentials)

                    assert "Attempting JWT token validation" in caplog.text
                    assert "JWT token validated successfully" in caplog.text


class TestAuthHooksOptimization:
    """Test cases for has_hooks_for optimization in get_current_user."""

    @pytest.mark.asyncio
    async def test_invoke_hook_skipped_when_has_hooks_for_returns_false(self):
        """Test that invoke_hook is NOT called when has_hooks_for returns False."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt_token")

        jwt_payload = {"sub": "test@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        mock_user = EmailUser(
            email="test@example.com",
            password_hash="hash",
            full_name="Test User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Create mock plugin manager with has_hooks_for returning False
        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=False)
        mock_pm.invoke_hook = AsyncMock()

        with patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm):
            with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
                with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        user = await get_current_user(credentials=credentials)

                        # Verify user was authenticated via standard JWT path
                        assert user.email == mock_user.email

                        # Verify has_hooks_for was called
                        mock_pm.has_hooks_for.assert_called_once()

                        # Verify invoke_hook was NOT called (optimization working)
                        mock_pm.invoke_hook.assert_not_called()

    @pytest.mark.asyncio
    async def test_invoke_hook_called_when_has_hooks_for_returns_true(self):
        """Test that invoke_hook IS called when has_hooks_for returns True."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt_token")

        # Mock plugin result that continues to standard auth
        from mcpgateway.plugins.framework import PluginResult

        mock_plugin_result = PluginResult(
            modified_payload=None,
            continue_processing=True,
        )

        jwt_payload = {"sub": "test@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        mock_user = EmailUser(
            email="test@example.com",
            password_hash="hash",
            full_name="Test User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Create mock plugin manager with has_hooks_for returning True
        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.invoke_hook = AsyncMock(return_value=(mock_plugin_result, None))

        with patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm):
            with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
                with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        user = await get_current_user(credentials=credentials)

                        # Verify user was authenticated
                        assert user.email == mock_user.email

                        # Verify has_hooks_for was called
                        mock_pm.has_hooks_for.assert_called_once()

                        # Verify invoke_hook WAS called
                        mock_pm.invoke_hook.assert_called_once()

    @pytest.mark.asyncio
    async def test_standard_auth_fallback_when_no_plugin_manager(self):
        """Test that standard JWT auth works when plugin manager is None."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt_token")

        jwt_payload = {"sub": "test@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        mock_user = EmailUser(
            email="test@example.com",
            password_hash="hash",
            full_name="Test User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Plugin manager returns None
        with patch("mcpgateway.auth.get_plugin_manager", return_value=None):
            with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
                with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        user = await get_current_user(credentials=credentials)

                        # Verify user was authenticated via standard JWT path
                        assert user.email == mock_user.email
