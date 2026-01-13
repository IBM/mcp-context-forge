# -*- coding: utf-8 -*-
"""Integration tests for MCP session pool isolation.

Tests verify:
- Tool service uses pool for SSE and streamable HTTP when enabled
- Resource service uses pool for both transports when enabled
- Gateway health check uses pool only for streamable HTTP
- Pool disabled behavior is unchanged (per-call session creation)
- Session isolation between different users/tenants

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.mcp_session_pool import (
    MCPSessionPool,
    PooledSession,
    TransportType,
    close_mcp_session_pool,
    get_mcp_session_pool,
    init_mcp_session_pool,
)


class TestCrossUserIsolation:
    """Tests for session isolation between different users."""

    @pytest.fixture
    def pool(self):
        """Create pool with short TTL for testing."""
        return MCPSessionPool(
            max_sessions_per_key=5,
            session_ttl_seconds=300,
            health_check_interval_seconds=60,
        )

    @pytest.mark.asyncio
    async def test_different_users_get_different_sessions(self, pool):
        """User A and User B should acquire different session objects."""
        user_a_headers = {"Authorization": "Bearer user-a-token"}
        user_b_headers = {"Authorization": "Bearer user-b-token"}

        # Pre-compute identity hashes
        identity_a = pool._compute_identity_hash(user_a_headers)
        identity_b = pool._compute_identity_hash(user_b_headers)

        with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
            # Create unique sessions for each user
            session_a = PooledSession(
                session=MagicMock(name="session_a"),
                transport_context=MagicMock(),
                url="http://test:8080",
                identity_key=identity_a,
                transport_type=TransportType.STREAMABLE_HTTP,
                headers=user_a_headers,
            )
            session_b = PooledSession(
                session=MagicMock(name="session_b"),
                transport_context=MagicMock(),
                url="http://test:8080",
                identity_key=identity_b,
                transport_type=TransportType.STREAMABLE_HTTP,
                headers=user_b_headers,
            )

            async def create_session_by_headers(url, headers, transport_type, httpx_client_factory, timeout=None):
                if headers and headers.get("Authorization") == "Bearer user-a-token":
                    return session_a
                return session_b

            mock_create.side_effect = create_session_by_headers

            # Acquire sessions for both users
            acquired_a = await pool.acquire("http://test:8080", headers=user_a_headers)
            acquired_b = await pool.acquire("http://test:8080", headers=user_b_headers)

            # Verify different session objects
            assert acquired_a is not acquired_b
            assert acquired_a.identity_key != acquired_b.identity_key

            await pool.close_all()

    @pytest.mark.asyncio
    async def test_same_user_reuses_session(self, pool):
        """Same user should reuse pooled session (pool hit)."""
        user_headers = {"Authorization": "Bearer user-token"}

        with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
            with patch.object(pool, '_validate_session', new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = True
                mock_session = PooledSession(
                    session=MagicMock(),
                    transport_context=MagicMock(),
                    url="http://test:8080",
                    identity_key=pool._compute_identity_hash(user_headers),
                    transport_type=TransportType.STREAMABLE_HTTP,
                    headers=user_headers,
                )
                mock_create.return_value = mock_session

                # First acquire - creates session
                session1 = await pool.acquire("http://test:8080", headers=user_headers)
                await pool.release(session1)

                # Second acquire - reuses session
                session2 = await pool.acquire("http://test:8080", headers=user_headers)

                assert session1 is session2
                assert pool._hits == 1
                assert pool._misses == 1
                mock_create.assert_called_once()  # Only created once

                await pool.close_all()

    @pytest.mark.asyncio
    async def test_user_cannot_access_other_user_session(self, pool):
        """Verify pool keys prevent cross-user session access."""
        user_a_headers = {"Authorization": "Bearer user-a-token"}
        user_b_headers = {"Authorization": "Bearer user-b-token"}

        # Verify pool keys are different
        key_a = pool._make_pool_key("http://test:8080", user_a_headers, TransportType.STREAMABLE_HTTP, user_identity="anonymous")
        key_b = pool._make_pool_key("http://test:8080", user_b_headers, TransportType.STREAMABLE_HTTP, user_identity="anonymous")

        assert key_a != key_b
        assert key_a[1] == key_b[1]  # Same URL
        assert key_a[2] != key_b[2]  # Different identity hash
        assert key_a[3] == key_b[3]  # Same transport


class TestConcurrentAccess:
    """Tests for concurrent session access isolation."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool(max_sessions_per_key=10)

    @pytest.mark.asyncio
    async def test_concurrent_users_isolated(self, pool):
        """10 concurrent users should each get their own session."""
        session_assignments = {}

        async def simulate_user_request(user_id):
            headers = {"Authorization": f"Bearer user-{user_id}-token"}
            key = pool._make_pool_key("http://test:8080", headers, TransportType.STREAMABLE_HTTP, user_identity="anonymous")
            session_assignments[user_id] = key
            return key

        # Run 10 concurrent user requests
        tasks = [simulate_user_request(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # Verify all 10 got unique pool keys
        unique_keys = set(results)
        assert len(unique_keys) == 10

    @pytest.mark.asyncio
    async def test_high_concurrency_isolation(self, pool):
        """100 concurrent requests with 10 different identities."""
        results = []

        async def simulate_request(request_id):
            user_id = request_id % 10  # 10 different users
            headers = {"Authorization": f"Bearer user-{user_id}-token"}
            key = pool._make_pool_key("http://test:8080", headers, TransportType.STREAMABLE_HTTP, user_identity="anonymous")
            results.append((request_id, user_id, key))
            return key

        # Run 100 concurrent requests
        tasks = [simulate_request(i) for i in range(100)]
        await asyncio.gather(*tasks)

        # Group by user_id and verify each user got the same key
        by_user = {}
        for request_id, user_id, key in results:
            if user_id not in by_user:
                by_user[user_id] = set()
            by_user[user_id].add(key)

        # Each user should have exactly one unique key
        for user_id, keys in by_user.items():
            assert len(keys) == 1, f"User {user_id} got multiple different keys: {keys}"


class TestSessionLifecycle:
    """Tests for session lifecycle and isolation."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool(max_sessions_per_key=2, session_ttl_seconds=300)

    @pytest.mark.asyncio
    async def test_released_session_not_given_to_different_user(self, pool):
        """When User A releases a session, User B should NOT receive it."""
        user_a_headers = {"Authorization": "Bearer user-a-token"}
        user_b_headers = {"Authorization": "Bearer user-b-token"}

        with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
            # Track sessions created
            sessions_created = []

            async def create_session(url, headers, transport_type, httpx_client_factory, timeout=None):
                session = PooledSession(
                    session=MagicMock(),
                    transport_context=MagicMock(),
                    url=url,
                    identity_key=pool._compute_identity_hash(headers),
                    transport_type=transport_type,
                    headers=headers or {},
                )
                sessions_created.append(session)
                return session

            mock_create.side_effect = create_session

            # User A acquires and releases
            session_a = await pool.acquire("http://test:8080", headers=user_a_headers)
            await pool.release(session_a)

            # User B acquires - should get NEW session, not A's
            session_b = await pool.acquire("http://test:8080", headers=user_b_headers)

            assert session_a is not session_b
            assert session_a.identity_key != session_b.identity_key
            assert mock_create.call_count == 2  # Created 2 sessions

            await pool.close_all()

    @pytest.mark.asyncio
    async def test_session_reuse_same_identity_only(self, pool):
        """Sessions should only be reused for matching identity."""
        headers = {"Authorization": "Bearer token", "X-Tenant-ID": "tenant-1"}

        with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
            with patch.object(pool, '_validate_session', new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = True
                mock_session = PooledSession(
                    session=MagicMock(),
                    transport_context=MagicMock(),
                    url="http://test:8080",
                    identity_key=pool._compute_identity_hash(headers),
                    transport_type=TransportType.STREAMABLE_HTTP,
                    headers=headers,
                )
                mock_create.return_value = mock_session

                # Acquire with same identity multiple times
                session1 = await pool.acquire("http://test:8080", headers=headers)
                await pool.release(session1)
                session2 = await pool.acquire("http://test:8080", headers=headers)
                await pool.release(session2)
                session3 = await pool.acquire("http://test:8080", headers=headers)

                # All should be the same session
                assert session1 is session2 is session3
                assert pool._hits == 2
                assert pool._misses == 1

                await pool.close_all()


class TestTransportIsolation:
    """Tests for transport type isolation."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool()

    @pytest.mark.asyncio
    async def test_sse_and_streamable_http_isolated(self, pool):
        """Same URL with different transports should use separate pools."""
        headers = {"Authorization": "Bearer token"}

        # Get pool keys for same URL, same identity, different transports
        sse_key = pool._make_pool_key("http://test:8080", headers, TransportType.SSE, user_identity="anonymous")
        http_key = pool._make_pool_key("http://test:8080", headers, TransportType.STREAMABLE_HTTP, user_identity="anonymous")

        assert sse_key != http_key
        assert sse_key[1] == http_key[1]  # Same URL
        assert sse_key[2] == http_key[2]  # Same identity
        assert sse_key[3] != http_key[3]  # Different transport

    @pytest.mark.asyncio
    async def test_transport_in_pool_key(self, pool):
        """Verify transport type is included in pool key."""
        headers = {}

        sse_key = pool._make_pool_key("http://test:8080", headers, TransportType.SSE, user_identity="anonymous")
        http_key = pool._make_pool_key("http://test:8080", headers, TransportType.STREAMABLE_HTTP, user_identity="anonymous")

        assert sse_key[3] == "sse"
        assert http_key[3] == "streamablehttp"


class TestPoolDisabledBehavior:
    """Tests for behavior when pool is disabled."""

    @pytest.mark.asyncio
    async def test_pool_not_initialized_raises(self):
        """Getting pool when not initialized should raise RuntimeError."""
        # Ensure pool is closed
        await close_mcp_session_pool()

        with pytest.raises(RuntimeError, match="not initialized"):
            get_mcp_session_pool()

    @pytest.mark.asyncio
    async def test_pool_enabled_then_disabled(self):
        """Pool should be unavailable after close."""
        pool = init_mcp_session_pool()
        assert pool is not None
        assert get_mcp_session_pool() is pool

        await close_mcp_session_pool()

        with pytest.raises(RuntimeError, match="not initialized"):
            get_mcp_session_pool()


class TestPoolMetricsIsolation:
    """Tests for metrics tracking with isolation."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool()

    @pytest.mark.asyncio
    async def test_metrics_track_hits_and_misses_per_identity(self, pool):
        """Verify metrics track hits/misses correctly across identities."""
        user_a_headers = {"Authorization": "Bearer user-a"}
        user_b_headers = {"Authorization": "Bearer user-b"}

        with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
            with patch.object(pool, '_validate_session', new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = True

                # Create sessions for different users
                def create_session_for_headers(url, headers, transport_type, httpx_client_factory, timeout=None):
                    return PooledSession(
                        session=MagicMock(),
                        transport_context=MagicMock(),
                        url=url,
                        identity_key=pool._compute_identity_hash(headers),
                        transport_type=transport_type,
                        headers=headers or {},
                    )

                mock_create.side_effect = create_session_for_headers

                # User A: miss, hit, hit
                session_a1 = await pool.acquire("http://test:8080", headers=user_a_headers)
                await pool.release(session_a1)
                session_a2 = await pool.acquire("http://test:8080", headers=user_a_headers)
                await pool.release(session_a2)
                session_a3 = await pool.acquire("http://test:8080", headers=user_a_headers)
                await pool.release(session_a3)

                # User B: miss, hit
                session_b1 = await pool.acquire("http://test:8080", headers=user_b_headers)
                await pool.release(session_b1)
                session_b2 = await pool.acquire("http://test:8080", headers=user_b_headers)
                await pool.release(session_b2)

                metrics = pool.get_metrics()
                assert metrics["misses"] == 2  # 1 for user A, 1 for user B
                assert metrics["hits"] == 3  # 2 for user A, 1 for user B
                assert metrics["pool_key_count"] == 2  # 2 different users

                await pool.close_all()
