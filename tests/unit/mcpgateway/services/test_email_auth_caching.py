# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_email_auth_caching.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for Email Authentication Service caching functionality.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailUser
from mcpgateway.services.email_auth_service import EmailAuthService


class TestEmailAuthCaching:
    """Test suite for Email Authentication Service caching."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def service(self, mock_db):
        """Create email auth service instance."""
        return EmailAuthService(mock_db)

    @pytest.fixture
    def mock_user(self):
        """Create a mock user with all required attributes."""
        user = MagicMock(spec=EmailUser)
        user.email = "test@example.com"
        user.password_hash = "hashed_password"
        user.full_name = "Test User"
        user.is_admin = False
        user.admin_origin = None
        user.is_active = True
        user.email_verified_at = None
        user.auth_provider = "local"
        user.password_hash_type = "argon2id"
        user.failed_login_attempts = 0
        user.locked_until = None
        user.password_change_required = False
        user.password_changed_at = datetime.now(timezone.utc)
        user.created_at = datetime.now(timezone.utc)
        user.updated_at = datetime.now(timezone.utc)
        user.last_login = None
        return user

    # =========================================================================
    # Cache Serialization Tests (Pydantic Model)
    # =========================================================================

    def test_cached_email_user_from_orm(self, mock_user):
        """Test that CachedEmailUser.from_orm properly serializes EmailUser."""
        from mcpgateway.schemas import CachedEmailUser

        result = CachedEmailUser.from_orm(mock_user)

        assert isinstance(result, CachedEmailUser)
        assert result.email == "test@example.com"
        assert result.password_hash == "hashed_password"
        assert result.full_name == "Test User"
        assert result.is_admin is False
        assert result.is_active is True
        assert result.auth_provider == "local"
        assert result.password_hash_type == "argon2id"
        assert result.failed_login_attempts == 0
        assert result.password_change_required is False

    def test_cached_email_user_to_orm(self):
        """Test that CachedEmailUser.to_orm properly reconstructs EmailUser."""
        from mcpgateway.schemas import CachedEmailUser

        now = datetime.now(timezone.utc)
        cached_user = CachedEmailUser(
            email="test@example.com",
            password_hash="hashed",
            full_name="Test User",
            is_admin=False,
            is_active=True,
            email_verified_at=now,
            auth_provider="local",
            password_hash_type="argon2id",
            failed_login_attempts=0,
            password_change_required=False,
            created_at=now,
            updated_at=now
        )

        result = cached_user.to_orm()

        assert isinstance(result, EmailUser)
        assert result.email == "test@example.com"
        assert result.password_hash == "hashed"
        assert result.full_name == "Test User"
        assert result.is_admin is False
        assert result.is_active is True
        assert result.email_verified_at == now

    def test_cached_email_user_model_dump(self, mock_user):
        """Test that CachedEmailUser.model_dump produces valid dict for caching."""
        from mcpgateway.schemas import CachedEmailUser

        cached_user = CachedEmailUser.from_orm(mock_user)
        result = cached_user.model_dump()

        assert isinstance(result, dict)
        assert result["email"] == "test@example.com"
        assert result["password_hash"] == "hashed_password"
        assert result["is_admin"] is False

    # =========================================================================
    # Cache Invalidation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_update_user_invalidates_cache(self, service, mock_db, mock_user):
        """Test that update_user invalidates cache after successful update."""
        # Mock database query to return user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        with patch.object(service, "_invalidate_user_auth_cache", new=AsyncMock()) as mock_invalidate:
            with patch.object(service, "is_last_active_admin", new=AsyncMock(return_value=False)):
                # Mock role_service methods to avoid AttributeError
                mock_role_service = MagicMock()
                mock_role_service.get_role_by_name = AsyncMock(return_value=None)
                service._role_service = mock_role_service
                
                await service.update_user(
                    email="test@example.com",
                    full_name="Updated Name"
                )

                # Verify cache was invalidated
                mock_invalidate.assert_called_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_activate_user_invalidates_cache(self, service, mock_db, mock_user):
        """Test that activate_user invalidates cache after activation."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        with patch.object(service, "_invalidate_user_auth_cache", new=AsyncMock()) as mock_invalidate:
            await service.activate_user("test@example.com")

            mock_invalidate.assert_called_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_deactivate_user_invalidates_cache(self, service, mock_db, mock_user):
        """Test that deactivate_user invalidates cache after deactivation."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        with patch.object(service, "_invalidate_user_auth_cache", new=AsyncMock()) as mock_invalidate:
            await service.deactivate_user("test@example.com")

            mock_invalidate.assert_called_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_unlock_user_account_invalidates_cache(self, service, mock_db, mock_user):
        """Test that unlock_user_account invalidates cache after unlocking."""
        with patch.object(service, "get_user_by_email", new=AsyncMock(return_value=mock_user)):
            with patch.object(service, "_invalidate_user_auth_cache", new=AsyncMock()) as mock_invalidate:
                with patch.object(service, "_log_auth_event"):
                    await service.unlock_user_account("test@example.com")

                    mock_invalidate.assert_called_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_reset_password_with_token_invalidates_cache(self, service, mock_db, mock_user):
        """Test that reset_password_with_token invalidates cache."""
        mock_token = MagicMock()
        mock_token.user_email = "test@example.com"

        with patch.object(service, "validate_password_reset_token", new=AsyncMock(return_value=mock_token)):
            with patch.object(service, "get_user_by_email", new=AsyncMock(return_value=mock_user)):
                with patch.object(service, "validate_password"):
                    with patch.object(service.password_service, "verify_password_async", new=AsyncMock(return_value=False)):
                        with patch.object(service.password_service, "hash_password_async", new=AsyncMock(return_value="new_hash")):
                            with patch.object(service, "_invalidate_user_auth_cache", new=AsyncMock()) as mock_invalidate:
                                with patch.object(service.email_notification_service, "send_password_reset_confirmation_email", new=AsyncMock()):
                                    await service.reset_password_with_token(
                                        token="valid_token",
                                        new_password="NewPassword123!"
                                    )

                                    mock_invalidate.assert_called_once_with("test@example.com")

    # =========================================================================
    # Cache Integration Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_user_by_email_cache_miss_stores_in_cache(self, service, mock_db, mock_user):
        """Test that cache miss results in storing user in cache."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        # Mock auth_cache methods
        with patch("mcpgateway.cache.auth_cache.auth_cache.get_user_by_email", new=AsyncMock(return_value=None)):
            with patch("mcpgateway.cache.auth_cache.auth_cache.cache_user_by_email", new=AsyncMock()) as mock_cache:
                result = await service.get_user_by_email("test@example.com")

                assert result == mock_user
                # Verify cache was called with serialized user data
                mock_cache.assert_called_once()
                call_args = mock_cache.call_args
                assert call_args[0][0] == "test@example.com"
                assert isinstance(call_args[0][1], dict)

    @pytest.mark.asyncio
    async def test_get_user_by_email_cache_hit_skips_database(self, service, mock_db):
        """Test that cache hit skips database query."""
        cached_data = {
            "email": "cached@example.com",
            "password_hash": "hashed",
            "full_name": "Cached User",
            "is_admin": False,
            "admin_origin": None,
            "is_active": True,
            "email_verified_at": None,
            "auth_provider": "local",
            "password_hash_type": "argon2id",
            "failed_login_attempts": 0,
            "locked_until": None,
            "password_change_required": False,
            "password_changed_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_login": None,
        }

        with patch("mcpgateway.cache.auth_cache.auth_cache.get_user_by_email", new=AsyncMock(return_value=cached_data)):
            result = await service.get_user_by_email("cached@example.com")

            # Should not hit database
            mock_db.execute.assert_not_called()
            assert result.email == "cached@example.com"
            assert result.full_name == "Cached User"

    @pytest.mark.asyncio
    async def test_cache_handles_errors_gracefully(self, service, mock_db, mock_user):
        """Test that cache errors don't break get_user_by_email."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        # Simulate cache error
        with patch("mcpgateway.cache.auth_cache.auth_cache.get_user_by_email", new=AsyncMock(side_effect=Exception("Cache error"))):
            with patch("mcpgateway.cache.auth_cache.auth_cache.cache_user_by_email", new=AsyncMock()):
                result = await service.get_user_by_email("test@example.com")

                # Should still return user from database
                assert result == mock_user
                mock_db.execute.assert_called_once()

# Made with Bob
