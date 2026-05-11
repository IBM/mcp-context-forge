# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth.py
Copyright 2026
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
from mcpgateway.transports.streamablehttp_transport import (
    _StreamableHttpAuthHandler,
    OAuthAuthResult,
)
from mcpgateway.utils.verify_credentials import (
    _discover_oidc_metadata,
    _oauth_jwks_client_cache,
    _oauth_oidc_metadata_cache,
    verify_oauth_access_token,
)


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
    async def test_token_revocation_check_failure_denies_access(self, caplog):
        """Test that token revocation check failure denies access (fail-secure)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt_with_jti")

        jwt_payload = {"sub": "test@example.com", "jti": "token_id_456", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}

        caplog.set_level(logging.WARNING, logger="mcpgateway.auth")

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._check_token_revoked_sync", side_effect=Exception("Database error")):
                with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        with pytest.raises(HTTPException) as exc_info:
                            await get_current_user(credentials=credentials)

                        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
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

    @pytest.mark.asyncio
    async def test_session_token_with_single_team_narrows_via_resolve_session_teams(self, monkeypatch):
        """Session tokens with a JWT teams claim narrow DB teams via resolve_session_teams."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="session_jwt_token")

        # JWT carries one team; DB has two — intersection narrows to one
        jwt_payload = {
            "sub": "test@example.com",
            "token_use": "session",
            "teams": ["team-123"],
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
            "jti": "session_jti_123",
        }

        cached_ctx = SimpleNamespace(
            is_token_revoked=False,
            user={"email": "test@example.com", "full_name": "Test User", "is_admin": False, "is_active": True},
            personal_team_id="team_123",
        )

        request = SimpleNamespace(state=SimpleNamespace())
        monkeypatch.setattr(settings, "auth_cache_enabled", True)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)):
                with patch("mcpgateway.auth._resolve_teams_from_db", return_value=["team-123", "team-456"]) as mock_resolve_db:
                    user = await get_current_user(credentials=credentials, request=request)

                    assert user.email == "test@example.com"
                    mock_resolve_db.assert_called_once()
                    # JWT teams=["team-123"] intersected with DB=["team-123","team-456"]
                    assert request.state.token_teams == ["team-123"]

    @pytest.mark.asyncio
    async def test_session_token_with_multiple_teams_resolves_from_db(self, monkeypatch):
        """Test that session tokens with multiple teams resolve from DB (else branch of line 1056)."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="session_jwt_token")

        # Session token with multiple teams
        jwt_payload = {
            "sub": "test@example.com",
            "token_use": "session",
            "teams": ["team-1", "team-2"],
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
            "jti": "session_jti_456",
        }

        # Mock cached context
        cached_ctx = SimpleNamespace(
            is_token_revoked=False,
            user={"email": "test@example.com", "full_name": "Test User", "is_admin": False, "is_active": True},
            personal_team_id="team_123",
        )

        request = SimpleNamespace(state=SimpleNamespace())

        # Enable auth cache
        monkeypatch.setattr(settings, "auth_cache_enabled", True)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)):
                with patch("mcpgateway.auth._resolve_teams_from_db", return_value=["db-team-1", "db-team-2"]) as mock_resolve_db:
                    user = await get_current_user(credentials=credentials, request=request)

                    assert user.email == "test@example.com"
                    # Verify _resolve_teams_from_db WAS called
                    mock_resolve_db.assert_called_once()
                    # JWT teams ["team-1","team-2"] don't overlap with DB teams
                    # ["db-team-1","db-team-2"], so intersection is empty →
                    # returns [] (public-only, denied from team-scoped resources)
                    assert request.state.token_teams == []

    @pytest.mark.asyncio
    async def test_session_token_with_teams_claim_still_resolves_from_db(self):
        """Session tokens always resolve teams from DB even when a teams claim is present."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="session_jwt_with_teams")

        # Session token with explicit single team claim — should still go to DB
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
                with patch("mcpgateway.auth._resolve_teams_from_db", return_value=["team-123"]) as mock_resolve_teams:
                    with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                        user = await get_current_user(credentials=credentials)

                        assert user.email == mock_user.email
                        # Session tokens always resolve from DB for current membership
                        mock_resolve_teams.assert_called_once()

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
                        with caplog.at_level(logging.WARNING, logger="mcpgateway.auth"):
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
    async def test_logging_debug_messages(self, caplog, monkeypatch):
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

        caplog.set_level(logging.DEBUG, logger="mcpgateway.auth")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    await get_current_user(credentials=credentials)

                    assert "Attempting JWT token validation" in caplog.text
                    assert "JWT token validated successfully" in caplog.text

    @pytest.mark.asyncio
    async def test_token_value_is_not_logged(self, caplog):
        """Ensure raw bearer token material is never emitted to logs."""
        raw_token = "super_secret_token_value_1234567890"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw_token)

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

        assert raw_token not in caplog.text
        assert raw_token[:20] not in caplog.text


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
        from cpex.framework import PluginResult

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
        from mcpgateway import auth
        from mcpgateway.auth import _update_api_token_last_used_sync
        from mcpgateway.db import EmailApiToken

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
        from mcpgateway import auth
        from mcpgateway.auth import _update_api_token_last_used_sync
        from mcpgateway.db import EmailApiToken

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
                        with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
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
                    with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
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
                            with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
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
            patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
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
        from cpex.framework import PluginResult

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
        db_user = EmailUser(
            email="plugin@example.com",
            password_hash="h",
            full_name="Plugin User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=db_user),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "plugin@example.com"
        assert request.state.auth_method == "custom_sso"
        assert request.state.plugin_context_table == {"ctx": "data"}

    @pytest.mark.asyncio
    async def test_plugin_violation_error(self):
        """Plugin denies auth with PluginViolationError (lines 649-656)."""
        # First-Party
        from cpex.framework.errors import PluginViolationError

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
        from cpex.framework import PluginResult

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
        from cpex.framework import PluginResult

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
        from cpex.framework import PluginResult

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
            patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
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
            patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
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

    @pytest.mark.asyncio
    async def test_fallback_multi_team_api_token_does_not_set_single_team_id(self, monkeypatch):
        """Multi-team API tokens should not collapse to a single request.state.team_id."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "teams": ["team-1", "team-2"],
            "token_use": "api",
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

        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._get_personal_team_sync", return_value=None),
        ):
            await get_current_user(credentials=credentials, request=request)

        assert request.state.token_teams == ["team-1", "team-2"]
        assert request.state.team_id is None
        assert request.state.token_use == "api"


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
        from cpex.framework import GlobalContext

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
        from cpex.framework import PluginResult

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
        db_user = EmailUser(
            email="plugin@example.com",
            password_hash="h",
            full_name="Plugin User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth._inject_userinfo_instate") as mock_inject,
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=db_user),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "plugin@example.com"
        mock_inject.assert_called_once()

    @pytest.mark.asyncio
    async def test_plugin_auth_metadata_without_auth_method(self):
        """Plugin returns metadata but without auth_method key (branch 633->637)."""
        # First-Party
        from cpex.framework import PluginResult

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
        db_user = EmailUser(
            email="plugin@example.com",
            password_hash="h",
            full_name="Plugin User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=db_user),
        ):
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


class TestResolveSessionTeams:
    """Direct tests for resolve_session_teams."""

    @pytest.mark.asyncio
    async def test_no_jwt_teams_returns_full_db_teams(self):
        """Without a JWT teams claim, returns full DB membership."""
        # First-Party
        from mcpgateway.auth import resolve_session_teams

        payload = {"sub": "u@example.com"}
        with patch("mcpgateway.auth._resolve_teams_from_db", return_value=["t1", "t2"]) as mock_db:
            result = await resolve_session_teams(payload, "u@example.com", {"is_admin": False})

        assert result == ["t1", "t2"]
        mock_db.assert_called_once()

    @pytest.mark.asyncio
    async def test_jwt_teams_narrows_to_intersection(self):
        """JWT teams claim narrows result to intersection with DB teams."""
        # First-Party
        from mcpgateway.auth import resolve_session_teams

        payload = {"sub": "u@example.com", "teams": ["t1"]}
        with patch("mcpgateway.auth._resolve_teams_from_db", return_value=["t1", "t2"]):
            result = await resolve_session_teams(payload, "u@example.com", {"is_admin": False})

        assert result == ["t1"]

    @pytest.mark.asyncio
    async def test_jwt_teams_all_revoked_returns_empty(self):
        """If all JWT teams were revoked, returns empty list (public-only / denied)."""
        # First-Party
        from mcpgateway.auth import resolve_session_teams

        payload = {"sub": "u@example.com", "teams": ["revoked-team"]}
        with patch("mcpgateway.auth._resolve_teams_from_db", return_value=["t1", "t2"]):
            result = await resolve_session_teams(payload, "u@example.com", {"is_admin": False})

        assert result == []

    @pytest.mark.asyncio
    async def test_admin_bypass_ignores_jwt_teams(self):
        """Admin bypass (None from DB) is returned regardless of JWT teams."""
        # First-Party
        from mcpgateway.auth import resolve_session_teams

        payload = {"sub": "admin@example.com", "teams": ["t1"]}
        with patch("mcpgateway.auth._resolve_teams_from_db", return_value=None):
            result = await resolve_session_teams(payload, "admin@example.com", {"is_admin": True})

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_db_teams_returns_empty(self):
        """User with no DB teams returns empty list (public-only)."""
        # First-Party
        from mcpgateway.auth import resolve_session_teams

        payload = {"sub": "u@example.com", "teams": ["t1"]}
        with patch("mcpgateway.auth._resolve_teams_from_db", return_value=[]):
            result = await resolve_session_teams(payload, "u@example.com", {"is_admin": False})

        assert result == []

    @pytest.mark.asyncio
    async def test_preresolved_db_teams_skips_db_call(self):
        """When preresolved_db_teams is provided, skips the DB call."""
        # First-Party
        from mcpgateway.auth import resolve_session_teams

        payload = {"sub": "u@example.com", "teams": ["t1"]}
        with patch("mcpgateway.auth._resolve_teams_from_db") as mock_db:
            result = await resolve_session_teams(
                payload,
                "u@example.com",
                {"is_admin": False},
                preresolved_db_teams=["t1", "t2"],
            )

        assert result == ["t1"]
        mock_db.assert_not_called()

    @pytest.mark.asyncio
    async def test_preresolved_none_returns_admin_bypass(self):
        """Preresolved None (admin) returns None without DB call."""
        # First-Party
        from mcpgateway.auth import resolve_session_teams

        payload = {"sub": "admin@example.com"}
        with patch("mcpgateway.auth._resolve_teams_from_db") as mock_db:
            result = await resolve_session_teams(
                payload,
                "admin@example.com",
                {"is_admin": True},
                preresolved_db_teams=None,
            )

        assert result is None
        mock_db.assert_not_called()

    @pytest.mark.asyncio
    async def test_jwt_teams_null_returns_full_db_teams(self):
        """Explicit teams: null in JWT is not a list, so no narrowing."""
        # First-Party
        from mcpgateway.auth import resolve_session_teams

        payload = {"sub": "u@example.com", "teams": None}
        with patch("mcpgateway.auth._resolve_teams_from_db", return_value=["t1"]):
            result = await resolve_session_teams(payload, "u@example.com", {"is_admin": False})

        assert result == ["t1"]

    @pytest.mark.asyncio
    async def test_jwt_teams_empty_list_returns_full_db_teams(self):
        """Explicit teams: [] in JWT is empty, so no narrowing."""
        # First-Party
        from mcpgateway.auth import resolve_session_teams

        payload = {"sub": "u@example.com", "teams": []}
        with patch("mcpgateway.auth._resolve_teams_from_db", return_value=["t1"]):
            result = await resolve_session_teams(payload, "u@example.com", {"is_admin": False})

        assert result == ["t1"]

    @pytest.mark.asyncio
    async def test_no_email_returns_public_only(self):
        """Identity-less session token gets public-only scope, never admin bypass."""
        # First-Party
        from mcpgateway.auth import resolve_session_teams

        # Even with is_admin=True, no email means no DB lookup and no admin bypass
        assert await resolve_session_teams({"is_admin": True}, None, {"is_admin": True}) == []
        assert await resolve_session_teams({"is_admin": True}, "", {"is_admin": True}) == []
        assert await resolve_session_teams({}, None, {"is_admin": False}) == []


class TestNarrowByJwtTeams:
    """Direct unit tests for the _narrow_by_jwt_teams helper."""

    def test_admin_bypass_passthrough(self):
        """Admin bypass (db_teams=None) is returned unchanged regardless of JWT teams."""
        # First-Party
        from mcpgateway.auth import _narrow_by_jwt_teams

        assert _narrow_by_jwt_teams({"teams": ["t1"]}, None) is None
        assert _narrow_by_jwt_teams({}, None) is None

    def test_normal_intersection(self):
        """Intersection of DB teams and JWT teams returns only the overlap."""
        # First-Party
        from mcpgateway.auth import _narrow_by_jwt_teams

        result = _narrow_by_jwt_teams({"teams": ["t1", "t3"]}, ["t1", "t2"])
        assert result == ["t1"]

    def test_empty_intersection(self):
        """No overlap between JWT and DB teams returns empty list."""
        # First-Party
        from mcpgateway.auth import _narrow_by_jwt_teams

        result = _narrow_by_jwt_teams({"teams": ["gone"]}, ["t1", "t2"])
        assert result == []

    def test_empty_jwt_teams_no_narrowing(self):
        """Explicit teams: [] means 'no restriction' — returns full DB teams."""
        # First-Party
        from mcpgateway.auth import _narrow_by_jwt_teams

        result = _narrow_by_jwt_teams({"teams": []}, ["t1", "t2"])
        assert result == ["t1", "t2"]

    def test_missing_jwt_teams_no_narrowing(self):
        """Missing teams key means 'no restriction' — returns full DB teams."""
        # First-Party
        from mcpgateway.auth import _narrow_by_jwt_teams

        result = _narrow_by_jwt_teams({}, ["t1", "t2"])
        assert result == ["t1", "t2"]

    def test_null_jwt_teams_no_narrowing(self):
        """Explicit teams: null is not a list — returns full DB teams."""
        # First-Party
        from mcpgateway.auth import _narrow_by_jwt_teams

        result = _narrow_by_jwt_teams({"teams": None}, ["t1"])
        assert result == ["t1"]

    def test_malformed_entries_filtered_by_normalize(self):
        """Non-string entries in JWT teams are handled by normalize_token_teams."""
        # First-Party
        from mcpgateway.auth import _narrow_by_jwt_teams

        # normalize_token_teams stringifies numeric entries
        result = _narrow_by_jwt_teams({"teams": [123, None, "t1"]}, ["t1", "123"])
        assert "t1" in result

    def test_empty_db_teams_returns_empty(self):
        """If user has no DB teams, intersection with any JWT teams is empty."""
        # First-Party
        from mcpgateway.auth import _narrow_by_jwt_teams

        result = _narrow_by_jwt_teams({"teams": ["t1"]}, [])
        assert result == []


class TestSessionTokenBranches:
    """Hit token_use='session' branches that weren't exercised by existing tests."""

    @pytest.mark.asyncio
    async def test_plugin_auth_success_without_request(self):
        """Plugin auth branch where request is None (branch 795->798)."""
        # First-Party
        from cpex.framework import PluginResult

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
        db_user = EmailUser(
            email="plugin@example.com",
            password_hash="h",
            full_name="Plugin User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=db_user),
        ):
            user = await get_current_user(credentials=credentials, request=None)

        assert user.email == "plugin@example.com"

    @pytest.mark.asyncio
    async def test_plugin_auth_ignores_plugin_admin_claim_and_uses_db_user(self):
        """Plugin-provided is_admin must not override database admin status."""
        # First-Party
        from cpex.framework import PluginResult

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="plugin_token")
        request = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config = SimpleNamespace(plugin_settings=SimpleNamespace(include_user_info=False))
        mock_pm.invoke_hook = AsyncMock(
            return_value=(
                PluginResult(
                    modified_payload={"email": "plugin@example.com", "is_admin": True},
                    continue_processing=False,
                    metadata={"auth_method": "plugin"},
                ),
                None,
            )
        )

        db_user = EmailUser(
            email="plugin@example.com",
            password_hash="h",
            full_name="Plugin User",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=db_user),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.is_admin is False

    @pytest.mark.asyncio
    async def test_plugin_auth_missing_user_rejected_when_require_user_in_db_enabled(self, monkeypatch):
        """Missing DB users are rejected when REQUIRE_USER_IN_DB is enabled."""
        # First-Party
        from cpex.framework import PluginResult

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="plugin_token")
        request = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config = SimpleNamespace(plugin_settings=SimpleNamespace(include_user_info=False))
        mock_pm.invoke_hook = AsyncMock(
            return_value=(
                PluginResult(
                    modified_payload={"email": "missing@example.com", "is_admin": True},
                    continue_processing=False,
                    metadata={"auth_method": "plugin"},
                ),
                None,
            )
        )

        monkeypatch.setattr(settings, "require_user_in_db", True)
        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=None),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(credentials=credentials, request=request)

        assert exc.value.status_code == 401
        assert exc.value.detail == "User not found in database"

    @pytest.mark.asyncio
    async def test_plugin_auth_existing_db_inactive_user_rejected(self):
        """Inactive DB users must be rejected even when plugin auth succeeds."""
        # First-Party
        from cpex.framework import PluginResult

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="plugin_token")
        request = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config = SimpleNamespace(plugin_settings=SimpleNamespace(include_user_info=False))
        mock_pm.invoke_hook = AsyncMock(
            return_value=(
                PluginResult(
                    modified_payload={"email": "disabled@example.com", "is_admin": True},
                    continue_processing=False,
                    metadata={"auth_method": "plugin"},
                ),
                None,
            )
        )

        db_user = EmailUser(
            email="disabled@example.com",
            password_hash="h",
            full_name="Disabled User",
            is_admin=False,
            is_active=False,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=db_user),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(credentials=credentials, request=request)

        assert exc.value.status_code == 401
        assert exc.value.detail == "Account disabled"

    @pytest.mark.asyncio
    async def test_plugin_auth_missing_user_defaults_to_non_admin_when_allowed(self, monkeypatch):
        """Missing DB users can authenticate as non-admin when DB-only mode is disabled."""
        # First-Party
        from cpex.framework import PluginResult

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="plugin_token")
        request = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config = SimpleNamespace(plugin_settings=SimpleNamespace(include_user_info=False))
        mock_pm.invoke_hook = AsyncMock(
            return_value=(
                PluginResult(
                    modified_payload={"email": "new@example.com", "is_admin": True, "full_name": "New User"},
                    continue_processing=False,
                    metadata={"auth_method": "plugin"},
                ),
                None,
            )
        )

        monkeypatch.setattr(settings, "require_user_in_db", False)
        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=None),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "new@example.com"
        assert user.is_admin is False

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
        """Batched session token caches raw DB teams, not the narrowed intersection.

        The JWT claims teams=["t1"] so the narrowed result is ["t1"], but the
        cache must receive the full batch_teams=["t1","t2"] so that other
        sessions for the same user can narrow independently.
        """
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")
        payload = {
            "sub": "user@example.com",
            "jti": "jti-1",
            "token_use": "session",
            "teams": ["t1"],  # narrows intersection to ["t1"]
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
        # Must cache raw DB teams (batch_teams=["t1","t2"]), not the narrowed
        # intersection (["t1"]), to prevent cross-session cache poisoning.
        mock_cache.set_user_teams.assert_called_once_with("user@example.com:True", ["t1", "t2"])

    @pytest.mark.asyncio
    async def test_cache_hit_populates_trace_context(self, monkeypatch):
        """Cache-hit auth should populate trace context for downstream spans."""
        # First-Party
        from mcpgateway.utils.trace_context import clear_trace_context, get_trace_auth_method, get_trace_team_name, get_trace_team_scope, get_trace_user_email

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt_token")
        payload = {
            "sub": "trace@example.com",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
            "jti": "jti-trace",
            "user": {"email": "trace@example.com", "full_name": "Trace User", "is_admin": False, "auth_provider": "local"},
        }
        cached_ctx = SimpleNamespace(
            is_token_revoked=False,
            user={"email": "trace@example.com", "full_name": "Trace User", "is_admin": False, "is_active": True},
            personal_team_id="team-trace",
        )
        request = SimpleNamespace(state=SimpleNamespace(token_teams=["team-trace"]))

        clear_trace_context()
        monkeypatch.setattr(settings, "auth_cache_enabled", True)

        with (
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "trace@example.com"
        assert get_trace_user_email() == "trace@example.com"
        assert get_trace_auth_method() == "jwt"
        assert get_trace_team_scope() == "public"
        assert get_trace_team_name() is None
        clear_trace_context()

    @pytest.mark.asyncio
    async def test_batched_auth_populates_primary_trace_team_name(self, monkeypatch):
        """Batched auth should resolve and store the primary team display name."""
        # First-Party
        from mcpgateway.utils.trace_context import clear_trace_context, get_trace_team_name, get_trace_team_scope, get_trace_user_email

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt_token")
        payload = {
            "sub": "trace@example.com",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
            "jti": "jti-trace",
            "token_use": "session",
            "user": {"email": "trace@example.com", "full_name": "Trace User", "is_admin": False, "auth_provider": "local"},
        }
        auth_ctx = {
            "user": {"email": "trace@example.com", "full_name": "Trace User", "is_admin": False, "is_active": True},
            "team_ids": ["team-trace"],
            "team_names": {"team-trace": "Trace Team"},
            "personal_team_id": "team-trace",
            "is_token_revoked": False,
        }
        request = SimpleNamespace(state=SimpleNamespace())

        clear_trace_context()
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", True)

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=None),
            patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
            patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx),
        ):
            user = await get_current_user(credentials=credentials, request=request)

        assert user.email == "trace@example.com"
        assert get_trace_user_email() == "trace@example.com"
        assert get_trace_team_scope() == "team-trace"
        assert get_trace_team_name() == "Trace Team"
        clear_trace_context()


def test_resolve_plugin_authenticated_user_sync_returns_none_for_missing_email():
    """Plugin-auth helper should reject empty or missing email claims."""
    # First-Party
    import mcpgateway.auth as auth_module

    assert auth_module._resolve_plugin_authenticated_user_sync({}) is None
    assert auth_module._resolve_plugin_authenticated_user_sync({"email": "   "}) is None


@pytest.mark.asyncio
async def test_resolve_trace_team_name_prefers_db_name_for_session_tokens(monkeypatch):
    """Session-token trace team names should prefer DB-authoritative values.

    Args:
        monkeypatch: Pytest fixture for patching team lookup behavior.
    """
    # First-Party
    from mcpgateway.auth import resolve_trace_team_name

    payload = {
        "token_use": "session",
        "teams": [{"id": "team-1", "name": "Claim Team"}],
    }

    monkeypatch.setattr("mcpgateway.auth._get_team_name_by_id_sync", lambda _team_id: "DB Team")

    resolved = await resolve_trace_team_name(payload, ["team-1"])

    assert resolved == "DB Team"


@pytest.mark.asyncio
async def test_resolve_trace_team_name_uses_preresolved_name_before_claims(monkeypatch):
    """Batched DB names should win over JWT team display names.

    Args:
        monkeypatch: Pytest fixture for patching unexpected DB fallback calls.
    """
    # First-Party
    from mcpgateway.auth import resolve_trace_team_name

    payload = {
        "teams": [{"id": "team-1", "name": "Claim Team"}],
    }

    def _unexpected_lookup(_team_id):
        raise AssertionError("DB fallback should not run when batched team names are present")

    monkeypatch.setattr("mcpgateway.auth._get_team_name_by_id_sync", _unexpected_lookup)

    resolved = await resolve_trace_team_name(
        payload,
        ["team-1"],
        preresolved_team_names={"team-1": "Batched Team"},
    )

    assert resolved == "Batched Team"


# =============================================================================
# P0/P1 Tests — tenant_id propagation from auth layer to GlobalContext
# =============================================================================


class TestTenantIdPropagation:
    """Verify that _inject_userinfo_instate and auth paths propagate team_id → tenant_id.

    The auth middleware resolves request.state.team_id from the JWT teams claim
    (single-team tokens only).  These tests verify that this value is propagated
    into GlobalContext.tenant_id so that the rate limiter plugin can enforce
    per-tenant limits correctly.

    These tests verify that _propagate_tenant_id() correctly propagates
    team_id into GlobalContext.tenant_id at every return path in
    get_current_user().
    """

    def _make_request(self, team_id=None, existing_global_context=None):
        """Build a minimal mock request with configurable state."""
        state = SimpleNamespace(
            team_id=team_id,
            plugin_global_context=existing_global_context,
        )
        return SimpleNamespace(state=state, client=None, headers={})

    def _make_user(self, email="alice@example.com"):
        # Standard
        from datetime import datetime, timezone  # noqa: PLC0415

        # First-Party
        from mcpgateway.db import EmailUser  # noqa: PLC0415

        return EmailUser(
            email=email,
            password_hash="h",
            full_name="Alice",
            is_admin=False,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def test_single_team_propagates_tenant_id(self):
        """P0: the get_current_user() calling sequence must propagate team_id → tenant_id.

        In production, _inject_userinfo_instate() runs first (may create
        GlobalContext), then _propagate_tenant_id() fills in tenant_id.
        """
        # First-Party
        import mcpgateway.auth as auth_module  # noqa: PLC0415
        from cpex.framework import GlobalContext  # noqa: PLC0415

        global_context = GlobalContext(request_id="r1")
        request = self._make_request(team_id="team-acme", existing_global_context=global_context)
        user = self._make_user()

        # Mirror the actual calling sequence in get_current_user():
        auth_module._inject_userinfo_instate(request=request, user=user)
        auth_module._propagate_tenant_id(request)

        assert request.state.plugin_global_context.tenant_id == "team-acme", "_propagate_tenant_id must propagate request.state.team_id into " "global_context.tenant_id for single-team tokens"

    def test_no_team_id_leaves_tenant_id_none(self):
        """P1: when request.state.team_id is None (multi-team or no team), tenant_id stays None.

        Multi-team tokens have team_id=None because there is no single authoritative tenant.
        The plugin must receive tenant_id=None and skip by_tenant — not invent a 'default'.
        """
        # First-Party
        import mcpgateway.auth as auth_module  # noqa: PLC0415
        from cpex.framework import GlobalContext  # noqa: PLC0415

        global_context = GlobalContext(request_id="r1")
        request = self._make_request(team_id=None, existing_global_context=global_context)
        user = self._make_user()

        auth_module._inject_userinfo_instate(request=request, user=user)
        auth_module._propagate_tenant_id(request)

        assert request.state.plugin_global_context.tenant_id is None, "When team_id is None (multi-team or no-team token), " "tenant_id must remain None — no fake 'default' tenant should be invented"

    def test_existing_tenant_id_is_not_overwritten(self):
        """P1: if global_context.tenant_id is already set (e.g. by an auth plugin), do not overwrite it.

        _propagate_tenant_id() must not clobber an explicit tenant identity.
        """
        # First-Party
        import mcpgateway.auth as auth_module  # noqa: PLC0415
        from cpex.framework import GlobalContext  # noqa: PLC0415

        global_context = GlobalContext(request_id="r1", tenant_id="existing-tenant")
        request = self._make_request(team_id="different-team", existing_global_context=global_context)
        user = self._make_user()

        auth_module._inject_userinfo_instate(request=request, user=user)
        auth_module._propagate_tenant_id(request)

        assert request.state.plugin_global_context.tenant_id == "existing-tenant", "An already-set tenant_id must not be overwritten by team_id resolution"

    @pytest.mark.asyncio
    async def test_get_current_user_fallback_propagates_team_id_to_tenant_id(self):
        """get_current_user() fallback constructs GlobalContext with tenant_id=team_id.

        When request.state has no plugin_global_context (i.e. middleware did not
        pre-populate it), get_current_user() must construct a GlobalContext with
        tenant_id set from request.state.team_id so the rate limiter can enforce
        per-tenant limits on this request path.
        """
        # First-Party
        from cpex.framework import PluginResult  # noqa: PLC0415

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
        request = SimpleNamespace(
            state=SimpleNamespace(team_id="team-acme"),  # no plugin_global_context set
            client=None,
            headers={},
        )

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config.plugin_settings.include_user_info = False
        plugin_result = PluginResult(modified_payload={"email": "alice@example.com"}, continue_processing=False)
        mock_pm.invoke_hook = AsyncMock(return_value=(plugin_result, None))
        db_user = self._make_user("alice@example.com")

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth._inject_userinfo_instate"),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=db_user),
        ):
            await get_current_user(credentials=credentials, request=request)

        call_kwargs = mock_pm.invoke_hook.call_args
        global_context = call_kwargs.kwargs.get("global_context")
        assert global_context is not None
        assert global_context.tenant_id == "team-acme", "get_current_user() fallback must propagate request.state.team_id " "into GlobalContext.tenant_id for by_tenant rate limiting"

    @pytest.mark.asyncio
    async def test_get_current_user_fallback_tenant_id_none_when_no_team(self):
        """get_current_user() fallback sets tenant_id=None when team_id is absent.

        When request.state.team_id is None (multi-team or admin token), the
        constructed GlobalContext must have tenant_id=None so the rate limiter
        skips by_tenant enforcement rather than inventing a phantom tenant.
        """
        # First-Party
        from cpex.framework import PluginResult  # noqa: PLC0415

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
        request = SimpleNamespace(
            state=SimpleNamespace(team_id=None),  # no plugin_global_context set
            client=None,
            headers={},
        )

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(return_value=True)
        mock_pm.config.plugin_settings.include_user_info = False
        plugin_result = PluginResult(modified_payload={"email": "alice@example.com"}, continue_processing=False)
        mock_pm.invoke_hook = AsyncMock(return_value=(plugin_result, None))
        db_user = self._make_user("alice@example.com")

        with (
            patch("mcpgateway.auth.get_plugin_manager", return_value=mock_pm),
            patch("mcpgateway.auth.get_correlation_id", return_value="req-1"),
            patch("mcpgateway.auth._inject_userinfo_instate"),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=db_user),
        ):
            await get_current_user(credentials=credentials, request=request)

        call_kwargs = mock_pm.invoke_hook.call_args
        global_context = call_kwargs.kwargs.get("global_context")
        assert global_context is not None
        assert global_context.tenant_id is None, "When team_id is None, GlobalContext.tenant_id must be None — " "no phantom tenant should be invented"

    def test_propagate_tenant_id_on_middleware_seeded_context(self):
        """_propagate_tenant_id must work when middleware has already created GlobalContext.

        Regression: the original fix only propagated team_id → tenant_id inside
        _inject_userinfo_instate (gated by include_user_info, default False) or
        in the get_current_user fallback (skipped when plugin_global_context exists).
        On the normal middleware path, tenant_id stayed None.
        """
        # First-Party
        import mcpgateway.auth as auth_module  # noqa: PLC0415
        from cpex.framework import GlobalContext  # noqa: PLC0415

        # Simulate middleware pre-creating context with tenant_id=None
        global_context = GlobalContext(request_id="r1", tenant_id=None)
        request = self._make_request(team_id="team-acme", existing_global_context=global_context)

        auth_module._propagate_tenant_id(request)

        assert request.state.plugin_global_context.tenant_id == "team-acme", (
            "_propagate_tenant_id must fill tenant_id even when middleware " "has already created plugin_global_context with tenant_id=None"
        )

    def test_propagate_tenant_id_no_overwrite(self):
        """_propagate_tenant_id must not overwrite an already-set tenant_id."""
        # First-Party
        import mcpgateway.auth as auth_module  # noqa: PLC0415
        from cpex.framework import GlobalContext  # noqa: PLC0415

        global_context = GlobalContext(request_id="r1", tenant_id="plugin-set-tenant")
        request = self._make_request(team_id="different-team", existing_global_context=global_context)

        auth_module._propagate_tenant_id(request)

        assert request.state.plugin_global_context.tenant_id == "plugin-set-tenant", "_propagate_tenant_id must not overwrite an already-set tenant_id"

    def test_propagate_tenant_id_none_request_is_noop(self):
        """_propagate_tenant_id with None request must not raise."""
        # First-Party
        import mcpgateway.auth as auth_module  # noqa: PLC0415

        # Should not raise
        auth_module._propagate_tenant_id(None)

    def test_propagate_tenant_id_missing_team_id_attribute(self):
        """_propagate_tenant_id must handle request.state without team_id attribute.

        Deny-path: request.state may not have team_id (e.g. unauthenticated
        requests or middleware that doesn't set it).  The function uses getattr
        fallback — verify it leaves tenant_id as None rather than raising.
        """
        # First-Party
        import mcpgateway.auth as auth_module  # noqa: PLC0415
        from cpex.framework import GlobalContext  # noqa: PLC0415

        global_context = GlobalContext(request_id="r1", tenant_id=None)
        # State has plugin_global_context but NO team_id attribute
        state = SimpleNamespace(plugin_global_context=global_context)
        request = SimpleNamespace(state=state, client=None, headers={})

        auth_module._propagate_tenant_id(request)

        assert global_context.tenant_id is None, "When request.state has no team_id attribute, tenant_id must remain None"

    @pytest.mark.asyncio
    async def test_propagate_tenant_id_on_cache_hit_path(self):
        """_propagate_tenant_id must be called on the auth cache hit return path.

        Regression: if _propagate_tenant_id(request) is accidentally removed
        from the cache-hit branch of get_current_user(), by_tenant rate limiting
        would silently stop working for cached auth requests.
        """
        with patch("mcpgateway.auth._propagate_tenant_id") as mock_prop:
            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
            payload = {
                "sub": "test@example.com",
                "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
                "jti": "jti-prop-cache",
                "teams": ["team-acme"],
                "user": {"email": "test@example.com", "full_name": "T", "is_admin": False, "auth_provider": "local"},
            }
            cached_ctx = SimpleNamespace(
                is_token_revoked=False,
                user={"email": "test@example.com", "full_name": "T", "is_admin": False, "is_active": True},
                personal_team_id="team_123",
            )
            request = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})

            with (
                patch("mcpgateway.auth.settings") as mock_settings,
                patch("mcpgateway.auth.get_plugin_manager", return_value=None),
                patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
                patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", AsyncMock(return_value=cached_ctx)),
            ):
                mock_settings.auth_cache_enabled = True
                mock_settings.auth_required = True
                mock_settings.jwt_secret = "secret"
                mock_settings.admin_api_enabled = True
                mock_settings.require_user_in_db = False
                await get_current_user(credentials=credentials, request=request)

            assert mock_prop.called, "_propagate_tenant_id must be called on the cache-hit return path"

    @pytest.mark.asyncio
    async def test_propagate_tenant_id_on_batched_query_path(self):
        """_propagate_tenant_id must be called on the batched DB query return path.

        Regression: if _propagate_tenant_id(request) is accidentally removed
        from the batched-query branch of get_current_user(), by_tenant rate
        limiting would silently stop working for batched-auth requests.
        """
        with patch("mcpgateway.auth._propagate_tenant_id") as mock_prop:
            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
            payload = {
                "sub": "test@example.com",
                "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
                "jti": "jti-prop-batch",
                "teams": ["team-acme"],
                "user": {"email": "test@example.com", "full_name": "T", "is_admin": False, "auth_provider": "local"},
            }
            auth_ctx = {
                "user": {"email": "test@example.com", "full_name": "T", "is_admin": False, "is_active": True},
                "personal_team_id": "team_123",
                "is_token_revoked": False,
            }
            request = SimpleNamespace(state=SimpleNamespace(), client=None, headers={})

            with (
                patch("mcpgateway.auth.settings") as mock_settings,
                patch("mcpgateway.auth.get_plugin_manager", return_value=None),
                patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)),
                patch("mcpgateway.auth._get_auth_context_batched_sync", return_value=auth_ctx),
            ):
                mock_settings.auth_cache_enabled = False
                mock_settings.auth_cache_batch_queries = True
                mock_settings.auth_required = True
                mock_settings.jwt_secret = "secret"
                mock_settings.admin_api_enabled = True
                await get_current_user(credentials=credentials, request=request)

            assert mock_prop.called, "_propagate_tenant_id must be called on the batched-query return path"


# ═══════════════════════════════════════════════════════════════════════════════
# OAuth access token verification via JWKS (RFC 9728)
# ═══════════════════════════════════════════════════════════════════════════════


class TestVerifyOauthAccessToken:
    """Tests for verify_oauth_access_token() in verify_credentials.py.

    Covers token verification via OIDC discovery + JWKS for Virtual Server
    MCP endpoints with oauth_enabled=True (RFC 9728).
    """

    ISSUER = "https://auth.example.com/application/o/test/"
    JWKS_URI = "https://auth.example.com/application/o/test/jwks/"

    @staticmethod
    def _generate_rsa_keypair():
        # Third-Party
        from cryptography.hazmat.primitives.asymmetric import rsa  # pylint: disable=import-outside-toplevel

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return private_key, private_key.public_key()

    @classmethod
    def _sign_token(cls, claims: dict, private_key, kid: str = "test-key-1") -> str:
        # Third-Party
        import jwt  # pylint: disable=import-outside-toplevel

        return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})

    @pytest.fixture(autouse=True)
    def _clear_oauth_caches(self):
        _oauth_oidc_metadata_cache.clear()
        _oauth_jwks_client_cache.clear()
        yield
        _oauth_oidc_metadata_cache.clear()
        _oauth_jwks_client_cache.clear()

    def _mock_discovery_and_jwks(self, public_key):
        """Return a context manager that mocks OIDC discovery and JWKS client."""
        mock_jwks_client = MagicMock()
        mock_signing_key = MagicMock()
        mock_signing_key.key = public_key
        mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issuer": self.ISSUER, "jwks_uri": self.JWKS_URI}
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        # Standard
        from contextlib import ExitStack  # pylint: disable=import-outside-toplevel

        stack = ExitStack()
        stack.enter_context(patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)))
        stack.enter_context(patch("mcpgateway.utils.verify_credentials._oauth_jwks_client_cache", {self.JWKS_URI: mock_jwks_client}))
        return stack

    @pytest.mark.asyncio
    async def test_valid_token_returns_claims(self):
        """A properly signed token from an allowed issuer returns verified claims."""
        private_key, public_key = self._generate_rsa_keypair()
        token = self._sign_token({"iss": self.ISSUER, "sub": "user@example.com", "email": "user@example.com", "exp": 9999999999, "iat": 1700000000}, private_key)

        with self._mock_discovery_and_jwks(public_key):
            result = await verify_oauth_access_token(token, [self.ISSUER])

        assert result is not None
        assert result["sub"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_issuer_not_in_allowlist_returns_none(self):
        """A token whose issuer is not in the allowlist is rejected."""
        private_key, _ = self._generate_rsa_keypair()
        token = self._sign_token({"iss": "https://evil.example.com/", "sub": "attacker", "exp": 9999999999, "iat": 1700000000}, private_key)

        result = await verify_oauth_access_token(token, [self.ISSUER])
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_issuer_claim_returns_none(self):
        """A token without an iss claim is rejected."""
        private_key, _ = self._generate_rsa_keypair()
        token = self._sign_token({"sub": "user@example.com", "exp": 9999999999, "iat": 1700000000}, private_key)

        result = await verify_oauth_access_token(token, [self.ISSUER])
        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_token_returns_none(self):
        """A non-JWT string is rejected gracefully."""
        result = await verify_oauth_access_token("not-a-jwt", [self.ISSUER])
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_token_returns_none(self):
        """An expired token is rejected."""
        private_key, public_key = self._generate_rsa_keypair()
        token = self._sign_token({"iss": self.ISSUER, "sub": "user@example.com", "exp": 1000000000, "iat": 999999000}, private_key)

        with self._mock_discovery_and_jwks(public_key):
            result = await verify_oauth_access_token(token, [self.ISSUER])

        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_signature_returns_none(self):
        """A token signed with a different key than JWKS provides is rejected."""
        private_key, _ = self._generate_rsa_keypair()
        _, wrong_public_key = self._generate_rsa_keypair()
        token = self._sign_token({"iss": self.ISSUER, "sub": "user@example.com", "exp": 9999999999, "iat": 1700000000}, private_key)

        with self._mock_discovery_and_jwks(wrong_public_key):
            result = await verify_oauth_access_token(token, [self.ISSUER])

        assert result is None

    @pytest.mark.asyncio
    async def test_oidc_discovery_failure_returns_none(self):
        """When OIDC discovery fails, verification returns None."""
        private_key, _ = self._generate_rsa_keypair()
        token = self._sign_token({"iss": self.ISSUER, "sub": "user@example.com", "exp": 9999999999, "iat": 1700000000}, private_key)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            result = await verify_oauth_access_token(token, [self.ISSUER])

        assert result is None

    @pytest.mark.asyncio
    async def test_trailing_slash_normalization(self):
        """Trailing slash differences between token issuer and allowlist are tolerated."""
        private_key, public_key = self._generate_rsa_keypair()
        issuer_no_slash = "https://auth.example.com/application/o/test"
        token = self._sign_token({"iss": issuer_no_slash, "sub": "user@example.com", "email": "user@example.com", "exp": 9999999999, "iat": 1700000000}, private_key)

        with self._mock_discovery_and_jwks(public_key):
            result = await verify_oauth_access_token(token, [self.ISSUER])  # allowlist has trailing slash

        assert result is not None

    @pytest.mark.asyncio
    async def test_discovery_cache_reused(self):
        """Second call within TTL reuses cached OIDC metadata."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issuer": self.ISSUER, "jwks_uri": self.JWKS_URI}
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            r1 = await _discover_oidc_metadata(self.ISSUER)
            r2 = await _discover_oidc_metadata(self.ISSUER)

        assert r1 == r2
        assert mock_http.get.call_count == 1

    @pytest.mark.asyncio
    async def test_valid_audience_passes(self):
        """Token with matching aud claim passes when expected_audience is set."""
        private_key, public_key = self._generate_rsa_keypair()
        client_id = "my-client-id"
        token = self._sign_token({"iss": self.ISSUER, "sub": "user@example.com", "email": "user@example.com", "aud": client_id, "exp": 9999999999, "iat": 1700000000}, private_key)

        with self._mock_discovery_and_jwks(public_key):
            result = await verify_oauth_access_token(token, [self.ISSUER], expected_audience=client_id)

        assert result is not None
        assert result["aud"] == client_id

    @pytest.mark.asyncio
    async def test_wrong_audience_rejected(self):
        """Token with mismatched aud claim is rejected when expected_audience is set."""
        private_key, public_key = self._generate_rsa_keypair()
        token = self._sign_token({"iss": self.ISSUER, "sub": "user@example.com", "aud": "wrong-client", "exp": 9999999999, "iat": 1700000000}, private_key)

        with self._mock_discovery_and_jwks(public_key):
            result = await verify_oauth_access_token(token, [self.ISSUER], expected_audience="correct-client")

        assert result is None

    @pytest.mark.asyncio
    async def test_no_audience_check_when_not_configured(self):
        """Token passes without aud check when expected_audience is not provided."""
        private_key, public_key = self._generate_rsa_keypair()
        token = self._sign_token({"iss": self.ISSUER, "sub": "user@example.com", "email": "user@example.com", "aud": "any-audience", "exp": 9999999999, "iat": 1700000000}, private_key)

        with self._mock_discovery_and_jwks(public_key):
            result = await verify_oauth_access_token(token, [self.ISSUER])  # no expected_audience

        assert result is not None

    @pytest.mark.asyncio
    async def test_discovery_negative_result_cached(self):
        """Failed discovery is cached so a misbehaving IdP is not retried every call."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            r1 = await _discover_oidc_metadata(self.ISSUER)
            r2 = await _discover_oidc_metadata(self.ISSUER)

        assert r1 is None
        assert r2 is None
        # First call probes both the RFC 8414 OAuth metadata URL and the
        # OIDC discovery URL; only after BOTH fail is the issuer negatively
        # cached. The second call is served entirely from that cache.
        assert mock_http.get.call_count == 2

    @pytest.mark.asyncio
    async def test_rfc8414_metadata_used_when_oidc_missing(self):
        """A non-OIDC OAuth server's RFC 8414 metadata document is accepted."""
        test_issuer = "https://auth.example.com"

        async def fake_get(url, *_args, **_kwargs):
            resp = MagicMock()
            if "oauth-authorization-server" in url:
                resp.status_code = 200
                resp.json.return_value = {"issuer": test_issuer, "jwks_uri": self.JWKS_URI}
            else:
                resp.status_code = 404
            return resp

        mock_http = AsyncMock()
        mock_http.get.side_effect = fake_get

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            metadata = await _discover_oidc_metadata(test_issuer)

        assert metadata is not None
        assert metadata["jwks_uri"] == self.JWKS_URI

    @pytest.mark.asyncio
    async def test_oidc_metadata_used_when_rfc8414_missing(self):
        """A pure OIDC server with no RFC 8414 document still discovers successfully."""
        test_issuer = "https://auth.example.com"

        async def fake_get(url, *_args, **_kwargs):
            resp = MagicMock()
            if "openid-configuration" in url:
                resp.status_code = 200
                resp.json.return_value = {"issuer": test_issuer, "jwks_uri": self.JWKS_URI}
            else:
                resp.status_code = 404
            return resp

        mock_http = AsyncMock()
        mock_http.get.side_effect = fake_get

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            metadata = await _discover_oidc_metadata(test_issuer)

        assert metadata is not None
        assert metadata["jwks_uri"] == self.JWKS_URI

    def test_build_metadata_urls_rfc8414_path_insertion(self):
        """RFC 8414 inserts the well-known segment between host and path."""
        # First-Party
        from mcpgateway.utils.verify_credentials import _build_metadata_urls  # pylint: disable=import-outside-toplevel

        urls = _build_metadata_urls("https://example.com/issuer1")
        assert "https://example.com/.well-known/oauth-authorization-server/issuer1" in urls
        assert "https://example.com/issuer1/.well-known/openid-configuration" in urls

    def test_build_metadata_urls_no_path(self):
        """With no issuer path, both well-known URLs share the root host."""
        # First-Party
        from mcpgateway.utils.verify_credentials import _build_metadata_urls  # pylint: disable=import-outside-toplevel

        urls = _build_metadata_urls("https://example.com")
        assert urls == [
            "https://example.com/.well-known/oauth-authorization-server",
            "https://example.com/.well-known/openid-configuration",
        ]

    @pytest.mark.asyncio
    async def test_id_token_with_nonce_rejected(self):
        """OIDC ID tokens carrying a ``nonce`` claim must not be accepted as access tokens.

        An attacker who obtains an ID token via SSO could otherwise replay it
        as an MCP bearer token when the virtual server is configured with the
        same ``client_id`` that ID token has in ``aud``. The claim-based
        detection catches this for every major IdP (Keycloak, Auth0, Entra,
        Okta, Authentik) without requiring RFC 9068 ``typ`` support.
        """
        private_key, public_key = self._generate_rsa_keypair()
        id_token = self._sign_token(
            {
                "iss": self.ISSUER,
                "sub": "user@example.com",
                "email": "user@example.com",
                "aud": "my-client",
                "nonce": "abc-123",  # ← ID-token-only claim
                "exp": 9999999999,
                "iat": 1700000000,
            },
            private_key,
        )

        with self._mock_discovery_and_jwks(public_key):
            result = await verify_oauth_access_token(id_token, [self.ISSUER], expected_audience="my-client")

        assert result is None  # Signature would have verified; claim check fails closed.

    @pytest.mark.asyncio
    async def test_id_token_with_at_hash_rejected(self):
        """An ID token with ``at_hash`` (OIDC Core §2) is rejected."""
        private_key, public_key = self._generate_rsa_keypair()
        id_token = self._sign_token(
            {
                "iss": self.ISSUER,
                "sub": "user@example.com",
                "aud": "my-client",
                "at_hash": "xxxx",  # ← ID-token-only claim
                "exp": 9999999999,
                "iat": 1700000000,
            },
            private_key,
        )

        with self._mock_discovery_and_jwks(public_key):
            result = await verify_oauth_access_token(id_token, [self.ISSUER], expected_audience="my-client")

        assert result is None

    @pytest.mark.asyncio
    async def test_access_token_without_id_claims_accepted(self):
        """A token lacking nonce/at_hash is still accepted (regression guard)."""
        private_key, public_key = self._generate_rsa_keypair()
        access_token = self._sign_token(
            {
                "iss": self.ISSUER,
                "sub": "user@example.com",
                "email": "user@example.com",
                "aud": "my-client",
                "exp": 9999999999,
                "iat": 1700000000,
            },
            private_key,
        )

        with self._mock_discovery_and_jwks(public_key):
            result = await verify_oauth_access_token(access_token, [self.ISSUER], expected_audience="my-client")

        assert result is not None
        assert result["sub"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_id_token_rejected_before_jwks_client_called(self):
        """ID-token rejection must happen *before* the JWKS signing-key lookup.

        This locks the ordering invariant: a refactor that moves the
        nonce/at_hash check after ``get_signing_key_from_jwt`` would still
        reject the token but would have already made an outbound call to
        the IdP's JWKS endpoint — an unnecessary attack surface and a
        potential DoS vector. Asserting the JWKS client is never touched
        proves the check is genuinely defensive.
        """
        private_key, public_key = self._generate_rsa_keypair()
        id_token = self._sign_token(
            {
                "iss": self.ISSUER,
                "sub": "user@example.com",
                "aud": "my-client",
                "nonce": "abc-123",
                "exp": 9999999999,
                "iat": 1700000000,
            },
            private_key,
        )

        mock_jwks_client = MagicMock()
        mock_signing_key = MagicMock()
        mock_signing_key.key = public_key
        mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issuer": self.ISSUER, "jwks_uri": self.JWKS_URI}
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)),
            patch("mcpgateway.utils.verify_credentials._oauth_jwks_client_cache", {self.JWKS_URI: mock_jwks_client}),
        ):
            result = await verify_oauth_access_token(id_token, [self.ISSUER], expected_audience="my-client")

        assert result is None
        # The critical invariant: the JWKS client was never consulted.
        assert mock_jwks_client.get_signing_key_from_jwt.called is False

    @pytest.mark.asyncio
    async def test_list_audience_any_match_accepted(self):
        """PyJWT's list-audience semantics: a token whose ``aud`` matches any list entry passes."""
        private_key, public_key = self._generate_rsa_keypair()
        token = self._sign_token(
            {
                "iss": self.ISSUER,
                "sub": "user@example.com",
                "email": "user@example.com",
                "aud": "second-audience",
                "exp": 9999999999,
                "iat": 1700000000,
            },
            private_key,
        )

        with self._mock_discovery_and_jwks(public_key):
            result = await verify_oauth_access_token(
                token,
                [self.ISSUER],
                expected_audience=["first-audience", "second-audience", "third-audience"],
            )

        assert result is not None
        assert result["sub"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_list_audience_none_match_rejected(self):
        """A token whose ``aud`` matches none of the list entries is rejected."""
        private_key, public_key = self._generate_rsa_keypair()
        token = self._sign_token(
            {
                "iss": self.ISSUER,
                "sub": "user@example.com",
                "aud": "wrong-audience",
                "exp": 9999999999,
                "iat": 1700000000,
            },
            private_key,
        )

        with self._mock_discovery_and_jwks(public_key):
            result = await verify_oauth_access_token(
                token,
                [self.ISSUER],
                expected_audience=["first-audience", "second-audience"],
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_expired_cache_entry_is_popped_and_reprobed(self, monkeypatch):
        """A cached entry past its TTL is evicted and rediscovery runs."""
        # First-Party
        from mcpgateway.utils import verify_credentials as vc  # pylint: disable=import-outside-toplevel

        # Seed a fake cached entry with a 0s TTL so the expiry branch fires.
        vc._oauth_oidc_metadata_cache[self.ISSUER.rstrip("/")] = (0.0, {"stale": True}, 0.0)  # pylint: disable=protected-access

        # Make the rediscovery produce fresh metadata.
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issuer": self.ISSUER, "jwks_uri": self.JWKS_URI}
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            metadata = await _discover_oidc_metadata(self.ISSUER)

        assert metadata == {"issuer": self.ISSUER, "jwks_uri": self.JWKS_URI}
        assert metadata != {"stale": True}

    @pytest.mark.asyncio
    async def test_probe_network_exception_marks_transient_and_logs(self):
        """Network errors (DNS, TLS, timeout) drive the transient-failure branch."""
        mock_http = AsyncMock()
        mock_http.get.side_effect = RuntimeError("dns down")

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            metadata = await _discover_oidc_metadata("https://unreachable.example.com")

        assert metadata is None
        # Both probes fail with the same exception, so the cache entry uses
        # the transient TTL (5s) rather than the permanent TTL (30s).
        # First-Party
        from mcpgateway.utils import verify_credentials as vc  # pylint: disable=import-outside-toplevel

        cached_at, cached_metadata, ttl = vc._oauth_oidc_metadata_cache["https://unreachable.example.com"]  # pylint: disable=protected-access
        assert cached_metadata is None
        assert ttl == vc._OAUTH_OIDC_METADATA_NEGATIVE_TTL_TRANSIENT  # pylint: disable=protected-access
        del cached_at  # silence ruff

    @pytest.mark.asyncio
    async def test_probe_invalid_json_treated_as_permanent_failure(self):
        """A 200 response with malformed JSON is a permanent (not transient) failure."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("not json")
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            metadata = await _discover_oidc_metadata("https://badjson.example.com")

        assert metadata is None
        # First-Party
        from mcpgateway.utils import verify_credentials as vc  # pylint: disable=import-outside-toplevel

        _, cached_metadata, ttl = vc._oauth_oidc_metadata_cache["https://badjson.example.com"]  # pylint: disable=protected-access
        assert cached_metadata is None
        assert ttl == vc._OAUTH_OIDC_METADATA_NEGATIVE_TTL_PERMANENT  # pylint: disable=protected-access

    @pytest.mark.asyncio
    async def test_probe_non_dict_metadata_rejected(self):
        """A JSON array (or other non-dict) is not valid metadata."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = ["not", "a", "dict"]
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            metadata = await _discover_oidc_metadata("https://weird.example.com")

        assert metadata is None

    @pytest.mark.asyncio
    async def test_metadata_without_jwks_uri_rejected(self):
        """Discovery returns 200 but no ``jwks_uri`` → verification bails out."""
        private_key, _ = self._generate_rsa_keypair()
        token = self._sign_token({"iss": self.ISSUER, "sub": "user@example.com", "exp": 9999999999, "iat": 1700000000}, private_key)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issuer": self.ISSUER}  # no jwks_uri
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            result = await verify_oauth_access_token(token, [self.ISSUER])

        assert result is None

    @pytest.mark.asyncio
    async def test_jwks_client_lazily_created_on_cache_miss(self):
        """A JWKS URI not yet in the client cache triggers PyJWKClient construction.

        Previous tests pre-populate ``_oauth_jwks_client_cache`` with a mock
        to bypass construction. This one lets the real ``jwt.PyJWKClient``
        instantiation path run (with ``PyJWKClient`` patched on the module
        so no network call is actually made).
        """
        # First-Party
        from mcpgateway.utils import verify_credentials as vc  # pylint: disable=import-outside-toplevel

        private_key, public_key = self._generate_rsa_keypair()
        token = self._sign_token(
            {"iss": self.ISSUER, "sub": "user@example.com", "email": "user@example.com", "exp": 9999999999, "iat": 1700000000},
            private_key,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issuer": self.ISSUER, "jwks_uri": self.JWKS_URI}
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        # Ensure the JWKS cache does not already contain our test JWKS URI.
        vc._oauth_jwks_client_cache.pop(self.JWKS_URI, None)  # pylint: disable=protected-access

        fake_signing_key = MagicMock()
        fake_signing_key.key = public_key
        fake_jwks_client = MagicMock()
        fake_jwks_client.get_signing_key_from_jwt.return_value = fake_signing_key

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)),
            patch("mcpgateway.utils.verify_credentials.jwt.PyJWKClient", return_value=fake_jwks_client) as mock_ctor,
        ):
            result = await verify_oauth_access_token(token, [self.ISSUER])

        assert result is not None
        assert result["sub"] == "user@example.com"
        # The constructor was called exactly once with the discovered JWKS URI.
        mock_ctor.assert_called_once_with(self.JWKS_URI)
        assert self.JWKS_URI in vc._oauth_jwks_client_cache  # pylint: disable=protected-access


class TestResolveAuthorizationServers:
    """Tests for the ``_resolve_authorization_servers`` helper."""

    def test_plural_list_returned_cleaned(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _resolve_authorization_servers  # pylint: disable=import-outside-toplevel

        result = _resolve_authorization_servers({"authorization_servers": ["  https://a.example  ", "https://b.example"]})
        assert result == ["https://a.example", "https://b.example"]

    def test_plural_list_with_empty_strings_skipped(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _resolve_authorization_servers  # pylint: disable=import-outside-toplevel

        result = _resolve_authorization_servers({"authorization_servers": ["", "   ", "https://a.example"]})
        assert result == ["https://a.example"]

    def test_singular_fallback_used_when_plural_missing(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _resolve_authorization_servers  # pylint: disable=import-outside-toplevel

        result = _resolve_authorization_servers({"authorization_server": "  https://single.example  "})
        assert result == ["https://single.example"]

    def test_singular_fallback_used_when_plural_empty(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _resolve_authorization_servers  # pylint: disable=import-outside-toplevel

        result = _resolve_authorization_servers({"authorization_servers": [], "authorization_server": "https://single.example"})
        assert result == ["https://single.example"]

    def test_empty_config_returns_empty(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _resolve_authorization_servers  # pylint: disable=import-outside-toplevel

        assert _resolve_authorization_servers({}) == []
        assert _resolve_authorization_servers({"authorization_servers": None, "authorization_server": None}) == []
        assert _resolve_authorization_servers({"authorization_server": "   "}) == []


class TestTryOAuthAccessTokenDbErrors:
    """Tests that DB failures inside ``_try_oauth_access_token`` fail closed.

    Covers the new ``SQLAlchemyError``/``Exception`` handlers around
    ``_get_user_by_email_sync`` and ``_resolve_teams_from_db``, and the
    singular ``authorization_server`` fallback path.
    """

    @pytest.fixture
    def handler_and_responses(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler  # pylint: disable=import-outside-toplevel

        responses: list = []

        async def fake_send(msg):
            responses.append(msg)

        async def fake_receive():
            return {}

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/servers/srv-1/mcp",
            "root_path": "",
            "scheme": "https",
            "server": ("gateway.example.com", 443),
            "headers": [(b"host", b"gateway.example.com")],
        }
        return _StreamableHttpAuthHandler(scope=scope, receive=fake_receive, send=fake_send), responses

    _OAUTH_TEST_ISSUER = "https://auth.example.com/application/o/test/"

    @staticmethod
    def _make_token(issuer: str) -> str:
        """Encode a minimal JWT whose unverified ``iss`` matches the allowlist peek."""
        # Third-Party
        import jwt as _jwt  # pylint: disable=import-outside-toplevel

        return _jwt.encode({"iss": issuer, "sub": "user@example.com"}, "unused", algorithm="HS256")

    @pytest.fixture
    def oauth_server_row(self):
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [self._OAUTH_TEST_ISSUER], "client_id": "test-client"}
        return server

    @staticmethod
    def _patched_get_db(server_row):
        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = server_row
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)
        return patch("mcpgateway.transports.streamablehttp_transport.get_db", return_value=cm)

    @pytest.mark.asyncio
    async def test_user_lookup_sqlalchemy_error_returns_failed_503(self, handler_and_responses, oauth_server_row):
        # Third-Party
        from sqlalchemy.exc import SQLAlchemyError  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.transports.streamablehttp_transport import OAuthAuthResult  # pylint: disable=import-outside-toplevel

        handler, responses = handler_and_responses
        token = self._make_token(self._OAUTH_TEST_ISSUER)

        async def fake_verify(*args, **kwargs):
            return {"sub": "user@example.com", "email": "user@example.com"}

        with (
            self._patched_get_db(oauth_server_row),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.auth._get_user_by_email_sync", side_effect=SQLAlchemyError("db down")),
        ):
            result = await handler._try_oauth_access_token(token)

        assert result is OAuthAuthResult.FAILED
        start = next(m for m in responses if m["type"] == "http.response.start")
        assert start["status"] == 503

    @pytest.mark.asyncio
    async def test_user_lookup_unexpected_error_returns_failed_401(self, handler_and_responses, oauth_server_row):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import OAuthAuthResult  # pylint: disable=import-outside-toplevel

        handler, responses = handler_and_responses
        token = self._make_token(self._OAUTH_TEST_ISSUER)

        async def fake_verify(*args, **kwargs):
            return {"sub": "user@example.com", "email": "user@example.com"}

        with (
            self._patched_get_db(oauth_server_row),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.auth._get_user_by_email_sync", side_effect=RuntimeError("boom")),
        ):
            result = await handler._try_oauth_access_token(token)

        assert result is OAuthAuthResult.FAILED
        start = next(m for m in responses if m["type"] == "http.response.start")
        assert start["status"] == 401

    @pytest.mark.asyncio
    async def test_teams_resolution_sqlalchemy_error_returns_failed_503(self, handler_and_responses, oauth_server_row):
        # Third-Party
        from sqlalchemy.exc import SQLAlchemyError  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.transports.streamablehttp_transport import OAuthAuthResult  # pylint: disable=import-outside-toplevel

        handler, responses = handler_and_responses
        mock_user = MagicMock(is_active=True, is_admin=False)
        token = self._make_token(self._OAUTH_TEST_ISSUER)

        async def fake_verify(*args, **kwargs):
            return {"sub": "user@example.com", "email": "user@example.com"}

        with (
            self._patched_get_db(oauth_server_row),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._resolve_teams_from_db", side_effect=SQLAlchemyError("teams unavailable")),
        ):
            result = await handler._try_oauth_access_token(token)

        assert result is OAuthAuthResult.FAILED
        start = next(m for m in responses if m["type"] == "http.response.start")
        assert start["status"] == 503

    @pytest.mark.asyncio
    async def test_singular_authorization_server_fallback_invoked(self, handler_and_responses, monkeypatch):
        """``oauth_config={"authorization_server": "..."}`` routes through the singular fallback."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import OAuthAuthResult  # pylint: disable=import-outside-toplevel

        monkeypatch.setattr(settings, "app_domain", "https://gateway.example.com")
        handler, _responses = handler_and_responses
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_server": "https://single.example/"}
        token = self._make_token("https://single.example/")

        captured: dict = {}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            # Returning None causes the helper to send a 401 and return FAILED.
            captured["authorization_servers"] = authorization_servers
            captured["expected_audience"] = expected_audience

        with (
            self._patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
        ):
            result = await handler._try_oauth_access_token(token)

        assert result is OAuthAuthResult.FAILED
        assert captured["authorization_servers"] == ["https://single.example/"]
        # No ``resource``/``client_id`` configured → handler falls back to
        # the canonical RFC 8707 resource URL (derived from app_domain).
        assert captured["expected_audience"] == "https://gateway.example.com/servers/srv-1/mcp"


# ---------------------------------------------------------------------------
# Regression tests for the OAuth audience & routing security fix
# ---------------------------------------------------------------------------

SERVER_ID = "srv-1"
GATEWAY_HOST = "gateway.example.com"
EXPECTED_RESOURCE_URL = f"https://{GATEWAY_HOST}/servers/{SERVER_ID}/mcp"
IDP_ISSUER = "https://idp.example.com/"
INTERNAL_JWT_ISSUER = "mcpgateway"


def _make_handler():
    """Build a ``_StreamableHttpAuthHandler`` against a fully-populated scope.

    The scope is rich enough for ``_build_server_resource_url`` to derive
    ``EXPECTED_RESOURCE_URL``. Tests that want to exercise the fail-closed
    "cannot derive URL" branch should use ``_make_handler_unknown_host``.
    """
    responses: list = []

    async def fake_send(msg):
        responses.append(msg)

    async def fake_receive():
        return {}

    scope = {
        "type": "http",
        "method": "POST",
        "path": f"/servers/{SERVER_ID}/mcp",
        "root_path": "",
        "scheme": "https",
        "server": (GATEWAY_HOST, 443),
        "headers": [(b"host", GATEWAY_HOST.encode())],
    }
    return _StreamableHttpAuthHandler(scope=scope, receive=fake_receive, send=fake_send), responses


def _make_handler_unknown_host():
    """Build a handler whose scope cannot yield a public base URL.

    No ``host`` header and ``server`` is ``None``, so ``_build_public_base_url``
    returns ``""`` and ``_try_oauth_access_token`` must take the fail-closed
    branch.
    """
    responses: list = []

    async def fake_send(msg):
        responses.append(msg)

    async def fake_receive():
        return {}

    scope = {
        "type": "http",
        "method": "POST",
        "path": f"/servers/{SERVER_ID}/mcp",
        "root_path": "",
        "scheme": "https",
        "server": None,
        "headers": [],
    }
    return _StreamableHttpAuthHandler(scope=scope, receive=fake_receive, send=fake_send), responses


def _patched_get_db(server_row):
    db_mock = MagicMock()
    db_mock.execute.return_value.scalar_one_or_none.return_value = server_row
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=db_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    return patch("mcpgateway.transports.streamablehttp_transport.get_db", return_value=cm)


def _make_idp_token(issuer: str = IDP_ISSUER) -> str:
    """Encode a minimal JWT with the given ``iss`` claim.

    Only the unverified ``iss`` peek in ``_route_idp_issued_token`` inspects
    this token — the signing key and algorithm are irrelevant to the routing
    decision, so we use HS256 with a throwaway key.
    """
    # Third-Party
    import jwt as _jwt  # pylint: disable=import-outside-toplevel

    return _jwt.encode({"iss": issuer, "sub": "user@example.com"}, "unused-key", algorithm="HS256")


def _response_body(responses: list) -> bytes:
    """Concatenate the body bytes from captured ASGI http.response.* messages."""
    return b"".join(m.get("body", b"") for m in responses if m["type"] == "http.response.body")


@pytest.fixture
def _pinned_app_domain(monkeypatch):
    """Pin ``settings.app_domain`` to the expected test gateway origin.

    The resource URL is derived from ``settings.app_domain`` (not from
    ASGI scope headers) to prevent Host-header replay. Tests exercising
    audience-binding must pin this value so the assertions against
    ``EXPECTED_RESOURCE_URL`` are deterministic and independent of whatever
    value the runtime config happens to load.
    """
    monkeypatch.setattr(settings, "app_domain", f"https://{GATEWAY_HOST}")


class TestOAuthAudienceEnforcement:
    """Audience enforcement behavior for OAuth-enabled virtual servers.

    When ``resource`` is configured in ``oauth_config`` (operator-set or
    previously learned), the handler enforces it strictly. When ``resource``
    is unset, the handler falls back to a list of acceptable audiences
    derived from ``[canonical resource URL, client_id]`` so first-request
    auth is still bound to known operator-controlled values. Skipping
    audience entirely would let any token from an allowed issuer
    authenticate (cross-resource token confusion).

    This accommodates IdPs that do not support RFC 8707 and set ``aud``
    to an abstract identifier (e.g. the OAuth client_id) rather than the
    resource URL the client requested.
    """

    @pytest.mark.asyncio
    async def test_no_resource_falls_back_to_canonical_url(self, _pinned_app_domain):
        """Server with only ``authorization_servers`` falls back to canonical URL."""
        handler, _responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER]}

        captured: dict = {}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            captured["expected_audience"] = expected_audience

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.transports.streamablehttp_transport._persist_learned_server_audience", new_callable=AsyncMock),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token())

        assert result is OAuthAuthResult.FAILED
        assert captured["expected_audience"] == EXPECTED_RESOURCE_URL

    @pytest.mark.asyncio
    async def test_no_resource_includes_client_id_in_fallback(self, _pinned_app_domain):
        """When ``client_id`` is set but ``resource`` is not, both feed the fallback list."""
        handler, _responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER], "client_id": "my-client-id"}

        captured: dict = {}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            captured["expected_audience"] = expected_audience

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.transports.streamablehttp_transport._persist_learned_server_audience", new_callable=AsyncMock),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token())

        assert result is OAuthAuthResult.FAILED
        assert captured["expected_audience"] == [EXPECTED_RESOURCE_URL, "my-client-id"]

    @pytest.mark.asyncio
    async def test_no_resource_no_client_id_no_canonical_fails_closed(self, monkeypatch):
        """No resource, no client_id, no derivable canonical URL → 401 fail closed with WWW-Authenticate."""
        monkeypatch.setattr(settings, "app_domain", "")
        handler, responses = _make_handler_unknown_host()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER]}

        verify_mock = AsyncMock(return_value={"sub": "user", "aud": "anything"})
        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", verify_mock),
            patch("mcpgateway.transports.streamablehttp_transport._persist_learned_server_audience") as persist_mock,
        ):
            result = await handler._try_oauth_access_token(_make_idp_token())

        assert result is OAuthAuthResult.FAILED
        verify_mock.assert_not_awaited()
        persist_mock.assert_not_called()

        start = next(m for m in responses if m["type"] == "http.response.start")
        assert start["status"] == 401
        header_dict = {k.decode().lower(): v.decode() for k, v in start["headers"]}
        assert "www-authenticate" in header_dict
        assert header_dict["www-authenticate"].startswith("Bearer")
        assert b"Invalid OAuth access token" in _response_body(responses)

    @pytest.mark.asyncio
    async def test_no_canonical_url_falls_back_to_client_id_only(self, monkeypatch):
        """When canonical URL cannot be derived but ``client_id`` is set, fallback uses client_id alone (C4)."""
        monkeypatch.setattr(settings, "app_domain", "")
        handler, _responses = _make_handler_unknown_host()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER], "client_id": "my-client-id"}

        captured: dict = {}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            captured["expected_audience"] = expected_audience

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.transports.streamablehttp_transport._persist_learned_server_audience", new_callable=AsyncMock),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token())

        assert result is OAuthAuthResult.FAILED
        # Single-element fallback collapses to scalar (per len-check at the call site).
        assert captured["expected_audience"] == "my-client-id"

    @pytest.mark.parametrize(
        "client_id_value",
        ["   ", "", 42, ["my-client-id"], {"id": "x"}, None],
        ids=["whitespace_string", "empty_string", "int", "list", "dict", "none"],
    )
    @pytest.mark.asyncio
    async def test_client_id_non_string_or_blank_treated_as_missing(self, monkeypatch, client_id_value):
        """Non-string or whitespace-only ``client_id`` is excluded from the fallback list (C7/C8)."""
        monkeypatch.setattr(settings, "app_domain", "")
        handler, responses = _make_handler_unknown_host()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER], "client_id": client_id_value}

        verify_mock = AsyncMock(return_value={"sub": "user", "aud": "anything"})
        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", verify_mock),
            patch("mcpgateway.transports.streamablehttp_transport._persist_learned_server_audience", new_callable=AsyncMock),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token())

        assert result is OAuthAuthResult.FAILED
        verify_mock.assert_not_awaited()
        start = next(m for m in responses if m["type"] == "http.response.start")
        assert start["status"] == 401

    @pytest.mark.asyncio
    async def test_resource_field_used_as_expected_audience(self, _pinned_app_domain):
        """``oauth_config.resource`` (scalar) is passed directly as expected_audience."""
        handler, _responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {
            "authorization_servers": [IDP_ISSUER],
            "resource": "https://api.example.com",
        }

        captured: dict = {}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            captured["expected_audience"] = expected_audience

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token())

        assert result is OAuthAuthResult.FAILED
        assert captured["expected_audience"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_resource_field_accepts_list_of_audiences(self, _pinned_app_domain):
        """``oauth_config.resource`` list is passed directly as expected_audience."""
        handler, _responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {
            "authorization_servers": [IDP_ISSUER],
            "resource": ["https://api-a.example.com", "https://api-b.example.com"],
        }

        captured: dict = {}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            captured["expected_audience"] = expected_audience

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token())

        assert result is OAuthAuthResult.FAILED
        assert captured["expected_audience"] == ["https://api-a.example.com", "https://api-b.example.com"]

    @pytest.mark.asyncio
    async def test_resource_used_regardless_of_app_domain(self, monkeypatch):
        """Configured ``resource`` is used even when ``settings.app_domain`` is unusable."""
        monkeypatch.setattr(settings, "app_domain", "")
        handler, responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER], "resource": "https://api.example.com"}

        captured: dict = {}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            captured["expected_audience"] = expected_audience

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token(), {"iss": IDP_ISSUER})

        assert result is OAuthAuthResult.FAILED
        assert captured["expected_audience"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_audience_ignores_host_header_when_resource_configured(self, monkeypatch):
        """The resource URL is anchored on ``settings.app_domain``, not the caller's Host header.

        If the audience were derived from the inbound ``Host`` header, a
        client could replay a token minted for ``https://other.example.com``
        simply by sending ``Host: other.example.com``. Pin ``app_domain`` to
        one value and the handler's scope Host to a *different* value — the
        computed audience must match ``app_domain``.

        This test uses a server with ``resource`` configured to exercise the
        strict audience path.
        """
        monkeypatch.setattr(settings, "app_domain", "https://canonical.example.com")

        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler  # pylint: disable=import-outside-toplevel

        responses: list = []

        async def fake_send(msg):
            responses.append(msg)

        async def fake_receive():
            return {}

        # Scope advertises a DIFFERENT host — if the helper trusted it, the
        # captured audience would be ``https://attacker.example.com/...``.
        scope = {
            "type": "http",
            "method": "POST",
            "path": f"/servers/{SERVER_ID}/mcp",
            "root_path": "",
            "scheme": "https",
            "server": ("attacker.example.com", 443),
            "headers": [(b"host", b"attacker.example.com")],
        }
        handler = _StreamableHttpAuthHandler(scope=scope, receive=fake_receive, send=fake_send)

        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER], "resource": "https://api.example.com"}

        captured: dict = {}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            captured["expected_audience"] = expected_audience

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
        ):
            await handler._try_oauth_access_token(_make_idp_token())

        assert captured["expected_audience"] == "https://api.example.com"
        assert "attacker.example.com" not in str(captured["expected_audience"])

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "spoofed_header",
        [
            (b"x-forwarded-host", b"attacker.example.com"),
            (b"forwarded", b"host=attacker.example.com"),
            (b"x-original-host", b"attacker.example.com"),
        ],
    )
    async def test_audience_ignores_forwarded_host_headers(self, monkeypatch, spoofed_header):
        """Forwarded-host header variants must not influence the audience.

        ``resource`` is passed directly from ``oauth_config``; inbound
        headers play no role.
        """
        monkeypatch.setattr(settings, "app_domain", "https://canonical.example.com")

        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler  # pylint: disable=import-outside-toplevel

        responses: list = []

        async def fake_send(msg):
            responses.append(msg)

        async def fake_receive():
            return {}

        scope = {
            "type": "http",
            "method": "POST",
            "path": f"/servers/{SERVER_ID}/mcp",
            "root_path": "",
            "scheme": "https",
            "server": ("attacker.example.com", 443),
            "headers": [
                (b"host", b"attacker.example.com"),
                spoofed_header,
            ],
        }
        handler = _StreamableHttpAuthHandler(scope=scope, receive=fake_receive, send=fake_send)

        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER], "resource": "https://api.example.com"}

        captured: dict = {}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            captured["expected_audience"] = expected_audience

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
        ):
            await handler._try_oauth_access_token(_make_idp_token())

        assert captured["expected_audience"] == "https://api.example.com"
        assert "attacker.example.com" not in str(captured["expected_audience"])


class TestPersistLearnedServerAudience:
    """Tests for auto-learning and persisting the IdP's audience claim.

    When ``resource`` is not configured on a virtual server, the handler
    skips audience enforcement and learns the IdP's ``aud`` from the first
    verified token.
    """

    @pytest.mark.asyncio
    async def test_persist_called_when_no_resource(self, _pinned_app_domain):
        """When ``resource`` is absent, the handler calls ``_persist_learned_server_audience``."""
        handler, _responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER]}

        verified_claims = {"sub": "user@example.com", "email": "user@example.com", "aud": "my-client-id"}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            return verified_claims

        mock_persist = MagicMock()
        mock_user = MagicMock(is_active=True, is_admin=False)

        async def fake_resolve_teams(*_args, **_kwargs):
            return ["team-a"]

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.transports.streamablehttp_transport._persist_learned_server_audience", mock_persist),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._resolve_teams_from_db", side_effect=fake_resolve_teams),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token())

        assert result is OAuthAuthResult.SUCCESS
        mock_persist.assert_called_once()
        call_args = mock_persist.call_args
        assert call_args[0][0] == SERVER_ID
        assert call_args[0][1] == verified_claims

    @pytest.mark.asyncio
    async def test_persist_called_when_resource_is_configured(self, _pinned_app_domain):
        """When ``resource`` is present, persist is still called (updates on aud change)."""
        handler, _responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER], "resource": "https://api.example.com"}

        verified_claims = {"sub": "user@example.com", "email": "user@example.com", "aud": "https://api.example.com"}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            return verified_claims

        mock_persist = MagicMock()
        mock_user = MagicMock(is_active=True, is_admin=False)

        async def fake_resolve_teams(*_args, **_kwargs):
            return ["team-a"]

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.transports.streamablehttp_transport._persist_learned_server_audience", mock_persist),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._resolve_teams_from_db", side_effect=fake_resolve_teams),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token())

        assert result is OAuthAuthResult.SUCCESS
        mock_persist.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_failure_does_not_break_auth(self, _pinned_app_domain):
        """If persisting the learned audience fails, the auth flow still succeeds."""
        handler, _responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER]}

        verified_claims = {"sub": "user@example.com", "email": "user@example.com", "aud": "my-client-id"}

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            return verified_claims

        mock_persist = MagicMock(side_effect=RuntimeError("DB exploded"))
        mock_user = MagicMock(is_active=True, is_admin=False)

        async def fake_resolve_teams(*_args, **_kwargs):
            return ["team-a"]

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.transports.streamablehttp_transport._persist_learned_server_audience", mock_persist),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._resolve_teams_from_db", side_effect=fake_resolve_teams),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token())

        # The persist function has its own try/except, but even if it propagated,
        # the handler should not fail the auth flow.
        assert result is OAuthAuthResult.SUCCESS

    @pytest.mark.asyncio
    async def test_first_request_learns_then_second_request_enforces_strictly(self, _pinned_app_domain):
        """Stateful regression: first-request learn → second-request strict enforce."""
        handler, _responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = dict({"authorization_servers": [IDP_ISSUER]})

        verified_claims = {"sub": "user@example.com", "email": "user@example.com", "aud": EXPECTED_RESOURCE_URL}

        captured_audiences: list = []

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            captured_audiences.append(expected_audience)
            return verified_claims

        mock_user = MagicMock(is_active=True, is_admin=False)

        async def fake_resolve_teams(*_args, **_kwargs):
            return ["team-a"]

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._resolve_teams_from_db", side_effect=fake_resolve_teams),
        ):
            result_one = await handler._try_oauth_access_token(_make_idp_token())
            assert result_one is OAuthAuthResult.SUCCESS
            assert captured_audiences[0] == EXPECTED_RESOURCE_URL
            assert server.oauth_config["resource"] == EXPECTED_RESOURCE_URL

            handler_two, _ = _make_handler()
            result_two = await handler_two._try_oauth_access_token(_make_idp_token())
            assert result_two is OAuthAuthResult.SUCCESS
            assert captured_audiences[1] == EXPECTED_RESOURCE_URL

    @pytest.mark.asyncio
    async def test_token_without_aud_succeeds_but_does_not_persist(self, _pinned_app_domain):
        """Token without ``aud`` claim: handler succeeds; persist helper no-ops."""
        handler, _responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = dict({"authorization_servers": [IDP_ISSUER]})

        async def fake_verify(token, authorization_servers, *, expected_audience=None):
            return {"sub": "user@example.com", "email": "user@example.com"}

        mock_user = MagicMock(is_active=True, is_admin=False)

        async def fake_resolve_teams(*_args, **_kwargs):
            return ["team-a"]

        with (
            _patched_get_db(server),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._resolve_teams_from_db", side_effect=fake_resolve_teams),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token())

        assert result is OAuthAuthResult.SUCCESS
        assert "resource" not in server.oauth_config


class TestPersistLearnedServerAudienceUnit:
    """Direct unit tests for ``_persist_learned_server_audience``."""

    def test_persists_string_aud(self):
        """A scalar ``aud`` claim is persisted as a string ``resource``."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        server = MagicMock()
        server.oauth_config = dict({"authorization_servers": ["https://idp.example.com"]})

        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = server

        _persist_learned_server_audience("srv-1", {"aud": "my-client-id", "sub": "user"}, db_mock)

        assert server.oauth_config["resource"] == "my-client-id"
        db_mock.flush.assert_called_once()

    def test_persists_list_aud_single_element(self):
        """A single-element ``aud`` list is persisted as-is (not collapsed to scalar)."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        server = MagicMock()
        server.oauth_config = dict({"authorization_servers": ["https://idp.example.com"]})

        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = server

        _persist_learned_server_audience("srv-1", {"aud": ["my-client-id"], "sub": "user"}, db_mock)

        assert server.oauth_config["resource"] == ["my-client-id"]

    def test_persists_list_aud_multiple_elements(self):
        """A multi-element ``aud`` list is persisted as a list."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        server = MagicMock()
        server.oauth_config = dict({"authorization_servers": ["https://idp.example.com"]})

        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = server

        _persist_learned_server_audience("srv-1", {"aud": ["aud-a", "aud-b"], "sub": "user"}, db_mock)

        assert server.oauth_config["resource"] == ["aud-a", "aud-b"]

    def test_skips_when_aud_missing(self):
        """No ``aud`` claim → no-op, DB is not touched."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        db_mock = MagicMock()

        _persist_learned_server_audience("srv-1", {"sub": "user"}, db_mock)

        db_mock.execute.assert_not_called()
        db_mock.flush.assert_not_called()

    def test_skips_when_aud_matches_existing_resource(self):
        """If ``resource`` already matches the token's ``aud``, skip (no-op)."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        server = MagicMock()
        server.oauth_config = dict({"authorization_servers": ["https://idp.example.com"], "resource": "my-client-id"})

        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = server

        _persist_learned_server_audience("srv-1", {"aud": "my-client-id", "sub": "user"}, db_mock)

        # Aud matches existing resource — flush should NOT be called.
        db_mock.flush.assert_not_called()

    def test_preserves_existing_resource_when_aud_differs(self):
        """If ``resource`` is already set, the helper preserves it (learn-once policy).

        Silent overwrite would (a) collapse operator-configured multi-audience
        lists and (b) hide IdP-side audience changes that should produce an
        explicit auth failure. Operators must clear ``resource`` to re-learn.
        """
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        server = MagicMock()
        server.oauth_config = dict({"authorization_servers": ["https://idp.example.com"], "resource": "old-client-id"})

        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = server

        _persist_learned_server_audience("srv-1", {"aud": "new-client-id", "sub": "user"}, db_mock)

        assert server.oauth_config["resource"] == "old-client-id"
        db_mock.flush.assert_not_called()

    def test_preserves_existing_list_resource(self):
        """A list-valued ``resource`` is never collapsed to a scalar (B3)."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        server = MagicMock()
        server.oauth_config = dict(
            {
                "authorization_servers": ["https://idp.example.com"],
                "resource": ["aud-a", "aud-b"],
            }
        )

        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = server

        _persist_learned_server_audience("srv-1", {"aud": "aud-a", "sub": "user"}, db_mock)

        assert server.oauth_config["resource"] == ["aud-a", "aud-b"]
        db_mock.flush.assert_not_called()

    @pytest.mark.parametrize(
        "falsy_resource",
        ["", [], None],
        ids=["empty_string", "empty_list", "none"],
    )
    def test_falsy_existing_resource_triggers_relearning(self, falsy_resource):
        """Falsy ``resource`` (empty string/list/None) counts as unset → re-learn."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        server = MagicMock()
        server.oauth_config = dict(
            {
                "authorization_servers": ["https://idp.example.com"],
                "resource": falsy_resource,
            }
        )

        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = server

        _persist_learned_server_audience("srv-1", {"aud": "learned-client-id", "sub": "user"}, db_mock)

        assert server.oauth_config["resource"] == "learned-client-id"
        db_mock.flush.assert_called_once()

    @pytest.mark.parametrize(
        "bad_aud",
        [
            {"foo": "bar"},
            42,
            ["", "valid"],
            [42, "valid"],
            [],
            "",
            "   ",
            [None],
            ["   "],
        ],
        ids=[
            "dict",
            "int",
            "list_with_empty_string",
            "list_with_int",
            "empty_list",
            "empty_string",
            "whitespace_string",
            "list_with_none",
            "list_with_whitespace_string",
        ],
    )
    def test_skips_when_aud_is_malformed(self, bad_aud, caplog):
        """Malformed ``aud`` shapes are rejected before persisting and a warning is logged (B2)."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        db_mock = MagicMock()

        with caplog.at_level(logging.WARNING, logger="mcpgateway.transports.streamablehttp_transport"):
            _persist_learned_server_audience("srv-1", {"aud": bad_aud, "sub": "user"}, db_mock)

        db_mock.execute.assert_not_called()
        db_mock.flush.assert_not_called()
        assert "Refusing to persist malformed aud claim" in caplog.text
        assert "srv-1" in caplog.text

    def test_skips_when_oauth_config_is_none(self):
        """``server.oauth_config`` being None is handled gracefully (no flush)."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        server = MagicMock()
        server.oauth_config = None

        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = server

        _persist_learned_server_audience("srv-1", {"aud": "my-client-id", "sub": "user"}, db_mock)

        db_mock.flush.assert_not_called()

    def test_skips_when_oauth_config_is_empty_dict(self):
        """``server.oauth_config`` being an empty dict is handled gracefully (B5)."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        server = MagicMock()
        server.oauth_config = {}

        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = server

        _persist_learned_server_audience("srv-1", {"aud": "my-client-id", "sub": "user"}, db_mock)

        db_mock.flush.assert_not_called()

    def test_skips_when_server_row_is_none(self):
        """``db.execute(...).scalar_one_or_none()`` returning None is handled gracefully (B4)."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = None

        _persist_learned_server_audience("srv-missing", {"aud": "my-client-id", "sub": "user"}, db_mock)

        db_mock.flush.assert_not_called()

    def test_flush_error_is_swallowed_and_logged(self, caplog):
        """``db.flush()`` raising is caught by the outer except and logged (B12)."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        server = MagicMock()
        server.oauth_config = dict({"authorization_servers": ["https://idp.example.com"]})

        db_mock = MagicMock()
        db_mock.execute.return_value.scalar_one_or_none.return_value = server
        db_mock.flush.side_effect = RuntimeError("constraint violation")

        with caplog.at_level(logging.WARNING, logger="mcpgateway.transports.streamablehttp_transport"):
            _persist_learned_server_audience("srv-1", {"aud": "my-client-id", "sub": "user"}, db_mock)

        assert "Failed to persist learned audience for server srv-1" in caplog.text

    def test_db_error_is_swallowed(self, caplog):
        """DB errors during persist are logged but do not propagate (B11)."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _persist_learned_server_audience  # pylint: disable=import-outside-toplevel

        db_mock = MagicMock()
        db_mock.execute.side_effect = RuntimeError("connection refused")

        with caplog.at_level(logging.WARNING, logger="mcpgateway.transports.streamablehttp_transport"):
            _persist_learned_server_audience("srv-1", {"aud": "my-client-id", "sub": "user"}, db_mock)

        assert "Failed to persist learned audience for server srv-1" in caplog.text

    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, False),
            ("", False),
            ("   ", False),
            ("aud", True),
            ([], False),
            ([None], False),
            ([""], False),
            (["aud"], True),
            (["aud-a", "aud-b"], True),
            ({"foo": "bar"}, False),
            (42, False),
            (b"aud", False),
        ],
        ids=[
            "none",
            "empty_string",
            "whitespace_string",
            "valid_string",
            "empty_list",
            "list_with_none",
            "list_with_empty_string",
            "list_with_one_valid",
            "list_with_two_valid",
            "dict",
            "int",
            "bytes",
        ],
    )
    def test_is_valid_audience_directly(self, value, expected):
        """Direct unit test of the shape validator across all RFC 7519 §4.1.3 edge cases (A1-A10)."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _is_valid_audience  # pylint: disable=import-outside-toplevel

        assert _is_valid_audience(value) is expected


class TestOAuthServerMisconfigurationRejected:
    """Invariant: an ``oauth_enabled`` server with an empty issuer allowlist fails closed.

    No IdP-issued token can be verified against an empty allowlist, so the
    handler must reject the request with 503 (server misconfiguration) rather
    than fall through to internal JWT verification, which would let an
    internal ContextForge JWT reach a resource that is supposed to require
    OAuth.
    """

    @pytest.mark.asyncio
    async def test_empty_authorization_servers_returns_failed_503(self):
        handler, responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        # Truthy dict so we pass the `not server.oauth_config` guard, but the
        # allowlist is empty — the misconfiguration we want to reject.
        server.oauth_config = {"authorization_servers": []}

        with _patched_get_db(server):
            result = await handler._try_oauth_access_token(_make_idp_token())

        assert result is OAuthAuthResult.FAILED
        start = next(m for m in responses if m["type"] == "http.response.start")
        assert start["status"] == 503
        assert b"OAuth authorization server not configured" in _response_body(responses)


class TestLegacyJwtOnOauthEnabledServer:
    """Invariant: tokens whose issuer is outside an oauth_enabled server's allowlist
    defer to internal JWT verification instead of being rejected as IdP tokens.

    A gateway-issued JWT may carry a missing ``iss`` claim or an older value
    that no longer matches ``settings.jwt_issuer``. Such tokens are still
    valid when ``JWT_ISSUER_VERIFICATION=false`` and must remain usable on
    ``oauth_enabled`` virtual servers: the caller (``_route_idp_issued_token``)
    is responsible for routing them to internal verification. The OAuth
    path must therefore return ``NOT_APPLICABLE`` — not reject — when the
    token's issuer is not in the server's OAuth allowlist.
    """

    def _oauth_server(self):
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER]}
        return server

    @pytest.mark.asyncio
    async def test_token_with_unknown_issuer_yields_not_applicable(self):
        """Token from an issuer outside the allowlist is not rejected by the OAuth path."""
        handler, responses = _make_handler()
        token = _make_idp_token(issuer="https://other-idp.example.com/")

        verify_called = False

        async def fake_verify(*_args, **_kwargs):
            nonlocal verify_called
            verify_called = True
            return {"sub": "x"}

        with (
            _patched_get_db(self._oauth_server()),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
        ):
            result = await handler._try_oauth_access_token(token)

        assert result is OAuthAuthResult.NOT_APPLICABLE
        assert verify_called is False  # OAuth verification was never attempted.
        assert responses == []  # No error response sent — caller decides.

    @pytest.mark.asyncio
    async def test_token_with_missing_iss_yields_not_applicable(self):
        """Token with no ``iss`` claim is treated as a potential legacy internal JWT."""
        # Third-Party
        import jwt as _jwt  # pylint: disable=import-outside-toplevel

        handler, responses = _make_handler()
        token = _jwt.encode({"sub": "user@example.com"}, "unused", algorithm="HS256")

        with (
            _patched_get_db(self._oauth_server()),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=AssertionError("must not be called")),
        ):
            result = await handler._try_oauth_access_token(token)

        assert result is OAuthAuthResult.NOT_APPLICABLE
        assert responses == []

    @pytest.mark.asyncio
    async def test_undecodable_token_yields_not_applicable(self):
        """A non-JWT bearer token on an oauth_enabled server defers to the internal path."""
        handler, responses = _make_handler()

        with (
            _patched_get_db(self._oauth_server()),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=AssertionError("must not be called")),
        ):
            result = await handler._try_oauth_access_token("not-a-jwt")

        assert result is OAuthAuthResult.NOT_APPLICABLE
        assert responses == []

    @pytest.mark.asyncio
    async def test_route_idp_falls_through_to_internal_verify_on_oauth_server(self, monkeypatch):
        """End-to-end: legacy JWT + oauth_enabled server + issuer check off → internal verify runs.

        This is the exact regression scenario: ``_route_idp_issued_token``
        peeks a mismatched ``iss``, routes to ``_try_oauth_access_token``,
        which now returns ``NOT_APPLICABLE`` (not ``FAILED``) so the caller
        falls through to internal verification instead of emitting a 401.
        """
        monkeypatch.setattr(settings, "jwt_issuer_verification", False)
        monkeypatch.setattr(settings, "jwt_issuer", INTERNAL_JWT_ISSUER)

        handler, responses = _make_handler()
        # Legacy token with an outdated iss, not in the server's allowlist.
        token = _make_idp_token(issuer="mcpgateway-legacy")

        with _patched_get_db(self._oauth_server()):
            result = await handler._route_idp_issued_token(token)

        # ``None`` means "continue with internal verify_credentials" — the
        # caller will validate signature + claims against the internal
        # signing key, which is exactly the legacy path we must preserve.
        assert result is None
        assert responses == []  # No 401 sent yet.


class TestRouteIdpIssuedToken:
    """Invariant: OAuth routing is independent of ``settings.jwt_issuer_verification``.

    ``_route_idp_issued_token`` dispatches based solely on whether the
    token's unverified ``iss`` claim matches the internal issuer. When it
    does not match, routing to the OAuth path must run regardless of the
    ``jwt_issuer_verification`` toggle — that toggle governs how
    ContextForge's *own* JWTs are checked, not whether externally-issued
    tokens are eligible for OAuth validation. Legacy fall-through to
    internal JWT verification is preserved only for non-OAuth servers when
    issuer verification is disabled.
    """

    @pytest.mark.asyncio
    async def test_matching_iss_skips_oauth_routing(self, monkeypatch):
        """A token whose ``iss`` equals ``settings.jwt_issuer`` is never routed to OAuth."""
        handler, _responses = _make_handler()
        monkeypatch.setattr(settings, "jwt_issuer", INTERNAL_JWT_ISSUER)
        monkeypatch.setattr(settings, "jwt_issuer_verification", True)
        token = _make_idp_token(issuer=INTERNAL_JWT_ISSUER)

        called = False

        async def fake_try_oauth(self, tok, unverified=None):  # pylint: disable=unused-argument
            nonlocal called
            called = True
            return OAuthAuthResult.SUCCESS

        with patch(
            "mcpgateway.transports.streamablehttp_transport._StreamableHttpAuthHandler._try_oauth_access_token",
            new=fake_try_oauth,
        ):
            result = await handler._route_idp_issued_token(token)

        # ``None`` means "caller should continue with internal JWT
        # verification"; crucially, OAuth dispatch must not fire when the
        # issuer already matches the internal one.
        assert result is None
        assert called is False

    @pytest.mark.asyncio
    async def test_undecodable_token_falls_through_without_routing(self, monkeypatch):
        """A non-JWT bearer token yields ``None`` so the canonical 401 is emitted downstream."""
        handler, responses = _make_handler()
        monkeypatch.setattr(settings, "jwt_issuer", INTERNAL_JWT_ISSUER)
        monkeypatch.setattr(settings, "jwt_issuer_verification", True)

        called = False

        async def fake_try_oauth(self, tok, unverified=None):  # pylint: disable=unused-argument
            nonlocal called
            called = True
            return OAuthAuthResult.SUCCESS

        with patch(
            "mcpgateway.transports.streamablehttp_transport._StreamableHttpAuthHandler._try_oauth_access_token",
            new=fake_try_oauth,
        ):
            result = await handler._route_idp_issued_token("not-a-jwt")

        assert result is None
        assert called is False
        assert responses == []  # Downstream verify_credentials produces the 401.

    @pytest.mark.asyncio
    async def test_idp_token_routes_to_oauth_even_when_issuer_verification_disabled(self, monkeypatch):
        """An IdP-issued token still reaches ``_try_oauth_access_token`` regardless of the toggle."""
        handler, _responses = _make_handler()
        monkeypatch.setattr(settings, "jwt_issuer_verification", False)
        monkeypatch.setattr(settings, "jwt_issuer", INTERNAL_JWT_ISSUER)
        token = _make_idp_token()

        called_with: dict = {}

        async def fake_try_oauth(self, tok, unverified=None):  # pylint: disable=unused-argument
            called_with["token"] = tok
            return OAuthAuthResult.SUCCESS

        with patch(
            "mcpgateway.transports.streamablehttp_transport._StreamableHttpAuthHandler._try_oauth_access_token",
            new=fake_try_oauth,
        ):
            result = await handler._route_idp_issued_token(token)

        assert result is True
        assert called_with["token"] == token

    @pytest.mark.asyncio
    async def test_non_oauth_server_falls_through_when_issuer_verification_disabled(self, monkeypatch):
        """NOT_APPLICABLE + issuer verification disabled → ``None`` (continue to internal verify)."""
        handler, responses = _make_handler()
        monkeypatch.setattr(settings, "jwt_issuer_verification", False)
        monkeypatch.setattr(settings, "jwt_issuer", INTERNAL_JWT_ISSUER)
        token = _make_idp_token()

        async def fake_try_oauth(self, tok, unverified=None):  # pylint: disable=unused-argument
            return OAuthAuthResult.NOT_APPLICABLE

        with patch(
            "mcpgateway.transports.streamablehttp_transport._StreamableHttpAuthHandler._try_oauth_access_token",
            new=fake_try_oauth,
        ):
            result = await handler._route_idp_issued_token(token)

        # ``None`` means "continue with internal JWT verification" — a
        # legacy internal token whose ``iss`` differs from
        # ``settings.jwt_issuer`` remains acceptable when issuer
        # verification is disabled.
        assert result is None
        assert responses == []  # No 401 sent yet.

    @pytest.mark.asyncio
    async def test_non_oauth_server_rejects_when_issuer_verification_enabled(self, monkeypatch):
        """When issuer verification is on, a mismatched ``iss`` on a non-OAuth server is a 401."""
        handler, responses = _make_handler()
        monkeypatch.setattr(settings, "jwt_issuer_verification", True)
        monkeypatch.setattr(settings, "jwt_issuer", INTERNAL_JWT_ISSUER)
        token = _make_idp_token()

        async def fake_try_oauth(self, tok, unverified=None):  # pylint: disable=unused-argument
            return OAuthAuthResult.NOT_APPLICABLE

        with patch(
            "mcpgateway.transports.streamablehttp_transport._StreamableHttpAuthHandler._try_oauth_access_token",
            new=fake_try_oauth,
        ):
            result = await handler._route_idp_issued_token(token)

        assert result is False
        start = next(m for m in responses if m["type"] == "http.response.start")
        assert start["status"] == 401

    @pytest.mark.asyncio
    async def test_idp_token_failed_returns_false_and_does_not_double_send(self, monkeypatch):
        """``_try_oauth_access_token`` → ``FAILED`` must surface as ``False`` without sending a second error.

        The FAILED contract is: the inner method already sent a 4xx/5xx
        response. The router must NOT wrap it in a second 401. Locks the
        third enum cell of the routing matrix (SUCCESS/FAILED/NOT_APPLICABLE)
        that was previously covered only by the SUCCESS and NOT_APPLICABLE
        tests.
        """
        handler, responses = _make_handler()
        monkeypatch.setattr(settings, "jwt_issuer", INTERNAL_JWT_ISSUER)
        token = _make_idp_token()

        async def fake_try_oauth(self, tok, unverified=None):  # pylint: disable=unused-argument
            # Simulate that _try_oauth_access_token already emitted a 401.
            await self._send_error(detail="simulated oauth failure", headers={"WWW-Authenticate": "Bearer"})
            return OAuthAuthResult.FAILED

        with patch(
            "mcpgateway.transports.streamablehttp_transport._StreamableHttpAuthHandler._try_oauth_access_token",
            new=fake_try_oauth,
        ):
            result = await handler._route_idp_issued_token(token)

        assert result is False
        # Exactly one http.response.start — the router did not send a second.
        starts = [m for m in responses if m["type"] == "http.response.start"]
        assert len(starts) == 1
        assert starts[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_exception_from_try_oauth_increments_error_metric(self, monkeypatch):
        """Unhandled exceptions must surface in ``oauth_verify_events_counter`` before propagating."""
        # First-Party
        from mcpgateway.services.metrics import oauth_verify_events_counter  # pylint: disable=import-outside-toplevel

        handler, _responses = _make_handler()
        monkeypatch.setattr(settings, "jwt_issuer", INTERNAL_JWT_ISSUER)
        token = _make_idp_token()

        async def fake_try_oauth(self, tok, unverified=None):  # pylint: disable=unused-argument
            raise RuntimeError("unexpected")

        before = oauth_verify_events_counter.labels(outcome="error")._value.get()  # pylint: disable=protected-access

        with patch(
            "mcpgateway.transports.streamablehttp_transport._StreamableHttpAuthHandler._try_oauth_access_token",
            new=fake_try_oauth,
        ):
            with pytest.raises(RuntimeError, match="unexpected"):
                await handler._route_idp_issued_token(token)

        after = oauth_verify_events_counter.labels(outcome="error")._value.get()  # pylint: disable=protected-access
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_success_failed_not_applicable_metric_labels(self, monkeypatch):
        """Each OAuthAuthResult outcome maps to its own ``oauth_verify_events_counter`` label.

        A label-swap mutation (e.g. ``outcome="failed"`` on the success
        branch) would previously ship green — no test referenced the
        counter. This test snapshots each label value before/after
        routing through a stubbed ``_try_oauth_access_token``.
        """
        # First-Party
        from mcpgateway.services.metrics import oauth_verify_events_counter  # pylint: disable=import-outside-toplevel

        handler, _responses = _make_handler()
        monkeypatch.setattr(settings, "jwt_issuer", INTERNAL_JWT_ISSUER)
        token = _make_idp_token()

        def snapshot(label):
            return oauth_verify_events_counter.labels(outcome=label)._value.get()  # pylint: disable=protected-access

        for outcome_enum, label in (
            (OAuthAuthResult.SUCCESS, "success"),
            (OAuthAuthResult.FAILED, "failed"),
            (OAuthAuthResult.NOT_APPLICABLE, "not_applicable"),
        ):
            before = snapshot(label)

            async def fake_try_oauth(self, tok, unverified=None, _outcome=outcome_enum):  # pylint: disable=unused-argument
                return _outcome

            with patch(
                "mcpgateway.transports.streamablehttp_transport._StreamableHttpAuthHandler._try_oauth_access_token",
                new=fake_try_oauth,
            ):
                await handler._route_idp_issued_token(token)

            after = snapshot(label)
            assert after == before + 1, f"outcome={label}: counter did not increment"

    @pytest.mark.asyncio
    async def test_non_string_iss_yields_not_applicable(self):
        """Tokens with a non-string ``iss`` defer to internal verification.

        Locks the ``isinstance(token_issuer, str)`` guard against a future
        refactor that coerces ``str(token_issuer)`` and accidentally
        matches ``['https://idp.example.com/']`` against its repr.
        """
        handler, responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER]}

        for bad_iss in (123, ["https://idp.example.com/"], {"nested": "dict"}, None):
            with _patched_get_db(server):
                result = await handler._try_oauth_access_token("irrelevant-token", {"iss": bad_iss})
            assert result is OAuthAuthResult.NOT_APPLICABLE, f"iss={bad_iss!r} should yield NOT_APPLICABLE"
        assert responses == []


class TestTryOauthAccessTokenErrorBranches:
    """Coverage for the reject/error paths in ``_try_oauth_access_token``.

    These are the branches that the happy-path and invariant tests don't
    reach: DB failure on server lookup, misconfigured / disabled servers,
    missing email claim, unknown / disabled users, and team-resolution
    failures. Each test drives a single branch to keep failures specific.
    """

    _GOOD_UNVERIFIED = {"iss": IDP_ISSUER}

    @pytest.fixture
    def oauth_server_row(self):
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {"authorization_servers": [IDP_ISSUER]}
        return server

    @pytest.mark.asyncio
    async def test_missing_server_id_in_path_yields_not_applicable(self):
        """Requests whose URL does not match ``/servers/<id>/mcp`` are not handled here."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler  # pylint: disable=import-outside-toplevel

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/health",  # no server id
            "root_path": "",
            "scheme": "https",
            "server": (GATEWAY_HOST, 443),
            "headers": [(b"host", GATEWAY_HOST.encode())],
        }

        async def fake_send(_msg):
            pass

        async def fake_receive():
            return {}

        handler = _StreamableHttpAuthHandler(scope=scope, receive=fake_receive, send=fake_send)
        result = await handler._try_oauth_access_token(_make_idp_token(), self._GOOD_UNVERIFIED)
        assert result is OAuthAuthResult.NOT_APPLICABLE

    @pytest.mark.asyncio
    async def test_db_sqlalchemy_error_sends_503(self):
        """A DB failure during the server lookup produces a 503 FAILED."""
        # Third-Party
        from sqlalchemy.exc import SQLAlchemyError  # pylint: disable=import-outside-toplevel

        handler, responses = _make_handler()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(side_effect=SQLAlchemyError("db down"))
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", return_value=cm):
            result = await handler._try_oauth_access_token(_make_idp_token(), self._GOOD_UNVERIFIED)

        assert result is OAuthAuthResult.FAILED
        start = next(m for m in responses if m["type"] == "http.response.start")
        assert start["status"] == 503

    @pytest.mark.asyncio
    async def test_server_oauth_disabled_yields_not_applicable(self):
        """A virtual server with ``oauth_enabled=False`` defers to internal verify."""
        handler, responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = False
        server.oauth_config = {"authorization_servers": [IDP_ISSUER]}

        with _patched_get_db(server):
            result = await handler._try_oauth_access_token(_make_idp_token(), self._GOOD_UNVERIFIED)

        assert result is OAuthAuthResult.NOT_APPLICABLE
        assert responses == []

    @pytest.mark.asyncio
    async def test_empty_oauth_config_fails_closed_503(self):
        """oauth_enabled=True with empty oauth_config → 503 (not fall-through)."""
        handler, responses = _make_handler()
        server = MagicMock()
        server.oauth_enabled = True
        server.oauth_config = {}

        with _patched_get_db(server):
            result = await handler._try_oauth_access_token(_make_idp_token(), self._GOOD_UNVERIFIED)

        assert result is OAuthAuthResult.FAILED
        start = next(m for m in responses if m["type"] == "http.response.start")
        assert start["status"] == 503
        assert b"OAuth authorization server not configured" in _response_body(responses)

    @pytest.mark.asyncio
    async def test_token_missing_valid_email_claim_rejected(self, _pinned_app_domain, oauth_server_row):
        """A verified token without an email-like claim is rejected with 401."""
        del _pinned_app_domain
        handler, responses = _make_handler()

        async def fake_verify(*_args, **_kwargs):
            # sub without @, no email, no preferred_username.
            return {"sub": "no-at-sign"}

        with (
            _patched_get_db(oauth_server_row),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token(), self._GOOD_UNVERIFIED)

        assert result is OAuthAuthResult.FAILED
        start = next(m for m in responses if m["type"] == "http.response.start")
        assert start["status"] == 401
        assert b"missing valid email claim" in _response_body(responses)

    @pytest.mark.asyncio
    async def test_user_not_registered_rejected(self, _pinned_app_domain, oauth_server_row):
        """A verified token for a user absent from the ContextForge DB is rejected."""
        del _pinned_app_domain
        handler, responses = _make_handler()

        async def fake_verify(*_args, **_kwargs):
            return {"sub": "user@example.com", "email": "user@example.com"}

        with (
            _patched_get_db(oauth_server_row),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=None),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token(), self._GOOD_UNVERIFIED)

        assert result is OAuthAuthResult.FAILED
        assert b"not registered in ContextForge" in _response_body(responses)

    @pytest.mark.asyncio
    async def test_inactive_user_rejected(self, _pinned_app_domain, oauth_server_row):
        """A verified token for a disabled user is rejected with 401."""
        del _pinned_app_domain
        handler, responses = _make_handler()
        mock_user = MagicMock(is_active=False, is_admin=False)

        async def fake_verify(*_args, **_kwargs):
            return {"sub": "user@example.com", "email": "user@example.com"}

        with (
            _patched_get_db(oauth_server_row),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token(), self._GOOD_UNVERIFIED)

        assert result is OAuthAuthResult.FAILED
        assert b"Account disabled" in _response_body(responses)

    @pytest.mark.asyncio
    async def test_teams_resolution_unexpected_exception_rejected(self, _pinned_app_domain, oauth_server_row):
        """A non-``SQLAlchemyError`` from team resolution falls into the generic 401 handler."""
        del _pinned_app_domain
        handler, responses = _make_handler()
        mock_user = MagicMock(is_active=True, is_admin=False)

        async def fake_verify(*_args, **_kwargs):
            return {"sub": "user@example.com", "email": "user@example.com"}

        with (
            _patched_get_db(oauth_server_row),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._resolve_teams_from_db", side_effect=RuntimeError("team lookup exploded")),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token(), self._GOOD_UNVERIFIED)

        assert result is OAuthAuthResult.FAILED
        start = next(m for m in responses if m["type"] == "http.response.start")
        assert start["status"] == 401
        assert b"Authentication failed" in _response_body(responses)

    @pytest.mark.asyncio
    async def test_full_success_path_populates_user_context(self, _pinned_app_domain, oauth_server_row):
        """End-to-end SUCCESS: verified claims → DB lookup → teams resolved → user_context set."""
        del _pinned_app_domain
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import user_context_var  # pylint: disable=import-outside-toplevel

        handler, _responses = _make_handler()
        mock_user = MagicMock(is_active=True, is_admin=False)

        async def fake_verify(*_args, **_kwargs):
            return {"sub": "user@example.com", "email": "User@Example.com"}

        async def fake_resolve_teams(*_args, **_kwargs):
            return ["team-a", "team-b"]

        with (
            _patched_get_db(oauth_server_row),
            patch("mcpgateway.transports.streamablehttp_transport.verify_oauth_access_token", side_effect=fake_verify),
            patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user),
            patch("mcpgateway.auth._resolve_teams_from_db", side_effect=fake_resolve_teams),
        ):
            result = await handler._try_oauth_access_token(_make_idp_token(), self._GOOD_UNVERIFIED)

        assert result is OAuthAuthResult.SUCCESS
        ctx = user_context_var.get()
        assert ctx["is_authenticated"] is True
        assert ctx["email"] == "user@example.com"  # lowercased
        assert ctx["teams"] == ["team-a", "team-b"]
        assert ctx["auth_method"] == "oauth_access_token"
        assert ctx["token_use"] == "session"


class TestBuildServerResourceUrlAppDomainError:
    """``_build_server_resource_url`` fails closed when ``settings.app_domain`` is unusable."""

    def test_app_domain_stringification_raises(self, monkeypatch, caplog):
        """``str(settings.app_domain)`` raising AttributeError is caught and logged."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _build_server_resource_url  # pylint: disable=import-outside-toplevel

        class Exploding:
            def __str__(self):
                raise AttributeError("no __str__ for you")

        monkeypatch.setattr(settings, "app_domain", Exploding())

        with caplog.at_level(logging.WARNING):
            result = _build_server_resource_url(None, "srv-1")

        assert result == ""
        assert any("settings.app_domain is not a usable URL" in rec.message for rec in caplog.records)


class TestAuthJwtRoutingReturn:
    """``_auth_jwt`` returns the outcome of ``_route_idp_issued_token`` without reaching verify_credentials."""

    @pytest.mark.asyncio
    async def test_auth_jwt_returns_true_when_route_succeeds(self, monkeypatch):
        handler, _responses = _make_handler()

        async def fake_route(_self, _tok):
            return True

        monkeypatch.setattr(_StreamableHttpAuthHandler, "_route_idp_issued_token", fake_route)

        # verify_credentials should never be called on this path.
        with patch("mcpgateway.transports.streamablehttp_transport.verify_credentials", side_effect=AssertionError("must not be called")):
            result = await handler._auth_jwt(token="unused")

        assert result is True

    @pytest.mark.asyncio
    async def test_auth_jwt_returns_false_when_route_fails(self, monkeypatch):
        handler, _responses = _make_handler()

        async def fake_route(_self, _tok):
            return False

        monkeypatch.setattr(_StreamableHttpAuthHandler, "_route_idp_issued_token", fake_route)

        with patch("mcpgateway.transports.streamablehttp_transport.verify_credentials", side_effect=AssertionError("must not be called")):
            result = await handler._auth_jwt(token="unused")

        assert result is False
