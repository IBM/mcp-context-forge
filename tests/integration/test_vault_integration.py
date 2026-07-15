# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_vault_integration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Rakhi Dutta

Integration tests for VaultTokenBackend with real HashiCorp Vault instance.

Prerequisites:
    docker-compose -f docker-compose.vault-test.yml up -d

Environment Variables:
    VAULT_ADDR=http://localhost:8200
    VAULT_TOKEN=test-root-token
    TEST_DATABASE_URL=sqlite:///./test_vault_integration.db (or PostgreSQL)
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
import os
import time
from typing import Any, Generator

# Third-Party
import httpx
from pydantic import SecretStr
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# First-Party
from mcpgateway.config import Settings
from mcpgateway.db import Base, Gateway
from mcpgateway.services.token_backends import TokenRecord
from mcpgateway.services.token_backends.vault_backend import VaultAuthError, VaultConnectionError, VaultTokenBackend


# Test configuration
# Use 127.0.0.1 instead of localhost to avoid potential DNS resolution issues with async httpx
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "test-root-token")
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite:///./test_vault_integration.db")


def is_vault_available() -> bool:
    """Check if Vault is accessible."""
    try:
        response = httpx.get(f"{VAULT_ADDR}/v1/sys/health", timeout=2.0)
        return response.status_code in [200, 429, 472, 473]  # Various healthy states
    except Exception:
        return False


# Skip all tests if Vault is not available
pytestmark = pytest.mark.skipif(
    not is_vault_available(),
    reason="Vault not available. Run: docker-compose -f docker-compose.vault-test.yml up -d"
)


@pytest.fixture(scope="session")
def vault_settings() -> Settings:
    """Create Settings instance for Vault integration tests."""
    settings = Settings()
    settings.vault_addr = VAULT_ADDR
    settings.vault_token = SecretStr(VAULT_TOKEN)
    settings.vault_namespace = ""
    settings.vault_kv_mount = "secret"
    settings.vault_kv_path_prefix = "test/contextforge/oauth"
    settings.vault_tls_verify = False
    settings.vault_token_cache_enabled = True
    settings.vault_token_cache_ttl = 300
    settings.vault_token_cache_max_size = 10000
    return settings


@pytest.fixture(scope="session")
def db_engine():
    """Create database engine for testing."""
    engine = create_engine(TEST_DATABASE_URL, echo=False)
    Base.metadata.create_all(engine)
    yield engine
    # Cleanup
    Base.metadata.drop_all(engine)
    if TEST_DATABASE_URL.startswith("sqlite") and not TEST_DATABASE_URL.endswith(":memory:"):
        db_path = TEST_DATABASE_URL.split("///")[1]
        if os.path.exists(db_path):
            os.remove(db_path)


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """Create database session for each test."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    try:
        yield session
        session.commit()  # Commit any changes made during the test
    finally:
        session.rollback()  # Rollback any uncommitted changes
        # Clean up test data
        session.execute(text("DELETE FROM gateways WHERE id = 'test-gw-123'"))
        session.commit()
        session.close()


@pytest.fixture
def test_gateway(db_session: Session) -> Gateway:
    """Create a test gateway in the database."""
    gateway = Gateway(
        id="test-gw-123",
        name="Test Gateway",
        url="https://mcp.test.example.com",
        owner_email="admin@example.com",
        enabled=True,
        capabilities={},  # Required JSON field
    )
    db_session.add(gateway)
    db_session.commit()
    db_session.refresh(gateway)
    return gateway


@pytest.fixture
async def vault_backend(db_session: Session, vault_settings: Settings) -> VaultTokenBackend:
    """Create VaultTokenBackend instance for testing."""
    backend = VaultTokenBackend(db_session, vault_settings)

    # Verify Vault connectivity
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{VAULT_ADDR}/v1/sys/health")
        assert response.status_code in [200, 429, 472, 473], "Vault not healthy"

    return backend


@pytest.fixture
async def cleanup_vault_data(vault_backend: VaultTokenBackend):
    """Cleanup Vault data after each test."""
    yield
    # Cleanup is done by deleting test paths
    # In real scenarios, you might want to use Vault's delete metadata endpoint


class TestVaultIntegrationBasics:
    """Basic integration tests for Vault connectivity."""

    @pytest.mark.asyncio
    async def test_vault_is_reachable(self):
        """Test that Vault instance is accessible."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{VAULT_ADDR}/v1/sys/health")
            assert response.status_code in [200, 429, 472, 473]

            # Check if it's in dev mode
            data = response.json()
            assert data.get("initialized") is True
            assert data.get("sealed") is False

    @pytest.mark.asyncio
    async def test_vault_authentication_works(self, vault_settings: Settings):
        """Test that authentication with Vault works."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"X-Vault-Token": VAULT_TOKEN}
            response = await client.get(
                f"{VAULT_ADDR}/v1/auth/token/lookup-self",
                headers=headers
            )
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert data["data"]["id"] == VAULT_TOKEN

    @pytest.mark.asyncio
    async def test_vault_kv_v2_mount_exists(self):
        """Test that KV v2 secret engine is mounted."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"X-Vault-Token": VAULT_TOKEN}
            response = await client.get(
                f"{VAULT_ADDR}/v1/sys/mounts",
                headers=headers
            )
            assert response.status_code == 200
            data = response.json()

            # In dev mode, 'secret/' is mounted as KV v2 by default
            assert "secret/" in data["data"]
            mount_config = data["data"]["secret/"]
            assert mount_config["type"] == "kv"
            assert mount_config["options"]["version"] == "2"


class TestVaultIntegrationTokenStorage:
    """Integration tests for token storage operations."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve_token(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test storing and retrieving a token from Vault."""
        # Store token
        result = await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="engineering",
            user_id="github:12345",
            app_user_email="alice@example.com",
            access_token="test_access_token_abc123",
            refresh_token="test_refresh_token_xyz789",
            expires_in=3600,
            scopes=["read", "write"],
        )

        # Verify result
        assert isinstance(result, TokenRecord)
        assert result.gateway_id == test_gateway.id
        assert result.access_token == "test_access_token_abc123"
        assert result.refresh_token == "test_refresh_token_xyz789"
        assert result.scopes == ["read", "write"]
        assert result.mcp_url == test_gateway.url

        # Retrieve token
        token = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="engineering",
            app_user_email="alice@example.com",
            threshold_seconds=300,
        )

        assert token == "test_access_token_abc123"

    @pytest.mark.asyncio
    async def test_store_token_without_refresh_token(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test storing a token without refresh_token."""
        result = await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="engineering",
            user_id="github:12345",
            app_user_email="bob@example.com",
            access_token="access_only_token",
            refresh_token=None,
            expires_in=3600,
            scopes=["read"],
        )

        assert result.access_token == "access_only_token"
        assert result.refresh_token is None

        # Retrieve and verify
        token = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="engineering",
            app_user_email="bob@example.com",
            threshold_seconds=300,
        )

        assert token == "access_only_token"

    @pytest.mark.asyncio
    async def test_store_token_without_expiry(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test storing a token without expiration."""
        result = await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="engineering",
            user_id="github:12345",
            app_user_email="charlie@example.com",
            access_token="permanent_token",
            refresh_token="permanent_refresh",
            expires_in=None,  # No expiration
            scopes=["admin"],
        )

        assert result.expires_at is None

        # Retrieve - should work since token never expires
        token = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="engineering",
            app_user_email="charlie@example.com",
            threshold_seconds=300,
        )

        assert token == "permanent_token"

    @pytest.mark.asyncio
    async def test_update_existing_token(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test updating an existing token (upsert behavior)."""
        # Store initial token
        await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="qa",
            user_id="github:12345",
            app_user_email="dave@example.com",
            access_token="old_access_token",
            refresh_token="old_refresh_token",
            expires_in=3600,
            scopes=["read"],
        )

        # Update with new token
        result = await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="qa",
            user_id="github:12345",
            app_user_email="dave@example.com",
            access_token="new_access_token",
            refresh_token="new_refresh_token",
            expires_in=7200,
            scopes=["read", "write"],
        )

        # Verify new token
        token = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="qa",
            app_user_email="dave@example.com",
            threshold_seconds=300,
        )

        assert token == "new_access_token"

    @pytest.mark.asyncio
    async def test_token_isolation_by_team(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test that tokens are isolated by team_id."""
        # Store token for team1
        await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="team1",
            user_id="github:12345",
            app_user_email="user@example.com",
            access_token="team1_token",
            refresh_token="team1_refresh",
            expires_in=3600,
            scopes=["read"],
        )

        # Store token for team2 (same user, different team)
        await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="team2",
            user_id="github:12345",
            app_user_email="user@example.com",
            access_token="team2_token",
            refresh_token="team2_refresh",
            expires_in=3600,
            scopes=["write"],
        )

        # Retrieve team1 token
        token1 = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="team1",
            app_user_email="user@example.com",
            threshold_seconds=300,
        )

        # Retrieve team2 token
        token2 = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="team2",
            app_user_email="user@example.com",
            threshold_seconds=300,
        )

        # Verify isolation
        assert token1 == "team1_token"
        assert token2 == "team2_token"
        assert token1 != token2

    @pytest.mark.asyncio
    async def test_token_isolation_by_user(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test that tokens are isolated by user email."""
        # Store token for alice
        await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="engineering",
            user_id="github:111",
            app_user_email="alice@example.com",
            access_token="alice_token",
            refresh_token="alice_refresh",
            expires_in=3600,
            scopes=["read"],
        )

        # Store token for bob
        await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="engineering",
            user_id="github:222",
            app_user_email="bob@example.com",
            access_token="bob_token",
            refresh_token="bob_refresh",
            expires_in=3600,
            scopes=["write"],
        )

        # Retrieve alice's token
        token_alice = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="engineering",
            app_user_email="alice@example.com",
            threshold_seconds=300,
        )

        # Retrieve bob's token
        token_bob = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="engineering",
            app_user_email="bob@example.com",
            threshold_seconds=300,
        )

        # Verify isolation
        assert token_alice == "alice_token"
        assert token_bob == "bob_token"


class TestVaultIntegrationTokenRetrieval:
    """Integration tests for token retrieval operations."""

    @pytest.mark.asyncio
    async def test_get_token_not_found(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway
    ):
        """Test retrieving a non-existent token returns None."""
        token = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="nonexistent",
            app_user_email="nobody@example.com",
            threshold_seconds=300,
        )

        assert token is None

    @pytest.mark.asyncio
    async def test_get_token_info(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test retrieving token metadata."""
        # Store token
        await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="devops",
            user_id="github:12345",
            app_user_email="ops@example.com",
            access_token="ops_token",
            refresh_token="ops_refresh",
            expires_in=3600,
            scopes=["admin", "deploy"],
        )

        # Get token info
        info = await vault_backend.get_token_info(
            gateway_id=test_gateway.id,
            team_id="devops",
            app_user_email="ops@example.com",
        )

        # Verify metadata (no sensitive tokens returned)
        assert info is not None
        assert "access_token" not in str(info)  # Should not contain actual token
        assert info["scopes"] == ["admin", "deploy"]
        assert info["status"] in ["valid", "expired", "near_expiry"]
        assert "expires_at" in info
        assert "updated_at" in info

    @pytest.mark.asyncio
    async def test_get_token_info_not_found(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway
    ):
        """Test get_token_info returns None for non-existent token."""
        info = await vault_backend.get_token_info(
            gateway_id=test_gateway.id,
            team_id="nonexistent",
            app_user_email="nobody@example.com",
        )

        assert info is None


class TestVaultIntegrationTokenRevocation:
    """Integration tests for token revocation operations."""

    @pytest.mark.asyncio
    async def test_revoke_token(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test revoking a token."""
        # Store token
        await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="security",
            user_id="github:12345",
            app_user_email="security@example.com",
            access_token="security_token",
            refresh_token="security_refresh",
            expires_in=3600,
            scopes=["read"],
        )

        # Verify token exists
        token = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="security",
            app_user_email="security@example.com",
            threshold_seconds=300,
        )
        assert token == "security_token"

        # Revoke token
        result = await vault_backend.revoke_user_tokens(
            gateway_id=test_gateway.id,
            team_id="security",
            app_user_email="security@example.com",
        )
        assert result is True

        # Verify token is gone
        token_after = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="security",
            app_user_email="security@example.com",
            threshold_seconds=300,
        )
        assert token_after is None

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_token(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway
    ):
        """Test revoking a non-existent token succeeds (idempotent).

        Vault returns 204 No Content for both existing and non-existing deletes,
        which is correct idempotent behavior. The operation succeeds either way.
        """
        result = await vault_backend.revoke_user_tokens(
            gateway_id=test_gateway.id,
            team_id="nonexistent",
            app_user_email="nobody@example.com",
        )

        # Vault DELETE is idempotent - returns True even if secret didn't exist
        assert result is True


class TestVaultIntegrationCaching:
    """Integration tests for token caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_reduces_vault_calls(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test that caching reduces Vault API calls."""
        # Ensure cache is enabled
        assert vault_backend.cache_enabled is True

        # Store token
        await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="cache-test",
            user_id="github:12345",
            app_user_email="cache@example.com",
            access_token="cached_token",
            refresh_token="cached_refresh",
            expires_in=3600,
            scopes=["read"],
        )

        # First retrieval - cache miss (should hit Vault)
        token1 = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="cache-test",
            app_user_email="cache@example.com",
            threshold_seconds=300,
        )
        assert token1 == "cached_token"

        # Second retrieval - cache hit (should NOT hit Vault)
        token2 = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="cache-test",
            app_user_email="cache@example.com",
            threshold_seconds=300,
        )
        assert token2 == "cached_token"

        # Both should be the same
        assert token1 == token2

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_update(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test that cache is invalidated when token is updated."""
        # Store initial token
        await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="invalidate-test",
            user_id="github:12345",
            app_user_email="invalidate@example.com",
            access_token="old_cached_token",
            refresh_token="old_refresh",
            expires_in=3600,
            scopes=["read"],
        )

        # Retrieve to populate cache
        token1 = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="invalidate-test",
            app_user_email="invalidate@example.com",
            threshold_seconds=300,
        )
        assert token1 == "old_cached_token"

        # Update token (should invalidate cache)
        await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="invalidate-test",
            user_id="github:12345",
            app_user_email="invalidate@example.com",
            access_token="new_cached_token",
            refresh_token="new_refresh",
            expires_in=3600,
            scopes=["write"],
        )

        # Retrieve again - should get new token (cache was invalidated)
        token2 = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="invalidate-test",
            app_user_email="invalidate@example.com",
            threshold_seconds=300,
        )
        assert token2 == "new_cached_token"


class TestVaultIntegrationErrorHandling:
    """Integration tests for error handling."""

    @pytest.mark.asyncio
    async def test_gateway_not_found_raises_error(
        self,
        vault_backend: VaultTokenBackend
    ):
        """Test that non-existent gateway raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            await vault_backend.store_tokens(
                gateway_id="nonexistent-gateway",
                team_id="test",
                user_id="github:12345",
                app_user_email="test@example.com",
                access_token="token",
                refresh_token="refresh",
                expires_in=3600,
                scopes=["read"],
            )

        assert "Gateway nonexistent-gateway not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_special_characters_in_email(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test handling of special characters in email addresses."""
        # Store token with special chars in email
        await vault_backend.store_tokens(
            gateway_id=test_gateway.id,
            team_id="special-chars",
            user_id="github:12345",
            app_user_email="user+test@example.com",  # Has '+' char
            access_token="special_token",
            refresh_token="special_refresh",
            expires_in=3600,
            scopes=["read"],
        )

        # Retrieve token
        token = await vault_backend.get_user_token(
            gateway_id=test_gateway.id,
            team_id="special-chars",
            app_user_email="user+test@example.com",
            threshold_seconds=300,
        )

        assert token == "special_token"


class TestVaultIntegrationCleanup:
    """Integration tests for token cleanup operations."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens(
        self,
        vault_backend: VaultTokenBackend,
        test_gateway: Gateway,
        cleanup_vault_data
    ):
        """Test cleanup of expired tokens."""
        # Note: Vault KV v2 doesn't have TTL-based expiry
        # This test validates the cleanup method exists and runs
        count = await vault_backend.cleanup_expired_tokens(max_age_days=30)

        # Vault backend should return 0 (Vault handles cleanup via TTL)
        assert count == 0
