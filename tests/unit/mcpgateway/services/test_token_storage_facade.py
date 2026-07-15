# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_token_storage_facade.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Rakhi Dutta

Unit tests for TokenStorageService façade pattern with pluggable backends.
Tests backend selection, team_id extraction, and delegation to backends.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.services.token_backends import TokenRecord
from mcpgateway.services.token_storage_service import TokenStorageService


class TestTokenStorageServiceBackendSelection:
    """Test suite for backend selection during initialization."""

    def test_init_with_database_backend_default(self):
        """Test initialization defaults to database backend."""
        mock_db = MagicMock()
        mock_db.get.return_value = None
        user_context = {"email": "user@example.com", "teams": ["team1"]}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)

            assert service.db == mock_db
            assert service.user_context == user_context
            assert service._backend is not None
            from mcpgateway.services.token_backends import DatabaseTokenBackend

            assert isinstance(service._backend, DatabaseTokenBackend)

    def test_init_with_vault_backend(self):
        """Test initialization with Vault backend."""
        mock_db = MagicMock()
        mock_db.get.return_value = None
        user_context = {"email": "user@example.com", "teams": ["team1"]}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "vault"
            settings.vault_addr = "http://vault:8200"
            settings.vault_token = SecretStr("hvs.test-token")  # Use SecretStr, not plain string
            settings.vault_namespace = ""
            settings.vault_kv_mount = "secret"
            settings.vault_kv_path_prefix = "contextforge/oauth"
            settings.vault_tls_verify = True
            settings.vault_token_cache_enabled = False
            settings.vault_token_cache_ttl = 300
            settings.vault_token_cache_max_size = 10000
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)

            assert service.db == mock_db
            assert service.user_context == user_context
            assert service._backend is not None
            from mcpgateway.services.token_backends import VaultTokenBackend

            assert isinstance(service._backend, VaultTokenBackend)

    def test_init_with_invalid_backend_raises_value_error(self):
        """Test initialization with invalid backend raises ValueError."""
        mock_db = MagicMock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "redis"  # Invalid backend
            mock_settings.return_value = settings

            with pytest.raises(ValueError) as exc_info:
                TokenStorageService(mock_db)

            assert "Unknown OAUTH_TOKEN_BACKEND: redis" in str(exc_info.value)
            assert "Expected 'database' or 'vault'" in str(exc_info.value)

    def test_init_without_user_context(self):
        """Test initialization without user context uses empty dict."""
        mock_db = MagicMock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db)

            assert service.user_context == {}

    def test_init_with_none_user_context(self):
        """Test initialization with None user_context converts to empty dict."""
        mock_db = MagicMock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context=None)

            assert service.user_context == {}


class TestTokenStorageServiceTeamIdExtraction:
    """Test suite for _get_team_id method."""

    def test_get_team_id_from_multiple_teams_returns_first(self):
        """Test team_id extraction returns gateway.team_id when available, fallback to first team."""
        mock_db = MagicMock()
        # Mock gateway lookup to return None (fallback to user teams)
        mock_db.get.return_value = None
        user_context = {"email": "user@example.com", "teams": ["engineering", "qa", "devops"]}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            team_id = service._get_team_id("gw-123", "user@example.com")

            assert team_id == "engineering"

    def test_get_team_id_from_single_team(self):
        """Test team_id extraction from single-team list."""
        mock_db = MagicMock()
        mock_db.get.return_value = None
        user_context = {"email": "user@example.com", "teams": ["sales"]}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            team_id = service._get_team_id("gw-123", "user@example.com")

            assert team_id == "sales"

    def test_get_team_id_with_empty_teams_list_returns_none(self):
        """Test team_id returns None when teams list is empty (triggers shared path fallback)."""
        mock_db = MagicMock()
        # Mock gateway with no team_id (None)
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_db.get.return_value = mock_gateway
        # Mock db.execute() to return empty team list
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []
        mock_db.execute.return_value = mock_result
        user_context = {"email": "user@example.com", "teams": []}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            team_id = service._get_team_id("gw-123", "user@example.com")

            assert team_id is None

    def test_get_team_id_with_missing_teams_key_returns_none(self):
        """Test team_id returns None when teams key is missing (triggers shared path fallback)."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_db.get.return_value = mock_gateway
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []
        mock_db.execute.return_value = mock_result
        user_context = {"email": "user@example.com", "is_admin": True}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            team_id = service._get_team_id("gw-123", "user@example.com")

            assert team_id is None

    def test_get_team_id_with_empty_user_context_returns_none(self):
        """Test team_id returns None when user_context is empty (triggers shared path fallback)."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_db.get.return_value = mock_gateway
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []
        mock_db.execute.return_value = mock_result
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_db.get.return_value = mock_gateway
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []
        mock_db.execute.return_value = mock_result

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context={})
            team_id = service._get_team_id("gw-123", "user@example.com")

            assert team_id is None

    def test_get_team_id_with_non_list_teams_returns_none(self):
        """Test team_id returns None when teams is not a list (triggers shared path fallback)."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_db.get.return_value = mock_gateway
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []
        mock_db.execute.return_value = mock_result
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_db.get.return_value = mock_gateway
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []
        mock_db.execute.return_value = mock_result
        # teams is a string instead of a list
        user_context = {"email": "user@example.com", "teams": "engineering"}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            team_id = service._get_team_id("gw-123", "user@example.com")

            assert team_id is None

    def test_get_team_id_with_none_teams_returns_none(self):
        """Test team_id returns None when teams is None (triggers shared path fallback)."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_db.get.return_value = mock_gateway
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []
        mock_db.execute.return_value = mock_result
        user_context = {"email": "user@example.com", "teams": None}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            team_id = service._get_team_id("gw-123", "user@example.com")

            assert team_id is None


class TestTokenStorageServiceStoreTokens:
    """Test suite for store_tokens method delegation."""

    @pytest.mark.asyncio
    async def test_store_tokens_delegates_to_backend(self):
        """Test store_tokens delegates to backend with correct parameters."""
        mock_db = MagicMock()
        # Mock Gateway lookup to return a gateway with team_id
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_db.get.return_value = mock_gateway
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()

        expected_record = TokenRecord(
            gateway_id="gw-123",
            mcp_url="https://mcp.example.com",
            team_id="team1",
            user_id="oauth-user-456",
            app_user_email="user@example.com",
            access_token="access_token_value",
            refresh_token="refresh_token_value",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=["read", "write"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_backend.store_tokens.return_value = expected_record

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            result = await service.store_tokens(
                gateway_id="gw-123",
                user_id="oauth-user-456",
                app_user_email="user@example.com",
                access_token="access_token_value",
                refresh_token="refresh_token_value",
                expires_in=3600,
                scopes=["read", "write"],
            )

            assert result == expected_record
            mock_backend.store_tokens.assert_called_once_with(
                gateway_id="gw-123",
                team_id="team1",
                user_id="oauth-user-456",
                app_user_email="user@example.com",
                access_token="access_token_value",
                refresh_token="refresh_token_value",
                expires_in=3600,
                scopes=["read", "write"],
            )

    @pytest.mark.asyncio
    async def test_store_tokens_extracts_team_id_from_context(self):
        """Test that store_tokens correctly extracts team_id from user context."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "engineering"
        mock_db.get.return_value = mock_gateway
        user_context = {"email": "user@example.com", "teams": ["engineering", "qa"]}
        mock_backend = AsyncMock()
        mock_backend.store_tokens.return_value = MagicMock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            await service.store_tokens(
                gateway_id="gw-123",
                user_id="oauth-user-456",
                app_user_email="user@example.com",
                access_token="token",
                refresh_token=None,
                expires_in=3600,
                scopes=["read"],
            )

            # Verify team_id is extracted as first team
            call_args = mock_backend.store_tokens.call_args[1]
            assert call_args["team_id"] == "engineering"

    @pytest.mark.asyncio
    async def test_store_tokens_with_no_refresh_token(self):
        """Test storing tokens when refresh_token is None."""
        mock_db = MagicMock()
        # Mock Gateway lookup to return a gateway with team_id
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_db.get.return_value = mock_gateway
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()
        mock_backend.store_tokens.return_value = MagicMock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            await service.store_tokens(
                gateway_id="gw-123",
                user_id="oauth-user-456",
                app_user_email="user@example.com",
                access_token="token",
                refresh_token=None,
                expires_in=3600,
                scopes=["read"],
            )

            call_args = mock_backend.store_tokens.call_args[1]
            assert call_args["refresh_token"] is None

    @pytest.mark.asyncio
    async def test_store_tokens_with_no_expiry(self):
        """Test storing tokens when expires_in is None."""
        mock_db = MagicMock()
        # Mock gateway with no team_id (None)
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_db.get.return_value = mock_gateway
        # Mock db.execute() to return empty team list
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []
        mock_db.execute.return_value = mock_result
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()
        mock_backend.store_tokens.return_value = MagicMock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            await service.store_tokens(
                gateway_id="gw-123",
                user_id="oauth-user-456",
                app_user_email="user@example.com",
                access_token="token",
                refresh_token="refresh",
                expires_in=None,
                scopes=["read"],
            )

            call_args = mock_backend.store_tokens.call_args[1]
            assert call_args["expires_in"] is None

    @pytest.mark.asyncio
    async def test_store_tokens_with_empty_scopes(self):
        """Test storing tokens with empty scopes list."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_db.get.return_value = mock_gateway
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []
        mock_db.execute.return_value = mock_result
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()
        mock_backend.store_tokens.return_value = MagicMock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            await service.store_tokens(
                gateway_id="gw-123",
                user_id="oauth-user-456",
                app_user_email="user@example.com",
                access_token="token",
                refresh_token="refresh",
                expires_in=3600,
                scopes=[],
            )

            call_args = mock_backend.store_tokens.call_args[1]
            assert call_args["scopes"] == []


class TestTokenStorageServiceGetUserToken:
    """Test suite for get_user_token method delegation."""

    @pytest.mark.asyncio
    async def test_get_user_token_delegates_to_backend(self):
        """Test get_user_token delegates to backend with correct parameters."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_db.get.return_value = mock_gateway
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()
        mock_backend.get_user_token.return_value = "valid_access_token"

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            token = await service.get_user_token(
                gateway_id="gw-123",
                app_user_email="user@example.com",
                threshold_seconds=300,
            )

            assert token == "valid_access_token"
            mock_backend.get_user_token.assert_called_once_with(
                gateway_id="gw-123",
                team_id="team1",
                app_user_email="user@example.com",
                threshold_seconds=300,
            )

    @pytest.mark.asyncio
    async def test_get_user_token_returns_none_when_not_found(self):
        """Test get_user_token returns None when no token exists."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_db.get.return_value = mock_gateway
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()
        mock_backend.get_user_token.return_value = None

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            token = await service.get_user_token(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )

            assert token is None

    @pytest.mark.asyncio
    async def test_get_user_token_uses_default_threshold(self):
        """Test get_user_token uses default threshold when not specified."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_db.get.return_value = mock_gateway
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []
        mock_db.execute.return_value = mock_result
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()
        mock_backend.get_user_token.return_value = "token"

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            await service.get_user_token(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )

            call_args = mock_backend.get_user_token.call_args[1]
            assert call_args["threshold_seconds"] == 300

    @pytest.mark.asyncio
    async def test_get_user_token_with_custom_threshold(self):
        """Test get_user_token with custom threshold."""
        mock_db = MagicMock()
        mock_db.get.return_value = None
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()
        mock_backend.get_user_token.return_value = "token"

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            await service.get_user_token(
                gateway_id="gw-123",
                app_user_email="user@example.com",
                threshold_seconds=600,
            )

            call_args = mock_backend.get_user_token.call_args[1]
            assert call_args["threshold_seconds"] == 600


class TestTokenStorageServiceGetTokenInfo:
    """Test suite for get_token_info method delegation."""

    @pytest.mark.asyncio
    async def test_get_token_info_delegates_to_backend(self):
        """Test get_token_info delegates to backend with correct parameters."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_db.get.return_value = mock_gateway
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()

        expected_info = {
            "scopes": ["read", "write"],
            "expires_at": "2026-07-10T12:00:00Z",
            "status": "valid",
            "updated_at": "2026-07-09T10:00:00Z",
        }
        mock_backend.get_token_info.return_value = expected_info

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            info = await service.get_token_info(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )

            assert info == expected_info
            mock_backend.get_token_info.assert_called_once_with(
                gateway_id="gw-123",
                team_id="team1",
                app_user_email="user@example.com",
            )

    @pytest.mark.asyncio
    async def test_get_token_info_returns_none_when_not_found(self):
        """Test get_token_info returns None when no token exists."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_db.get.return_value = mock_gateway
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()
        mock_backend.get_token_info.return_value = None

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            info = await service.get_token_info(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )

            assert info is None


class TestTokenStorageServiceRevokeUserTokens:
    """Test suite for revoke_user_tokens method delegation."""

    @pytest.mark.asyncio
    async def test_revoke_user_tokens_delegates_to_backend(self):
        """Test revoke_user_tokens delegates to backend with correct parameters."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_db.get.return_value = mock_gateway
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()
        mock_backend.revoke_user_tokens.return_value = True

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            result = await service.revoke_user_tokens(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )

            assert result is True
            mock_backend.revoke_user_tokens.assert_called_once_with(
                gateway_id="gw-123",
                team_id="team1",
                app_user_email="user@example.com",
            )

    @pytest.mark.asyncio
    async def test_revoke_user_tokens_returns_false_when_not_found(self):
        """Test revoke_user_tokens returns False when no token exists."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_db.get.return_value = mock_gateway
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()
        mock_backend.revoke_user_tokens.return_value = False

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            result = await service.revoke_user_tokens(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )

            assert result is False


class TestTokenStorageServiceIntegration:
    """Integration tests for complete token lifecycle through façade."""

    @pytest.mark.asyncio
    async def test_full_token_lifecycle_with_database_backend(self):
        """Test complete token lifecycle: store, retrieve, get info, revoke."""
        mock_db = MagicMock()
        mock_db.get.return_value = None
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()

        # Setup mock backend responses
        token_record = TokenRecord(
            gateway_id="gw-123",
            mcp_url="https://mcp.example.com",
            team_id="team1",
            user_id="oauth-user-456",
            app_user_email="user@example.com",
            access_token="access_token_value",
            refresh_token="refresh_token_value",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=["read", "write"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_backend.store_tokens.return_value = token_record
        mock_backend.get_user_token.return_value = "access_token_value"
        mock_backend.get_token_info.return_value = {
            "scopes": ["read", "write"],
            "expires_at": token_record.expires_at.isoformat(),
            "status": "valid",
            "updated_at": token_record.updated_at.isoformat(),
        }
        mock_backend.revoke_user_tokens.return_value = True

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            # 1. Store tokens
            stored = await service.store_tokens(
                gateway_id="gw-123",
                user_id="oauth-user-456",
                app_user_email="user@example.com",
                access_token="access_token_value",
                refresh_token="refresh_token_value",
                expires_in=3600,
                scopes=["read", "write"],
            )
            assert stored.access_token == "access_token_value"
            assert stored.team_id == "team1"

            # 2. Retrieve token
            token = await service.get_user_token(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )
            assert token == "access_token_value"

            # 3. Get token info
            info = await service.get_token_info(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )
            assert info["status"] == "valid"
            assert info["scopes"] == ["read", "write"]

            # 4. Revoke tokens
            revoked = await service.revoke_user_tokens(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )
            assert revoked is True

    @pytest.mark.asyncio
    async def test_full_token_lifecycle_with_vault_backend(self):
        """Test complete token lifecycle with Vault backend."""
        mock_db = MagicMock()
        mock_db.get.return_value = None
        user_context = {"email": "user@example.com", "teams": ["team1"]}
        mock_backend = AsyncMock()

        # Setup mock backend responses (Vault backend)
        token_record = TokenRecord(
            gateway_id="gw-123",
            mcp_url="https://mcp.example.com",
            team_id="team1",
            user_id="oauth-user-456",
            app_user_email="user@example.com",
            access_token="vault_access_token",
            refresh_token="vault_refresh_token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=["read", "write"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_backend.store_tokens.return_value = token_record
        mock_backend.get_user_token.return_value = "vault_access_token"
        mock_backend.get_token_info.return_value = {
            "scopes": ["read", "write"],
            "expires_at": token_record.expires_at.isoformat(),
            "status": "valid",
            "updated_at": token_record.updated_at.isoformat(),
        }
        mock_backend.revoke_user_tokens.return_value = True

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "vault"
            settings.vault_addr = "http://vault:8200"
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend = mock_backend

            # Store, retrieve, info, revoke lifecycle
            stored = await service.store_tokens(
                gateway_id="gw-123",
                user_id="oauth-user-456",
                app_user_email="user@example.com",
                access_token="vault_access_token",
                refresh_token="vault_refresh_token",
                expires_in=3600,
                scopes=["read", "write"],
            )
            assert stored.access_token == "vault_access_token"

            token = await service.get_user_token(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )
            assert token == "vault_access_token"

            info = await service.get_token_info(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )
            assert info["status"] == "valid"

            revoked = await service.revoke_user_tokens(
                gateway_id="gw-123",
                app_user_email="user@example.com",
            )
            assert revoked is True
