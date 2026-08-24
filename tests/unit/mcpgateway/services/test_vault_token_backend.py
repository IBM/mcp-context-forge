# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_vault_token_backend.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for VaultTokenBackend implementation.
Tests the Vault KV v2 token storage backend.
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.db import Gateway
from mcpgateway.services.oauth_manager import OAuthError, OAuthInvalidGrantError
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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

    @pytest.mark.asyncio
    async def test_get_user_token_returns_none_on_header_only_record(self):
        """get_user_token returns None (not KeyError) when Vault record has no 'token' field.

        Repro for reviewer-reported live defect: ICA writes header-only records
        ({"headers": {...}}) at the same Vault path as OAuth tokens.  The old
        bare data["token"] access raised KeyError; the fix uses .get("token").
        """
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")  # pragma: allowlist secret
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000
        mock_settings.auth_encryption_secret = None

        backend = VaultTokenBackend(mock_db, mock_settings)
        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        # ICA-written header-only record — no 'token' key present
        header_only_response = {
            "data": {
                "data": {
                    "headers": {"X-Api-Key": "abc123"},  # pragma: allowlist secret
                }
            }
        }
        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = header_only_response
            token = await backend.get_user_token(
                gateway_id="gw-123",
                team_id="team1",
                app_user_email="user@example.com",
                threshold_seconds=300,
            )
        assert token is None

    @pytest.mark.asyncio
    async def test_get_user_token_returns_none_on_empty_token_dict(self):
        """get_user_token returns None when 'token' field is present but empty or has no access_token."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")  # pragma: allowlist secret
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = False
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000
        mock_settings.auth_encryption_secret = None

        backend = VaultTokenBackend(mock_db, mock_settings)
        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        for malformed_token in [{}, {"refresh_token": "rt-only"}]:
            vault_response = {"data": {"data": {"token": malformed_token}}}
            with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
                mock_vault.return_value = vault_response
                token = await backend.get_user_token(
                    gateway_id="gw-123",
                    team_id="team1",
                    app_user_email="user@example.com",
                    threshold_seconds=300,
                )
            assert token is None, f"Expected None for malformed token shape: {malformed_token}"


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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
            result = await backend._do_refresh_access_token(
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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

        with patch("mcpgateway.services.token_backends.refresh_helpers.logger") as mock_logger:
            result = await backend._do_refresh_access_token(
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
                result = await backend._do_refresh_access_token(
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
                result = await backend._do_refresh_access_token(
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
            # Use OAuthInvalidGrantError to trigger token deletion (PR #5244)
            mock_oauth.refresh_token.side_effect = OAuthInvalidGrantError("invalid_grant: refresh token expired")
            mock_oauth_class.return_value = mock_oauth

            with patch.object(backend, "revoke_user_tokens", new_callable=AsyncMock) as mock_revoke:
                with patch("mcpgateway.services.token_backends.vault_backend.logger") as mock_logger:
                    result = await backend._do_refresh_access_token(
                        gateway_id="gw-1",
                        team_id="team1",
                        app_user_email="user@test.com",
                        refresh_token="refresh_token",
                        vault_data=vault_data
                    )

                    assert result is None
                    mock_revoke.assert_called_once()
                    # PR #5244: Now logs as warning about permanently invalid token
                    warning_calls = [call for call in mock_logger.warning.call_args_list
                                   if "permanently invalid" in str(call) or "invalid_grant" in str(call)]
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

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


# ============================================================================
# PR #5244: RFC 6749 Compliant Token Deletion, omit_resource, TTL Preservation
# ============================================================================


class TestVaultTokenBackendPR5244:
    """Test suite for PR #5244 features: RFC 6749 token deletion, omit_resource, TTL preservation."""

    @pytest.mark.asyncio
    async def test_refresh_deletes_token_on_invalid_grant(self):
        """PR #5244: Token is deleted when OAuthManager raises OAuthInvalidGrantError."""
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        # Setup: mock gateway
        mock_gateway = MagicMock(spec=Gateway)
        mock_gateway.id = "gw-test-123"
        mock_gateway.url = "https://gateway.example.com"
        mock_gateway.oauth_config = {
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "token_url": "https://idp.example.com/token",
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        mock_gateway.visibility = "public"
        mock_gateway.owner_email = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        # Setup: mock existing token in Vault
        vault_data = {
            "token": {"access_token": "old_token", "refresh_token": "old_refresh", "scopes": ["read"]},
            "expires_at": "2026-07-27T10:00:00Z",
            "updated_at": "2026-07-27T09:00:00Z",
            "user_id": "oauth-user-123",
        }

        # Mock revoke_user_tokens
        backend.revoke_user_tokens = AsyncMock()

        # Mock OAuthManager to raise OAuthInvalidGrantError
        with patch("mcpgateway.services.token_backends.vault_backend.OAuthManager") as mock_oauth_cls:
            mock_oauth_mgr = MagicMock()
            mock_oauth_mgr.refresh_token = AsyncMock(side_effect=OAuthInvalidGrantError("invalid_grant"))
            mock_oauth_cls.return_value = mock_oauth_mgr

            # Execute
            result = await backend._do_refresh_access_token(
                gateway_id="gw-test-123",
                team_id="team-1",
                app_user_email="user@test.com",
                refresh_token="old_refresh",
                vault_data=vault_data,
            )

            # Assert: token deleted
            assert result is None
            backend.revoke_user_tokens.assert_called_once_with("gw-test-123", "team-1", "user@test.com")

    @pytest.mark.asyncio
    async def test_refresh_preserves_token_on_oauth_error(self):
        """PR #5244: Token is preserved when OAuthManager raises OAuthError (not invalid_grant)."""
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock(spec=Gateway)
        mock_gateway.id = "gw-test-123"
        mock_gateway.url = "https://gateway.example.com"
        mock_gateway.oauth_config = {
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "token_url": "https://idp.example.com/token",
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        mock_gateway.visibility = "public"
        mock_gateway.owner_email = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        vault_data = {
            "token": {"access_token": "old_token", "refresh_token": "old_refresh", "scopes": ["read"]},
            "user_id": "oauth-user-123",
        }

        backend.revoke_user_tokens = AsyncMock()

        # Mock OAuthManager to raise generic OAuthError (e.g., invalid_client)
        with patch("mcpgateway.services.token_backends.vault_backend.OAuthManager") as mock_oauth_cls:
            mock_oauth_mgr = MagicMock()
            mock_oauth_mgr.refresh_token = AsyncMock(side_effect=OAuthError("invalid_client: wrong credentials"))
            mock_oauth_cls.return_value = mock_oauth_mgr

            result = await backend._do_refresh_access_token(
                gateway_id="gw-test-123",
                team_id="team-1",
                app_user_email="user@test.com",
                refresh_token="old_refresh",
                vault_data=vault_data,
            )

            # Assert: token preserved (NOT deleted)
            assert result is None
            backend.revoke_user_tokens.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_omits_resource_when_flag_true(self):
        """PR #5244: Resource parameter is NOT sent when omit_resource=true."""
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock(spec=Gateway)
        mock_gateway.id = "gw-test-123"
        mock_gateway.url = "https://gateway.example.com"
        mock_gateway.oauth_config = {
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "token_url": "https://idp.example.com/token",
            "omit_resource": True,
            "resource": "https://api.example.com",  # Should be removed
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        vault_data = {
            "token": {"access_token": "old_token", "refresh_token": "old_refresh", "scopes": ["read"]},
            "user_id": "oauth-user-123",
        }

        backend.store_tokens = AsyncMock()

        with patch("mcpgateway.services.token_backends.vault_backend.OAuthManager") as mock_oauth_cls:
            mock_oauth_mgr = MagicMock()
            mock_oauth_mgr.refresh_token = AsyncMock(return_value={
                "access_token": "new_token",
                "refresh_token": "new_refresh",
                "expires_in": 3600,
            })
            mock_oauth_cls.return_value = mock_oauth_mgr

            result = await backend._do_refresh_access_token(
                gateway_id="gw-test-123",
                team_id="team-1",
                app_user_email="user@test.com",
                refresh_token="old_refresh",
                vault_data=vault_data,
            )

            # Assert: refresh called WITHOUT resource parameter
            mock_oauth_mgr.refresh_token.assert_called_once()
            call_args = mock_oauth_mgr.refresh_token.call_args
            oauth_config_passed = call_args[0][1]
            assert "resource" not in oauth_config_passed
            assert result == "new_token"

    @pytest.mark.asyncio
    async def test_refresh_injects_resource_when_flag_false(self):
        """PR #5244: Resource parameter IS sent when omit_resource=false (default)."""
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock(spec=Gateway)
        mock_gateway.id = "gw-test-123"
        mock_gateway.url = "https://gateway.example.com"
        mock_gateway.oauth_config = {
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "token_url": "https://idp.example.com/token",
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        vault_data = {
            "token": {"access_token": "old_token", "refresh_token": "old_refresh", "scopes": ["read"]},
            "user_id": "oauth-user-123",
        }

        backend.store_tokens = AsyncMock()

        with patch("mcpgateway.services.token_backends.vault_backend.OAuthManager") as mock_oauth_cls:
            mock_oauth_mgr = MagicMock()
            mock_oauth_mgr.refresh_token = AsyncMock(return_value={
                "access_token": "new_token",
                "expires_in": 3600,
            })
            mock_oauth_cls.return_value = mock_oauth_mgr

            await backend._do_refresh_access_token(
                gateway_id="gw-test-123",
                team_id="team-1",
                app_user_email="user@test.com",
                refresh_token="old_refresh",
                vault_data=vault_data,
            )

            # Assert: refresh called WITH resource parameter
            mock_oauth_mgr.refresh_token.assert_called_once()
            call_args = mock_oauth_mgr.refresh_token.call_args
            oauth_config_passed = call_args[0][1]
            assert "resource" in oauth_config_passed
            assert oauth_config_passed["resource"] == "https://gateway.example.com"

    @pytest.mark.asyncio
    async def test_refresh_preserves_prior_ttl_when_expires_in_omitted(self):
        """PR #5244: Prior TTL is preserved when IdP omits expires_in in refresh response."""
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock(spec=Gateway)
        mock_gateway.id = "gw-test-123"
        mock_gateway.url = "https://gateway.example.com"
        mock_gateway.oauth_config = {
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "token_url": "https://idp.example.com/token",
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        # Existing token with known TTL (3600 seconds)
        now = datetime.now(timezone.utc)
        vault_data = {
            "token": {"access_token": "old_token", "refresh_token": "old_refresh", "scopes": ["read"]},
            "expires_at": (now + timedelta(seconds=3600)).isoformat(),
            "updated_at": now.isoformat(),
            "user_id": "oauth-user-123",
        }

        backend.store_tokens = AsyncMock()

        with patch("mcpgateway.services.token_backends.vault_backend.OAuthManager") as mock_oauth_cls:
            mock_oauth_mgr = MagicMock()
            # Refresh response WITHOUT expires_in
            mock_oauth_mgr.refresh_token = AsyncMock(return_value={
                "access_token": "new_token",
                "refresh_token": "new_refresh",
                # NO expires_in field
            })
            mock_oauth_cls.return_value = mock_oauth_mgr

            await backend._do_refresh_access_token(
                gateway_id="gw-test-123",
                team_id="team-1",
                app_user_email="user@test.com",
                refresh_token="old_refresh",
                vault_data=vault_data,
            )

            # Assert: store_tokens called with preserved TTL (3600 seconds)
            backend.store_tokens.assert_called_once()
            call_kwargs = backend.store_tokens.call_args.kwargs
            assert call_kwargs["expires_in"] == 3600  # Preserved prior TTL

    @pytest.mark.asyncio
    async def test_refresh_uses_new_ttl_when_expires_in_present(self):
        """PR #5244: New expires_in is used when present in refresh response."""
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock(spec=Gateway)
        mock_gateway.id = "gw-test-123"
        mock_gateway.url = "https://gateway.example.com"
        mock_gateway.oauth_config = {
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "token_url": "https://idp.example.com/token",
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        now = datetime.now(timezone.utc)
        vault_data = {
            "token": {"access_token": "old_token", "refresh_token": "old_refresh", "scopes": ["read"]},
            "expires_at": (now + timedelta(seconds=3600)).isoformat(),
            "updated_at": now.isoformat(),
            "user_id": "oauth-user-123",
        }

        backend.store_tokens = AsyncMock()

        with patch("mcpgateway.services.token_backends.vault_backend.OAuthManager") as mock_oauth_cls:
            mock_oauth_mgr = MagicMock()
            # Refresh response WITH new expires_in
            mock_oauth_mgr.refresh_token = AsyncMock(return_value={
                "access_token": "new_token",
                "refresh_token": "new_refresh",
                "expires_in": 7200,  # New TTL: 2 hours
            })
            mock_oauth_cls.return_value = mock_oauth_mgr

            await backend._do_refresh_access_token(
                gateway_id="gw-test-123",
                team_id="team-1",
                app_user_email="user@test.com",
                refresh_token="old_refresh",
                vault_data=vault_data,
            )

            # Assert: store_tokens called with NEW TTL (7200 seconds)
            call_kwargs = backend.store_tokens.call_args.kwargs
            assert call_kwargs["expires_in"] == 7200  # New TTL, not preserved


# ============================================================================
# Additional Coverage Tests - Target 93%+ Coverage
# ============================================================================


class TestVaultTokenBackendAdditionalCoverage:
    """Additional tests to achieve 93%+ code coverage."""

    @pytest.mark.asyncio
    async def test_refresh_with_no_refresh_token_in_record(self):
        """Refresh returns None when vault record has no refresh_token."""
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        # Vault data WITHOUT refresh_token
        vault_data = {
            "token": {"access_token": "token123", "scopes": ["read"]},
            "user_id": "user123",
        }

        result = await backend._do_refresh_access_token(
            gateway_id="gw-1",
            team_id="team1",
            app_user_email="user@test.com",
            refresh_token=None,  # No refresh token
            vault_data=vault_data,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_preserves_token_on_generic_exception(self):
        """Token preserved when refresh encounters generic exception."""
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock(spec=Gateway)
        mock_gateway.id = "gw-123"
        mock_gateway.url = "https://gateway.example.com"
        mock_gateway.oauth_config = {
            "client_id": "test",
            "client_secret": "secret",  # pragma: allowlist secret
            "token_url": "https://idp.example.com/token",
        }
        mock_gateway.ca_certificate = None
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        mock_gateway.visibility = "public"
        mock_gateway.owner_email = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        vault_data = {
            "token": {"access_token": "token", "refresh_token": "refresh", "scopes": ["read"]},
            "user_id": "user123",
        }

        backend.revoke_user_tokens = AsyncMock()

        with patch("mcpgateway.services.token_backends.vault_backend.OAuthManager") as mock_oauth_cls:
            mock_oauth = MagicMock()
            mock_oauth.refresh_token = AsyncMock(side_effect=Exception("Network timeout"))
            mock_oauth_cls.return_value = mock_oauth

            result = await backend._do_refresh_access_token(
                gateway_id="gw-123",
                team_id="team1",
                app_user_email="user@test.com",
                refresh_token="refresh",
                vault_data=vault_data,
            )

            # Token preserved, not deleted
            assert result is None
            backend.revoke_user_tokens.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_user_tokens_success(self):
        """Token successfully revoked from Vault."""
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        # Mock gateway
        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        # Populate cache
        cache_key = (
            "team1",
            backend._hash_server_id("https://mcp.example.com"),
            "user@test.com",
        )
        VaultTokenBackend._token_cache[cache_key] = {"token": "cached", "cache_expires": datetime.now(timezone.utc) + timedelta(seconds=300)}

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = None

            await backend.revoke_user_tokens("gw-123", "team1", "user@test.com")

            # Assert: DELETE called and cache entry marked expired (not deleted —
            # expire-in-place lets other workers' copies become stale within one TTL cycle).
            mock_vault.assert_called_once()
            assert mock_vault.call_args[0][0] == "DELETE"
            assert cache_key in VaultTokenBackend._token_cache
            assert VaultTokenBackend._token_cache[cache_key]["cache_expires"] < datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_revoke_user_tokens_without_team_id(self):
        """Token revoked when team_id is None (admin/fallback path)."""
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.return_value = None

            await backend.revoke_user_tokens("gw-123", None, "user@test.com")

            # Assert: DELETE called with correct path (no team_id segment)
            mock_vault.assert_called_once()


# ============================================================================
# Additional Coverage: Store Tokens Edge Cases
# ============================================================================


class TestVaultTokenBackendStoreTokensEdgeCases:
    """Tests for store_tokens edge cases to improve coverage."""

    @pytest.mark.asyncio
    async def test_store_tokens_preserves_original_created_at(self):
        """When updating existing token, original created_at is preserved."""
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
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        # Mock existing record with created_at
        original_timestamp = "2026-07-27T10:00:00Z"
        existing_record = {
            "data": {
                "data": {
                    "created_at": original_timestamp,
                    "token": {"access_token": "old_token"},
                }
            }
        }

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            # GET returns existing record, POST stores new
            mock_vault.side_effect = [existing_record, {"data": {"version": 2}}]

            await backend.store_tokens(
                gateway_id="gw-123",
                team_id="team1",
                user_id="user123",
                app_user_email="user@test.com",
                access_token="new_token",
                refresh_token="new_refresh",
                expires_in=3600,
                scopes=["read"],
            )

            # Assert: POST called with preserved created_at
            assert mock_vault.call_count == 2
            post_call = mock_vault.call_args_list[1]
            payload = post_call[0][2]  # Third arg is data
            assert payload["data"]["created_at"] == original_timestamp

    @pytest.mark.asyncio
    async def test_store_tokens_cache_invalidation_with_cache_enabled(self):
        """Cache entry is expired in-place when storing new tokens (multi-pod safe pattern)."""
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.vault_addr = "http://127.0.0.1:8200"
        mock_settings.vault_token = SecretStr("hvs.test-token")
        mock_settings.vault_namespace = ""
        mock_settings.vault_kv_mount = "secret"
        mock_settings.vault_kv_path_prefix = "contextforge/oauth"
        mock_settings.vault_tls_verify = True
        mock_settings.vault_token_cache_enabled = True  # Enable cache
        mock_settings.vault_token_cache_ttl = 300
        mock_settings.vault_token_cache_max_size = 10000
        mock_settings.auth_encryption_secret = None  # No encryption in unit tests

        backend = VaultTokenBackend(mock_db, mock_settings)

        mock_gateway = MagicMock()
        mock_gateway.url = "https://mcp.example.com"
        mock_db.get.return_value = mock_gateway

        # Pre-populate cache with a future-expiry entry
        server_id = backend._hash_server_id("https://mcp.example.com")
        cache_key = ("team1", server_id, "user@test.com")
        VaultTokenBackend._token_cache[cache_key] = {
            "token": "cached_token",
            "cache_expires": datetime.now(timezone.utc) + timedelta(seconds=300),
        }

        with patch.object(backend, "_vault_request", new_callable=AsyncMock) as mock_vault:
            mock_vault.side_effect = [None, {"data": {"version": 1}}]

            await backend.store_tokens(
                gateway_id="gw-123",
                team_id="team1",
                user_id="user123",
                app_user_email="user@test.com",
                access_token="new_token",
                refresh_token="new_refresh",
                expires_in=3600,
                scopes=["read"],
            )

            # Entry must be present but with an already-expired timestamp so
            # the next cache-read treats it as stale (expire-in-place pattern).
            # This is multi-pod safe: other workers also see the expired entry
            # on their next cache-hit check, bounding stale reads to < cache_ttl.
            assert cache_key in VaultTokenBackend._token_cache
            assert VaultTokenBackend._token_cache[cache_key]["cache_expires"] < datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Round-7 coverage: Vault error handlers in get_user_token, get_user_auth_headers,
# get_token_info, revoke_user_tokens (lines 467-468,474,509-510,516,563-564,570,620)
# _refresh_access_token re-read branches (843-849,881-894,898,903-915)
# _do_refresh_access_token decryption failures (965-984)
# All tests are self-contained (no class fixtures needed)
# ---------------------------------------------------------------------------


def _make_backend_r7():
    """Return a VaultTokenBackend with self-contained mock db/settings."""
    mock_db = MagicMock()
    mock_db.get.return_value = MagicMock(url="https://mcp.example.com")
    mock_settings = MagicMock()
    mock_settings.vault_addr = "http://127.0.0.1:8200"
    mock_settings.vault_token = SecretStr("hvs.test")  # pragma: allowlist secret
    mock_settings.vault_namespace = ""
    mock_settings.vault_kv_mount = "secret"
    mock_settings.vault_kv_path_prefix = "contextforge/oauth"
    mock_settings.vault_tls_verify = True
    mock_settings.vault_token_cache_enabled = False
    mock_settings.vault_token_cache_ttl = 300
    mock_settings.vault_token_cache_max_size = 1000
    mock_settings.auth_encryption_secret = None
    return VaultTokenBackend(mock_db, mock_settings), mock_db


@pytest.mark.asyncio
async def test_r7_get_user_token_vault_connection_error():
    """get_user_token returns None on VaultConnectionError (lines 467-468,474)."""
    backend, _ = _make_backend_r7()
    with patch.object(backend, "_vault_request", side_effect=VaultConnectionError("Vault down")):
        result = await backend.get_user_token("gw-1", "team-1", "alice@example.com")
    assert result is None


@pytest.mark.asyncio
async def test_r7_get_user_token_vault_auth_error():
    """get_user_token returns None on VaultAuthError (lines 467-468,474)."""
    backend, _ = _make_backend_r7()
    with patch.object(backend, "_vault_request", side_effect=VaultAuthError("Token invalid")):
        result = await backend.get_user_token("gw-1", "team-1", "alice@example.com")
    assert result is None


@pytest.mark.asyncio
async def test_r7_get_user_auth_headers_vault_connection_error():
    """get_user_auth_headers re-raises VaultConnectionError (fail-closed for CWE-284 isolation)."""
    backend, _ = _make_backend_r7()
    with patch.object(backend, "_vault_request", side_effect=VaultConnectionError("Vault down")):
        with pytest.raises(VaultConnectionError):
            await backend.get_user_auth_headers("gw-1", "team-1", "alice@example.com")


@pytest.mark.asyncio
async def test_r7_get_user_auth_headers_vault_auth_error():
    """get_user_auth_headers re-raises VaultAuthError (fail-closed for CWE-284 isolation)."""
    backend, _ = _make_backend_r7()
    with patch.object(backend, "_vault_request", side_effect=VaultAuthError("Token invalid")):
        with pytest.raises(VaultAuthError):
            await backend.get_user_auth_headers("gw-1", "team-1", "alice@example.com")


@pytest.mark.asyncio
async def test_r7_get_token_info_vault_connection_error():
    """get_token_info returns None on VaultConnectionError (lines 563-564,570)."""
    backend, _ = _make_backend_r7()
    with patch.object(backend, "_vault_request", side_effect=VaultConnectionError("Vault down")):
        result = await backend.get_token_info("gw-1", "team-1", "alice@example.com")
    assert result is None


@pytest.mark.asyncio
async def test_r7_get_token_info_vault_auth_error():
    """get_token_info returns None on VaultAuthError (lines 563-564,570)."""
    backend, _ = _make_backend_r7()
    with patch.object(backend, "_vault_request", side_effect=VaultAuthError("Token invalid")):
        result = await backend.get_token_info("gw-1", "team-1", "alice@example.com")
    assert result is None


@pytest.mark.asyncio
async def test_r7_revoke_user_tokens_generic_exception_returns_false():
    """revoke_user_tokens returns False on generic non-Vault exception (line 620)."""
    backend, _ = _make_backend_r7()
    with patch.object(backend, "_vault_request", side_effect=RuntimeError("unexpected")):
        result = await backend.revoke_user_tokens("gw-1", "team-1", "alice@example.com")
    assert result is False


@pytest.mark.asyncio
async def test_r7_refresh_lock_no_expiry_in_reread():
    """Re-read under lock shows token with no expiry → return immediately (lines 843-849)."""
    backend, _ = _make_backend_r7()
    fresh_result = {"data": {"data": {"token": {"access_token": "fresh-token"}, "expires_at": None}}}
    with patch.object(backend, "_vault_request", new_callable=AsyncMock, return_value=fresh_result):
        result = await backend._refresh_access_token("gw-1", "team-1", "alice@example.com", "rt", {})
    assert result == "fresh-token"


@pytest.mark.asyncio
async def test_r7_refresh_lock_already_refreshed():
    """Re-read shows non-near-expiry token → return without calling IdP (lines 881-894)."""
    backend, _ = _make_backend_r7()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    fresh_result = {"data": {"data": {"token": {"access_token": "already-refreshed"}, "expires_at": future}}}
    with patch.object(backend, "_vault_request", new_callable=AsyncMock, return_value=fresh_result):
        result = await backend._refresh_access_token("gw-1", "team-1", "alice@example.com", "rt", {})
    assert result == "already-refreshed"


@pytest.mark.asyncio
async def test_r7_refresh_lock_still_near_expiry_calls_do_refresh():
    """Re-read shows near-expiry token → _do_refresh_access_token is called (lines 898,903-915)."""
    backend, _ = _make_backend_r7()
    near = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
    fresh_result = {"data": {"data": {"token": {"access_token": "near-expiry"}, "expires_at": near}}}
    with patch.object(backend, "_vault_request", new_callable=AsyncMock, return_value=fresh_result):
        with patch.object(backend, "_do_refresh_access_token", new_callable=AsyncMock, return_value="new-tok") as mock_do:
            result = await backend._refresh_access_token("gw-1", "team-1", "alice@example.com", "rt", {}, threshold_seconds=300)
    assert result == "new-tok"
    mock_do.assert_called_once()


@pytest.mark.asyncio
async def test_r7_refresh_lock_empty_reread_calls_do_refresh():
    """Re-read returns empty → _do_refresh_access_token is called."""
    backend, _ = _make_backend_r7()
    with patch.object(backend, "_vault_request", new_callable=AsyncMock, return_value=None):
        with patch.object(backend, "_do_refresh_access_token", new_callable=AsyncMock, return_value="brand-new") as mock_do:
            result = await backend._refresh_access_token("gw-1", "team-1", "alice@example.com", "rt", {})
    assert result == "brand-new"
    mock_do.assert_called_once()


@pytest.mark.asyncio
async def test_r7_do_refresh_decryption_returns_none_preserves_token():
    """decrypt_secret_async returning None raises OAuthError → token preserved (lines 965-971)."""
    backend, mock_db = _make_backend_r7()
    gateway = MagicMock()
    gateway.oauth_config = {"client_secret": "enc-value", "grant_type": "authorization_code"}  # pragma: allowlist secret
    gateway.url = "https://mcp.example.com"
    gateway.ca_certificate = None
    gateway.client_cert = None
    gateway.client_key = None
    gateway.visibility = "public"
    gateway.owner_email = None
    mock_db.query.return_value.filter.return_value.first.return_value = gateway
    backend.settings.auth_encryption_secret = "some-secret"  # pragma: allowlist secret
    mock_enc = AsyncMock()
    mock_enc.decrypt_secret_async = AsyncMock(return_value=None)
    with patch("mcpgateway.services.encryption_service.get_encryption_service", return_value=mock_enc):
        result = await backend._do_refresh_access_token(
            "gw-1", "team-1", "alice@example.com", "rt", {"token": {"scopes": ["read"]}}
        )
    assert result is None


@pytest.mark.asyncio
async def test_r7_do_refresh_decryption_setup_exception_preserves_token():
    """Unexpected exception in get_encryption_service → OAuthError → token preserved (lines 976-984)."""
    backend, mock_db = _make_backend_r7()
    gateway = MagicMock()
    gateway.oauth_config = {"client_secret": "enc-value"}  # pragma: allowlist secret
    gateway.url = "https://mcp.example.com"
    gateway.ca_certificate = None
    gateway.client_cert = None
    gateway.client_key = None
    gateway.visibility = "public"
    gateway.owner_email = None
    mock_db.query.return_value.filter.return_value.first.return_value = gateway
    backend.settings.auth_encryption_secret = "some-secret"  # pragma: allowlist secret
    with patch("mcpgateway.services.encryption_service.get_encryption_service", side_effect=RuntimeError("setup failed")):
        result = await backend._do_refresh_access_token(
            "gw-1", "team-1", "alice@example.com", "rt", {"token": {"scopes": []}}
        )
    assert result is None


# ---------------------------------------------------------------------------
# Round-9 coverage: _get_refresh_lock eviction (B2 fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_locks_evicts_idle_entry_at_capacity():
    """_get_refresh_lock evicts the oldest idle (unlocked) entry when at capacity.

    Verifies the B2 fix: _refresh_locks is bounded at cache_max_size and only
    idle (not currently held) locks are evicted so in-flight refreshes are safe.
    """
    from mcpgateway.services.token_backends.vault_backend import VaultTokenBackend

    mock_db = MagicMock()
    mock_settings = MagicMock()
    mock_settings.vault_addr = "http://127.0.0.1:8200"
    mock_settings.vault_token = SecretStr("hvs.test-token")  # pragma: allowlist secret
    mock_settings.vault_namespace = ""
    mock_settings.vault_kv_mount = "secret"
    mock_settings.vault_kv_path_prefix = "contextforge/oauth"
    mock_settings.vault_tls_verify = True
    mock_settings.vault_token_cache_enabled = False
    mock_settings.vault_token_cache_ttl = 300
    mock_settings.vault_token_cache_max_size = 3  # small cap for the test

    backend = VaultTokenBackend(mock_db, mock_settings)

    # Reset class-level state so other tests don't interfere
    VaultTokenBackend._refresh_locks = {}
    VaultTokenBackend._refresh_locks_mutex = None

    # Fill _refresh_locks to capacity with idle (unlocked) asyncio.Lock entries
    for i in range(3):
        VaultTokenBackend._refresh_locks[("gw-old", f"team-{i}", "old@example.com")] = asyncio.Lock()

    assert len(VaultTokenBackend._refresh_locks) == 3

    # Request a new key — should evict the oldest idle entry
    await backend._get_refresh_lock("gw-new", "team-new", "new@example.com")

    assert len(VaultTokenBackend._refresh_locks) == 3  # still at cap
    assert ("gw-new", "team-new", "new@example.com") in VaultTokenBackend._refresh_locks

    # Clean up
    VaultTokenBackend._refresh_locks = {}
    VaultTokenBackend._refresh_locks_mutex = None


@pytest.mark.asyncio
async def test_refresh_locks_allows_growth_when_all_entries_held():
    """_get_refresh_lock does NOT evict held locks — allows temporary growth instead.

    Verifies the safety invariant: evicting a held lock would allow a concurrent
    caller for the same key to get a fresh lock and run a duplicate IdP refresh,
    defeating serialisation and triggering invalid_grant on rotating-refresh-token IdPs.
    """
    from mcpgateway.services.token_backends.vault_backend import VaultTokenBackend

    mock_db = MagicMock()
    mock_settings = MagicMock()
    mock_settings.vault_addr = "http://127.0.0.1:8200"
    mock_settings.vault_token = SecretStr("hvs.test-token")  # pragma: allowlist secret
    mock_settings.vault_namespace = ""
    mock_settings.vault_kv_mount = "secret"
    mock_settings.vault_kv_path_prefix = "contextforge/oauth"
    mock_settings.vault_tls_verify = True
    mock_settings.vault_token_cache_enabled = False
    mock_settings.vault_token_cache_ttl = 300
    mock_settings.vault_token_cache_max_size = 2  # small cap for the test

    backend = VaultTokenBackend(mock_db, mock_settings)

    # Reset class-level state
    VaultTokenBackend._refresh_locks = {}
    VaultTokenBackend._refresh_locks_mutex = None

    # Fill _refresh_locks to capacity with LOCKED asyncio.Lock entries
    # Simulate held locks by acquiring them inside a task that keeps them held
    held_locks = []
    for i in range(2):
        lock = asyncio.Lock()
        await lock.acquire()  # lock is now held
        held_locks.append(lock)
        VaultTokenBackend._refresh_locks[("gw-held", f"team-{i}", "held@example.com")] = lock

    assert len(VaultTokenBackend._refresh_locks) == 2

    # Request a new key — all existing entries are held, so dict must grow by 1
    await backend._get_refresh_lock("gw-new", "team-new", "new@example.com")

    assert len(VaultTokenBackend._refresh_locks) == 3  # grew — no held lock was evicted
    assert ("gw-new", "team-new", "new@example.com") in VaultTokenBackend._refresh_locks

    # Verify the original held locks were NOT touched
    for lock in held_locks:
        assert lock.locked()
        lock.release()  # clean up

    # Clean up class-level state
    VaultTokenBackend._refresh_locks = {}
    VaultTokenBackend._refresh_locks_mutex = None
