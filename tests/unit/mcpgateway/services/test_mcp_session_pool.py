# -*- coding: utf-8 -*-
"""Tests for the MCP session pool service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.mcp_session_pool import (
    MCPSessionPool,
    PooledSession,
    TransportType,
    get_mcp_session_pool,
    init_mcp_session_pool,
    close_mcp_session_pool,
)


class TestMCPSessionPoolInit:
    """Tests for MCPSessionPool initialization."""

    def test_init_defaults(self):
        """Test pool initialization with defaults."""
        pool = MCPSessionPool()

        assert pool._max_sessions == 10
        assert pool._session_ttl == 300.0
        assert pool._health_check_interval == 60.0
        assert pool._acquire_timeout == 30.0
        assert pool._session_create_timeout == 30.0
        assert pool._circuit_breaker_threshold == 5
        assert pool._circuit_breaker_reset == 60.0
        assert pool._idle_pool_eviction == 600.0
        assert pool._default_transport_timeout == 30.0  # Default transport timeout (matches MCP SDK)
        assert pool._closed is False

    def test_init_custom_values(self):
        """Test pool initialization with custom values."""
        pool = MCPSessionPool(
            max_sessions_per_key=5,
            session_ttl_seconds=120.0,
            health_check_interval_seconds=30.0,
            acquire_timeout_seconds=15.0,
            session_create_timeout_seconds=20.0,
            circuit_breaker_threshold=3,
            circuit_breaker_reset_seconds=30.0,
            idle_pool_eviction_seconds=300.0,
        )

        assert pool._max_sessions == 5
        assert pool._session_ttl == 120.0
        assert pool._health_check_interval == 30.0
        assert pool._acquire_timeout == 15.0
        assert pool._session_create_timeout == 20.0
        assert pool._circuit_breaker_threshold == 3
        assert pool._circuit_breaker_reset == 30.0
        assert pool._idle_pool_eviction == 300.0

    def test_init_custom_identity_headers(self):
        """Test pool initialization with custom identity headers."""
        custom_headers = frozenset(["x-custom-header", "authorization"])
        pool = MCPSessionPool(identity_headers=custom_headers)

        assert pool._identity_headers == custom_headers

    def test_init_custom_transport_timeout(self):
        """Test pool initialization with custom transport timeout (timeout consolidation)."""
        pool = MCPSessionPool(default_transport_timeout_seconds=10.0)

        assert pool._default_transport_timeout == 10.0

    @pytest.mark.asyncio
    async def test_init_transport_timeout_passed_through_init_mcp_session_pool(self):
        """Test that default_transport_timeout_seconds is passed through init_mcp_session_pool()."""
        try:
            # Initialize with custom timeout
            pool = init_mcp_session_pool(default_transport_timeout_seconds=7.5)

            assert pool._default_transport_timeout == 7.5
        finally:
            # Always cleanup to prevent leaking global pool into other tests
            await close_mcp_session_pool()


class TestValidateSession:
    """Tests for session validation and health checks."""

    @pytest.fixture
    def pool(self):
        # Use short health check interval so sessions become stale quickly
        # Configure to use list_tools for testing (easier to mock than ping)
        return MCPSessionPool(
            health_check_interval_seconds=0.01,  # 10ms
            health_check_timeout_seconds=3.0,  # Custom health check timeout
            health_check_methods=["list_tools"],  # Use list_tools for testing
        )

    @pytest.mark.asyncio
    async def test_validate_session_uses_configurable_timeout(self, pool):
        """Test that _validate_session uses _health_check_timeout (not hardcoded 5.0)."""
        mock_session = MagicMock()
        mock_list_tools = AsyncMock(return_value=[])
        mock_session.list_tools = mock_list_tools

        pooled = PooledSession(
            session=mock_session,
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            created_at=time.time(),
            last_used=time.time() - 1,  # Make it stale (> health_check_interval)
        )

        # Patch asyncio.wait_for to capture the timeout argument
        captured_timeout = None

        async def capture_wait_for(coro, timeout):
            nonlocal captured_timeout
            captured_timeout = timeout
            return await coro

        with patch('mcpgateway.services.mcp_session_pool.asyncio.wait_for', side_effect=capture_wait_for):
            result = await pool._validate_session(pooled)

        # Should have used the configurable health check timeout (3.0), not hardcoded 5.0
        assert captured_timeout == 3.0
        assert result is True
        # Verify list_tools() was actually awaited (health check executed)
        mock_list_tools.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_validate_session_health_check_timeout_failure(self, pool):
        """Test that health check failures due to timeout are handled correctly."""
        mock_session = MagicMock()
        mock_list_tools = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_session.list_tools = mock_list_tools

        pooled = PooledSession(
            session=mock_session,
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            created_at=time.time(),
            last_used=time.time() - 1,  # Make it stale
        )

        result = await pool._validate_session(pooled)

        assert result is False
        assert pool._health_check_failures == 1


class TestIdentityHashing:
    """Tests for identity hashing / session isolation."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool()

    def test_identity_hash_different_for_different_auth(self, pool):
        """Different Authorization headers should produce different identity hashes."""
        hash1 = pool._compute_identity_hash({"Authorization": "Bearer token-user-1"})
        hash2 = pool._compute_identity_hash({"Authorization": "Bearer token-user-2"})

        assert hash1 != hash2
        assert hash1 != "anonymous"
        assert hash2 != "anonymous"

    def test_identity_hash_same_for_same_auth(self, pool):
        """Same Authorization header should produce same identity hash."""
        hash1 = pool._compute_identity_hash({"Authorization": "Bearer token-user-1"})
        hash2 = pool._compute_identity_hash({"Authorization": "Bearer token-user-1"})

        assert hash1 == hash2

    def test_identity_hash_case_insensitive(self, pool):
        """Header names should be case-insensitive for identity hashing."""
        hash1 = pool._compute_identity_hash({"Authorization": "Bearer token"})
        hash2 = pool._compute_identity_hash({"authorization": "Bearer token"})
        hash3 = pool._compute_identity_hash({"AUTHORIZATION": "Bearer token"})

        assert hash1 == hash2 == hash3

    def test_identity_hash_anonymous_for_no_headers(self, pool):
        """No headers should return 'anonymous' identity."""
        assert pool._compute_identity_hash(None) == "anonymous"
        assert pool._compute_identity_hash({}) == "anonymous"
        assert pool._compute_identity_hash({"Content-Type": "application/json"}) == "anonymous"

    def test_identity_hash_with_multiple_headers(self, pool):
        """Multiple identity headers should be combined."""
        hash1 = pool._compute_identity_hash({
            "Authorization": "Bearer token",
            "X-Tenant-ID": "tenant-1",
        })
        hash2 = pool._compute_identity_hash({
            "Authorization": "Bearer token",
            "X-Tenant-ID": "tenant-2",
        })

        assert hash1 != hash2
        assert hash1 != "anonymous"

    def test_tenant_header_isolation(self, pool):
        """X-Tenant-ID creates separate identity hashes (tenant isolation)."""
        # Same auth but different tenant
        tenant_a_hash = pool._compute_identity_hash({
            "Authorization": "Bearer shared-token",
            "X-Tenant-ID": "tenant-a",
        })
        tenant_b_hash = pool._compute_identity_hash({
            "Authorization": "Bearer shared-token",
            "X-Tenant-ID": "tenant-b",
        })

        assert tenant_a_hash != tenant_b_hash
        assert tenant_a_hash != "anonymous"
        assert tenant_b_hash != "anonymous"

    def test_combined_identity_headers(self, pool):
        """Auth + Tenant + User combined correctly for isolation."""
        full_identity = pool._compute_identity_hash({
            "Authorization": "Bearer token",
            "X-Tenant-ID": "tenant-1",
            "X-User-ID": "user-123",
        })
        # Same auth, same tenant, different user
        diff_user = pool._compute_identity_hash({
            "Authorization": "Bearer token",
            "X-Tenant-ID": "tenant-1",
            "X-User-ID": "user-456",
        })
        # Same auth, different tenant, same user
        diff_tenant = pool._compute_identity_hash({
            "Authorization": "Bearer token",
            "X-Tenant-ID": "tenant-2",
            "X-User-ID": "user-123",
        })

        assert full_identity != diff_user
        assert full_identity != diff_tenant
        assert diff_user != diff_tenant

    @pytest.mark.asyncio
    async def test_pool_key_determinism_under_concurrent_calls(self, pool):
        """Pool key generation is deterministic: same identity always produces same key.

        Note: This tests _make_pool_key determinism, not concurrent acquire/release
        session isolation. For full concurrent session isolation tests, see
        tests/integration/test_mcp_session_pool_integration.py::TestConcurrentAccess.
        """
        results = []

        async def get_pool_key(headers, task_id):
            key = pool._make_pool_key("http://test:8080", headers, TransportType.STREAMABLE_HTTP, user_identity="anonymous")
            results.append((task_id, key))
            return key

        # Simulate concurrent requests from different users
        await asyncio.gather(
            get_pool_key({"Authorization": "Bearer user-1"}, 1),
            get_pool_key({"Authorization": "Bearer user-2"}, 2),
            get_pool_key({"Authorization": "Bearer user-3"}, 3),
            get_pool_key({"Authorization": "Bearer user-1"}, 4),  # Same as task 1
            get_pool_key({"Authorization": "Bearer user-2"}, 5),  # Same as task 2
        )

        # Verify results
        assert len(results) == 5
        task_keys = {task_id: key for task_id, key in results}

        # Same user should get same key (determinism)
        assert task_keys[1] == task_keys[4]
        assert task_keys[2] == task_keys[5]

        # Different users should get different keys (isolation)
        assert task_keys[1] != task_keys[2]
        assert task_keys[1] != task_keys[3]
        assert task_keys[2] != task_keys[3]


class TestSessionPoolIsolation:
    """Tests for strict user isolation in MCPSessionPool."""

    @pytest.mark.asyncio
    async def test_session_isolation_by_user_identity(self):
        """Test that sessions are isolated by user identity."""
        pool = MCPSessionPool(max_sessions_per_key=10)

        # Mock _create_session to avoid network calls and return a mock PooledSession
        pool._create_session = AsyncMock()

        async def create_mock_session(url, headers, transport_type, *args, **kwargs):
            # Extract gateway_id from kwargs if provided
            gateway_id = kwargs.get("gateway_id", "") or ""

            # Create a mock that mimics PooledSession behavior needed by acquire/release
            real_pooled = MagicMock()
            real_pooled.url = url
            real_pooled.transport_type = transport_type
            real_pooled.is_closed = False
            real_pooled.age_seconds = 0.5
            real_pooled.idle_seconds = 0.5
            real_pooled.last_used = time.time()
            real_pooled.created_at = time.time()
            real_pooled.gateway_id = gateway_id  # Required for pool key reconstruction

            # Setup session mock behavior
            real_pooled.session = AsyncMock()
            real_pooled.session.send_ping = AsyncMock(return_value=True)

            # Mock transport context
            real_pooled.transport_context = AsyncMock()
            real_pooled.transport_context.__aexit__ = AsyncMock()

            return real_pooled

        pool._create_session.side_effect = create_mock_session

        # Mock validation to always succeed so we can reuse sessions
        pool._validate_session = AsyncMock(return_value=True)

        url = "http://example.com"
        headers = {"Authorization": "Bearer token"}

        # 1. Acquire for User A
        session_a = await pool.acquire(url, headers=headers, user_identity="user_a")

        # 2. Acquire for User B (same headers, should be different pool)
        session_b = await pool.acquire(url, headers=headers, user_identity="user_b")

        # 3. Assert they are different objects (created separately)
        assert session_a is not session_b

        # 4. Release both to put them back in their respective pools
        await pool.release(session_a)
        await pool.release(session_b)

        # 5. Re-acquire for User A
        session_a_2 = await pool.acquire(url, headers=headers, user_identity="user_a")

        # 6. Assert reuse: Should get the exact same object back if isolation works
        assert session_a_2 is session_a

        # 7. Re-acquire for User B
        session_b_2 = await pool.acquire(url, headers=headers, user_identity="user_b")
        assert session_b_2 is session_b

        # 8. Verify Metrics keys contain user identities
        metrics = pool.get_metrics()
        pools = metrics["pools"]
        keys = list(pools.keys())

        assert any(hashlib.sha256(b"user_a").hexdigest() in k for k in keys), "Pool keys missing user_a hash"
        assert any(hashlib.sha256(b"user_b").hexdigest() in k for k in keys), "Pool keys missing user_b hash"

        # 9. Verify Isolation: Ensure User A cannot get User B's session
        # If we request for User A again, we should get session_a (already acquired as session_a_2)
        # Wait, session_a_2 is still active (not released).
        # Requesting another session for User A should create a NEW one or wait (max=10)
        # Since max=10, it creates a new one.

        session_a_3 = await pool.acquire(url, headers=headers, user_identity="user_a")
        assert session_a_3 is not session_b  # Should definitively NOT be user B's session
        assert session_a_3 is not session_a  # Should be a new session for user A

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_session_isolation_defaults(self):
        """Test backward compatibility (defaulting to anonymous)."""
        pool = MCPSessionPool(max_sessions_per_key=10)
        pool._create_session = AsyncMock()

        async def create_mock_session(url, headers, transport_type, *args, **kwargs):
            real_pooled = MagicMock()
            real_pooled.url = url
            real_pooled.transport_type = transport_type
            real_pooled.is_closed = False
            real_pooled.age_seconds = 0
            real_pooled.idle_seconds = 0
            return real_pooled

        pool._create_session.side_effect = create_mock_session
        pool._validate_session = AsyncMock(return_value=True)

        url = "http://example.com"

        # Acquire without user_identity
        session = await pool.acquire(url, headers={})

        # Check that user_identity was set to "anonymous" on the pooled object
        # Note: acquire sets this on the returned object
        assert session.user_identity == "anonymous"

        await pool.release(session)

        # Check metrics for anonymous key
        metrics = pool.get_metrics()
        pools = metrics["pools"]
        keys = list(pools.keys())
        assert any("anonymous" in k for k in keys)

        await pool.close_all()


class TestIdentityExtractor:
    """Tests for custom identity extractor."""

    def test_identity_extractor_used_when_provided(self):
        """Identity extractor should be used when provided."""
        def extract_user_id(headers: dict) -> str:
            return "user-123"

        pool = MCPSessionPool(identity_extractor=extract_user_id)

        # Different tokens should hash to same identity
        hash1 = pool._compute_identity_hash({"Authorization": "Bearer token-abc"})
        hash2 = pool._compute_identity_hash({"Authorization": "Bearer token-xyz"})

        assert hash1 == hash2
        assert hash1 != "anonymous"

    def test_identity_extractor_fallback_on_failure(self):
        """Should fall back to header hash if extractor fails."""
        def failing_extractor(headers: dict) -> str:
            raise ValueError("Failed to extract")

        pool = MCPSessionPool(identity_extractor=failing_extractor)

        # Should not raise, should fall back to header hashing
        hash1 = pool._compute_identity_hash({"Authorization": "Bearer token"})
        assert hash1 != "anonymous"

    def test_identity_extractor_fallback_on_none(self):
        """Should fall back to header hash if extractor returns None."""
        def none_extractor(headers: dict) -> str | None:
            return None

        pool = MCPSessionPool(identity_extractor=none_extractor)

        hash1 = pool._compute_identity_hash({"Authorization": "Bearer token"})
        assert hash1 != "anonymous"


class TestPoolKeyGeneration:
    """Tests for pool key generation."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool()

    def test_pool_key_includes_url(self, pool):
        """Pool key should include URL."""
        key1 = pool._make_pool_key("http://server1:8080", {}, TransportType.STREAMABLE_HTTP, user_identity="anonymous")
        key2 = pool._make_pool_key("http://server2:8080", {}, TransportType.STREAMABLE_HTTP, user_identity="anonymous")

        assert key1[1] != key2[1]

    def test_pool_key_includes_identity(self, pool):
        """Pool key should include identity hash."""
        key1 = pool._make_pool_key("http://server:8080", {"Authorization": "Bearer user1"}, TransportType.STREAMABLE_HTTP, user_identity="anonymous")
        key2 = pool._make_pool_key("http://server:8080", {"Authorization": "Bearer user2"}, TransportType.STREAMABLE_HTTP, user_identity="anonymous")

        assert key1[2] != key2[2]

    def test_pool_key_includes_transport_type(self, pool):
        """Pool key should include transport type."""
        key1 = pool._make_pool_key("http://server:8080", {}, TransportType.SSE, user_identity="anonymous")
        key2 = pool._make_pool_key("http://server:8080", {}, TransportType.STREAMABLE_HTTP, user_identity="anonymous")

        assert key1[3] != key2[3]
        assert key1[3] == "sse"
        assert key2[3] == "streamablehttp"

    def test_pool_key_hashes_user_identity(self, pool):
        """Pool key should hash user identity with full SHA-256."""
        user_id = "user@example.com"
        # Expect full SHA-256 hash (64 hex chars) for collision resistance
        expected_hash = hashlib.sha256(user_id.encode()).hexdigest()

        key = pool._make_pool_key(
            "http://server:8080",
            {},
            TransportType.STREAMABLE_HTTP,
            user_identity=user_id
        )

        assert key[0] == expected_hash
        assert len(key[0]) == 64  # Full SHA-256 hash
        assert key[0] != user_id


class TestCircuitBreaker:
    """Tests for circuit breaker functionality."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool(
            circuit_breaker_threshold=3,
            circuit_breaker_reset_seconds=0.1,  # Short for testing
        )

    def test_circuit_starts_closed(self, pool):
        """Circuit should start closed."""
        assert not pool._is_circuit_open("http://test:8080")

    def test_failures_tracked(self, pool):
        """Failures should be tracked per URL."""
        pool._record_failure("http://test:8080")
        pool._record_failure("http://test:8080")

        assert pool._failures.get("http://test:8080") == 2

    def test_success_resets_failures(self, pool):
        """Success should reset failure count."""
        pool._record_failure("http://test:8080")
        pool._record_failure("http://test:8080")
        pool._record_success("http://test:8080")

        assert pool._failures.get("http://test:8080") == 0

    def test_circuit_opens_after_threshold(self, pool):
        """Circuit should open after threshold failures."""
        for _ in range(3):
            pool._record_failure("http://test:8080")

        assert pool._is_circuit_open("http://test:8080")
        assert pool._circuit_breaker_trips == 1

    @pytest.mark.asyncio
    async def test_circuit_resets_after_timeout(self, pool):
        """Circuit should reset after timeout."""
        for _ in range(3):
            pool._record_failure("http://test:8080")

        assert pool._is_circuit_open("http://test:8080")

        await asyncio.sleep(0.25)  # Wait for reset (with margin for slow/busy systems)

        assert not pool._is_circuit_open("http://test:8080")


class TestPooledSession:
    """Tests for PooledSession dataclass."""

    def test_pooled_session_age(self):
        """Test age_seconds property."""
        session = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="test",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            created_at=time.time() - 10,
        )

        assert session.age_seconds >= 10
        assert session.age_seconds < 11

    def test_pooled_session_idle(self):
        """Test idle_seconds property."""
        session = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="test",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            last_used=time.time() - 5,
        )

        assert session.idle_seconds >= 5
        assert session.idle_seconds < 6

    def test_pooled_session_hashable(self):
        """PooledSession with eq=False should be hashable."""
        session = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url="http://test:8080",
            identity_key="test",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
        )

        # Should be hashable (can be added to set)
        session_set = {session}
        assert session in session_set


class TestPoolMetrics:
    """Tests for pool metrics."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool()

    def test_initial_metrics(self, pool):
        """Test initial metrics are zero."""
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

    def test_hit_rate_calculation(self, pool):
        """Test hit rate is calculated correctly."""
        pool._hits = 8
        pool._misses = 2
        metrics = pool.get_metrics()

        assert metrics["hit_rate"] == 0.8


class TestGlobalPoolFunctions:
    """Tests for global pool initialization functions."""

    @pytest.mark.asyncio
    async def test_init_and_get_pool(self):
        """Test pool initialization and retrieval."""
        # Initialize
        pool = init_mcp_session_pool(max_sessions_per_key=5)

        assert pool is not None
        assert pool._max_sessions == 5

        # Get
        retrieved = get_mcp_session_pool()
        assert retrieved is pool

        # Cleanup
        await close_mcp_session_pool()

    @pytest.mark.asyncio
    async def test_get_pool_before_init_raises(self):
        """Getting pool before initialization should raise."""
        # Ensure pool is closed
        await close_mcp_session_pool()

        with pytest.raises(RuntimeError, match="not initialized"):
            get_mcp_session_pool()

    @pytest.mark.asyncio
    async def test_close_pool(self):
        """Test pool closure."""
        init_mcp_session_pool()
        pool = get_mcp_session_pool()

        await close_mcp_session_pool()

        assert pool._closed is True

        # Should raise after close
        with pytest.raises(RuntimeError, match="not initialized"):
            get_mcp_session_pool()


class TestAcquireAndRelease:
    """Tests for acquire and release operations."""

    @pytest.fixture
    def pool(self):
        return MCPSessionPool(max_sessions_per_key=2, session_ttl_seconds=60)

    @pytest.mark.asyncio
    async def test_acquire_creates_new_session(self, pool):
        """First acquire should create a new session."""
        with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
            mock_session = PooledSession(
                session=MagicMock(),
                transport_context=MagicMock(),
                url="http://test:8080",
                identity_key="anonymous",
                transport_type=TransportType.STREAMABLE_HTTP,
                headers={},
            )
            mock_create.return_value = mock_session

            pooled = await pool.acquire("http://test:8080")

            assert pooled is not None
            assert pool._misses == 1
            assert pool._hits == 0
            mock_create.assert_called_once()

            await pool.close_all()

    @pytest.mark.asyncio
    async def test_release_and_reacquire_reuses_session(self, pool):
        """Released session should be reused on next acquire."""
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

                # First acquire
                session1 = await pool.acquire("http://test:8080")
                await pool.release(session1)

                # Second acquire should reuse
                session2 = await pool.acquire("http://test:8080")

                assert session1 is session2
                assert pool._hits == 1
                assert pool._misses == 1

                await pool.close_all()

    @pytest.mark.asyncio
    async def test_acquire_fails_when_closed(self, pool):
        """Acquire should fail when pool is closed."""
        await pool.close_all()

        with pytest.raises(RuntimeError, match="closed"):
            await pool.acquire("http://test:8080")

    @pytest.mark.asyncio
    async def test_acquire_fails_when_circuit_open(self, pool):
        """Acquire should fail when circuit breaker is open."""
        # Trip the circuit
        pool._circuit_breaker_threshold = 1
        pool._record_failure("http://test:8080")

        with pytest.raises(RuntimeError, match="Circuit breaker"):
            await pool.acquire("http://test:8080")


class TestIdlePoolEviction:
    """Tests for idle pool key eviction."""

    @pytest.fixture
    def pool(self):
        # Use longer TTL so sessions don't expire during test
        pool = MCPSessionPool(idle_pool_eviction_seconds=0.1, session_ttl_seconds=300)
        pool._eviction_run_interval = 0  # No throttling for tests
        return pool

    @pytest.mark.asyncio
    async def test_eviction_throttling(self):
        """Eviction should be throttled to prevent excessive runs."""
        pool = MCPSessionPool()
        pool._eviction_run_interval = 1.0  # 1 second throttle

        # First eviction should run
        pool._last_eviction_run = 0
        await pool._maybe_evict_idle_pool_keys()
        first_run = pool._last_eviction_run

        # Immediate second call should be throttled (no-op)
        await pool._maybe_evict_idle_pool_keys()
        assert pool._last_eviction_run == first_run  # Unchanged

    @pytest.mark.asyncio
    async def test_stale_sessions_reaped_during_eviction(self):
        """Stale sessions parked in pools should be closed during eviction."""
        # Use specific TTL that we'll override on the session
        pool = MCPSessionPool(idle_pool_eviction_seconds=0.05, session_ttl_seconds=0.01)
        pool._eviction_run_interval = 0

        with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
            with patch.object(pool, '_close_session', new_callable=AsyncMock) as mock_close:
                mock_session = PooledSession(
                    session=MagicMock(),
                    transport_context=MagicMock(),
                    url="http://test:8080",
                    identity_key="anonymous",
                    transport_type=TransportType.STREAMABLE_HTTP,
                    headers={},
                    created_at=time.time() - 100,  # Created 100s ago (expired)
                )
                mock_create.return_value = mock_session

                # Acquire session
                session = await pool.acquire("http://test:8080")

                # Force session back into pool by patching release to skip TTL check
                # Key structure: (user_hash, url, identity_hash, transport, gateway_id)
                pool_key = ("anonymous", "http://test:8080", "anonymous", "streamablehttp", "")
                pool._active.get(pool_key, set()).discard(session)
                pool._pools[pool_key].put_nowait(session)

                # Verify session is in pool
                assert pool._pools[pool_key].qsize() == 1

                # Set pool last used to old time to trigger eviction
                pool._pool_last_used[pool_key] = time.time() - 1000

                # Reset eviction timer and trigger
                pool._last_eviction_run = 0
                await pool._maybe_evict_idle_pool_keys()

                # Session should be reaped (closed) and pool key evicted
                assert pool._sessions_reaped == 1
                assert pool._pool_keys_evicted == 1
                assert len(pool._pools) == 0
                mock_close.assert_called_once()

        await pool.close_all()

    @pytest.mark.asyncio
    async def test_release_updates_last_used_before_removing_from_active(self):
        """release() should update _pool_last_used before removing from _active.

        This prevents a race where eviction sees the key as idle + inactive
        while release is in progress.
        """
        pool = MCPSessionPool(
            idle_pool_eviction_seconds=1000,  # Very long so eviction doesn't trigger
            session_ttl_seconds=300,
        )
        pool._eviction_run_interval = 1000  # Also disable throttled eviction

        with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
            mock_session = PooledSession(
                session=MagicMock(),
                transport_context=MagicMock(),
                url="http://test:8080",
                identity_key="anonymous",
                transport_type=TransportType.STREAMABLE_HTTP,
                headers={},
            )
            mock_create.return_value = mock_session

            # Acquire session (now in _active)
            session = await pool.acquire("http://test:8080")
            # simulate long-running tool call by setting old last_used time
            # Key structure: (user_hash, url, identity_hash, transport, gateway_id)
            pool_key = ("anonymous", "http://test:8080", "anonymous", "streamablehttp", "")
            pool._pool_last_used[pool_key] = time.time() - 1000

            # Release should update _pool_last_used
            await pool.release(session)

            # Verify pool_last_used was updated (should be recent, not 1000s ago)
            assert time.time() - pool._pool_last_used[pool_key] < 5

            # Verify key was NOT evicted
            assert pool_key in pool._pools
            assert pool._pool_keys_evicted == 0

            # Verify session is back in pool
            assert pool._pools[pool_key].qsize() == 1

            await pool.close_all()


class TestContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_pool_context_manager(self):
        """Test pool as async context manager."""
        async with MCPSessionPool() as pool:
            assert pool._closed is False

        assert pool._closed is True

    @pytest.mark.asyncio
    async def test_session_context_manager(self):
        """Test session context manager."""
        pool = MCPSessionPool()

        with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
            mock_session = PooledSession(
                session=MagicMock(),
                transport_context=MagicMock(),
                url="http://test:8080",
                identity_key="anonymous",
                transport_type=TransportType.STREAMABLE_HTTP,
                headers={},
            )
            mock_create.return_value = mock_session

            async with pool.session("http://test:8080") as pooled:
                assert pooled is not None
                assert pooled.session is not None

            # Session should be back in pool
            pool_key = ("anonymous", "http://test:8080", "anonymous", "streamablehttp", "")
            assert pool._pools[pool_key].qsize() == 1

        await pool.close_all()
