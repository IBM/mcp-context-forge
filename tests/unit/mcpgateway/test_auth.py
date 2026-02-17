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
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user, get_db, get_user_team_roles
from mcpgateway.config import settings
from mcpgateway.db import EmailUser


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
    async def test_auth_method_set_on_cache_hit(self, monkeypatch):
        """Ensure auth_method is set when auth cache returns early."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt_token")

        payload = {
            "sub": "test@example.com",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
            "jti": "jti-123",
            "user": {"email": "test@example.com", "full_name": "Test User", "is_admin": False, "auth_provider": "local"},
        }
        cached_ctx = SimpleNamespace(
            is_token_revoked=False,
            user={"email": "test@example.com", "full_name": "Test User", "is_admin": False, "is_active": True},
            personal_team_id="team_123",
        )
        request = SimpleNamespace(state=SimpleNamespace())

        monkeypatch.setattr(settings, "auth_cache_enabled", True)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)):
            with patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)):
                user = await get_current_user(credentials=credentials, request=request)

                assert user.email == "test@example.com"
                assert request.state.auth_method == "jwt"

    @pytest.mark.asyncio
    async def test_auth_method_set_on_batched_query(self, monkeypatch):
        """Ensure auth_method is set when batched DB path returns early."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt_token")

        payload = {
            "sub": "test@example.com",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
            "jti": "jti-456",
            "user": {"email": "test@example.com", "full_name": "Test User", "is_admin": False, "auth_provider": "local"},
        }
        auth_ctx = {
            "user": {"email": "test@example.com", "full_name": "Test User", "is_admin": False, "is_active": True},
            "personal_team_id": "team_123",
            "is_token_revoked": False,
        }
        request = SimpleNamespace(state=SimpleNamespace())

        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)):
            with patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx):
                user = await get_current_user(credentials=credentials, request=request)

                assert user.email == "test@example.com"
                assert request.state.auth_method == "jwt"

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
            auth_provider="api_token",
            password_change_required=False,
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
                    assert user.auth_provider == "api_token"
                    assert user.password_change_required is False

    @pytest.mark.asyncio
    async def test_session_token_with_teams_claim_uses_embedded_teams(self):
        """Test that session tokens with single team in 'teams' claim use embedded teams instead of DB lookup."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="session_jwt_with_teams")

        # Session token with explicit single team claim
        jwt_payload = {
            "sub": "test@example.com",
            "token_use": "session",
            "teams": ["team-123"],
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        }

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
                with patch("mcpgateway.auth._resolve_teams_from_db") as mock_resolve_teams:
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        user = await get_current_user(credentials=credentials)

                        # Verify user was authenticated
                        assert user.email == mock_user.email

                        # Verify _resolve_teams_from_db was NOT called (teams came from token)
                        mock_resolve_teams.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_token_without_teams_claim_resolves_from_db(self):
        """Test that session tokens without 'teams' claim resolve teams from DB."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="session_jwt_no_teams")

        # Session token WITHOUT teams claim
        jwt_payload = {
            "sub": "test@example.com",
            "token_use": "session",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        }

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
                with patch("mcpgateway.auth._resolve_teams_from_db", return_value=["db-team-1"]) as mock_resolve_teams:
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        user = await get_current_user(credentials=credentials)

                        # Verify user was authenticated
                        assert user.email == mock_user.email

                        # Verify _resolve_teams_from_db WAS called
                        mock_resolve_teams.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_token_with_null_teams_claim_uses_db_resolve(self):
        """Test that session tokens with teams=null use _resolve_teams_from_db (which returns None for admin)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="session_jwt_null_teams")

        # Session token with explicit null teams (admin bypass)
        jwt_payload = {
            "sub": "admin@example.com",
            "token_use": "session",
            "teams": None,
            "is_admin": True,
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        }

        mock_user = EmailUser(
            email="admin@example.com",
            password_hash="hash",
            full_name="Admin User",
            is_admin=True,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._resolve_teams_from_db", return_value=None) as mock_resolve_teams:
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        user = await get_current_user(credentials=credentials)

                        # Verify user was authenticated
                        assert user.email == mock_user.email

                        # Verify _resolve_teams_from_db WAS called (teams=null is not a list with len==1)
                        mock_resolve_teams.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_token_always_uses_embedded_teams(self):
        """Test that API tokens always use embedded teams regardless of teams claim."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="api_jwt_token")

        # API token (not session)
        jwt_payload = {
            "sub": "api@example.com",
            "token_use": "api",
            "teams": ["api-team-1"],
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        }

        mock_user = EmailUser(
            email="api@example.com",
            password_hash="hash",
            full_name="API User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._resolve_teams_from_db") as mock_resolve_teams:
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        user = await get_current_user(credentials=credentials)

                        # Verify user was authenticated
                        assert user.email == mock_user.email

                        # Verify _resolve_teams_from_db was NOT called (API tokens use embedded teams)
                        mock_resolve_teams.assert_not_called()

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
    async def test_require_user_in_db_rejects_platform_admin(self):
        """Test that REQUIRE_USER_IN_DB=true rejects even platform admin when user not in DB."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="admin_jwt")

        jwt_payload = {"sub": "admin@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):  # User not in DB
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    with patch("mcpgateway.config.settings.platform_admin_email", "admin@example.com"):
                        with patch("mcpgateway.config.settings.require_user_in_db", True):
                            with pytest.raises(HTTPException) as exc_info:
                                await get_current_user(credentials=credentials)

                            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                            assert exc_info.value.detail == "User not found in database"

    @pytest.mark.asyncio
    async def test_require_user_in_db_allows_existing_user(self):
        """Test that REQUIRE_USER_IN_DB=true allows users that exist in the database."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt")

        jwt_payload = {"sub": "existing@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        mock_user = EmailUser(
            email="existing@example.com",
            password_hash="hash",
            full_name="Existing User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    with patch("mcpgateway.config.settings.require_user_in_db", True):
                        user = await get_current_user(credentials=credentials)

                        assert user.email == "existing@example.com"
                        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_require_user_in_db_logs_rejection(self, caplog):
        """Test that REQUIRE_USER_IN_DB rejection is logged."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="admin_jwt")

        jwt_payload = {"sub": "admin@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    with patch("mcpgateway.config.settings.require_user_in_db", True):
                        with caplog.at_level(logging.WARNING):
                            with pytest.raises(HTTPException):
                                await get_current_user(credentials=credentials)

                        assert any("REQUIRE_USER_IN_DB is enabled" in record.message for record in caplog.records)
                        assert any("user not found in database" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_require_user_in_db_rejects_cached_user_not_in_db(self):
        """Test that REQUIRE_USER_IN_DB=true rejects cached users that no longer exist in DB."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt")

        jwt_payload = {"sub": "cached@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        # Mock cached auth context with a user
        mock_cached_ctx = MagicMock()
        mock_cached_ctx.is_token_revoked = False
        mock_cached_ctx.user = {"email": "cached@example.com", "is_active": True, "is_admin": False}
        mock_cached_ctx.personal_team_id = None

        mock_auth_cache = MagicMock()
        mock_auth_cache.get_auth_context = AsyncMock(return_value=mock_cached_ctx)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.config.settings.auth_cache_enabled", True):
                with patch("mcpgateway.cache.auth_cache.auth_cache", mock_auth_cache):
                    with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):  # User deleted from DB
                        with patch("mcpgateway.config.settings.require_user_in_db", True):
                            with pytest.raises(HTTPException) as exc_info:
                                await get_current_user(credentials=credentials)

                            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                            assert exc_info.value.detail == "User not found in database"

    @pytest.mark.asyncio
    async def test_require_user_in_db_batched_path_rejects_missing_user(self):
        """Test that REQUIRE_USER_IN_DB=true rejects users via batched auth path."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="admin_jwt")

        jwt_payload = {"sub": "admin@example.com", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        # Mock the batched query to return no user (user=None means not found)
        mock_batch_result = {"user": None, "is_token_revoked": False, "personal_team_id": None}

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.config.settings.auth_cache_enabled", False):  # Disable cache
                with patch("mcpgateway.config.settings.auth_cache_batch_queries", True):  # Enable batched queries
                    with patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=mock_batch_result):
                        with patch("mcpgateway.config.settings.platform_admin_email", "admin@example.com"):
                            with patch("mcpgateway.config.settings.require_user_in_db", True):
                                with pytest.raises(HTTPException) as exc_info:
                                    await get_current_user(credentials=credentials)

                                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                                assert exc_info.value.detail == "User not found in database"

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
        # First-Party
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


class TestGetSyncRedisClient:
    """Test cases for _get_sync_redis_client helper function."""

    def test_get_sync_redis_client_returns_cached_client(self):
        """Test that _get_sync_redis_client returns cached client if already initialized."""
        # First-Party
        from mcpgateway import auth

        # Set up a mock cached client
        mock_redis = MagicMock()
        auth._SYNC_REDIS_CLIENT = mock_redis

        try:
            result = auth._get_sync_redis_client()
            assert result is mock_redis
        finally:
            # Clean up
            auth._SYNC_REDIS_CLIENT = None

    def test_get_sync_redis_client_returns_none_when_redis_not_configured(self):
        """Test that _get_sync_redis_client returns None when Redis is not configured."""
        # First-Party
        from mcpgateway import auth

        # Reset cached client
        auth._SYNC_REDIS_CLIENT = None

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.redis_url = ""
            mock_settings.cache_type = "redis"

            result = auth._get_sync_redis_client()
            assert result is None

    def test_get_sync_redis_client_returns_none_when_cache_type_not_redis(self):
        """Test that _get_sync_redis_client returns None when cache_type is not redis."""
        # First-Party
        from mcpgateway import auth

        # Reset cached client
        auth._SYNC_REDIS_CLIENT = None

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            mock_settings.cache_type = "memory"

            result = auth._get_sync_redis_client()
            assert result is None

    def test_get_sync_redis_client_initializes_on_first_call(self):
        """Test that _get_sync_redis_client initializes Redis client on first call."""
        # Standard
        import sys

        # First-Party
        from mcpgateway import auth

        # Reset cached client
        original_client = auth._SYNC_REDIS_CLIENT
        auth._SYNC_REDIS_CLIENT = None

        try:
            mock_redis_client = MagicMock()
            mock_redis_client.ping.return_value = True

            # Mock the redis module
            mock_redis_module = MagicMock()
            mock_redis_module.from_url.return_value = mock_redis_client

            with patch("mcpgateway.config.settings") as mock_settings, patch.dict(sys.modules, {"redis": mock_redis_module}):
                mock_settings.redis_url = "redis://localhost:6379/0"
                mock_settings.cache_type = "redis"

                result = auth._get_sync_redis_client()

                mock_redis_module.from_url.assert_called_once()
                mock_redis_client.ping.assert_called_once()
                assert result is mock_redis_client
                # Verify it's cached
                assert auth._SYNC_REDIS_CLIENT is mock_redis_client
        finally:
            # Restore original state
            auth._SYNC_REDIS_CLIENT = original_client

    def test_get_sync_redis_client_handles_redis_connection_failure(self):
        """Test that _get_sync_redis_client handles Redis connection failure gracefully."""
        # Standard
        import sys

        # First-Party
        from mcpgateway import auth

        # Reset cached client
        original_client = auth._SYNC_REDIS_CLIENT
        auth._SYNC_REDIS_CLIENT = None

        try:
            # Mock the redis module to raise an exception
            mock_redis_module = MagicMock()
            mock_redis_module.from_url.side_effect = Exception("Connection failed")

            with patch("mcpgateway.config.settings") as mock_settings, patch.dict(sys.modules, {"redis": mock_redis_module}):
                mock_settings.redis_url = "redis://localhost:6379/0"
                mock_settings.cache_type = "redis"

                result = auth._get_sync_redis_client()

                assert result is None
                # Verify None is cached
                assert auth._SYNC_REDIS_CLIENT is None
        finally:
            # Restore original state
            auth._SYNC_REDIS_CLIENT = original_client

    def test_get_sync_redis_client_handles_redis_ping_failure(self):
        """Test that _get_sync_redis_client handles Redis ping failure gracefully."""
        # Standard
        import sys

        # First-Party
        from mcpgateway import auth

        # Reset cached client
        original_client = auth._SYNC_REDIS_CLIENT
        auth._SYNC_REDIS_CLIENT = None

        try:
            mock_redis_client = MagicMock()
            mock_redis_client.ping.side_effect = Exception("Ping failed")

            # Mock the redis module
            mock_redis_module = MagicMock()
            mock_redis_module.from_url.return_value = mock_redis_client

            with patch("mcpgateway.config.settings") as mock_settings, patch.dict(sys.modules, {"redis": mock_redis_module}):
                mock_settings.redis_url = "redis://localhost:6379/0"
                mock_settings.cache_type = "redis"

                result = auth._get_sync_redis_client()

                assert result is None
                # Verify None is cached
                assert auth._SYNC_REDIS_CLIENT is None
        finally:
            # Restore original state
            auth._SYNC_REDIS_CLIENT = original_client

    def test_get_sync_redis_client_double_check_locking(self):
        """Test that _get_sync_redis_client properly handles double-check locking."""
        # Standard
        import sys
        import threading

        # First-Party
        from mcpgateway import auth

        # Reset cached client
        original_client = auth._SYNC_REDIS_CLIENT
        auth._SYNC_REDIS_CLIENT = None

        try:
            mock_redis_client = MagicMock()
            mock_redis_client.ping.return_value = True

            call_count = 0

            def mock_from_url_with_delay(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                # Simulate initialization delay
                # Standard
                import time

                time.sleep(0.01)
                return mock_redis_client

            # Mock the redis module
            mock_redis_module = MagicMock()
            mock_redis_module.from_url.side_effect = mock_from_url_with_delay

            with patch("mcpgateway.config.settings") as mock_settings, patch.dict(sys.modules, {"redis": mock_redis_module}):
                mock_settings.redis_url = "redis://localhost:6379/0"
                mock_settings.cache_type = "redis"

                # Call from multiple threads simultaneously
                results = []

                def call_get_sync():
                    results.append(auth._get_sync_redis_client())

                threads = [threading.Thread(target=call_get_sync) for _ in range(5)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                # Should only initialize once despite multiple concurrent calls
                assert call_count <= 1  # May be 0 if already cached or 1 if initialized
                # All threads should get the same instance (or None if uninitialized)
                assert all(r == results[0] for r in results)
        finally:
            # Restore original state
            auth._SYNC_REDIS_CLIENT = original_client

    def test_get_sync_redis_client_backoff_after_failure(self):
        """Test that _get_sync_redis_client backs off for 30s after a failure."""
        # Standard
        import sys
        import time as time_module

        # First-Party
        from mcpgateway import auth

        # Save and reset state
        original_client = auth._SYNC_REDIS_CLIENT
        original_failure_time = auth._SYNC_REDIS_FAILURE_TIME
        auth._SYNC_REDIS_CLIENT = None
        auth._SYNC_REDIS_FAILURE_TIME = None

        try:
            mock_redis_module = MagicMock()
            mock_redis_module.from_url.side_effect = Exception("Connection refused")

            with patch("mcpgateway.config.settings") as mock_settings, patch.dict(sys.modules, {"redis": mock_redis_module}):
                mock_settings.redis_url = "redis://localhost:6379/0"
                mock_settings.cache_type = "redis"

                # First call: should attempt connection and fail
                result1 = auth._get_sync_redis_client()
                assert result1 is None
                assert auth._SYNC_REDIS_FAILURE_TIME is not None
                mock_redis_module.from_url.assert_called_once()

                # Second call within 30s: should skip retry due to backoff
                mock_redis_module.from_url.reset_mock()
                result2 = auth._get_sync_redis_client()
                assert result2 is None
                mock_redis_module.from_url.assert_not_called()

                # Simulate 31 seconds passing
                auth._SYNC_REDIS_FAILURE_TIME = time_module.time() - 31

                # Third call after backoff: should retry
                mock_redis_module.from_url.reset_mock()
                mock_redis_module.from_url.side_effect = Exception("Still down")
                result3 = auth._get_sync_redis_client()
                assert result3 is None
                mock_redis_module.from_url.assert_called_once()
        finally:
            auth._SYNC_REDIS_CLIENT = original_client
            auth._SYNC_REDIS_FAILURE_TIME = original_failure_time


class TestUpdateApiTokenLastUsed:
    """Test cases for _update_api_token_last_used_sync helper function."""

    def test_update_api_token_last_used_sync_updates_timestamp(self):
        """Test that _update_api_token_last_used_sync updates last_used timestamp."""
        # First-Party
        from mcpgateway.auth import _update_api_token_last_used_sync
        from mcpgateway.db import EmailApiToken

        mock_api_token = MagicMock(spec=EmailApiToken)
        mock_api_token.jti = "jti-123"
        mock_api_token.last_used = None

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_api_token
        mock_db.execute.return_value = mock_result

        with patch("mcpgateway.auth.fresh_db_session") as mock_fresh_session:
            mock_fresh_session.return_value.__enter__.return_value = mock_db
            mock_fresh_session.return_value.__exit__.return_value = None

            with patch("mcpgateway.db.utc_now") as mock_utc_now:
                mock_time = datetime(2026, 2, 3, 12, 0, 0, tzinfo=timezone.utc)
                mock_utc_now.return_value = mock_time

                _update_api_token_last_used_sync("jti-123")

                # Verify last_used was updated
                assert mock_api_token.last_used == mock_time
                mock_db.commit.assert_called_once()

    def test_update_api_token_last_used_sync_handles_missing_token(self):
        """Test that _update_api_token_last_used_sync handles missing token gracefully."""
        # First-Party
        from mcpgateway.auth import _update_api_token_last_used_sync

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # Token not found
        mock_db.execute.return_value = mock_result

        with patch("mcpgateway.auth.fresh_db_session") as mock_fresh_session:
            mock_fresh_session.return_value.__enter__.return_value = mock_db
            mock_fresh_session.return_value.__exit__.return_value = None

            # Should not raise exception
            _update_api_token_last_used_sync("jti-nonexistent")

            # Should not commit if token not found
            mock_db.commit.assert_not_called()

    def test_update_api_token_last_used_sync_rate_limits_with_redis(self):
        """Test that _update_api_token_last_used_sync rate-limits updates using Redis."""
        # First-Party
        from mcpgateway.auth import _update_api_token_last_used_sync

        mock_redis_client = MagicMock()
        mock_redis_client.get.return_value = "1234567890.0"  # Last update timestamp

        with (
            patch("mcpgateway.auth._get_sync_redis_client", return_value=mock_redis_client),
            patch("mcpgateway.auth.settings") as mock_settings,
            patch("mcpgateway.auth.fresh_db_session") as mock_fresh_session,
            patch("time.time", return_value=1234567890.0),
        ):  # Same time (no elapsed time)
            mock_settings.token_last_used_update_interval_minutes = 5

            _update_api_token_last_used_sync("jti-123")

            # Should skip DB update due to rate limiting
            mock_fresh_session.assert_not_called()
            mock_redis_client.get.assert_called_once_with("api_token_last_used:jti-123")

    def test_update_api_token_last_used_sync_updates_after_interval(self):
        """Test that _update_api_token_last_used_sync updates after rate-limit interval."""
        # First-Party
        from mcpgateway.auth import _update_api_token_last_used_sync
        from mcpgateway.db import EmailApiToken

        mock_api_token = MagicMock(spec=EmailApiToken)
        mock_api_token.jti = "jti-123"
        mock_api_token.last_used = None

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_api_token
        mock_db.execute.return_value = mock_result

        mock_redis_client = MagicMock()
        # Last update was 400 seconds ago (> 5 minutes)
        mock_redis_client.get.return_value = "1234567490.0"

        with (
            patch("mcpgateway.auth._get_sync_redis_client", return_value=mock_redis_client),
            patch("mcpgateway.auth.settings") as mock_settings,
            patch("mcpgateway.auth.fresh_db_session") as mock_fresh_session,
            patch("time.time", return_value=1234567890.0),
            patch("mcpgateway.db.utc_now") as mock_utc_now,
        ):
            mock_settings.token_last_used_update_interval_minutes = 5
            mock_fresh_session.return_value.__enter__.return_value = mock_db
            mock_fresh_session.return_value.__exit__.return_value = None
            mock_time = datetime(2026, 2, 3, 12, 0, 0, tzinfo=timezone.utc)
            mock_utc_now.return_value = mock_time

            _update_api_token_last_used_sync("jti-123")

            # Should update DB after rate-limit interval
            mock_fresh_session.assert_called_once()
            mock_db.commit.assert_called_once()
            assert mock_api_token.last_used == mock_time
            # Should update Redis cache
            mock_redis_client.setex.assert_called_once()

    def test_update_api_token_last_used_sync_falls_back_to_memory_cache(self):
        """Test that _update_api_token_last_used_sync falls back to in-memory cache when Redis unavailable."""
        # Standard
        import sys

        # First-Party
        from mcpgateway.auth import _update_api_token_last_used_sync
        from mcpgateway.db import EmailApiToken

        # First-Party
        from mcpgateway import auth

        # Clear the module-level in-memory cache
        auth._LAST_USED_CACHE.clear()

        mock_api_token = MagicMock(spec=EmailApiToken)
        mock_api_token.jti = "jti-fallback-123"
        mock_api_token.last_used = None

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_api_token
        mock_db.execute.return_value = mock_result

        # Mock the redis module to raise an exception
        mock_redis_module = MagicMock()
        mock_redis_module.from_url.side_effect = Exception("Redis unavailable")

        with (
            patch("mcpgateway.auth.settings") as mock_settings,
            patch.dict(sys.modules, {"redis": mock_redis_module}),
            patch("mcpgateway.auth.fresh_db_session") as mock_fresh_session,
            patch("time.time", return_value=1234567890.0),
            patch("mcpgateway.db.utc_now") as mock_utc_now,
        ):
            mock_settings.redis_url = "redis://localhost:6379/0"
            mock_settings.cache_type = "redis"
            mock_settings.token_last_used_update_interval_minutes = 5
            mock_fresh_session.return_value.__enter__.return_value = mock_db
            mock_fresh_session.return_value.__exit__.return_value = None
            mock_time = datetime(2026, 2, 3, 12, 0, 0, tzinfo=timezone.utc)
            mock_utc_now.return_value = mock_time

            # First call should update
            _update_api_token_last_used_sync("jti-fallback-123")
            mock_db.commit.assert_called_once()
            assert mock_api_token.last_used == mock_time

            # Second call immediately after should be rate-limited
            mock_db.reset_mock()
            _update_api_token_last_used_sync("jti-fallback-123")
            mock_db.commit.assert_not_called()

    def test_update_api_token_last_used_sync_redis_exception_falls_back_to_memory(self):
        """Test that _update_api_token_last_used_sync falls back to memory cache when Redis operations fail."""
        # First-Party
        from mcpgateway.auth import _update_api_token_last_used_sync
        from mcpgateway.db import EmailApiToken

        # First-Party
        from mcpgateway import auth

        # Clear the module-level in-memory cache
        auth._LAST_USED_CACHE.clear()

        mock_api_token = MagicMock(spec=EmailApiToken)
        mock_api_token.jti = "jti-redis-error-123"
        mock_api_token.last_used = None

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_api_token
        mock_db.execute.return_value = mock_result

        # Mock a Redis client that exists but throws exceptions on operations
        mock_redis_client = MagicMock()
        mock_redis_client.get.side_effect = Exception("Redis get failed")

        with (
            patch("mcpgateway.auth.settings") as mock_settings,
            patch("mcpgateway.auth._get_sync_redis_client", return_value=mock_redis_client),
            patch("mcpgateway.auth.fresh_db_session") as mock_fresh_session,
            patch("time.time", return_value=1234567890.0),
            patch("mcpgateway.db.utc_now") as mock_utc_now,
        ):
            mock_settings.token_last_used_update_interval_minutes = 5
            mock_fresh_session.return_value.__enter__.return_value = mock_db
            mock_fresh_session.return_value.__exit__.return_value = None
            mock_time = datetime(2026, 2, 3, 12, 0, 0, tzinfo=timezone.utc)
            mock_utc_now.return_value = mock_time

            # Should fall back to in-memory cache when Redis get fails
            _update_api_token_last_used_sync("jti-redis-error-123")

            # Verify Redis was attempted
            mock_redis_client.get.assert_called()
            # Verify DB update still occurred via fallback
            mock_db.commit.assert_called_once()
            assert mock_api_token.last_used == mock_time

    @pytest.mark.asyncio
    async def test_api_token_last_used_updated_on_jwt_auth(self, monkeypatch):
        """Test that last_used is updated when API token is authenticated via JWT."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="api_token_jwt")

        jwt_payload = {
            "sub": "api@example.com",
            "jti": "jti-api-456",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
            "user": {"auth_provider": "api_token"},
        }

        mock_user = EmailUser(
            email="api@example.com",
            password_hash="hash",
            full_name="API User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        request = SimpleNamespace(state=SimpleNamespace())

        # Disable batch queries to use the standard code path that's already mocked
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    with patch("mcpgateway.auth._update_api_token_last_used_sync") as mock_update:
                        with patch("mcpgateway.auth.asyncio.to_thread", AsyncMock(side_effect=lambda f, *args: f(*args))):
                            user = await get_current_user(credentials=credentials, request=request)

                            # Verify user was authenticated
                            assert user.email == "api@example.com"

                            # Verify auth_method was set to api_token
                            assert request.state.auth_method == "api_token"

                            # Verify JTI was stored in request.state
                            assert request.state.jti == "jti-api-456"

                            # Verify last_used update was called
                            mock_update.assert_called_once_with("jti-api-456")

    @pytest.mark.asyncio
    async def test_api_token_last_used_update_failure_continues_auth(self, monkeypatch):
        """Test that authentication continues even if last_used update fails (lines 711-712)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="api_token_jwt")

        jwt_payload = {
            "sub": "api@example.com",
            "jti": "jti-api-fail-123",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
            "user": {"auth_provider": "api_token"},
        }

        mock_user = EmailUser(
            email="api@example.com",
            password_hash="hash",
            full_name="API User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        request = SimpleNamespace(state=SimpleNamespace())

        # Disable batch queries to use the standard code path that's already mocked
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        # Mock the update function to raise an exception
        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                        with patch("mcpgateway.auth._update_api_token_last_used_sync", side_effect=Exception("DB connection failed")):
                            with patch("mcpgateway.auth.asyncio.to_thread", AsyncMock(side_effect=lambda f, *args: f(*args))):
                                # Authentication should succeed despite update failure
                                user = await get_current_user(credentials=credentials, request=request)

                                # Verify user was authenticated
                                assert user.email == "api@example.com"

                                # Verify auth_method was still set to api_token
                                assert request.state.auth_method == "api_token"

    @pytest.mark.asyncio
    async def test_api_token_jti_stored_in_request_state(self, monkeypatch):
        """Test that JTI is stored in request.state for middleware use."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt_with_jti")

        jwt_payload = {
            "sub": "test@example.com",
            "jti": "jti-store-test-789",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
            "user": {
                "email": "test@example.com",
                "auth_provider": "email",
            },
        }

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

        request = SimpleNamespace(state=SimpleNamespace())

        # Disable batch queries to use the standard code path that's already mocked
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value="team_123"):
                    user = await get_current_user(credentials=credentials, request=request)

                    # Verify user was authenticated
                    assert user.email == "test@example.com"

                    # Verify JTI was stored in request.state
                    assert hasattr(request.state, "jti")
                    assert request.state.jti == "jti-store-test-789"

    @pytest.mark.asyncio
    async def test_legacy_api_token_last_used_updated(self, monkeypatch):
        """Test that last_used is updated for legacy API tokens (DB lookup path)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="legacy_api_token")

        # JWT payload without auth_provider (legacy format)
        jwt_payload = {
            "sub": "legacy@example.com",
            "jti": "jti-legacy-999",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        }

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

        request = SimpleNamespace(state=SimpleNamespace())

        # Disable batch queries to use the standard code path that's already mocked
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    with patch("mcpgateway.auth._is_api_token_jti_sync", return_value=True):
                        with patch("mcpgateway.auth._update_api_token_last_used_sync") as mock_update:
                            with patch("mcpgateway.auth.asyncio.to_thread", AsyncMock(side_effect=lambda f, *args: f(*args))):
                                user = await get_current_user(credentials=credentials, request=request)

                                # Verify user was authenticated
                                assert user.email == "legacy@example.com"

                                # Verify auth_method was set to api_token
                                assert request.state.auth_method == "api_token"

                                # Verify last_used update was called for legacy token
                                assert mock_update.call_count == 1
                                mock_update.assert_called_with("jti-legacy-999")

    @pytest.mark.asyncio
    async def test_legacy_api_token_last_used_update_failure_continues_auth(self, monkeypatch):
        """Test that authentication continues even if legacy token last_used update fails (lines 732-733)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="legacy_api_token")

        # JWT payload without auth_provider (legacy format)
        jwt_payload = {
            "sub": "legacy@example.com",
            "jti": "jti-legacy-fail-888",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        }

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

        request = SimpleNamespace(state=SimpleNamespace())

        # Disable batch queries to use the standard code path that's already mocked
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        # Mock functions individually
        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                        with patch("mcpgateway.auth._is_api_token_jti_sync", return_value=True):
                            with patch("mcpgateway.auth._update_api_token_last_used_sync", side_effect=Exception("DB update failed")):
                                with patch("mcpgateway.auth.asyncio.to_thread", AsyncMock(side_effect=lambda f, *args: f(*args))):
                                    # Authentication should succeed despite update failure
                                    user = await get_current_user(credentials=credentials, request=request)

                                    # Verify user was authenticated
                                    assert user.email == "legacy@example.com"

                                    # Verify auth_method was still set to api_token
                                    assert request.state.auth_method == "api_token"

                                    # Verify JTI was stored in request.state
                                    assert request.state.jti == "jti-legacy-fail-888"

    def test_update_api_token_last_used_sync_evicts_old_cache_entries(self):
        """Test that in-memory cache evicts oldest entries when max size is reached."""
        # First-Party
        from mcpgateway import auth
        from mcpgateway.auth import _update_api_token_last_used_sync
        from mcpgateway.db import EmailApiToken

        # Clear the module-level cache
        auth._LAST_USED_CACHE.clear()

        mock_api_token = MagicMock(spec=EmailApiToken)
        mock_api_token.jti = "jti-evict"
        mock_api_token.last_used = None

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_api_token
        mock_db.execute.return_value = mock_result

        # Pre-fill cache to _MAX_CACHE_SIZE (1024) entries
        base_time = 1000000.0
        for i in range(1024):
            auth._LAST_USED_CACHE[f"jti-old-{i}"] = base_time + i

        assert len(auth._LAST_USED_CACHE) == 1024

        with (
            patch("mcpgateway.auth._get_sync_redis_client", return_value=None),
            patch("mcpgateway.auth.settings") as mock_settings,
            patch("mcpgateway.auth.fresh_db_session") as mock_fresh_session,
            patch("time.time", return_value=base_time + 2000),
            patch("mcpgateway.db.utc_now") as mock_utc_now,
        ):
            mock_settings.token_last_used_update_interval_minutes = 5
            mock_fresh_session.return_value.__enter__.return_value = mock_db
            mock_fresh_session.return_value.__exit__.return_value = None
            mock_utc_now.return_value = datetime(2026, 2, 3, 12, 0, 0, tzinfo=timezone.utc)

            _update_api_token_last_used_sync("jti-evict")

        # Cache should have been evicted to ~512 + the new entry
        assert len(auth._LAST_USED_CACHE) <= 513
        assert "jti-evict" in auth._LAST_USED_CACHE
        # Oldest entries (lower indices) should have been evicted
        assert "jti-old-0" not in auth._LAST_USED_CACHE
        # Newer entries should remain
        assert "jti-old-1023" in auth._LAST_USED_CACHE

    def test_update_api_token_last_used_sync_no_jti_in_api_token(self):
        """Test that _set_auth_method_from_payload handles api_token without JTI."""
        # This tests the branch where auth_provider == "api_token" but no JTI is present
        # First-Party
        from mcpgateway.auth import _update_api_token_last_used_sync

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("mcpgateway.auth._get_sync_redis_client", return_value=None), patch("mcpgateway.auth.settings") as mock_settings, patch("mcpgateway.auth.fresh_db_session") as mock_fresh_session:
            mock_settings.token_last_used_update_interval_minutes = 5
            mock_fresh_session.return_value.__enter__.return_value = mock_db
            mock_fresh_session.return_value.__exit__.return_value = None

            # Should not raise when token not found
            _update_api_token_last_used_sync("jti-nonexistent-xyz")

            # DB was queried but no commit since token not found
            mock_db.execute.assert_called_once()
            mock_db.commit.assert_not_called()


# ============================================================================
# Coverage improvement tests
# ============================================================================


class TestLogAuthEventBranches:
    """Tests for _log_auth_event helper covering optional parameters."""

    def test_log_auth_event_without_user_id_and_auth_method(self):
        """Test _log_auth_event when user_id and auth_method are None."""
        # First-Party
        from mcpgateway.auth import _log_auth_event

        captured = {}

        class FakeLogger:
            def log(self, level, message, extra=None):
                captured["extra"] = extra

        with patch("mcpgateway.auth.get_correlation_id", return_value="req-2"):
            _log_auth_event(FakeLogger(), "msg", user_id=None, auth_method=None)

        assert "user_id" not in captured["extra"]
        assert "auth_method" not in captured["extra"]


class TestNormalizeTokenTeamsEdgeCases:
    """Tests for normalize_token_teams edge cases."""

    def test_dict_without_id_skipped(self):
        """Dict team entry with no 'id' key is skipped (branch 194->191)."""
        # First-Party
        from mcpgateway.auth import normalize_token_teams

        result = normalize_token_teams({"teams": [{"name": "team-no-id"}, "team2"]})
        assert result == ["team2"]

    def test_non_string_non_dict_team_skipped(self):
        """Numeric team entry is skipped (branch 196->191)."""
        # First-Party
        from mcpgateway.auth import normalize_token_teams

        result = normalize_token_teams({"teams": [42, "team1"]})
        assert result == ["team1"]

    def test_teams_null_non_admin_no_user(self):
        """Null teams with user as non-dict is treated as non-admin."""
        # First-Party
        from mcpgateway.auth import normalize_token_teams

        result = normalize_token_teams({"teams": None, "user": "not-a-dict"})
        assert result == []


class TestGetDbInvalidateException:
    """Test get_db rollback + invalidate both failing."""

    def test_invalidate_also_fails(self):
        """Invalidate exception is swallowed (pass) (lines 118-119)."""
        # First-Party
        from mcpgateway.auth import get_db

        class FailSession:
            def rollback(self):
                raise RuntimeError("rollback fail")

            def invalidate(self):
                raise RuntimeError("invalidate fail")

            def close(self):
                pass

        with patch("mcpgateway.auth.SessionLocal", return_value=FailSession()):
            gen = get_db()
            next(gen)
            with pytest.raises(RuntimeError, match="body error"):
                gen.throw(RuntimeError("body error"))


class TestLookupApiTokenSyncNone:
    """Test _lookup_api_token_sync returns None for missing token."""

    def test_api_token_not_found(self, monkeypatch):
        """Returns None when no API token matches (line 322)."""
        # Standard
        from contextlib import contextmanager

        class DummyResult:
            def scalar_one_or_none(self):
                return None

        class DummySession:
            def execute(self, _q):
                return DummyResult()

        @contextmanager
        def _session_ctx():
            yield DummySession()

        monkeypatch.setattr("mcpgateway.auth.fresh_db_session", _session_ctx)
        # First-Party
        from mcpgateway.auth import _lookup_api_token_sync

        result = _lookup_api_token_sync("nonexistent_hash")
        assert result is None


class TestGetUserByEmailSyncNone:
    """Test _get_user_by_email_sync returns None for missing user."""

    def test_user_not_found(self, monkeypatch):
        """Returns None when user not in DB (line 387)."""
        # Standard
        from contextlib import contextmanager

        class DummyResult:
            def scalar_one_or_none(self):
                return None

        class DummySession:
            def execute(self, _q):
                return DummyResult()

        @contextmanager
        def _session_ctx():
            yield DummySession()

        monkeypatch.setattr("mcpgateway.auth.fresh_db_session", _session_ctx)
        # First-Party
        from mcpgateway.auth import _get_user_by_email_sync

        result = _get_user_by_email_sync("missing@example.com")
        assert result is None


class TestBatchedSyncNoPTeam:
    """Test _get_auth_context_batched_sync with user but no personal team."""

    def test_no_personal_team(self, monkeypatch):
        """User exists but has no personal team (branch 455->459)."""
        # Standard
        from contextlib import contextmanager

        results = [
            SimpleNamespace(  # user
                email="user@example.com",
                password_hash="h",
                full_name="U",
                is_admin=False,
                is_active=True,
                auth_provider="local",
                password_change_required=False,
                email_verified_at=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ),
            None,  # no personal team
            [],  # no team memberships (query 4: team_ids)
        ]

        class DummyResult:
            def __init__(self, val):
                self._val = val

            def scalar_one_or_none(self):
                return self._val

            def all(self):
                return self._val if isinstance(self._val, list) else []

        class DummySession:
            def __init__(self):
                self._idx = 0

            def execute(self, _q):
                val = results[self._idx] if self._idx < len(results) else None
                self._idx += 1
                return DummyResult(val)

        @contextmanager
        def _session_ctx():
            yield DummySession()

        monkeypatch.setattr("mcpgateway.auth.fresh_db_session", _session_ctx)
        # First-Party
        from mcpgateway.auth import _get_auth_context_batched_sync

        result = _get_auth_context_batched_sync("user@example.com")
        assert result["user"] is not None
        assert result["personal_team_id"] is None
        assert result["team_ids"] == []


class TestSetAuthMethodFromPayload:
    """Tests for _set_auth_method_from_payload inner function."""

    @pytest.fixture(autouse=True)
    def disable_auth_cache(self, monkeypatch):
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

    @pytest.mark.asyncio
    async def test_api_token_auth_provider(self):
        """auth_provider == 'api_token' → request.state.auth_method = 'api_token' (lines 524-525)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt")
        payload = {
            "sub": "user@example.com",
            "user": {"auth_provider": "api_token"},
            "jti": "jti-123",
        }
        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            auth_provider="api_token",
            password_change_required=False,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        request = SimpleNamespace(state=SimpleNamespace())

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
            patch("mcpgateway.auth._update_api_token_last_used_sync", return_value=None),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert request.state.auth_method == "api_token"

    @pytest.mark.asyncio
    async def test_legacy_api_token_jti_check(self):
        """No auth_provider + JTI → legacy DB check (lines 534-544)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt")
        payload = {
            "sub": "user@example.com",
            "user": {},  # no auth_provider
            "jti": "legacy-jti",
        }
        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        request = SimpleNamespace(state=SimpleNamespace())

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
            patch("mcpgateway.auth._is_api_token_jti_sync", return_value=True),
            patch("mcpgateway.auth._update_api_token_last_used_sync", return_value=None),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert request.state.auth_method == "api_token"

    @pytest.mark.asyncio
    async def test_legacy_non_api_token_jti(self):
        """No auth_provider + JTI not in api_tokens → jwt (lines 540-541)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt")
        payload = {
            "sub": "user@example.com",
            "user": {},
            "jti": "not-api-jti",
        }
        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        request = SimpleNamespace(state=SimpleNamespace())

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._is_api_token_jti_sync", return_value=False),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert request.state.auth_method == "jwt"

    @pytest.mark.asyncio
    async def test_no_auth_provider_no_jti(self):
        """No auth_provider and no JTI → default jwt (lines 542-544)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt")
        payload = {
            "sub": "user@example.com",
            "user": {},
            # no jti
        }
        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        request = SimpleNamespace(state=SimpleNamespace())

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert request.state.auth_method == "jwt"


class TestPluginAuthHook:
    """Tests for plugin HTTP_AUTH_RESOLVE_USER hook path."""

    @pytest.mark.asyncio
    async def test_plugin_auth_success(self):
        """Plugin successfully authenticates user (lines 614-646)."""
        # First-Party
        from mcpgateway.plugins.framework import PluginResult

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="plugin_token")
        request = SimpleNamespace(
            state=SimpleNamespace(),
            client=SimpleNamespace(host="127.0.0.1", port=9999),
            headers={"authorization": "Bearer plugin_token"},
        )

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config.plugin_settings.include_user_info = False

        plugin_result = PluginResult(
            modified_payload={
                "email": "plugin@example.com",
                "full_name": "Plugin User",
                "is_admin": False,
                "is_active": True,
                "auth_provider": "plugin",
            },
            continue_processing=False,
            metadata={"auth_method": "custom_sso"},
        )
        mock_pm.invoke_hook = AsyncMock(return_value=(plugin_result, {"ctx": "data"}))

        with patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm), patch("mcpgateway.auth.get_correlation_id", return_value="req-1"):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "plugin@example.com"
        assert request.state.auth_method == "custom_sso"
        assert request.state.plugin_context_table == {"ctx": "data"}

    @pytest.mark.asyncio
    async def test_plugin_violation_error(self):
        """Plugin denies auth with PluginViolationError (lines 649-656)."""
        # First-Party
        from mcpgateway.plugins.framework.errors import PluginViolationError

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="denied_token")
        request = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)

        mock_pm.invoke_hook = AsyncMock(side_effect=PluginViolationError(message="Access denied by plugin"))

        with patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm), patch("mcpgateway.auth.get_correlation_id", return_value=None):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(credentials=credentials, request=request)

            assert exc.value.status_code == 401
            assert "Access denied by plugin" in exc.value.detail

    @pytest.mark.asyncio
    async def test_plugin_generic_exception_falls_through(self):
        """Plugin hook raises generic exception → falls through to standard auth (lines 660-662)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt")
        request = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config.plugin_settings.include_user_info = False
        mock_pm.invoke_hook = AsyncMock(side_effect=RuntimeError("plugin crash"))

        jwt_payload = {"sub": "user@example.com", "user": {"auth_provider": "local"}}
        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_plugin_auth_no_credentials_no_request(self):
        """Plugin hook with no credentials and no request (lines 562, 573)."""
        # First-Party
        from mcpgateway.plugins.framework import PluginResult

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config.plugin_settings.include_user_info = False

        plugin_result = PluginResult(modified_payload=None, continue_processing=True)
        mock_pm.invoke_hook = AsyncMock(return_value=(plugin_result, None))

        # No credentials → falls through plugin to standard auth → 401
        with patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm), patch("mcpgateway.auth.get_correlation_id", return_value="req-1"):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(credentials=None, request=None)

            assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_plugin_auth_fallback_request_id(self):
        """Request_id fallback to request.state.request_id (lines 577-580)."""
        # First-Party
        from mcpgateway.plugins.framework import PluginResult

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
        request = SimpleNamespace(
            state=SimpleNamespace(request_id="fallback-req-id"),
            client=None,
            headers={},
        )

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config.plugin_settings.include_user_info = False

        plugin_result = PluginResult(modified_payload=None, continue_processing=True)
        mock_pm.invoke_hook = AsyncMock(return_value=(plugin_result, None))

        jwt_payload = {"sub": "user@example.com", "user": {"auth_provider": "local"}}
        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value=None),
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_plugin_auth_uuid_fallback_request_id(self):
        """Request_id fallback to uuid when neither correlation_id nor state (lines 581-583)."""
        # First-Party
        from mcpgateway.plugins.framework import PluginResult

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
        # Request without request_id in state
        request = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config.plugin_settings.include_user_info = False

        plugin_result = PluginResult(modified_payload=None, continue_processing=True)
        mock_pm.invoke_hook = AsyncMock(return_value=(plugin_result, None))

        jwt_payload = {"sub": "user@example.com", "user": {"auth_provider": "local"}}
        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value=None),
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "user@example.com"


class TestCachePathBranches:
    """Tests for get_current_user cache-hit branches."""

    def _make_user(self, email="user@example.com", is_admin=False, is_active=True):
        return EmailUser(
            email=email,
            password_hash="h",
            full_name="U",
            is_admin=is_admin,
            is_active=is_active,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    @pytest.mark.asyncio
    async def test_cache_revoked_token(self, monkeypatch):
        """Cached context shows token revoked → 401 (line 713)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {"sub": "user@example.com", "jti": "jti-1"}

        cached_ctx = SimpleNamespace(is_token_revoked=True, user=None, personal_team_id=None)
        monkeypatch.setattr(settings, "auth_cache_enabled", True)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)), patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(credentials=credentials)
            assert exc.value.detail == "Token has been revoked"

    @pytest.mark.asyncio
    async def test_cache_inactive_user(self, monkeypatch):
        """Cached user is inactive → 401 (line 721)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {"sub": "user@example.com", "jti": "jti-1"}

        cached_ctx = SimpleNamespace(
            is_token_revoked=False,
            user={"email": "user@example.com", "is_active": False, "is_admin": False},
            personal_team_id=None,
        )
        monkeypatch.setattr(settings, "auth_cache_enabled", True)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)), patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(credentials=credentials)
            assert exc.value.detail == "Account disabled"

    @pytest.mark.asyncio
    async def test_cache_admin_bypass_teams(self, monkeypatch):
        """Cached path with admin token (teams=None) → admin bypass (line 737)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "admin@example.com",
            "jti": "jti-1",
            "teams": None,
            "is_admin": True,
            "user": {"auth_provider": "local", "is_admin": True},
        }

        cached_ctx = SimpleNamespace(
            is_token_revoked=False,
            user={"email": "admin@example.com", "is_active": True, "is_admin": True},
            personal_team_id=None,
        )
        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "auth_cache_enabled", True)
        monkeypatch.setattr(settings, "require_user_in_db", False)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)), patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)):
            user = await get_current_user(credentials=credentials, request=request)

        assert request.state.token_teams is None  # admin bypass
        assert request.state.team_id is None

    @pytest.mark.asyncio
    async def test_cache_dict_team_id(self, monkeypatch):
        """Cached path with dict team ID → extract id (lines 743-746)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "jti": "jti-1",
            "teams": [{"id": "team-1"}],
            "user": {"auth_provider": "local"},
        }

        cached_ctx = SimpleNamespace(
            is_token_revoked=False,
            user={"email": "user@example.com", "is_active": True, "is_admin": False},
            personal_team_id=None,
        )
        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "auth_cache_enabled", True)
        monkeypatch.setattr(settings, "require_user_in_db", False)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)), patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)):
            user = await get_current_user(credentials=credentials, request=request)

        assert request.state.team_id == "team-1"

    @pytest.mark.asyncio
    async def test_cache_user_missing_fallthrough(self, monkeypatch):
        """Cached context exists but user is None → fall through to DB (line 773)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "jti": "jti-1",
            "user": {"auth_provider": "local"},
        }

        cached_ctx = SimpleNamespace(is_token_revoked=False, user=None, personal_team_id=None)
        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "auth_cache_enabled", True)

        mock_user = self._make_user()

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_cache_exception_fallthrough(self, monkeypatch):
        """Cache raises exception → fall through to DB (lines 777-778)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "jti": "jti-1",
            "user": {"auth_provider": "local"},
        }
        monkeypatch.setattr(settings, "auth_cache_enabled", True)

        mock_user = self._make_user()

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(side_effect=RuntimeError("cache down"))),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials)

        assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_cache_include_user_info(self, monkeypatch):
        """Cached path with include_user_info enabled (line 768)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "jti": "jti-1",
            "user": {"auth_provider": "local"},
        }

        cached_ctx = SimpleNamespace(
            is_token_revoked=False,
            user={"email": "user@example.com", "is_active": True, "is_admin": False},
            personal_team_id=None,
        )
        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "auth_cache_enabled", True)
        monkeypatch.setattr(settings, "require_user_in_db", False)

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=False)
        mock_pm.config.plugin_settings.include_user_info = True

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)),
            patch("mcpgateway.auth._inject_userinfo_instate") as mock_inject,
        ):
            user = await get_current_user(credentials=credentials, request=request)

        mock_inject.assert_called_once()


class TestBatchedPathBranches:
    """Tests for get_current_user batched query branches."""

    @pytest.mark.asyncio
    async def test_batch_revoked_token(self, monkeypatch):
        """Batched query shows token revoked → 401 (line 787)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {"sub": "user@example.com", "jti": "jti-1"}

        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        auth_ctx = {"user": None, "personal_team_id": None, "is_token_revoked": True}

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)), patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(credentials=credentials)
            assert exc.value.detail == "Token has been revoked"

    @pytest.mark.asyncio
    async def test_batch_admin_bypass(self, monkeypatch):
        """Batched path with admin token (teams=None) → admin bypass (line 802)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "admin@example.com",
            "jti": "jti-1",
            "teams": None,
            "is_admin": True,
            "user": {"auth_provider": "local", "is_admin": True},
        }

        auth_ctx = {
            "user": {"email": "admin@example.com", "is_active": True, "is_admin": True},
            "personal_team_id": None,
            "is_token_revoked": False,
        }
        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)), patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx):
            user = await get_current_user(credentials=credentials, request=request)

        assert request.state.team_id is None
        assert request.state.token_teams is None

    @pytest.mark.asyncio
    async def test_batch_dict_team_id(self, monkeypatch):
        """Batched path with dict team_id → extract id (lines 808-810)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "jti": "jti-1",
            "teams": [{"id": "team-1"}],
            "user": {"auth_provider": "local"},
        }

        auth_ctx = {
            "user": {"email": "user@example.com", "is_active": True, "is_admin": False},
            "personal_team_id": None,
            "is_token_revoked": False,
        }
        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)), patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx):
            user = await get_current_user(credentials=credentials, request=request)

        assert request.state.team_id == "team-1"

    @pytest.mark.asyncio
    async def test_batch_cache_store(self, monkeypatch):
        """Batched result stored in cache (lines 818-832)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "jti": "jti-1",
            "user": {"auth_provider": "local"},
        }

        auth_ctx = {
            "user": {"email": "user@example.com", "is_active": True, "is_admin": False},
            "personal_team_id": None,
            "is_token_revoked": False,
        }
        monkeypatch.setattr(settings, "auth_cache_enabled", True)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        mock_cache = MagicMock()
        mock_cache.get_auth_context = AsyncMock(return_value=None)  # cache miss
        mock_cache.set_auth_context = AsyncMock()

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx),
            patch("mcpgateway.cache.auth_cache.auth_cache", mock_cache),
        ):
            user = await get_current_user(credentials=credentials)

        mock_cache.set_auth_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_cache_store_fails(self, monkeypatch):
        """Cache store fails but doesn't break auth (line 832)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "jti": "jti-1",
            "user": {"auth_provider": "local"},
        }

        auth_ctx = {
            "user": {"email": "user@example.com", "is_active": True, "is_admin": False},
            "personal_team_id": None,
            "is_token_revoked": False,
        }
        monkeypatch.setattr(settings, "auth_cache_enabled", True)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        mock_cache = MagicMock()
        mock_cache.get_auth_context = AsyncMock(return_value=None)
        mock_cache.set_auth_context = AsyncMock(side_effect=RuntimeError("cache write fail"))

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx),
            patch("mcpgateway.cache.auth_cache.auth_cache", mock_cache),
        ):
            user = await get_current_user(credentials=credentials)

        assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_batch_inactive_user(self, monkeypatch):
        """Batched user is inactive → 401 (line 838)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {"sub": "user@example.com", "jti": "jti-1", "user": {"auth_provider": "local"}}

        auth_ctx = {
            "user": {"email": "user@example.com", "is_active": False, "is_admin": False},
            "personal_team_id": None,
            "is_token_revoked": False,
        }
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)), patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(credentials=credentials)
            assert exc.value.detail == "Account disabled"

    @pytest.mark.asyncio
    async def test_batch_platform_admin_bootstrap(self, monkeypatch):
        """Batched user not found → platform admin bootstrap (lines 864-882)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {"sub": "admin@example.com", "jti": "jti-1", "user": {"auth_provider": "local"}}

        auth_ctx = {"user": None, "personal_team_id": None, "is_token_revoked": False}
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)
        monkeypatch.setattr(settings, "require_user_in_db", False)
        monkeypatch.setattr(settings, "platform_admin_email", "admin@example.com")

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)), patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx):
            user = await get_current_user(credentials=credentials)

        assert user.email == "admin@example.com"
        assert user.is_admin is True

    @pytest.mark.asyncio
    async def test_batch_user_not_found_not_admin(self, monkeypatch):
        """Batched user not found + not platform admin → 401 (lines 882-886)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {"sub": "nobody@example.com", "jti": "jti-1", "user": {"auth_provider": "local"}}

        auth_ctx = {"user": None, "personal_team_id": None, "is_token_revoked": False}
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)
        monkeypatch.setattr(settings, "require_user_in_db", False)
        monkeypatch.setattr(settings, "platform_admin_email", "admin@example.com")

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)), patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(credentials=credentials)
            assert exc.value.detail == "User not found"

    @pytest.mark.asyncio
    async def test_batch_include_user_info(self, monkeypatch):
        """Batched path with include_user_info (line 889)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {"sub": "user@example.com", "jti": "jti-1", "user": {"auth_provider": "local"}}

        auth_ctx = {
            "user": {"email": "user@example.com", "is_active": True, "is_admin": False},
            "personal_team_id": None,
            "is_token_revoked": False,
        }
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=False)
        mock_pm.config.plugin_settings.include_user_info = True

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx),
            patch("mcpgateway.auth._inject_userinfo_instate") as mock_inject,
        ):
            user = await get_current_user(credentials=credentials)

        mock_inject.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_exception_falls_through(self, monkeypatch):
        """Batch query fails → falls through to individual queries (line 896)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {"sub": "user@example.com", "jti": "jti-1", "user": {"auth_provider": "local"}}

        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._get_auth_context_batched_sync", side_effect=RuntimeError("batch fail")),
            patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials)

        assert user.email == "user@example.com"


class TestFallbackPathWithRequest:
    """Tests for fallback individual query path with request object."""

    @pytest.mark.asyncio
    async def test_fallback_sets_teams_on_request(self):
        """Fallback path sets token_teams and team_id on request (lines 919-921)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "teams": ["team-1"],
            "user": {"auth_provider": "local"},
        }

        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        request = SimpleNamespace(state=SimpleNamespace())

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert request.state.token_teams == ["team-1"]
        assert request.state.team_id == "team-1"
        assert request.state.auth_method == "jwt"


class TestApiTokenWithRequest:
    """Tests for API token fallback with request object."""

    @pytest.mark.asyncio
    async def test_api_token_sets_auth_method_on_request(self):
        """API token sets auth_method='api_token' on request (line 960)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="api_token_value")

        mock_user = EmailUser(
            email="api@example.com",
            password_hash="h",
            full_name="API",
            is_admin=False,
            is_active=True,
            auth_provider="api_token",
            password_change_required=False,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        request = SimpleNamespace(state=SimpleNamespace())

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(side_effect=Exception("JWT fail"))),
            patch("mcpgateway.auth._lookup_api_token_sync", return_value={"user_email": "api@example.com", "jti": "api-jti"}),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert request.state.auth_method == "api_token"


class TestInjectUserInfoInState:
    """Tests for _inject_userinfo_instate function."""

    def test_inject_with_no_request_id(self):
        """Fallback to request.state.request_id (line 1054)."""
        # First-Party
        from mcpgateway.auth import _inject_userinfo_instate

        request = SimpleNamespace(state=SimpleNamespace(request_id="state-req-id"))
        user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.get_correlation_id", return_value=None):
            _inject_userinfo_instate(request, user)

        assert request.state.plugin_global_context.user["email"] == "user@example.com"

    def test_inject_with_uuid_fallback(self):
        """Fallback to uuid when no correlation_id or state (lines 1055-1057)."""
        # First-Party
        from mcpgateway.auth import _inject_userinfo_instate

        request = SimpleNamespace(state=SimpleNamespace())
        user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.get_correlation_id", return_value=None):
            _inject_userinfo_instate(request, user)

        assert request.state.plugin_global_context.user["email"] == "user@example.com"

    def test_inject_with_existing_global_context(self):
        """Existing global_context has user dict already (line 1070-1072)."""
        # First-Party
        from mcpgateway.auth import _inject_userinfo_instate
        from mcpgateway.plugins.framework import GlobalContext

        gc = GlobalContext(request_id="req-1", server_id=None, tenant_id=None)
        gc.user = {"existing_key": "value"}
        request = SimpleNamespace(state=SimpleNamespace(plugin_global_context=gc))
        user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="User",
            is_admin=True,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch("mcpgateway.auth.get_correlation_id", return_value="req-1"):
            _inject_userinfo_instate(request, user)

        assert gc.user["email"] == "user@example.com"
        assert gc.user["is_admin"] is True

    def test_inject_without_user(self):
        """user is None → skip user injection (branch 1069->1076)."""
        # First-Party
        from mcpgateway.auth import _inject_userinfo_instate

        request = SimpleNamespace(state=SimpleNamespace())

        with patch("mcpgateway.auth.get_correlation_id", return_value="req-1"):
            _inject_userinfo_instate(request, None)

        assert hasattr(request.state, "plugin_global_context")

    def test_inject_no_request(self):
        """request is None → minimal execution."""
        # First-Party
        from mcpgateway.auth import _inject_userinfo_instate

        with patch("mcpgateway.auth.get_correlation_id", return_value="req-1"):
            # Should not raise
            _inject_userinfo_instate(None, None)


class TestPluginAuthHookEdgeCases:
    """Additional tests for plugin auth hook edge cases."""

    @pytest.mark.asyncio
    async def test_plugin_auth_no_metadata_no_context(self):
        """Plugin returns user with no metadata and no context_table (branches 631-641)."""
        # First-Party
        from mcpgateway.plugins.framework import PluginResult

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="plugin_token")
        request = SimpleNamespace(
            state=SimpleNamespace(plugin_global_context=MagicMock()),
            client=SimpleNamespace(host="127.0.0.1", port=9999),
            headers={},
        )

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config.plugin_settings.include_user_info = True

        plugin_result = PluginResult(
            modified_payload={"email": "plugin@example.com", "full_name": "Plugin User"},
            continue_processing=False,
            metadata=None,  # No metadata
        )
        mock_pm.invoke_hook = AsyncMock(return_value=(plugin_result, None))  # No context_table

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth._inject_userinfo_instate") as mock_inject,
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "plugin@example.com"
        mock_inject.assert_called_once()

    @pytest.mark.asyncio
    async def test_plugin_auth_metadata_without_auth_method(self):
        """Plugin returns metadata but without auth_method key (branch 633->637)."""
        # First-Party
        from mcpgateway.plugins.framework import PluginResult

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="plugin_token")
        request = SimpleNamespace(
            state=SimpleNamespace(),
            client=None,
            headers={},
        )

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config.plugin_settings.include_user_info = False

        plugin_result = PluginResult(
            modified_payload={"email": "plugin@example.com"},
            continue_processing=False,
            metadata={"other_key": "value"},  # metadata present but no auth_method
        )
        mock_pm.invoke_hook = AsyncMock(return_value=(plugin_result, None))

        with patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm), patch("mcpgateway.auth.get_correlation_id", return_value="req-1"):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "plugin@example.com"
        assert not hasattr(request.state, "auth_method")

    @pytest.mark.asyncio
    async def test_plugin_http_exception_reraised(self):
        """Plugin invoke_hook raises HTTPException → re-raised (line 659)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
        request = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)

        mock_pm.invoke_hook = AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden by plugin"))

        with patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm), patch("mcpgateway.auth.get_correlation_id", return_value="req-1"):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(credentials=credentials, request=request)

            assert exc.value.status_code == 403
            assert exc.value.detail == "Forbidden by plugin"


class TestCacheRequireUserInDbFound:
    """Test cache path when require_user_in_db=True and user IS found."""

    @pytest.mark.asyncio
    async def test_cache_require_user_in_db_found(self, monkeypatch):
        """Cached user + require_user_in_db + DB has user → success (branch 756->767)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "jti": "jti-1",
            "user": {"auth_provider": "local"},
        }

        cached_ctx = SimpleNamespace(
            is_token_revoked=False,
            user={"email": "user@example.com", "is_active": True, "is_admin": False},
            personal_team_id=None,
        )
        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "auth_cache_enabled", True)
        monkeypatch.setattr(settings, "require_user_in_db", True)

        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "user@example.com"


class TestFallbackPathBatchDisabled:
    """Test fallback path when batch queries are explicitly disabled."""

    @pytest.mark.asyncio
    async def test_batch_disabled_falls_through_to_individual(self, monkeypatch):
        """Batch disabled → skip to individual queries (branch 781->899)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "jti": "jti-1",
            "user": {"auth_provider": "local"},
        }

        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        request = SimpleNamespace(state=SimpleNamespace())

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "user@example.com"
        assert request.state.auth_method == "jwt"


class TestGetUserTeamRoles:
    """Tests for the get_user_team_roles() helper function."""

    def test_get_user_team_roles_returns_mapping(self):
        """Active memberships are returned as a {team_id: role} dict."""
        mock_db = MagicMock(spec=Session)
        mock_rows = [
            SimpleNamespace(team_id="team-1", role="owner"),
            SimpleNamespace(team_id="team-2", role="member"),
        ]
        mock_db.query.return_value.filter.return_value.all.return_value = mock_rows

        result = get_user_team_roles(mock_db, "user@example.com")

        assert result == {"team-1": "owner", "team-2": "member"}

    def test_get_user_team_roles_filters_inactive(self):
        """Only active memberships are returned (filter is applied by the query)."""
        mock_db = MagicMock(spec=Session)
        # The function filters by is_active=True in the query; inactive rows
        # are excluded at the DB level, so the mock returns only active rows.
        mock_db.query.return_value.filter.return_value.all.return_value = [
            SimpleNamespace(team_id="team-active", role="owner"),
        ]

        result = get_user_team_roles(mock_db, "user@example.com")

        assert result == {"team-active": "owner"}
        # Verify the query was constructed (filter was called)
        mock_db.query.assert_called_once()
        mock_db.query.return_value.filter.assert_called_once()

    def test_get_user_team_roles_empty_for_unknown_user(self):
        """Unknown email returns empty dict."""
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.all.return_value = []

        result = get_user_team_roles(mock_db, "unknown@example.com")

        assert result == {}

    def test_get_user_team_roles_returns_empty_on_db_error(self):
        """DB exception returns empty dict (safe default)."""
        mock_db = MagicMock(spec=Session)
        mock_db.query.side_effect = RuntimeError("DB connection failed")

        result = get_user_team_roles(mock_db, "user@example.com")

        assert result == {}

    def test_get_user_team_roles_multiple_teams(self):
        """User in 3 teams returns all 3 in result."""
        mock_db = MagicMock(spec=Session)
        mock_rows = [
            SimpleNamespace(team_id="team-a", role="owner"),
            SimpleNamespace(team_id="team-b", role="member"),
            SimpleNamespace(team_id="team-c", role="viewer"),
        ]
        mock_db.query.return_value.filter.return_value.all.return_value = mock_rows

        result = get_user_team_roles(mock_db, "user@example.com")

        assert len(result) == 3
        assert result == {"team-a": "owner", "team-b": "member", "team-c": "viewer"}


class TestResolveTeamsFromDbHelpers:
    """Targeted tests for small cache/DB helper branches in auth.py."""

    def test_resolve_teams_from_db_sync_cache_read_exception(self, monkeypatch):
        """Cache read errors are non-fatal and fall back to DB (lines 224-225)."""
        # First-Party
        from mcpgateway.auth import _resolve_teams_from_db_sync
        from mcpgateway.cache.auth_cache import auth_cache

        class BadGetDict(dict):
            def get(self, *args, **kwargs):  # noqa: ANN002, ANN003 - test helper
                raise RuntimeError("cache read fail")

        monkeypatch.setattr(auth_cache, "_teams_list_cache", BadGetDict())

        with patch("mcpgateway.auth._get_user_team_ids_sync", return_value=["t1"]):
            assert _resolve_teams_from_db_sync("user@example.com", is_admin=False) == ["t1"]

    def test_resolve_teams_from_db_sync_cache_write_exception(self, monkeypatch):
        """Cache write errors are non-fatal and still return DB result (lines 243-244)."""
        # First-Party
        from mcpgateway.auth import _resolve_teams_from_db_sync
        from mcpgateway.cache.auth_cache import auth_cache

        class ExplodingLock:
            def __enter__(self):  # noqa: ANN001 - test helper
                raise RuntimeError("lock fail")

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001 - test helper
                return False

        monkeypatch.setattr(auth_cache, "_lock", ExplodingLock())
        # Ensure L1 cache is empty so we reach the write path
        monkeypatch.setattr(auth_cache, "_teams_list_cache", {})

        with patch("mcpgateway.auth._get_user_team_ids_sync", return_value=["t1"]):
            assert _resolve_teams_from_db_sync("user@example.com", is_admin=False) == ["t1"]

    @pytest.mark.asyncio
    async def test_resolve_teams_from_db_cache_get_exception(self):
        """Async cache read errors are non-fatal and fall back to DB (lines 274-275)."""
        # First-Party
        from mcpgateway.auth import _resolve_teams_from_db
        from mcpgateway.cache.auth_cache import auth_cache

        with (
            patch.object(auth_cache, "get_user_teams", AsyncMock(side_effect=RuntimeError("cache down"))),
            patch.object(auth_cache, "set_user_teams", AsyncMock()),
            patch("mcpgateway.auth._get_user_team_ids_sync", return_value=["t1"]),
        ):
            teams = await _resolve_teams_from_db("user@example.com", {"is_admin": False})

        assert teams == ["t1"]

    @pytest.mark.asyncio
    async def test_resolve_teams_from_db_cache_set_exception(self):
        """Async cache write errors are non-fatal and still return DB result (lines 286-287)."""
        # First-Party
        from mcpgateway.auth import _resolve_teams_from_db
        from mcpgateway.cache.auth_cache import auth_cache

        with (
            patch.object(auth_cache, "get_user_teams", AsyncMock(return_value=None)),
            patch.object(auth_cache, "set_user_teams", AsyncMock(side_effect=RuntimeError("cache write fail"))),
            patch("mcpgateway.auth._get_user_team_ids_sync", return_value=["t1"]),
        ):
            teams = await _resolve_teams_from_db("user@example.com", {"is_admin": False})

        assert teams == ["t1"]


class TestSessionTokenBranches:
    """Hit token_use='session' branches that weren't exercised by existing tests."""

    @pytest.mark.asyncio
    async def test_plugin_auth_success_without_request(self):
        """Plugin auth branch where request is None (branch 795->798)."""
        # First-Party
        from mcpgateway.plugins.framework import PluginResult

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="plugin_token")

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config = SimpleNamespace(plugin_settings=SimpleNamespace(include_user_info=False))
        mock_pm.invoke_hook = AsyncMock(
            return_value=(
                PluginResult(
                    modified_payload={"email": "plugin@example.com", "full_name": "Plugin User"},
                    continue_processing=False,
                    metadata={"auth_method": "plugin"},
                ),
                None,
            )
        )

        with patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm), patch("mcpgateway.auth.get_correlation_id", return_value="req-1"):
            user = await get_current_user(credentials=credentials, request=None)

        assert user.email == "plugin@example.com"

    @pytest.mark.asyncio
    async def test_cache_session_token_falls_through_and_resolves_teams(self, monkeypatch):
        """Cache-hit session token with missing cached user falls through to DB path (line 889, 1084)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "token_use": "session",
            "user": {"auth_provider": "local"},
        }
        cached_ctx = SimpleNamespace(is_token_revoked=False, user=None, personal_team_id=None)
        request = SimpleNamespace(state=SimpleNamespace())

        monkeypatch.setattr(settings, "auth_cache_enabled", True)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        mock_user = EmailUser(
            email="user@example.com",
            password_hash="h",
            full_name="U",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_teams = ["team-a", "team-b"]
        mock_resolve = AsyncMock(return_value=mock_teams)

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=None),
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)),
            patch("mcpgateway.auth._resolve_teams_from_db", mock_resolve),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "user@example.com"
        assert request.state.token_use == "session"
        assert request.state.token_teams == mock_teams
        assert mock_resolve.call_count == 2

    @pytest.mark.asyncio
    async def test_batched_session_token_admin_teams_none(self, monkeypatch):
        """Batched path session token where user is admin sets teams=None (lines 952-957)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "admin@example.com",
            "jti": "jti-1",
            "token_use": "session",
            "user": {"auth_provider": "local"},
        }
        auth_ctx = {
            "user": {"email": "admin@example.com", "is_active": True, "is_admin": True},
            "team_ids": ["t1"],
            "personal_team_id": None,
            "is_token_revoked": False,
        }

        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=None),
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx),
        ):
            user = await get_current_user(credentials=credentials)

        assert user.email == "admin@example.com"

    @pytest.mark.asyncio
    async def test_batched_session_token_caches_team_list(self, monkeypatch):
        """Batched session token populates teams-list cache (line 996)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "jti": "jti-1",
            "token_use": "session",
            "user": {"auth_provider": "local"},
        }
        auth_ctx = {
            "user": {"email": "user@example.com", "is_active": True, "is_admin": False},
            "team_ids": ["t1", "t2"],
            "personal_team_id": None,
            "is_token_revoked": False,
        }

        monkeypatch.setattr(settings, "auth_cache_enabled", True)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        mock_cache = MagicMock()
        mock_cache.get_auth_context = AsyncMock(return_value=None)  # cache miss
        mock_cache.set_auth_context = AsyncMock()
        mock_cache.set_user_teams = AsyncMock()

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=None),
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx),
            patch("mcpgateway.cache.auth_cache.auth_cache", mock_cache),
        ):
            user = await get_current_user(credentials=credentials)

        assert user.email == "user@example.com"
        mock_cache.set_user_teams.assert_called_once()
