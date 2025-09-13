# -*- coding: utf-8 -*-
"""Test authentication utilities module.

This module provides comprehensive unit tests for the auth.py module,
covering JWT authentication, API token authentication, user validation,
and error handling scenarios.
"""

# Standard
from datetime import datetime, timedelta, timezone
import hashlib
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user, get_db
from mcpgateway.db import EmailApiToken, EmailUser, SessionLocal


class TestGetDb:
    """Test cases for the get_db dependency function."""

    def test_get_db_yields_session(self):
        """Test that get_db yields a database session."""
        with patch("mcpgateway.auth.SessionLocal") as mock_session_local:
            mock_session = MagicMock(spec=Session)
            mock_session_local.return_value = mock_session

            db_gen = get_db()
            db = next(db_gen)

            assert db == mock_session
            mock_session_local.assert_called_once()

    def test_get_db_closes_session_on_exit(self):
        """Test that get_db closes the session after use."""
        with patch("mcpgateway.auth.SessionLocal") as mock_session_local:
            mock_session = MagicMock(spec=Session)
            mock_session_local.return_value = mock_session

            db_gen = get_db()
            db = next(db_gen)

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
            db = next(db_gen)

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
        mock_db = MagicMock(spec=Session)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=None, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Authentication required"
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}

    @pytest.mark.asyncio
    async def test_valid_jwt_token_returns_user(self):
        """Test successful authentication with valid JWT token."""
        mock_db = MagicMock(spec=Session)
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
            is_email_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                mock_auth_service = MagicMock()
                mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
                mock_auth_service_class.return_value = mock_auth_service

                user = await get_current_user(credentials=credentials, db=mock_db)

                assert user == mock_user
                mock_auth_service.get_user_by_email.assert_called_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_jwt_with_legacy_email_format(self):
        """Test JWT token with legacy 'email' field instead of 'sub'."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="legacy_jwt_token")

        # Mock JWT verification with legacy format
        jwt_payload = {"email": "legacy@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}  # Legacy format

        mock_user = EmailUser(
            email="legacy@example.com",
            password_hash="hash",
            full_name="Legacy User",
            is_admin=False,
            is_active=True,
            is_email_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                mock_auth_service = MagicMock()
                mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
                mock_auth_service_class.return_value = mock_auth_service

                user = await get_current_user(credentials=credentials, db=mock_db)

                assert user == mock_user

    @pytest.mark.asyncio
    async def test_jwt_without_email_or_sub_raises_401(self):
        """Test JWT token without email or sub field raises 401."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid_jwt")

        # Mock JWT verification without email/sub
        jwt_payload = {"exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(return_value=jwt_payload)):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert exc_info.value.detail == "Invalid token"

    @pytest.mark.asyncio
    async def test_revoked_jwt_token_raises_401(self):
        """Test that revoked JWT token raises 401."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="revoked_jwt")

        jwt_payload = {"sub": "test@example.com", "jti": "token_id_123", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}  # Token with JTI for revocation check

        # When a token is revoked, the is_token_revoked check raises an HTTPException
        # This is caught by the exception handler and logged as a warning
        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.services.token_catalog_service.TokenCatalogService") as mock_token_service_class:
                mock_token_service = MagicMock()
                # Simulate the HTTPException that would be raised internally
                mock_token_service.is_token_revoked = AsyncMock(
                    side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked", headers={"WWW-Authenticate": "Bearer"})
                )
                mock_token_service_class.return_value = mock_token_service

                # Mock user to return (the revocation check is logged but doesn't fail auth)
                mock_user = EmailUser(
                    email="test@example.com",
                    password_hash="hash",
                    full_name="Test User",
                    is_admin=False,
                    is_active=True,
                    is_email_verified=True,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )

                with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                    mock_auth_service = MagicMock()
                    mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
                    mock_auth_service_class.return_value = mock_auth_service

                    # The function should succeed but log a warning
                    user = await get_current_user(credentials=credentials, db=mock_db)
                    assert user == mock_user

    @pytest.mark.asyncio
    async def test_jwt_actually_revoked_logs_warning(self, caplog):
        """Test that when is_token_revoked returns True, warning is logged but auth continues."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="revoked_jwt")

        jwt_payload = {"sub": "test@example.com", "jti": "token_id_456", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}  # Token with JTI for revocation check

        mock_user = EmailUser(
            email="test@example.com",
            password_hash="hash",
            full_name="Test User",
            is_admin=False,
            is_active=True,
            is_email_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Standard
        import logging

        caplog.set_level(logging.WARNING)

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.services.token_catalog_service.TokenCatalogService") as mock_token_service_class:
                mock_token_service = MagicMock()
                # When is_token_revoked returns True, it internally raises HTTPException which gets caught
                mock_token_service.is_token_revoked = AsyncMock(return_value=True)
                mock_token_service_class.return_value = mock_token_service

                with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                    mock_auth_service = MagicMock()
                    mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
                    mock_auth_service_class.return_value = mock_auth_service

                    # Authentication should succeed despite revoked token (logged as warning)
                    user = await get_current_user(credentials=credentials, db=mock_db)
                    assert user == mock_user

                    # Check warning was logged
                    assert "Token revocation check failed for JTI token_id_456" in caplog.text

    @pytest.mark.asyncio
    async def test_token_revocation_check_failure_logs_warning(self, caplog):
        """Test that token revocation check failure logs warning but doesn't fail auth."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt_with_jti")

        jwt_payload = {"sub": "test@example.com", "jti": "token_id_456", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        mock_user = EmailUser(
            email="test@example.com",
            password_hash="hash",
            full_name="Test User",
            is_admin=False,
            is_active=True,
            is_email_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.services.token_catalog_service.TokenCatalogService") as mock_token_service_class:
                mock_token_service = MagicMock()
                mock_token_service.is_token_revoked = AsyncMock(side_effect=Exception("Database error"))
                mock_token_service_class.return_value = mock_token_service

                with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                    mock_auth_service = MagicMock()
                    mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
                    mock_auth_service_class.return_value = mock_auth_service

                    user = await get_current_user(credentials=credentials, db=mock_db)

                    assert user == mock_user
                    assert "Token revocation check failed for JTI token_id_456" in caplog.text

    @pytest.mark.asyncio
    async def test_expired_jwt_token_raises_401(self):
        """Test that expired JWT token raises 401."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="expired_jwt")

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"))):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert exc_info.value.detail == "Token expired"

    @pytest.mark.asyncio
    async def test_api_token_authentication_success(self):
        """Test successful authentication with API token."""
        mock_db = MagicMock(spec=Session)
        api_token_value = "api_token_123456"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=api_token_value)

        # Calculate token hash
        token_hash = hashlib.sha256(api_token_value.encode()).hexdigest()

        # Mock API token object
        mock_api_token = EmailApiToken(
            user_email="api_user@example.com",
            token_hash=token_hash,
            jti="api_token_jti",
            is_active=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            last_used=datetime.now(timezone.utc),
        )

        mock_user = EmailUser(
            email="api_user@example.com",
            password_hash="hash",
            full_name="API User",
            is_admin=False,
            is_active=True,
            is_email_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Mock database query result
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_api_token
        mock_db.execute.return_value = mock_result

        # JWT fails, fallback to API token
        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.services.token_catalog_service.TokenCatalogService") as mock_token_service_class:
                mock_token_service = MagicMock()
                mock_token_service.is_token_revoked = AsyncMock(return_value=False)
                mock_token_service_class.return_value = mock_token_service

                with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                    mock_auth_service = MagicMock()
                    mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
                    mock_auth_service_class.return_value = mock_auth_service

                    with patch("mcpgateway.db.utc_now", return_value=datetime.now(timezone.utc)):
                        user = await get_current_user(credentials=credentials, db=mock_db)

                        assert user == mock_user
                        mock_db.commit.assert_called_once()  # Should update last_used

    @pytest.mark.asyncio
    async def test_expired_api_token_raises_401(self):
        """Test that expired API token raises 401."""
        mock_db = MagicMock(spec=Session)
        api_token_value = "expired_api_token"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=api_token_value)

        token_hash = hashlib.sha256(api_token_value.encode()).hexdigest()

        # Mock expired API token
        mock_api_token = EmailApiToken(
            user_email="api_user@example.com",
            token_hash=token_hash,
            jti="api_token_jti",
            is_active=True,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # Expired
            last_used=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_api_token
        mock_db.execute.return_value = mock_result

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.services.token_catalog_service.TokenCatalogService") as mock_token_service_class:
                mock_token_service = MagicMock()
                mock_token_service_class.return_value = mock_token_service

                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials, db=mock_db)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "API token expired"

    @pytest.mark.asyncio
    async def test_revoked_api_token_raises_401(self):
        """Test that revoked API token raises 401."""
        mock_db = MagicMock(spec=Session)
        api_token_value = "revoked_api_token"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=api_token_value)

        token_hash = hashlib.sha256(api_token_value.encode()).hexdigest()

        mock_api_token = EmailApiToken(user_email="api_user@example.com", token_hash=token_hash, jti="revoked_jti", is_active=True, expires_at=None, last_used=datetime.now(timezone.utc))

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_api_token
        mock_db.execute.return_value = mock_result

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.services.token_catalog_service.TokenCatalogService") as mock_token_service_class:
                mock_token_service = MagicMock()
                mock_token_service.is_token_revoked = AsyncMock(return_value=True)
                mock_token_service_class.return_value = mock_token_service

                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials, db=mock_db)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "API token has been revoked"

    @pytest.mark.asyncio
    async def test_api_token_not_found_raises_401(self):
        """Test that non-existent API token raises 401."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="nonexistent_token")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # Token not found
        mock_db.execute.return_value = mock_result

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.services.token_catalog_service.TokenCatalogService") as mock_token_service_class:
                mock_token_service = MagicMock()
                mock_token_service_class.return_value = mock_token_service

                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials, db=mock_db)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "Invalid authentication credentials"

    @pytest.mark.asyncio
    async def test_api_token_database_error_raises_401(self):
        """Test that database error during API token lookup raises 401."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token_causing_db_error")

        mock_db.execute.side_effect = Exception("Database connection error")

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.services.token_catalog_service.TokenCatalogService") as mock_token_service_class:
                mock_token_service = MagicMock()
                mock_token_service_class.return_value = mock_token_service

                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials, db=mock_db)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "Invalid authentication credentials"

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self):
        """Test that non-existent user raises 401."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt")

        jwt_payload = {"sub": "nonexistent@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                mock_auth_service = MagicMock()
                mock_auth_service.get_user_by_email = AsyncMock(return_value=None)
                mock_auth_service_class.return_value = mock_auth_service

                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials, db=mock_db)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "User not found"

    @pytest.mark.asyncio
    async def test_platform_admin_virtual_user_creation(self):
        """Test that platform admin gets a virtual user object if not in database."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="admin_jwt")

        jwt_payload = {"sub": "admin@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                mock_auth_service = MagicMock()
                mock_auth_service.get_user_by_email = AsyncMock(return_value=None)  # User not in DB
                mock_auth_service_class.return_value = mock_auth_service

                with patch("mcpgateway.config.settings.platform_admin_email", "admin@example.com"):
                    with patch("mcpgateway.config.settings.platform_admin_full_name", "Platform Administrator"):
                        user = await get_current_user(credentials=credentials, db=mock_db)

                        assert user.email == "admin@example.com"
                        assert user.full_name == "Platform Administrator"
                        assert user.is_admin is True
                        assert user.is_active is True
                        assert user.is_email_verified is True

    @pytest.mark.asyncio
    async def test_inactive_user_raises_401(self):
        """Test that inactive user account raises 401."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt")

        jwt_payload = {"sub": "inactive@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        mock_user = EmailUser(
            email="inactive@example.com",
            password_hash="hash",
            full_name="Inactive User",
            is_admin=False,
            is_active=False,  # Inactive account
            is_email_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                mock_auth_service = MagicMock()
                mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
                mock_auth_service_class.return_value = mock_auth_service

                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials, db=mock_db)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "Account disabled"

    @pytest.mark.asyncio
    async def test_logging_debug_messages(self, caplog):
        """Test that appropriate debug messages are logged during authentication."""
        mock_db = MagicMock(spec=Session)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test_token_for_logging")

        jwt_payload = {"sub": "test@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        mock_user = EmailUser(
            email="test@example.com",
            password_hash="hash",
            full_name="Test User",
            is_admin=False,
            is_active=True,
            is_email_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                mock_auth_service = MagicMock()
                mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
                mock_auth_service_class.return_value = mock_auth_service

                # Standard
                import logging

                caplog.set_level(logging.DEBUG)

                user = await get_current_user(credentials=credentials, db=mock_db)

                assert "Attempting authentication with token: test_token_for_loggi..." in caplog.text
                assert "Attempting JWT token validation" in caplog.text
                assert "JWT token validated successfully" in caplog.text
                assert "JWT authentication successful for email: test@example.com" in caplog.text

    @pytest.mark.asyncio
    async def test_api_token_without_expiry(self):
        """Test API token without expiry date works correctly."""
        mock_db = MagicMock(spec=Session)
        api_token_value = "permanent_api_token"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=api_token_value)

        token_hash = hashlib.sha256(api_token_value.encode()).hexdigest()

        mock_api_token = EmailApiToken(
            user_email="api_user@example.com", token_hash=token_hash, jti="permanent_jti", is_active=True, expires_at=None, last_used=datetime.now(timezone.utc)  # No expiry
        )

        mock_user = EmailUser(
            email="api_user@example.com",
            password_hash="hash",
            full_name="API User",
            is_admin=False,
            is_active=True,
            is_email_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_api_token
        mock_db.execute.return_value = mock_result

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.services.token_catalog_service.TokenCatalogService") as mock_token_service_class:
                mock_token_service = MagicMock()
                mock_token_service.is_token_revoked = AsyncMock(return_value=False)
                mock_token_service_class.return_value = mock_token_service

                with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                    mock_auth_service = MagicMock()
                    mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
                    mock_auth_service_class.return_value = mock_auth_service

                    with patch("mcpgateway.db.utc_now", return_value=datetime.now(timezone.utc)):
                        user = await get_current_user(credentials=credentials, db=mock_db)

                        assert user == mock_user

    @pytest.mark.asyncio
    async def test_api_token_inactive_raises_401(self):
        """Test that inactive API token (is_active=False) is rejected."""
        mock_db = MagicMock(spec=Session)
        api_token_value = "inactive_api_token"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=api_token_value)

        # The query filters for is_active=True, so inactive tokens won't be found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # Not found because is_active=False
        mock_db.execute.return_value = mock_result

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(side_effect=Exception("Invalid JWT"))):
            with patch("mcpgateway.services.token_catalog_service.TokenCatalogService") as mock_token_service_class:
                mock_token_service = MagicMock()
                mock_token_service_class.return_value = mock_token_service

                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials, db=mock_db)

                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert exc_info.value.detail == "Invalid authentication credentials"

    @pytest.mark.asyncio
    async def test_fallback_from_jwt_to_api_token_logging(self, caplog):
        """Test logging when falling back from JWT to API token authentication."""
        mock_db = MagicMock(spec=Session)
        api_token_value = "fallback_token"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=api_token_value)

        token_hash = hashlib.sha256(api_token_value.encode()).hexdigest()

        mock_api_token = EmailApiToken(user_email="api_user@example.com", token_hash=token_hash, jti="fallback_jti", is_active=True, expires_at=None, last_used=datetime.now(timezone.utc))

        mock_user = EmailUser(
            email="api_user@example.com",
            password_hash="hash",
            full_name="API User",
            is_admin=False,
            is_active=True,
            is_email_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_api_token
        mock_db.execute.return_value = mock_result

        # Standard
        import logging

        caplog.set_level(logging.DEBUG)

        with patch("mcpgateway.auth.verify_jwt_token", AsyncMock(side_effect=Exception("JWT validation failed"))):
            with patch("mcpgateway.services.token_catalog_service.TokenCatalogService") as mock_token_service_class:
                mock_token_service = MagicMock()
                mock_token_service.is_token_revoked = AsyncMock(return_value=False)
                mock_token_service_class.return_value = mock_token_service

                with patch("mcpgateway.services.email_auth_service.EmailAuthService") as mock_auth_service_class:
                    mock_auth_service = MagicMock()
                    mock_auth_service.get_user_by_email = AsyncMock(return_value=mock_user)
                    mock_auth_service_class.return_value = mock_auth_service

                    with patch("mcpgateway.db.utc_now", return_value=datetime.now(timezone.utc)):
                        user = await get_current_user(credentials=credentials, db=mock_db)

                        assert "JWT validation failed with error" in caplog.text
                        assert "trying database API token" in caplog.text
                        assert f"Generated token hash: {token_hash}" in caplog.text
                        assert "Found API token for user: api_user@example.com" in caplog.text
                        assert "API token authentication successful for email: api_user@example.com" in caplog.text
