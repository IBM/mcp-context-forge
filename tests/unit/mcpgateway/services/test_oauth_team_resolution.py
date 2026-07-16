# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_oauth_team_resolution.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Rakhi Dutta

Comprehensive unit tests for OAuth token storage team resolution logic.
Tests the team_id extraction and routing to appropriate storage paths (DB vs Vault).
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.services.token_backends import DatabaseTokenBackend, TokenRecord, VaultTokenBackend
from mcpgateway.services.token_storage_service import TokenStorageService


class TestTeamResolutionWithDatabaseBackend:
    """Test team_id resolution with DatabaseTokenBackend (team_id ignored in Phase 1)."""

    @pytest.mark.asyncio
    async def test_store_tokens_ignores_team_id_in_database_backend(self):
        """Database backend accepts team_id but ignores it (Phase 1 - no DB column yet)."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_db.get.return_value = mock_gateway

        user_context = {"email": "user@example.com", "teams": ["team1", "team2"]}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            settings.auth_encryption_secret = "test-secret-key"  # pragma: allowlist secret
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)

            # Mock backend.store_tokens to verify team_id is passed
            mock_backend_result = TokenRecord(
                gateway_id="gw-123",
                mcp_url="https://mcp.example.com",
                team_id="team1",  # Backend receives team_id
                user_id="oauth-user-456",
                app_user_email="user@example.com",
                access_token="access_token_value",
                refresh_token="refresh_token_value",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc),
                scopes=["read", "write"],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            with patch.object(service._backend, "store_tokens", new_callable=AsyncMock) as mock_store:
                mock_store.return_value = mock_backend_result

                await service.store_tokens(
                    gateway_id="gw-123",
                    user_id="oauth-user-456",
                    app_user_email="user@example.com",
                    access_token="access_token_value",
                    refresh_token="refresh_token_value",
                    expires_in=3600,
                    scopes=["read", "write"],
                )

                # Verify backend.store_tokens was called with team_id="team1" (first team)
                mock_store.assert_called_once()
                call_kwargs = mock_store.call_args[1]
                assert call_kwargs["team_id"] == "team1"
                # Database backend ignores this internally, but service passes it

    @pytest.mark.asyncio
    async def test_get_user_token_uses_first_team_with_database_backend(self):
        """Database backend uses first team from JWT teams list."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_db.get.return_value = mock_gateway

        user_context = {"email": "user@example.com", "teams": ["engineering", "sales"]}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            settings.auth_encryption_secret = "test-secret-key"  # pragma: allowlist secret
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)

            with patch.object(service._backend, "get_user_token", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = "access_token_value"

                await service.get_user_token("gw-123", "user@example.com")

                # Verify backend.get_user_token was called with team_id="engineering" (first team)
                mock_get.assert_called_once()
                call_kwargs = mock_get.call_args[1]
                assert call_kwargs["team_id"] == "engineering"


class TestTeamResolutionWithVaultBackend:
    """Test team_id resolution with VaultTokenBackend (uses team_id in path)."""

    @pytest.mark.asyncio
    async def test_store_tokens_uses_team_id_in_vault_path(self):
        """Vault backend uses team_id to construct storage path."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        user_context = {"email": "alice@example.com", "teams": ["engineering"]}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "vault"
            settings.vault_addr = "http://vault:8200"
            settings.vault_token = SecretStr("hvs.test-token")
            settings.vault_namespace = ""
            settings.vault_kv_mount = "secret"
            settings.vault_kv_path_prefix = "contextforge/oauth"
            settings.vault_tls_verify = True
            settings.vault_token_cache_enabled = False
            settings.vault_token_cache_ttl = 300
            settings.vault_token_cache_max_size = 10000
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)

            mock_backend_result = TokenRecord(
                gateway_id="gw-123",
                mcp_url="https://mcp.example.com",
                team_id="engineering",
                user_id="oauth-user-456",
                app_user_email="alice@example.com",
                access_token="access_token_value",
                refresh_token="refresh_token_value",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc),
                scopes=["read", "write"],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            with patch.object(service._backend, "store_tokens", new_callable=AsyncMock) as mock_store:
                mock_store.return_value = mock_backend_result

                await service.store_tokens(
                    gateway_id="gw-123",
                    user_id="oauth-user-456",
                    app_user_email="alice@example.com",
                    access_token="access_token_value",
                    refresh_token="refresh_token_value",
                    expires_in=3600,
                    scopes=["read", "write"],
                )

                # Verify backend.store_tokens was called with team_id="engineering"
                mock_store.assert_called_once()
                call_kwargs = mock_store.call_args[1]
                assert call_kwargs["team_id"] == "engineering"

    @pytest.mark.asyncio
    async def test_get_user_token_with_multi_team_uses_first_team(self):
        """Vault backend uses first team when user has multiple teams."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        # User has multiple teams - should use first one for stable path
        user_context = {"email": "alice@example.com", "teams": ["engineering", "sales", "support"]}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "vault"
            settings.vault_addr = "http://vault:8200"
            settings.vault_token = SecretStr("hvs.test-token")
            settings.vault_namespace = ""
            settings.vault_kv_mount = "secret"
            settings.vault_kv_path_prefix = "contextforge/oauth"
            settings.vault_tls_verify = True
            settings.vault_token_cache_enabled = False
            settings.vault_token_cache_ttl = 300
            settings.vault_token_cache_max_size = 10000
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)

            with patch.object(service._backend, "get_user_token", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = "access_token_value"

                result = await service.get_user_token("gw-123", "alice@example.com")

                assert result == "access_token_value"
                # Verify backend was called with team_id="engineering" (first team)
                mock_get.assert_called_once()
                call_kwargs = mock_get.call_args[1]
                assert call_kwargs["team_id"] == "engineering"


class TestSharedPathFallback:
    """Test shared path fallback when no team_id is available."""

    @pytest.mark.asyncio
    async def test_vault_backend_uses_none_when_no_teams(self):
        """Vault backend receives None team_id and uses shared path."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        # User has no teams (e.g., Admin UI session)
        user_context = {"email": "admin@example.com"}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "vault"
            settings.vault_addr = "http://vault:8200"
            settings.vault_token = SecretStr("hvs.test-token")
            settings.vault_namespace = ""
            settings.vault_kv_mount = "secret"
            settings.vault_kv_path_prefix = "contextforge/oauth"
            settings.vault_tls_verify = True
            settings.vault_token_cache_enabled = False
            settings.vault_token_cache_ttl = 300
            settings.vault_token_cache_max_size = 10000
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)

            mock_backend_result = TokenRecord(
                gateway_id="gw-123",
                mcp_url="https://mcp.example.com",
                team_id=None,  # Shared path
                user_id="oauth-user-456",
                app_user_email="admin@example.com",
                access_token="access_token_value",
                refresh_token="refresh_token_value",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc),
                scopes=["read", "write"],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            with patch.object(service._backend, "store_tokens", new_callable=AsyncMock) as mock_store:
                mock_store.return_value = mock_backend_result

                await service.store_tokens(
                    gateway_id="gw-123",
                    user_id="oauth-user-456",
                    app_user_email="admin@example.com",
                    access_token="access_token_value",
                    refresh_token="refresh_token_value",
                    expires_in=3600,
                    scopes=["read", "write"],
                )

                # Verify backend.store_tokens was called with team_id=None
                mock_store.assert_called_once()
                call_kwargs = mock_store.call_args[1]
                assert call_kwargs["team_id"] is None

    @pytest.mark.asyncio
    async def test_database_backend_accepts_none_team_id(self):
        """Database backend accepts None team_id (ignored in Phase 1)."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = None
        mock_db.get.return_value = mock_gateway

        user_context = {"email": "admin@example.com", "is_admin": True}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            settings.auth_encryption_secret = "test-secret-key"  # pragma: allowlist secret
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)

            mock_backend_result = TokenRecord(
                gateway_id="gw-123",
                mcp_url="https://mcp.example.com",
                team_id=None,
                user_id="oauth-user-456",
                app_user_email="admin@example.com",
                access_token="access_token_value",
                refresh_token="refresh_token_value",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc),
                scopes=["read", "write"],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            with patch.object(service._backend, "store_tokens", new_callable=AsyncMock) as mock_store:
                mock_store.return_value = mock_backend_result

                await service.store_tokens(
                    gateway_id="gw-123",
                    user_id="oauth-user-456",
                    app_user_email="admin@example.com",
                    access_token="access_token_value",
                    refresh_token="refresh_token_value",
                    expires_in=3600,
                    scopes=["read", "write"],
                )

                # Verify backend.store_tokens was called with team_id=None
                mock_store.assert_called_once()
                call_kwargs = mock_store.call_args[1]
                assert call_kwargs["team_id"] is None


class TestVaultPathConstruction:
    """Test Vault path construction with and without team_id."""

    def test_construct_vault_path_with_team(self):
        """Vault path includes team segment when team_id is provided."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://vault:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        path = backend._construct_vault_path(
            team_id="engineering",
            mcp_url="https://mcp.example.com",
            app_user_email="alice@example.com"
        )

        # Verify path structure: mount/data/prefix/team_id/server_id/email
        assert "secret/data/contextforge/oauth/engineering/" in path
        assert "alice%40example.com" in path

    def test_construct_vault_path_with_none_team_uses_shared(self):
        """Vault path uses 'shared' segment when team_id is None."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://vault:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        path = backend._construct_vault_path(
            team_id=None,
            mcp_url="https://mcp.example.com",
            app_user_email="admin@example.com"
        )

        # Verify path structure uses "shared" when team_id is None
        assert "secret/data/contextforge/oauth/shared/" in path
        assert "admin%40example.com" in path

    def test_construct_credentials_path_with_team(self):
        """Vault credentials path includes team segment."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://vault:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        path = backend._construct_credentials_path(
            team_id="engineering",
            mcp_url="https://mcp.example.com"
        )

        # Verify credentials path: mount/data/prefix/credentials/team_id/server_id
        assert "secret/data/contextforge/oauth/credentials/engineering/" in path

    def test_construct_credentials_path_with_none_team_uses_shared(self):
        """Vault credentials path uses 'shared' segment when team_id is None."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://vault:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        path = backend._construct_credentials_path(
            team_id=None,
            mcp_url="https://mcp.example.com"
        )

        # Verify credentials path uses "shared" when team_id is None
        assert "secret/data/contextforge/oauth/credentials/shared/" in path


class TestRevokeTokensWithTeams:
    """Test token revocation with team resolution."""

    @pytest.mark.asyncio
    async def test_revoke_tokens_uses_correct_team_id(self):
        """Revoke tokens uses first team from JWT teams list."""
        mock_db = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.team_id = "team1"
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        user_context = {"email": "user@example.com", "teams": ["engineering", "sales"]}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "vault"
            settings.vault_addr = "http://vault:8200"
            settings.vault_token = SecretStr("hvs.test-token")
            settings.vault_namespace = ""
            settings.vault_kv_mount = "secret"
            settings.vault_kv_path_prefix = "contextforge/oauth"
            settings.vault_tls_verify = True
            settings.vault_token_cache_enabled = False
            settings.vault_token_cache_ttl = 300
            settings.vault_token_cache_max_size = 10000
            mock_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)

            with patch.object(service._backend, "revoke_user_tokens", new_callable=AsyncMock) as mock_revoke:
                mock_revoke.return_value = True

                result = await service.revoke_user_tokens("gw-123", "user@example.com")

                assert result is True
                # Verify backend was called with team_id="engineering" (first team)
                mock_revoke.assert_called_once()
                call_kwargs = mock_revoke.call_args[1]
                assert call_kwargs["team_id"] == "engineering"


# ---------------------------------------------------------------------------
# Coverage gap fill: base.py AbstractTokenBackend.get_oauth_credentials
# default implementation (line 185) returns None.
# ---------------------------------------------------------------------------


class TestAbstractTokenBackendGetOAuthCredentials:
    """Line 185 in base.py: default get_oauth_credentials returns None."""

    @pytest.mark.asyncio
    async def test_database_backend_get_oauth_credentials_returns_none(self):
        """Line 185: DatabaseTokenBackend (concrete subclass using default impl) → None."""
        # First-Party
        from mcpgateway.services.token_backends.db_backend import DatabaseTokenBackend

        mock_db = MagicMock()
        backend = DatabaseTokenBackend(mock_db, None)

        result = await backend.get_oauth_credentials(team_id="team-1", mcp_url="https://mcp.example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_database_backend_get_oauth_credentials_none_team_returns_none(self):
        """Line 185: team_id=None (shared path) also returns None via default impl."""
        # First-Party
        from mcpgateway.services.token_backends.db_backend import DatabaseTokenBackend

        mock_db = MagicMock()
        backend = DatabaseTokenBackend(mock_db, None)

        result = await backend.get_oauth_credentials(team_id=None, mcp_url="https://mcp.example.com")

        assert result is None


class TestTokenStorageServiceGetOAuthCredentials:
    """Line 362 in token_storage_service.py: delegates to backend.get_oauth_credentials."""

    @pytest.mark.asyncio
    async def test_get_oauth_credentials_delegates_to_backend(self):
        """Line 362: TokenStorageService.get_oauth_credentials calls _backend.get_oauth_credentials."""
        mock_db = MagicMock()
        user_context = {"email": "user@example.com", "teams": ["team-1"]}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            settings.auth_encryption_secret = "test-secret"  # pragma: allowlist secret
            mock_get_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)

            # Patch the backend's get_oauth_credentials to return a known value
            mock_creds = {"client_id": "cid", "client_secret": "s3cr3t"}  # pragma: allowlist secret
            service._backend.get_oauth_credentials = AsyncMock(return_value=mock_creds)

            result = await service.get_oauth_credentials(team_id="team-1", mcp_url="https://mcp.example.com")

        assert result == mock_creds
        service._backend.get_oauth_credentials.assert_awaited_once_with("team-1", "https://mcp.example.com")

    @pytest.mark.asyncio
    async def test_get_oauth_credentials_returns_none_from_backend(self):
        """Line 362: None returned from backend is propagated directly."""
        mock_db = MagicMock()
        user_context = {"email": "user@example.com", "teams": None}

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            settings = MagicMock()
            settings.oauth_token_backend = "database"
            settings.auth_encryption_secret = "test-secret"  # pragma: allowlist secret
            mock_get_settings.return_value = settings

            service = TokenStorageService(mock_db, user_context)
            service._backend.get_oauth_credentials = AsyncMock(return_value=None)

            result = await service.get_oauth_credentials(team_id=None, mcp_url="https://mcp.example.com")

        assert result is None
