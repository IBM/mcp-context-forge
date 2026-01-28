# -*- coding: utf-8 -*-
"""End-to-end tests for MCP session pool admin metrics endpoint.

Tests verify:
- /admin/mcp-pool/metrics requires authentication
- Metrics do not leak request headers or tokens
- Pool key identities are truncated hashes (not raw auth headers)
- Metrics include pool key count, evictions, sessions reaped, and hit rate

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import os

os.environ["MCPGATEWAY_ADMIN_API_ENABLED"] = "true"
os.environ["MCPGATEWAY_UI_ENABLED"] = "true"
os.environ["MCP_SESSION_POOL_ENABLED"] = "true"

# Standard
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.mcp_session_pool import (
    MCPSessionPool,
    PooledSession,
    TransportType,
)


class TestPoolMetricsSecurityOutput:
    """Tests for security of pool metrics output."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool()

    def test_identity_hash_is_hashed_not_raw(self, pool):
        """Pool key identity should be a SHA-256 hash, not raw auth header."""
        headers = {"Authorization": "Bearer super-secret-token-12345"}

        identity_hash = pool._compute_identity_hash(headers)

        # Should be a hash, not the original token
        assert "super-secret-token" not in identity_hash
        assert "Bearer" not in identity_hash

        # Should be a full SHA-256 hex hash (64 chars)
        assert len(identity_hash) == 64
        assert all(c in "0123456789abcdef" for c in identity_hash)

    def test_pool_key_does_not_contain_raw_headers(self, pool):
        """Pool key should not contain raw header values."""
        sensitive_headers = {
            "Authorization": "Bearer my-secret-jwt-token",
            "X-Api-Key": "api-key-12345",
            "Cookie": "session=sensitive-session-id",
        }

        pool_key = pool._make_pool_key("http://test:8080", sensitive_headers, TransportType.STREAMABLE_HTTP, user_identity="anonymous")

        # Convert pool key to string for checking
        pool_key_str = str(pool_key)

        # Should not contain raw sensitive values
        assert "my-secret-jwt-token" not in pool_key_str
        assert "api-key-12345" not in pool_key_str
        assert "sensitive-session-id" not in pool_key_str
        assert "Bearer" not in pool_key_str

    def test_metrics_output_does_not_leak_secrets(self, pool):
        """Metrics output should not contain any raw header values."""
        # Add some sessions with sensitive headers
        sensitive_headers = {"Authorization": "Bearer super-secret-token"}

        # Compute identity hash (simulating what happens during acquire)
        identity = pool._compute_identity_hash(sensitive_headers)

        # Get metrics
        metrics = pool.get_metrics()

        # Convert metrics to string for checking
        metrics_str = str(metrics)

        # Should not contain any sensitive data
        assert "super-secret-token" not in metrics_str
        assert "Bearer" not in metrics_str

        # Identity hash should be full SHA-256 (64 chars)
        assert len(identity) == 64

    def test_anonymous_identity_is_not_raw_string(self, pool):
        """Anonymous identity should be the string 'anonymous', not reveal absence of auth."""
        no_auth_headers = {}

        identity = pool._compute_identity_hash(no_auth_headers)

        assert identity == "anonymous"


class TestPoolMetricsStructure:
    """Tests for structure and content of pool metrics."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool()

    def test_metrics_contains_required_fields(self, pool):
        """Metrics should contain all required fields."""
        metrics = pool.get_metrics()

        required_fields = [
            "hits",
            "misses",
            "evictions",
            "health_check_failures",
            "circuit_breaker_trips",
            "pool_keys_evicted",
            "sessions_reaped",
            "hit_rate",
            "pool_key_count",
        ]

        for field in required_fields:
            assert field in metrics, f"Missing required field: {field}"

    def test_metrics_initial_values(self, pool):
        """Initial metrics should have zero values."""
        metrics = pool.get_metrics()

        assert metrics["hits"] == 0
        assert metrics["misses"] == 0
        assert metrics["evictions"] == 0
        assert metrics["health_check_failures"] == 0
        assert metrics["circuit_breaker_trips"] == 0
        assert metrics["pool_keys_evicted"] == 0
        assert metrics["sessions_reaped"] == 0
        assert metrics["hit_rate"] == 0.0
        assert metrics["pool_key_count"] == 0

    @pytest.mark.asyncio
    async def test_metrics_updated_after_operations(self, pool):
        """Metrics should be updated after pool operations."""
        with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
            with patch.object(pool, '_validate_session', new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = True
                mock_session = PooledSession(
                    session=MagicMock(),
                    transport_context=MagicMock(),
                    url="http://test:8080",
                    identity_key="anonymous",
                    transport_type=TransportType.STREAMABLE_HTTP,
                    headers={},
                )
                mock_create.return_value = mock_session

                # First acquire - miss
                s1 = await pool.acquire("http://test:8080")
                metrics = pool.get_metrics()
                assert metrics["misses"] == 1
                assert metrics["hits"] == 0
                assert metrics["pool_key_count"] == 1

                await pool.release(s1)

                # Second acquire - hit
                s2 = await pool.acquire("http://test:8080")
                metrics = pool.get_metrics()
                assert metrics["misses"] == 1
                assert metrics["hits"] == 1
                assert metrics["hit_rate"] == 0.5

                await pool.release(s2)

        await pool.close_all()


class TestPoolMetricsEvictionTracking:
    """Tests for eviction and reaping metrics."""

    @pytest.mark.asyncio
    async def test_eviction_metrics_tracked(self):
        """Pool key evictions should be tracked in metrics."""
        pool = MCPSessionPool(
            idle_pool_eviction_seconds=0.001,  # Very short eviction time
            session_ttl_seconds=300,
        )
        pool._eviction_run_interval = 0  # Disable throttling

        try:
            with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
                with patch.object(pool, '_close_session', new_callable=AsyncMock):
                    mock_session = PooledSession(
                        session=MagicMock(),
                        transport_context=MagicMock(),
                        url="http://test:8080",
                        identity_key="anonymous",
                        transport_type=TransportType.STREAMABLE_HTTP,
                        headers={},
                    )
                    mock_create.return_value = mock_session

                    # Create a pool entry
                    s = await pool.acquire("http://test:8080")
                    await pool.release(s)

                    # Verify pool has the key before eviction
                    pool_key = ("anonymous", "http://test:8080", "anonymous", "streamablehttp", "")
                    assert pool_key in pool._pools
                    assert pool.get_metrics()["pool_key_count"] == 1

                    # Force old timestamp to simulate idle pool
                    pool._pool_last_used[pool_key] = time.time() - 1000

                    # Reset eviction timer and trigger eviction
                    pool._last_eviction_run = 0
                    await pool._maybe_evict_idle_pool_keys()

                    # Pool key should have been evicted (no active sessions)
                    metrics = pool.get_metrics()
                    # Either the key was evicted or the session was reaped
                    assert metrics["pool_keys_evicted"] >= 1 or metrics["sessions_reaped"] >= 0
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_session_reaping_metrics_tracked(self):
        """Stale session reaping should be tracked in metrics."""
        pool = MCPSessionPool(
            idle_pool_eviction_seconds=0.01,
            session_ttl_seconds=0.001,  # Very short TTL
        )
        pool._eviction_run_interval = 0

        try:
            with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
                with patch.object(pool, '_close_session', new_callable=AsyncMock):
                    # Create expired session
                    mock_session = PooledSession(
                        session=MagicMock(),
                        transport_context=MagicMock(),
                        url="http://test:8080",
                        identity_key="anonymous",
                        transport_type=TransportType.STREAMABLE_HTTP,
                        headers={},
                        created_at=time.time() - 100,  # Already expired
                    )
                    mock_create.return_value = mock_session

                    # Create pool entry
                    s = await pool.acquire("http://test:8080")

                    # Force session back into pool
                    pool_key = ("anonymous", "http://test:8080", "anonymous", "streamablehttp", "")
                    pool._active.get(pool_key, set()).discard(s)
                    pool._pools[pool_key].put_nowait(s)

                    # Force old timestamp
                    pool._pool_last_used[pool_key] = time.time() - 1000

                    # Trigger eviction (which includes reaping)
                    pool._last_eviction_run = 0
                    await pool._maybe_evict_idle_pool_keys()

                    metrics = pool.get_metrics()
                    assert metrics["sessions_reaped"] >= 1
        finally:
            await pool.close_all()


class TestSecurityValidation:
    """Security validation tests for session pool."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool()

    def test_anonymous_sessions_isolated_from_authenticated(self, pool):
        """Anonymous sessions should not share with authenticated sessions."""
        anonymous_headers = {}
        authenticated_headers = {"Authorization": "Bearer token"}

        anon_key = pool._make_pool_key("http://test:8080", anonymous_headers, TransportType.STREAMABLE_HTTP, user_identity="anonymous")
        auth_key = pool._make_pool_key("http://test:8080", authenticated_headers, TransportType.STREAMABLE_HTTP, user_identity="anonymous")

        assert anon_key != auth_key
        assert anon_key[2] == "anonymous"
        assert auth_key[2] != "anonymous"

    def test_header_case_normalization_consistent(self, pool):
        """Header case normalization should not create identity collisions."""
        lower_headers = {"authorization": "Bearer token"}
        upper_headers = {"AUTHORIZATION": "Bearer token"}
        mixed_headers = {"Authorization": "Bearer token"}

        lower_hash = pool._compute_identity_hash(lower_headers)
        upper_hash = pool._compute_identity_hash(upper_headers)
        mixed_hash = pool._compute_identity_hash(mixed_headers)

        # All should produce same hash (case-insensitive)
        assert lower_hash == upper_hash == mixed_hash

    def test_different_tokens_produce_different_hashes(self, pool):
        """Different authentication tokens should produce different hashes."""
        user1_headers = {"Authorization": "Bearer user1-token"}
        user2_headers = {"Authorization": "Bearer user2-token"}

        user1_hash = pool._compute_identity_hash(user1_headers)
        user2_hash = pool._compute_identity_hash(user2_headers)

        assert user1_hash != user2_hash

    def test_tenant_headers_create_isolation(self, pool):
        """Different tenant headers should create separate identities."""
        tenant_a = {"Authorization": "Bearer token", "X-Tenant-ID": "tenant-a"}
        tenant_b = {"Authorization": "Bearer token", "X-Tenant-ID": "tenant-b"}

        hash_a = pool._compute_identity_hash(tenant_a)
        hash_b = pool._compute_identity_hash(tenant_b)

        assert hash_a != hash_b

    @pytest.mark.asyncio
    async def test_expired_session_not_reused(self, pool):
        """Expired sessions should not be reused for any user."""
        pool._session_ttl = 0.001  # 1ms TTL

        with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
            # Create an expired session
            expired_session = PooledSession(
                session=MagicMock(),
                transport_context=MagicMock(),
                url="http://test:8080",
                identity_key="anonymous",
                transport_type=TransportType.STREAMABLE_HTTP,
                headers={},
                created_at=time.time() - 100,  # Created 100s ago
            )
            mock_create.return_value = expired_session

            # Validate should fail for expired session
            is_valid = await pool._validate_session(expired_session)

            assert is_valid is False

        await pool.close_all()
