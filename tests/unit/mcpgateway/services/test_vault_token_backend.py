# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_vault_token_backend.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Rakhi Dutta

Unit tests for VaultTokenBackend implementation.
Tests the Vault KV v2 token storage backend.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.db import Gateway
from mcpgateway.services.token_backends.vault_backend import VaultAuthError, VaultConnectionError, VaultTokenBackend


class TestVaultTokenBackendInit:
    """Test suite for VaultTokenBackend initialization."""

    def test_init_with_default_settings(self):
        """Test initialization with default Vault settings."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        assert backend.db == mock_db
        assert backend.vault_addr == "http://127.0.0.1:8200"
        assert backend.vault_token == "hvs.test-token"
        assert backend.mount == "secret"
        assert backend.prefix == "contextforge/oauth"
        assert backend.tls_verify is True
        assert backend.cache_enabled is False

    def test_init_with_cache_enabled(self):
        """Test initialization with token caching enabled."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = True
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        assert backend.cache_enabled is True
        assert backend.cache_ttl == 300
        assert backend.cache_max_size == 10000
        # Cache is class-level, not instance-level
        assert hasattr(VaultTokenBackend, "_token_cache")

    def test_init_with_enterprise_namespace(self):
        """Test initialization with Vault Enterprise namespace."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "https://vault.acme.com:8200"
        mock_settings.vault_token = SecretStr("hvs.prod-token")
        mock_settings.vault_namespace = "engineering/team1"
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        assert backend.vault_namespace == "engineering/team1"

    def test_init_with_custom_mount_and_prefix(self):
        """Test initialization with custom KV mount and path prefix."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "kv-v2"
        mock_settings.vault_kv_path_prefix = "oauth/tokens"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        assert backend.mount == "kv-v2"
        assert backend.prefix == "oauth/tokens"

    def test_init_without_vault_token_raises_error(self):
        """Test that initialization fails without VAULT_TOKEN."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = None  # No token provided
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        with pytest.raises(ValueError) as exc_info:
            VaultTokenBackend(mock_db, mock_settings)

        assert "VAULT_TOKEN is required" in str(exc_info.value)


class TestVaultTokenBackendPathHelpers:
    """Test suite for path construction helper methods."""

    def test_resolve_mcp_url_success(self):
        """Test successful gateway_id to mcp_url resolution."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        # Mock gateway lookup
        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        result = backend._resolve_mcp_url("gw-123")

        assert result == "https://mcp.example.com"
        mock_db.get.assert_called_once_with(Gateway, "gw-123")

    def test_resolve_mcp_url_not_found(self):
        """Test gateway_id resolution raises ValueError when gateway not found."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        # Mock gateway not found
        mock_db.get.return_value = None

        with pytest.raises(ValueError) as exc_info:
            backend._resolve_mcp_url("nonexistent-gw")

        assert "Gateway nonexistent-gw not found" in str(exc_info.value)

    def test_hash_server_id(self):
        """Test MCP URL hashing to server_id."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        # Test consistent hashing (16 hex chars per implementation)
        server_id1 = backend._hash_server_id("https://mcp.example.com")
        server_id2 = backend._hash_server_id("https://mcp.example.com")
        assert server_id1 == server_id2
        assert len(server_id1) == 16  # First 16 hex chars (64-bit prefix)

        # Different URLs produce different hashes
        server_id3 = backend._hash_server_id("https://mcp.different.com")
        assert server_id1 != server_id3

    def test_construct_vault_path(self):
        """Test Vault KV v2 path construction."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
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

        # Verify path structure
        assert path.startswith("secret/data/contextforge/oauth/engineering/")
        assert "alice%40example.com" in path  # Email URL-encoded

    def test_construct_vault_path_with_special_chars_in_email(self):
        """Test path construction with special characters in email."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
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
            team_id="team1",
            mcp_url="https://mcp.example.com",
            app_user_email="user+test@example.com"
        )

        # Special chars should be URL-encoded
        assert "user%2Btest%40example.com" in path

    def test_construct_metadata_path(self):
        """Test Vault metadata path construction for hard delete."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        path = backend._construct_metadata_path(
            team_id="team1",
            mcp_url="https://mcp.example.com",
            app_user_email="alice@example.com"
        )

        # Metadata path uses /metadata/ instead of /data/
        assert "secret/metadata/contextforge/oauth/team1/" in path
        assert "alice%40example.com" in path


class TestVaultTokenBackendStoreTokens:
    """Test suite for store_tokens method."""

    @pytest.mark.asyncio
    async def test_store_tokens_success(self):
        """Test successful token storage in Vault."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        # Mock gateway lookup
        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        # Mock Vault API call
        # store_tokens now calls _vault_request TWICE:
        # 1. GET to check for existing record (to preserve created_at)
        # 2. POST to write the new/updated token
        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            # First call (GET) returns None (no existing record)
            # Second call (POST) returns success
            mock_vault.side_effect = [None, {"data": {"version": 1}}]

            result = await backend.store_tokens(
                gateway_id="gw-123",
                team_id="team1",
                user_id="oauth-user-456",
                app_user_email="user@example.com",
                access_token="access_token_value",
                refresh_token="refresh_token_value",
                expires_in=3600,
                scopes=["read", "write"],
            )

            # Verify result
            assert result.gateway_id == "gw-123"
            assert result.team_id == "team1"
            assert result.access_token == "access_token_value"
            assert result.refresh_token == "refresh_token_value"
            assert result.scopes == ["read", "write"]
            assert result.mcp_url == "https://mcp.example.com"

            # Verify Vault API was called twice (GET then POST)
            assert mock_vault.call_count == 2
            # First call is GET to check for existing record
            assert mock_vault.call_args_list[0][0][0] == "GET"
            # Second call is POST to write tokens
            assert mock_vault.call_args_list[1][0][0] == "POST"
            call_args = mock_vault.call_args_list[1]
            # call_args[1] is kwargs dict, or if using positional args, check call_args[0]
            # The data is passed as third positional argument or as 'data' keyword
            assert len(call_args[0]) >= 2  # At minimum: method, path

    @pytest.mark.asyncio
    async def test_store_tokens_without_refresh_token(self):
        """Test storing tokens when refresh_token is None."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = {"data": {"version": 1}}

            result = await backend.store_tokens(
                gateway_id="gw-123",
                team_id="team1",
                user_id="oauth-user-456",
                app_user_email="user@example.com",
                access_token="access_token_value",
                refresh_token=None,
                expires_in=3600,
                scopes=["read"],
            )

            assert result.refresh_token is None


class TestVaultTokenBackendGetUserToken:
    """Test suite for get_user_token method."""

    @pytest.mark.asyncio
    async def test_get_user_token_returns_valid_token(self):
        """Test retrieving a valid non-expired token."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        # Mock Vault response with valid token (matches actual storage format)
        vault_response = {
            "data": {
                "data": {
                    "email": "user@example.com",
                    "team_id": "team1",
                    "mcp_url": "https://mcp.example.com",
                    "token": {
                        "access_token": "valid_access_token",
                        "refresh_token": "refresh_token_value",
                        "scopes": ["read", "write"],
                    },
                    "user_id": "oauth-user-456",
                    "token_type": "Bearer",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        }

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = vault_response

            token = await backend.get_user_token(
                gateway_id="gw-123",
                team_id="team1",
                app_user_email="user@example.com",
                threshold_seconds=300,
            )

            assert token == "valid_access_token"

    @pytest.mark.asyncio
    async def test_get_user_token_returns_none_when_not_found(self):
        """Test token retrieval when no token exists (404)."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        # Mock 404 response
        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = None  # _vault_request returns None on 404

            token = await backend.get_user_token(
                gateway_id="gw-123",
                team_id="team1",
                app_user_email="user@example.com",
                threshold_seconds=300,
            )

            assert token is None


class TestVaultTokenBackendRevoke:
    """Test suite for revoke_user_tokens method."""

    @pytest.mark.asyncio
    async def test_revoke_user_tokens_success(self):
        """Test successful token revocation."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = {}  # Successful delete

            result = await backend.revoke_user_tokens(
                gateway_id="gw-123",
                team_id="team1",
                app_user_email="user@example.com",
            )

            assert result is True
            # Verify DELETE was called
            call_args = mock_vault.call_args
            assert call_args[0][0] == "DELETE"

    @pytest.mark.asyncio
    async def test_revoke_user_tokens_not_found(self):
        """Test revoking tokens when no token exists."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = None  # 404 Not Found

            result = await backend.revoke_user_tokens(
                gateway_id="gw-123",
                team_id="team1",
                app_user_email="user@example.com",
            )

            # Should return False when token doesn't exist
            assert result is False
