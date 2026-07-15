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


class TestVaultTokenBackendVaultRequest:
    """Test suite for _vault_request HTTP error handling."""

    @pytest.mark.asyncio
    async def test_vault_request_with_namespace(self):
        """Test that Vault Enterprise namespace is included in headers."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = "engineering/team1"
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000

        backend = VaultTokenBackend(mock_db, mock_settings)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{"data": {}}'
            mock_response.json.return_value = {"data": {}}
            mock_client.get.return_value = mock_response

            await backend._vault_request("GET", "secret/data/test")

            # Verify namespace header was included
            call_kwargs = mock_client.get.call_args[1]
            assert "X-Vault-Namespace" in call_kwargs["headers"]
            assert call_kwargs["headers"]["X-Vault-Namespace"] == "engineering/team1"

    @pytest.mark.asyncio
    async def test_vault_request_unsupported_method(self):
        """Test that unsupported HTTP methods raise ValueError."""
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

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ValueError, match="Unsupported HTTP method"):
                await backend._vault_request("PUT", "secret/data/test")

    @pytest.mark.asyncio
    async def test_vault_request_empty_response_non_delete_logs_warning(self):
        """Test that empty response for non-DELETE methods logs warning."""
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

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b''  # Empty response
            mock_client.get.return_value = mock_response

            with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
                result = await backend._vault_request("GET", "secret/data/test")

                mock_logger.warning.assert_called_once()
                assert "empty body" in mock_logger.warning.call_args[0][0].lower()
                assert result == {}

    @pytest.mark.asyncio
    async def test_vault_request_empty_response_delete_no_warning(self):
        """Test that empty response for DELETE method doesn't log warning."""
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

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.content = b''
            mock_client.delete.return_value = mock_response

            with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
                result = await backend._vault_request("DELETE", "secret/data/test")

                mock_logger.warning.assert_not_called()
                assert result == {}

    @pytest.mark.asyncio
    async def test_vault_request_connect_timeout_retries(self):
        """Test retry logic for connection timeout errors."""
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

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Fail twice, succeed on third attempt
            success_response = MagicMock()
            success_response.status_code = 200
            success_response.content = b'{"data":{}}'
            success_response.json.return_value = {"data": {}}

            mock_client.get.side_effect = [
                httpx.ConnectTimeout("Connection timeout"),
                httpx.ConnectTimeout("Connection timeout"),
                success_response
            ]

            with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await backend._vault_request("GET", "secret/data/test")

                    assert mock_logger.warning.call_count == 2
                    assert result == {"data": {}}

    @pytest.mark.asyncio
    async def test_vault_request_connect_error_raises_after_retries(self):
        """Test that connection errors raise VaultConnectionError after 3 attempts."""
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

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.ConnectError("Connection failed")

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(VaultConnectionError, match="Credential storage unavailable"):
                    await backend._vault_request("GET", "secret/data/test")

    @pytest.mark.asyncio
    async def test_vault_request_5xx_error_retries(self):
        """Test retry logic for 5xx server errors."""
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

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Create mock responses for 500 errors and success
            error_response = MagicMock()
            error_response.status_code = 500

            success_response = MagicMock()
            success_response.status_code = 200
            success_response.content = b'{"data":{}}'
            success_response.json.return_value = {"data": {}}

            # Fail twice with 500, succeed on third
            mock_client.get.side_effect = [
                httpx.HTTPStatusError("Server error", request=MagicMock(), response=error_response),
                httpx.HTTPStatusError("Server error", request=MagicMock(), response=error_response),
                success_response
            ]

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
                    result = await backend._vault_request("GET", "secret/data/test")

                    assert mock_logger.warning.call_count == 2
                    assert result == {"data": {}}

    @pytest.mark.asyncio
    async def test_vault_request_403_raises_auth_error(self):
        """Test that 403 errors raise VaultAuthError."""
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

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            error_response = MagicMock()
            error_response.status_code = 403
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "Forbidden",
                request=MagicMock(),
                response=error_response
            )

            with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
                with pytest.raises(VaultAuthError, match="VAULT_TOKEN invalid or expired"):
                    await backend._vault_request("GET", "secret/data/test")

                mock_logger.critical.assert_called_once()


class TestVaultTokenBackendGetOAuthCredentials:
    """Test suite for get_oauth_credentials method."""

    @pytest.mark.asyncio
    async def test_get_oauth_credentials_success(self):
        """Test retrieving OAuth credentials from Vault."""
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

        vault_response = {
            "data": {
                "data": {
                    "client_id": "oauth_client_id",
                    "client_secret": "oauth_client_secret",  # pragma: allowlist secret
                    "authorization_endpoint": "https://oauth.example.com/authorize",
                    "token_endpoint": "https://oauth.example.com/token",
                    "scopes": ["read", "write"]
                }
            }
        }

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = vault_response

            result = await backend.get_oauth_credentials(
                team_id="team1",
                mcp_url="https://mcp.example.com"
            )

            assert result["client_id"] == "oauth_client_id"
            assert result["client_secret"] == "oauth_client_secret"
            assert result["scopes"] == ["read", "write"]

    @pytest.mark.asyncio
    async def test_get_oauth_credentials_not_found(self):
        """Test get_oauth_credentials returns None when credentials don't exist."""
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

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = None  # Not found

            with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
                result = await backend.get_oauth_credentials(
                    team_id="team1",
                    mcp_url="https://mcp.example.com"
                )

                assert result is None
                mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_oauth_credentials_exception(self):
        """Test get_oauth_credentials handles exceptions gracefully."""
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

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.side_effect = Exception("Vault error")

            with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
                result = await backend.get_oauth_credentials(
                    team_id="team1",
                    mcp_url="https://mcp.example.com"
                )

                assert result is None
                mock_logger.warning.assert_called_once()


class TestVaultTokenBackendCleanupExpiredTokens:
    """Test suite for cleanup_expired_tokens method."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens_logs_warning(self):
        """Test that cleanup_expired_tokens logs info about no-op behavior."""
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

        # Reset the warning flag to test first-time behavior
        VaultTokenBackend._cleanup_warned = False

        with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
            result = await backend.cleanup_expired_tokens(max_age_days=30)

            assert result == 0
            mock_logger.info.assert_called_once()
            assert "cleanup_expired_tokens is a no-op" in mock_logger.info.call_args[0][0]


class TestVaultTokenBackendStoreOAuthCredentials:
    """Test suite for store_oauth_credentials method."""

    @pytest.mark.asyncio
    async def test_store_oauth_credentials_success(self):
        """Test storing OAuth credentials in Vault."""
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

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = {"data": {"version": 1}}

            credentials = {
                "client_id": "oauth_client_id",
                "client_secret": "oauth_client_secret",  # pragma: allowlist secret
                "authorization_endpoint": "https://oauth.example.com/authorize",
                "token_endpoint": "https://oauth.example.com/token",
                "scopes": ["read", "write"]
            }

            result = await backend.store_oauth_credentials(
                team_id="team1",
                mcp_url="https://mcp.example.com",
                credentials=credentials
            )

            assert result is True
            # Verify POST was called
            call_args = mock_vault.call_args
            assert call_args[0][0] == "POST"

    @pytest.mark.asyncio
    async def test_store_oauth_credentials_exception(self):
        """Test store_oauth_credentials handles exceptions."""
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

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.side_effect = Exception("Vault error")

            credentials = {
                "client_id": "oauth_client_id",
                "client_secret": "oauth_client_secret",  # pragma: allowlist secret
                "authorization_endpoint": "https://oauth.example.com/authorize",
                "token_endpoint": "https://oauth.example.com/token",
                "scopes": ["read", "write"]
            }

            with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
                result = await backend.store_oauth_credentials(
                    team_id="team1",
                    mcp_url="https://mcp.example.com",
                    credentials=credentials
                )

                assert result is False
                mock_logger.error.assert_called_once()


class TestVaultTokenBackendGetTokenInfo:
    """Test suite for get_token_info method."""

    @pytest.mark.asyncio
    async def test_get_token_info_success(self):
        """Test get_token_info returns token metadata."""
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

        vault_response = {
            "data": {
                "data": {
                    "email": "user@example.com",
                    "team_id": "team1",
                    "mcp_url": "https://mcp.example.com",
                    "token": {
                        "access_token": "access_token_value",
                        "scopes": ["read", "write"],
                    },
                    "user_id": "oauth-user-456",
                    "token_type": "Bearer",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        }

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = vault_response

            result = await backend.get_token_info(
                gateway_id="gw-123",
                team_id="team1",
                app_user_email="user@example.com",
            )

            assert result is not None
            assert "access_token" not in result  # Should not include sensitive data


class TestVaultTokenBackendRefreshToken:
    """Test suite for _refresh_access_token method."""

    @pytest.mark.asyncio
    async def test_refresh_token_no_gateway_config(self):
        """Test refresh returns None when gateway has no OAuth config."""
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

        # Mock gateway without oauth_config
        mock_gateway = MagicMock()
        mock_gateway.oauth_config = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        vault_data = {
            "token": {"access_token": "old_token", "scopes": ["read"]},
            "user_id": "user123"
        }

        with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
            result = await backend._refresh_access_token(
                gateway_id="gw-1",
                team_id="team1",
                app_user_email="user@test.com",
                refresh_token="refresh_token",
                vault_data=vault_data
            )

            assert result is None
            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_token_private_gateway_wrong_owner(self):
        """Test refresh denied for private gateway with different owner."""
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

        # Mock private gateway owned by someone else
        mock_gateway = MagicMock()
        mock_gateway.oauth_config = {"client_id": "test", "client_secret": "secret"}
        mock_gateway.visibility = "private"
        mock_gateway.owner_email = "owner@test.com"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        vault_data = {
            "token": {"access_token": "old_token", "scopes": ["read"]},
            "user_id": "user123"
        }

        with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
            result = await backend._refresh_access_token(
                gateway_id="gw-1",
                team_id="team1",
                app_user_email="user@test.com",  # Different from owner
                refresh_token="refresh_token",
                vault_data=vault_data
            )

            assert result is None
            mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_refresh_token_success(self):
        """Test successful token refresh in Vault."""
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

        # Mock gateway
        mock_gateway = MagicMock()
        mock_gateway.oauth_config = {
            "client_id": "test",
            "client_secret": "secret",
            "token_url": "https://oauth.example.com/token"
        }
        mock_gateway.visibility = "public"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        vault_data = {
            "token": {"access_token": "old_token", "scopes": ["read"]},
            "user_id": "user123"
        }

        # Mock OAuthManager
        with patch("mcpgateway.services.token_backends.vault_backend.OAuthManager") as mock_oauth_class:
            mock_oauth = AsyncMock()
            mock_oauth.refresh_token.return_value = {
                "access_token": "new_access_token",
                "refresh_token": "new_refresh_token",
                "expires_in": 3600
            }
            mock_oauth_class.return_value = mock_oauth

            with patch.object(backend, "store_tokens", new_callable=AsyncMock) as mock_store:
                result = await backend._refresh_access_token(
                    gateway_id="gw-1",
                    team_id="team1",
                    app_user_email="user@test.com",
                    refresh_token="refresh_token",
                    vault_data=vault_data
                )

                assert result == "new_access_token"
                mock_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_token_with_resource_normalization(self):
        """Test refresh with resource list normalization."""
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

        # Mock gateway with resource list
        mock_gateway = MagicMock()
        mock_gateway.oauth_config = {
            "client_id": "test",
            "client_secret": "secret",
            "resource": ["https://api1.example.com", "https://api2.example.com"]
        }
        mock_gateway.visibility = "public"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        vault_data = {
            "token": {"access_token": "old_token", "scopes": ["read"]},
            "user_id": "user123"
        }

        with patch("mcpgateway.services.token_backends.vault_backend.OAuthManager") as mock_oauth_class:
            mock_oauth = AsyncMock()
            mock_oauth.refresh_token.return_value = {
                "access_token": "new_token",
                "expires_in": 3600
            }
            mock_oauth_class.return_value = mock_oauth

            with patch.object(backend, "store_tokens", new_callable=AsyncMock):
                result = await backend._refresh_access_token(
                    gateway_id="gw-1",
                    team_id="team1",
                    app_user_email="user@test.com",
                    refresh_token="refresh_token",
                    vault_data=vault_data
                )

                assert result == "new_token"

    @pytest.mark.asyncio
    async def test_refresh_token_invalid_error_clears_tokens(self):
        """Test that invalid/expired refresh token errors trigger revocation."""
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
        mock_gateway.oauth_config = {"client_id": "test", "client_secret": "secret"}
        mock_gateway.visibility = "public"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        vault_data = {
            "token": {"access_token": "old_token", "scopes": ["read"]},
            "user_id": "user123"
        }

        with patch("mcpgateway.services.token_backends.vault_backend.OAuthManager") as mock_oauth_class:
            mock_oauth = AsyncMock()
            mock_oauth.refresh_token.side_effect = Exception("invalid_grant: refresh token expired")
            mock_oauth_class.return_value = mock_oauth

            with patch.object(backend, "revoke_user_tokens", new_callable=AsyncMock) as mock_revoke:
                with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
                    result = await backend._refresh_access_token(
                        gateway_id="gw-1",
                        team_id="team1",
                        app_user_email="user@test.com",
                        refresh_token="refresh_token",
                        vault_data=vault_data
                    )

                    assert result is None
                    mock_revoke.assert_called_once()
                    warning_calls = [call for call in mock_logger.warning.call_args_list
                                   if "invalid/expired" in str(call)]
                    assert len(warning_calls) > 0


class TestVaultTokenBackendExpiredTokenHandling:
    """Test suite for expired token detection and refresh."""

    @pytest.mark.asyncio
    async def test_get_user_token_expired_with_refresh(self):
        """Test that expired token triggers refresh when refresh_token exists."""
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

        # Mock expired token in Vault
        past_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        vault_response = {
            "data": {
                "data": {
                    "email": "user@example.com",
                    "team_id": "team1",
                    "mcp_url": "https://mcp.example.com",
                    "token": {
                        "access_token": "expired_token",
                        "refresh_token": "refresh_token_value",
                        "scopes": ["read"],
                    },
                    "user_id": "oauth-user-456",
                    "token_type": "Bearer",
                    "expires_at": past_time,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        }

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = vault_response

            with patch.object(backend, "_refresh_access_token", new_callable=AsyncMock) as mock_refresh:
                mock_refresh.return_value = "refreshed_token"

                token = await backend.get_user_token(
                    gateway_id="gw-123",
                    team_id="team1",
                    app_user_email="user@example.com",
                    threshold_seconds=0,
                )

                assert token == "refreshed_token"
                mock_refresh.assert_called_once()


    @pytest.mark.asyncio
    async def test_get_user_token_expired_no_refresh_token(self):
        """Test that expired token without refresh_token returns None."""
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

        # Mock expired token without refresh_token
        past_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        vault_response = {
            "data": {
                "data": {
                    "email": "user@example.com",
                    "team_id": "team1",
                    "mcp_url": "https://mcp.example.com",
                    "token": {
                        "access_token": "expired_token",
                        "refresh_token": None,  # No refresh token
                        "scopes": ["read"],
                    },
                    "user_id": "oauth-user-456",
                    "token_type": "Bearer",
                    "expires_at": past_time,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        }

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = vault_response

            token = await backend.get_user_token(
                gateway_id="gw-123",
                team_id="team1",
                app_user_email="user@example.com",
                threshold_seconds=0,
            )

            assert token is None
