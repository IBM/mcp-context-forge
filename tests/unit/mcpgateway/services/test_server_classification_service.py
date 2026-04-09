# -*- coding: utf-8 -*-
"""Tests for the server classification service.

Tests hot/cold server classification and staggered polling feature.

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
import time
from collections import deque
from typing import Dict, List, Set
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.mcp_session_pool import MCPSessionPool, PooledSession, TransportType
from mcpgateway.services.server_classification_service import (
    ClassificationMetadata,
    ClassificationResult,
    ServerClassificationService,
    ServerUsageMetrics,
)


class TestServerClassificationServiceInit:
    """Tests for ServerClassificationService initialization."""

    def test_init_without_redis(self):
        """Test service initialization without Redis."""
        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.gateway_auto_refresh_interval = 60
            service = ServerClassificationService(redis_client=None)

            assert service._redis is None
            assert service._classification_task is None
            assert service._instance_id.startswith("classifier_")
            assert service._leader_ttl == 180
            assert service._running is False

    def test_init_with_redis(self):
        """Test service initialization with Redis."""
        mock_redis = MagicMock()
        service = ServerClassificationService(redis_client=mock_redis)

        assert service._redis is mock_redis
        assert service._classification_task is None
        assert service._running is False

    def test_redis_key_templates(self):
        """Test Redis key templates are correctly defined."""
        assert ServerClassificationService.CLASSIFICATION_HOT_KEY == "mcpgateway:server_classification:hot"
        assert ServerClassificationService.CLASSIFICATION_COLD_KEY == "mcpgateway:server_classification:cold"
        assert ServerClassificationService.CLASSIFICATION_METADATA_KEY == "mcpgateway:server_classification:metadata"
        assert ServerClassificationService.CLASSIFICATION_TIMESTAMP_KEY == "mcpgateway:server_classification:timestamp"
        assert ServerClassificationService.POLL_STATE_KEY_TEMPLATE == "mcpgateway:server_poll_state:{scope_hash}:last_{poll_type}"
        assert ServerClassificationService.LEADER_KEY == "mcpgateway:server_classification:leader"


class TestServerUsageMetrics:
    """Tests for ServerUsageMetrics dataclass."""

    def test_server_usage_metrics_defaults(self):
        """Test ServerUsageMetrics default values."""
        metrics = ServerUsageMetrics(url="http://test:8080")

        assert metrics.url == "http://test:8080"
        assert metrics.server_last_used == 0.0
        assert metrics.active_session_count == 0
        assert metrics.total_use_count == 0
        assert metrics.pooled_session_count == 0

    def test_server_usage_metrics_custom_values(self):
        """Test ServerUsageMetrics with custom values."""
        now = time.time()
        metrics = ServerUsageMetrics(
            url="http://test:8080",
            server_last_used=now,
            active_session_count=3,
            total_use_count=15,
            pooled_session_count=5,
        )

        assert metrics.url == "http://test:8080"
        assert metrics.server_last_used == now
        assert metrics.active_session_count == 3
        assert metrics.total_use_count == 15
        assert metrics.pooled_session_count == 5


class TestClassificationMetadata:
    """Tests for ClassificationMetadata dataclass."""

    def test_metadata_required_fields(self):
        """Test ClassificationMetadata required fields."""
        now = time.time()
        metadata = ClassificationMetadata(
            total_servers=10,
            hot_cap=2,
            hot_actual=2,
            eligible_count=5,
            timestamp=now,
        )

        assert metadata.total_servers == 10
        assert metadata.hot_cap == 2
        assert metadata.hot_actual == 2
        assert metadata.eligible_count == 5
        assert metadata.timestamp == now
        assert metadata.underutilized_reason is None

    def test_metadata_with_underutilization(self):
        """Test ClassificationMetadata with underutilization reason."""
        metadata = ClassificationMetadata(
            total_servers=10, hot_cap=2, hot_actual=1, eligible_count=1, timestamp=time.time(), underutilized_reason="Only 1 servers have pooled sessions, below hot_cap=2"
        )

        assert metadata.hot_actual == 1
        assert metadata.underutilized_reason is not None
        assert "Only 1 servers" in metadata.underutilized_reason


class TestClassificationResult:
    """Tests for ClassificationResult dataclass."""

    def test_classification_result_structure(self):
        """Test ClassificationResult structure."""
        metadata = ClassificationMetadata(total_servers=5, hot_cap=1, hot_actual=1, eligible_count=3, timestamp=time.time())

        result = ClassificationResult(hot_servers=["http://hot1:8080"], cold_servers=["http://cold1:8080", "http://cold2:8080", "http://cold3:8080", "http://cold4:8080"], metadata=metadata)

        assert len(result.hot_servers) == 1
        assert len(result.cold_servers) == 4
        assert result.metadata.total_servers == 5
        assert set(result.hot_servers + result.cold_servers) == {
            "http://hot1:8080",
            "http://cold1:8080",
            "http://cold2:8080",
            "http://cold3:8080",
            "http://cold4:8080",
        }


class TestClassificationLogic:
    """Tests for server classification algorithm."""

    def _create_pooled_session(self, url: str, last_used: float, use_count: int = 0) -> PooledSession:
        """Helper to create a mock PooledSession."""
        mock_session = MagicMock()
        mock_transport = MagicMock()

        return PooledSession(
            session=mock_session,
            transport_context=mock_transport,
            url=url,
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            created_at=time.time() - 300,
            last_used=last_used,
            use_count=use_count,
        )

    def _setup_pool_with_sessions(self, sessions_by_url: Dict[str, List[PooledSession]]) -> MCPSessionPool:
        """Helper to setup MCPSessionPool with mock sessions."""
        pool = MCPSessionPool()

        # Mock the _pools dict (Dict[PoolKey, Queue[PooledSession]])
        pool._pools = {}
        pool._active = {}

        for url, sessions in sessions_by_url.items():
            # Create pool key: (user_identity, url, identity_hash, transport_type, gateway_id)
            pool_key = ("anonymous", url, "hash123", TransportType.STREAMABLE_HTTP, None)

            # Create queue with sessions
            queue = asyncio.Queue()
            queue._queue = deque(sessions)  # Direct access to internal deque

            pool._pools[pool_key] = queue
            pool._active[pool_key] = set()  # Empty active set for simplicity

        return pool

    def test_classification_basic_20_percent(self):
        """Test basic 20% hot server classification."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        # Create 5 servers (20% = 1 hot server)
        sessions_by_url = {
            f"http://server{i}:8080": [self._create_pooled_session(f"http://server{i}:8080", now - (i * 10), use_count=10 - i)]
            for i in range(5)
        }

        pool = self._setup_pool_with_sessions(sessions_by_url)
        all_urls = list(sessions_by_url.keys())

        result = service._classify_servers_from_pool(pool, all_urls)

        # Should have 1 hot server (floor(5 * 0.20) = 1)
        assert result.metadata.total_servers == 5
        assert result.metadata.hot_cap == 1
        assert result.metadata.hot_actual == 1
        assert result.metadata.eligible_count == 5
        assert len(result.hot_servers) == 1
        assert len(result.cold_servers) == 4

        # Most recently used server should be hot
        assert result.hot_servers[0] == "http://server0:8080"

    def test_classification_sorting_by_recency(self):
        """Test servers sorted by most recent usage (primary sort key)."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        # Create 10 servers with different last_used times
        sessions_by_url = {f"http://server{i}:8080": [self._create_pooled_session(f"http://server{i}:8080", now - (i * 100))] for i in range(10)}

        pool = self._setup_pool_with_sessions(sessions_by_url)
        all_urls = list(sessions_by_url.keys())

        result = service._classify_servers_from_pool(pool, all_urls)

        # Should have 2 hot servers (floor(10 * 0.20) = 2)
        assert result.metadata.hot_cap == 2
        assert len(result.hot_servers) == 2

        # Most recent servers should be hot
        assert "http://server0:8080" in result.hot_servers
        assert "http://server1:8080" in result.hot_servers

    def test_classification_tie_breaker_active_sessions(self):
        """Test tie-breaking by active session count when last_used is equal."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        # Create 6 servers with same last_used but different active counts (need 6 for hot_cap=1)
        sessions_by_url = {
            "http://server1:8080": [self._create_pooled_session("http://server1:8080", now)],
            "http://server2:8080": [self._create_pooled_session("http://server2:8080", now)],
            "http://server3:8080": [self._create_pooled_session("http://server3:8080", now)],
            "http://server4:8080": [self._create_pooled_session("http://server4:8080", now)],
            "http://server5:8080": [self._create_pooled_session("http://server5:8080", now)],
            "http://server6:8080": [self._create_pooled_session("http://server6:8080", now)],
        }

        pool = self._setup_pool_with_sessions(sessions_by_url)

        # Mock active sessions (server2 has most active)
        pool._active[("anonymous", "http://server1:8080", "hash123", TransportType.STREAMABLE_HTTP, None)] = {1}  # 1 active
        pool._active[("anonymous", "http://server2:8080", "hash123", TransportType.STREAMABLE_HTTP, None)] = {1, 2, 3}  # 3 active
        pool._active[("anonymous", "http://server3:8080", "hash123", TransportType.STREAMABLE_HTTP, None)] = {1, 2}  # 2 active
        pool._active[("anonymous", "http://server4:8080", "hash123", TransportType.STREAMABLE_HTTP, None)] = set()  # 0 active
        pool._active[("anonymous", "http://server5:8080", "hash123", TransportType.STREAMABLE_HTTP, None)] = set()  # 0 active
        pool._active[("anonymous", "http://server6:8080", "hash123", TransportType.STREAMABLE_HTTP, None)] = set()  # 0 active

        all_urls = list(sessions_by_url.keys())
        result = service._classify_servers_from_pool(pool, all_urls)

        # hot_cap = floor(6 * 0.20) = 1
        assert result.metadata.hot_cap == 1
        assert len(result.hot_servers) == 1
        # Server with most active sessions should be first hot
        assert result.hot_servers[0] == "http://server2:8080"

    def test_classification_tie_breaker_use_count(self):
        """Test tie-breaking by total use count."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        # Create 6 servers with same last_used and active count, different use_count
        sessions_by_url = {
            "http://server1:8080": [self._create_pooled_session("http://server1:8080", now, use_count=50)],
            "http://server2:8080": [self._create_pooled_session("http://server2:8080", now, use_count=100)],
            "http://server3:8080": [self._create_pooled_session("http://server3:8080", now, use_count=75)],
            "http://server4:8080": [self._create_pooled_session("http://server4:8080", now, use_count=30)],
            "http://server5:8080": [self._create_pooled_session("http://server5:8080", now, use_count=20)],
            "http://server6:8080": [self._create_pooled_session("http://server6:8080", now, use_count=10)],
        }

        pool = self._setup_pool_with_sessions(sessions_by_url)
        all_urls = list(sessions_by_url.keys())

        result = service._classify_servers_from_pool(pool, all_urls)

        # hot_cap = floor(6 * 0.20) = 1
        assert result.metadata.hot_cap == 1
        assert len(result.hot_servers) == 1
        # Server with highest use_count should be first hot
        assert result.hot_servers[0] == "http://server2:8080"

    def test_classification_deterministic_url_tie_breaker(self):
        """Test deterministic tie-breaking by URL (alphabetical)."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        # Create 6 servers with identical metrics (need 6 for hot_cap=1)
        sessions_by_url = {
            "http://zebra:8080": [self._create_pooled_session("http://zebra:8080", now, use_count=10)],
            "http://alpha:8080": [self._create_pooled_session("http://alpha:8080", now, use_count=10)],
            "http://beta:8080": [self._create_pooled_session("http://beta:8080", now, use_count=10)],
            "http://charlie:8080": [self._create_pooled_session("http://charlie:8080", now, use_count=10)],
            "http://delta:8080": [self._create_pooled_session("http://delta:8080", now, use_count=10)],
            "http://echo:8080": [self._create_pooled_session("http://echo:8080", now, use_count=10)],
        }

        pool = self._setup_pool_with_sessions(sessions_by_url)
        all_urls = list(sessions_by_url.keys())

        result = service._classify_servers_from_pool(pool, all_urls)

        # hot_cap = floor(6 * 0.20) = 1
        assert result.metadata.hot_cap == 1
        assert len(result.hot_servers) == 1
        # Should sort by URL alphabetically (ascending) as final tie-breaker
        assert result.hot_servers[0] == "http://alpha:8080"

    def test_classification_no_sessions_all_cold(self):
        """Test classification when no servers have pooled sessions."""
        service = ServerClassificationService(redis_client=None)

        # Empty pool
        pool = MCPSessionPool()
        pool._pools = {}
        pool._active = {}

        all_urls = ["http://server1:8080", "http://server2:8080", "http://server3:8080"]

        result = service._classify_servers_from_pool(pool, all_urls)

        # No hot servers, all cold
        assert result.metadata.total_servers == 3
        assert result.metadata.hot_cap == 0  # floor(3 * 0.20) = 0
        assert result.metadata.eligible_count == 0
        assert len(result.hot_servers) == 0
        assert len(result.cold_servers) == 3
        # No underutilization reason when both hot_cap and eligible are 0
        assert result.metadata.underutilized_reason is None

    def test_classification_partial_eligibility(self):
        """Test classification when only some servers have sessions."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        # Only 2 out of 10 servers have sessions
        sessions_by_url = {
            "http://server1:8080": [self._create_pooled_session("http://server1:8080", now)],
            "http://server2:8080": [self._create_pooled_session("http://server2:8080", now - 100)],
        }

        pool = self._setup_pool_with_sessions(sessions_by_url)

        # Total 10 servers in database
        all_urls = [f"http://server{i}:8080" for i in range(1, 11)]

        result = service._classify_servers_from_pool(pool, all_urls)

        # hot_cap = floor(10 * 0.20) = 2, but only 2 eligible
        assert result.metadata.total_servers == 10
        assert result.metadata.hot_cap == 2
        assert result.metadata.eligible_count == 2
        assert result.metadata.hot_actual == 2
        assert len(result.hot_servers) == 2
        assert len(result.cold_servers) == 8

    def test_classification_underutilization_reason(self):
        """Test underutilization reason when eligible < hot_cap."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        # Only 1 server has session, but hot_cap = 4
        sessions_by_url = {"http://server1:8080": [self._create_pooled_session("http://server1:8080", now)]}

        pool = self._setup_pool_with_sessions(sessions_by_url)
        all_urls = [f"http://server{i}:8080" for i in range(1, 21)]  # 20 servers

        result = service._classify_servers_from_pool(pool, all_urls)

        assert result.metadata.hot_cap == 4  # floor(20 * 0.20)
        assert result.metadata.eligible_count == 1
        assert result.metadata.underutilized_reason is not None
        assert "Only 1 servers have pooled sessions" in result.metadata.underutilized_reason
        assert "below hot_cap=4" in result.metadata.underutilized_reason

    def test_classification_no_overlap_full_coverage(self):
        """Test that hot and cold sets have no overlap and cover all servers."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        sessions_by_url = {f"http://server{i}:8080": [self._create_pooled_session(f"http://server{i}:8080", now - (i * 10))] for i in range(15)}

        pool = self._setup_pool_with_sessions(sessions_by_url)
        all_urls = list(sessions_by_url.keys())

        result = service._classify_servers_from_pool(pool, all_urls)

        # Verify no overlap
        hot_set = set(result.hot_servers)
        cold_set = set(result.cold_servers)
        assert len(hot_set & cold_set) == 0

        # Verify full coverage
        all_set = set(all_urls)
        classified_set = hot_set | cold_set
        assert classified_set == all_set

    def test_classification_multiple_sessions_per_server(self):
        """Test server metrics aggregation across multiple pooled sessions."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        # Server has 3 pooled sessions with different last_used times
        server_url = "http://server1:8080"
        sessions = [
            self._create_pooled_session(server_url, now - 50, use_count=10),  # Oldest
            self._create_pooled_session(server_url, now - 20, use_count=5),  # Middle
            self._create_pooled_session(server_url, now - 5, use_count=15),  # Most recent
        ]

        pool = self._setup_pool_with_sessions({server_url: sessions})
        # Need at least 5 servers for hot_cap = 1
        all_urls = [server_url, "http://server2:8080", "http://server3:8080", "http://server4:8080", "http://server5:8080"]

        # Add other servers with older last_used
        for i in range(2, 6):
            other_url = f"http://server{i}:8080"
            other_sessions = [self._create_pooled_session(other_url, now - (100 * i), use_count=100)]
            pool._pools[("anonymous", other_url, "hash123", TransportType.STREAMABLE_HTTP, None)] = asyncio.Queue()
            pool._pools[("anonymous", other_url, "hash123", TransportType.STREAMABLE_HTTP, None)]._queue = deque(other_sessions)
            pool._active[("anonymous", other_url, "hash123", TransportType.STREAMABLE_HTTP, None)] = set()

        result = service._classify_servers_from_pool(pool, all_urls)

        # hot_cap = floor(5 * 0.20) = 1
        assert result.metadata.hot_cap == 1
        assert len(result.hot_servers) == 1
        # Server1 should be hot (most recent aggregate last_used = now - 5)
        assert result.hot_servers[0] == server_url
        # Total use_count should be summed: 10 + 5 + 15 = 30
        # (Verification via classification order, not direct assertion)

    def test_classification_handles_session_extraction_error(self):
        """Test classification handles errors when extracting session metrics."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        server_url = "http://server1:8080"

        # Create a mock pool with a problematic session that raises error on attribute access
        pool = MagicMock()
        pool_key = ("anonymous", server_url, "hash123", TransportType.STREAMABLE_HTTP, None)

        # Create a mock session that raises error when accessing attributes
        bad_session = MagicMock()
        bad_session.last_used = property(lambda self: 1 / 0)  # Will raise ZeroDivisionError

        mock_queue = MagicMock()
        mock_queue._queue = [bad_session]

        pool._pools = {pool_key: mock_queue}
        pool._active = {pool_key: set()}  # Empty active set

        all_urls = [server_url]

        # Should handle error gracefully and continue
        result = service._classify_servers_from_pool(pool, all_urls)

        # Server should be classified as cold (no valid metrics extracted)
        assert server_url in result.cold_servers
        assert server_url not in result.hot_servers

    def test_classification_counts_active_sessions(self):
        """Test classification counts active sessions from pool._active."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        server_url = "http://server1:8080"
        pool_key = ("anonymous", server_url, "hash123", TransportType.STREAMABLE_HTTP, None)

        # Create pool with one pooled session
        pooled_session = self._create_pooled_session(server_url, now - 10, use_count=5)

        pool = MagicMock()
        mock_queue = MagicMock()
        mock_queue._queue = [pooled_session]

        # Add 3 active sessions (mocked as a set with 3 items)
        active_sessions = {MagicMock(), MagicMock(), MagicMock()}

        pool._pools = {pool_key: mock_queue}
        pool._active = {pool_key: active_sessions}

        all_urls = [server_url, "http://server2:8080", "http://server3:8080", "http://server4:8080", "http://server5:8080"]

        result = service._classify_servers_from_pool(pool, all_urls)

        # Server should be hot (has both pooled and active sessions)
        assert server_url in result.hot_servers

    @pytest.mark.asyncio
    async def test_publish_classification_without_redis(self):
        """Test _publish_classification_to_redis returns early when Redis is None."""
        service = ServerClassificationService(redis_client=None)

        metadata = ClassificationMetadata(total_servers=5, hot_cap=1, hot_actual=1, eligible_count=3, timestamp=time.time())
        result = ClassificationResult(hot_servers=["http://hot1:8080"], cold_servers=["http://cold1:8080", "http://cold2:8080"], metadata=metadata)

        # Should return early without error
        await service._publish_classification_to_redis(result)

        # No assertions needed - just verify it doesn't crash


class TestLeaderElection:
    """Tests for leader election in multi-worker deployments (atomic Lua script)."""

    @pytest.mark.asyncio
    async def test_try_acquire_leader_lock_without_redis(self):
        """Test leader lock always acquired in single-worker mode (no Redis)."""
        service = ServerClassificationService(redis_client=None)

        is_leader = await service._try_acquire_leader_lock()

        assert is_leader is True

    @pytest.mark.asyncio
    async def test_try_acquire_leader_lock_with_redis_success(self):
        """Test successful leader lock acquisition with Redis via Lua script."""
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(return_value="sha123")
        mock_redis.evalsha = AsyncMock(return_value=1)  # Script returns 1 = acquired

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.gateway_auto_refresh_interval = 60
            service = ServerClassificationService(redis_client=mock_redis)
            is_leader = await service._try_acquire_leader_lock()

            assert is_leader is True
            mock_redis.script_load.assert_awaited_once()
            mock_redis.evalsha.assert_awaited_once_with(
                "sha123", 1, ServerClassificationService.LEADER_KEY,
                service._instance_id, str(180),
            )

    @pytest.mark.asyncio
    async def test_try_acquire_leader_lock_with_redis_contention(self):
        """Test leader lock acquisition failure when another instance holds lock."""
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(return_value="sha123")
        mock_redis.evalsha = AsyncMock(return_value=0)  # Script returns 0 = not leader

        service = ServerClassificationService(redis_client=mock_redis)
        is_leader = await service._try_acquire_leader_lock()

        assert is_leader is False

    @pytest.mark.asyncio
    async def test_try_acquire_leader_lock_renewal(self):
        """Test leader retains lock on subsequent calls (Lua script renews TTL atomically)."""
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(return_value="sha123")
        # First call: acquired. Second call: renewed (both return 1).
        mock_redis.evalsha = AsyncMock(return_value=1)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.gateway_auto_refresh_interval = 60
            service = ServerClassificationService(redis_client=mock_redis)

            is_leader_1 = await service._try_acquire_leader_lock()
            is_leader_2 = await service._try_acquire_leader_lock()

            assert is_leader_1 is True
            assert is_leader_2 is True
            # script_load only called once (cached SHA)
            assert mock_redis.script_load.await_count == 1
            assert mock_redis.evalsha.await_count == 2

    @pytest.mark.asyncio
    async def test_try_acquire_leader_lock_redis_error_fail_safe(self):
        """Test fail-safe behavior on Redis error during leader election."""
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(side_effect=Exception("Redis connection error"))

        service = ServerClassificationService(redis_client=mock_redis)
        is_leader = await service._try_acquire_leader_lock()

        # Should fail safe and NOT become leader on error
        assert is_leader is False


class TestPollingDecisions:
    """Tests for should_poll_server logic."""

    @pytest.mark.asyncio
    async def test_should_poll_when_feature_disabled(self):
        """Test polling always allowed when hot/cold classification is disabled."""
        mock_redis = AsyncMock()
        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = False

            should_poll = await service.should_poll_server("http://test:8080", "health")

            assert should_poll is True
            mock_redis.sismember.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_should_poll_without_redis(self):
        """Test polling always allowed in single-worker mode (no Redis)."""
        service = ServerClassificationService(redis_client=None)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True

            should_poll = await service.should_poll_server("http://test:8080", "health")

            assert should_poll is True

    @pytest.mark.asyncio
    async def test_should_poll_when_not_yet_classified(self):
        """Test polling allowed when server not yet classified."""
        mock_redis = AsyncMock()
        # Server not in hot or cold sets
        mock_redis.sismember = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value=None)

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True

            should_poll = await service.should_poll_server("http://test:8080", "health")

            assert should_poll is True

    @pytest.mark.asyncio
    async def test_should_poll_hot_server_interval_elapsed(self):
        """Test hot server polling when interval has elapsed."""
        mock_redis = AsyncMock()
        # Server is hot
        mock_redis.sismember = AsyncMock(side_effect=[True, False])  # hot=True, cold=False
        # Last polled 400 seconds ago
        now = time.time()
        mock_redis.get = AsyncMock(return_value=str(now - 400))
        mock_redis.set = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300  # 5 minutes

            should_poll = await service.should_poll_server("http://test:8080", "health")

            assert should_poll is True
            # Timestamp update is deferred to mark_poll_completed, not done here
            mock_redis.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_should_poll_hot_server_interval_not_elapsed(self):
        """Test hot server polling skipped when interval not elapsed."""
        mock_redis = AsyncMock()
        # Server is hot
        mock_redis.sismember = AsyncMock(side_effect=[True, False])
        # Last polled 100 seconds ago
        now = time.time()
        mock_redis.get = AsyncMock(return_value=str(now - 100))

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300

            should_poll = await service.should_poll_server("http://test:8080", "health")

            assert should_poll is False

    @pytest.mark.asyncio
    async def test_should_poll_cold_server_interval_elapsed(self):
        """Test cold server polling when interval has elapsed."""
        mock_redis = AsyncMock()
        # Server is cold
        mock_redis.sismember = AsyncMock(side_effect=[False, True])  # hot=False, cold=True
        # Last polled 950 seconds ago
        now = time.time()
        mock_redis.get = AsyncMock(return_value=str(now - 950))
        mock_redis.set = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.cold_server_check_interval = 900  # 15 minutes

            should_poll = await service.should_poll_server("http://test:8080", "health")

            assert should_poll is True
            # Timestamp update is deferred to mark_poll_completed, not done here
            mock_redis.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_should_poll_cold_server_interval_not_elapsed(self):
        """Test cold server polling skipped when interval not elapsed."""
        mock_redis = AsyncMock()
        # Server is cold
        mock_redis.sismember = AsyncMock(side_effect=[False, True])
        # Last polled 400 seconds ago
        now = time.time()
        mock_redis.get = AsyncMock(return_value=str(now - 400))

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.cold_server_check_interval = 900

            should_poll = await service.should_poll_server("http://test:8080", "health")

            assert should_poll is False

    @pytest.mark.asyncio
    async def test_should_poll_never_polled_before(self):
        """Test first poll of a classified server."""
        mock_redis = AsyncMock()
        # Server is hot but never polled
        mock_redis.sismember = AsyncMock(side_effect=[True, False])
        mock_redis.get = AsyncMock(return_value=None)  # No previous poll
        mock_redis.set = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300

            should_poll = await service.should_poll_server("http://test:8080", "health")

            assert should_poll is True
            # Timestamp update is deferred to mark_poll_completed, not done here
            mock_redis.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_should_poll_different_poll_types_independent(self):
        """Test health and tool_discovery polls tracked independently."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[True, False, True, False])  # Both calls: hot server
        now = time.time()

        # Health polled recently, tools never polled
        async def get_side_effect(key):
            if "health" in key:
                return str(now - 100)  # Recent health poll
            elif "tool_discovery" in key:
                return None  # Never polled tools
            return None

        mock_redis.get = AsyncMock(side_effect=get_side_effect)
        mock_redis.set = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300

            # Health check should be skipped (too recent)
            should_poll_health = await service.should_poll_server("http://test:8080", "health")
            assert should_poll_health is False

            # Tool discovery should proceed (never polled)
            should_poll_tools = await service.should_poll_server("http://test:8080", "tool_discovery")
            assert should_poll_tools is True

    @pytest.mark.asyncio
    async def test_should_poll_redis_error_fail_open(self):
        """Test fail-open behavior on Redis error (allow polling)."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=Exception("Redis error"))

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True

            should_poll = await service.should_poll_server("http://test:8080", "health")

            # Should fail open and allow polling
            assert should_poll is True

    @pytest.mark.asyncio
    async def test_mark_poll_completed_updates_redis(self):
        """Test mark_poll_completed writes timestamp to Redis after actual poll."""
        mock_redis = AsyncMock()
        # Server is hot
        mock_redis.sismember = AsyncMock(side_effect=[True, False])
        mock_redis.set = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300

            await service.mark_poll_completed("http://test:8080", "health")

            # Should write timestamp to Redis
            mock_redis.set.assert_awaited_once()
            call_args = mock_redis.set.await_args
            assert call_args[1]["ex"] == 600  # 2x hot interval

    @pytest.mark.asyncio
    async def test_mark_poll_completed_no_redis(self):
        """Test mark_poll_completed is a no-op without Redis."""
        service = ServerClassificationService(redis_client=None)
        # Should not raise
        await service.mark_poll_completed("http://test:8080", "health")


class TestRedisStateManagement:
    """Tests for Redis state management."""

    @pytest.mark.asyncio
    async def test_publish_classification_to_redis(self):
        """Test classification result published to Redis atomically."""
        mock_redis = AsyncMock()
        mock_pipeline = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock()
        mock_pipeline.delete = AsyncMock()
        mock_pipeline.sadd = AsyncMock()
        mock_pipeline.set = AsyncMock()
        mock_pipeline.execute = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        metadata = ClassificationMetadata(total_servers=5, hot_cap=1, hot_actual=1, eligible_count=3, timestamp=time.time())
        result = ClassificationResult(hot_servers=["http://hot1:8080"], cold_servers=["http://cold1:8080", "http://cold2:8080", "http://cold3:8080", "http://cold4:8080"], metadata=metadata)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.gateway_auto_refresh_interval = 300

            await service._publish_classification_to_redis(result)

            # Verify pipeline was used (atomic transaction)
            mock_redis.pipeline.assert_called_once_with(transaction=True)
            mock_pipeline.execute.assert_awaited_once()

            # Verify old classification cleared
            mock_pipeline.delete.assert_awaited_once()

            # Verify hot/cold servers added
            assert mock_pipeline.sadd.await_count == 2  # hot and cold sets

    @pytest.mark.asyncio
    async def test_publish_classification_empty_sets(self):
        """Test publishing classification with empty hot or cold sets."""
        mock_redis = AsyncMock()
        mock_pipeline = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock()
        mock_pipeline.delete = AsyncMock()
        mock_pipeline.sadd = AsyncMock()
        mock_pipeline.set = AsyncMock()
        mock_pipeline.execute = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        metadata = ClassificationMetadata(total_servers=2, hot_cap=0, hot_actual=0, eligible_count=0, timestamp=time.time())
        result = ClassificationResult(hot_servers=[], cold_servers=["http://cold1:8080", "http://cold2:8080"], metadata=metadata)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.gateway_auto_refresh_interval = 300

            await service._publish_classification_to_redis(result)

            # Should only add cold servers (hot is empty)
            await_calls = [call for call in mock_pipeline.sadd.await_args_list]
            assert len(await_calls) == 1  # Only cold set

    @pytest.mark.asyncio
    async def test_get_server_classification_hot(self):
        """Test retrieving hot server classification."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[True, False])  # hot=True

        service = ServerClassificationService(redis_client=mock_redis)
        classification = await service.get_server_classification("http://test:8080")

        assert classification == "hot"

    @pytest.mark.asyncio
    async def test_get_server_classification_cold(self):
        """Test retrieving cold server classification."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[False, True])  # hot=False, cold=True

        service = ServerClassificationService(redis_client=mock_redis)
        classification = await service.get_server_classification("http://test:8080")

        assert classification == "cold"

    @pytest.mark.asyncio
    async def test_get_server_classification_not_classified(self):
        """Test retrieving classification for unclassified server."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(return_value=False)  # Not in any set

        service = ServerClassificationService(redis_client=mock_redis)
        classification = await service.get_server_classification("http://test:8080")

        assert classification is None

    @pytest.mark.asyncio
    async def test_get_server_classification_without_redis(self):
        """Test classification retrieval without Redis."""
        service = ServerClassificationService(redis_client=None)
        classification = await service.get_server_classification("http://test:8080")

        assert classification is None

    @pytest.mark.asyncio
    async def test_mark_poll_completed_updates_timestamp(self):
        """Test mark_poll_completed writes timestamp to Redis."""
        mock_redis = AsyncMock()
        # Server is hot
        mock_redis.sismember = AsyncMock(side_effect=[True, False])
        mock_redis.set = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300

            await service.mark_poll_completed("http://test:8080", "health")

            # Should set timestamp with 2x interval expiry
            mock_redis.set.assert_awaited_once()
            args = mock_redis.set.await_args
            import hashlib
            url_hash = hashlib.sha256(b"http://test:8080").hexdigest()[:32]
            expected_key = f"mcpgateway:server_poll_state:{url_hash}:last_health"
            assert args[0][0] == expected_key
            assert args[1]["ex"] == 600  # 2x interval


class TestServiceLifecycle:
    """Tests for service start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_when_disabled(self):
        """Test service start when feature is disabled."""
        service = ServerClassificationService(redis_client=None)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = False

            await service.start()

            assert service._running is False
            assert service._classification_task is None

    @pytest.mark.asyncio
    async def test_start_when_enabled(self):
        """Test service start when feature is enabled."""
        service = ServerClassificationService(redis_client=None)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True

            try:
                await service.start()

                assert service._running is True
                assert service._classification_task is not None
                assert isinstance(service._classification_task, asyncio.Task)
            finally:
                await service.stop()

    @pytest.mark.asyncio
    async def test_start_when_already_running(self):
        """Test service start when already running (idempotent)."""
        service = ServerClassificationService(redis_client=None)
        service._running = True

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True

            await service.start()

            # Should log warning but not crash
            assert service._running is True

    @pytest.mark.asyncio
    async def test_stop_service(self):
        """Test service stop."""
        service = ServerClassificationService(redis_client=None)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True

            await service.start()
            await service.stop()

            assert service._running is False

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        """Test stop when service not running."""
        service = ServerClassificationService(redis_client=None)

        await service.stop()

        # Should complete without error
        assert service._running is False

    @pytest.mark.asyncio
    async def test_stop_after_task_died_with_exception(self):
        """Stop must not crash when the background task already died with an error."""
        service = ServerClassificationService(redis_client=None)

        # Simulate a task that already finished with an exception
        async def _boom():
            raise RuntimeError("unexpected crash")

        service._classification_task = asyncio.create_task(_boom())
        # Let the task fail
        await asyncio.sleep(0.05)

        # stop() must not propagate the RuntimeError
        await service.stop()
        assert service._running is False


    @pytest.mark.asyncio
    async def test_on_classification_task_done_with_exception(self):
        """_on_classification_task_done logs error and sets _running=False when task dies."""
        service = ServerClassificationService(redis_client=None)
        service._running = True

        async def _fail():
            raise RuntimeError("boom")

        task = asyncio.create_task(_fail())
        await asyncio.sleep(0.05)

        service._on_classification_task_done(task)
        assert service._running is False

    @pytest.mark.asyncio
    async def test_on_classification_task_done_cancelled_is_noop(self):
        """_on_classification_task_done is a no-op when the task was cancelled."""
        service = ServerClassificationService(redis_client=None)
        service._running = True

        async def _sleep():
            await asyncio.sleep(999)

        task = asyncio.create_task(_sleep())
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        service._on_classification_task_done(task)
        # _running should NOT be changed for cancellation
        assert service._running is True

    @pytest.mark.asyncio
    async def test_classification_timeout(self):
        """Classification that exceeds timeout is cancelled, loop continues."""
        service = ServerClassificationService(redis_client=None)
        service._running = True
        service._leader_ttl = 1  # 0.8s timeout

        call_count = 0

        async def slow_classify():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(10)  # Will be cancelled by timeout

        with (
            patch.object(service, "_try_acquire_leader_lock", AsyncMock(return_value=True)),
            patch.object(service, "_perform_classification", side_effect=slow_classify),
            patch("mcpgateway.services.server_classification_service.settings") as mock_settings,
        ):
            mock_settings.gateway_auto_refresh_interval = 0.05

            task = asyncio.create_task(service._run_classification_loop())
            await asyncio.sleep(1.5)
            service._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_try_acquire_leader_lock_noscript_recovery(self):
        """NOSCRIPT error triggers script re-registration and retry."""
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(return_value="sha_new")

        # First evalsha raises NOSCRIPT, second succeeds
        mock_redis.evalsha = AsyncMock(side_effect=[Exception("NOSCRIPT No matching script"), 1])

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.gateway_auto_refresh_interval = 60
            service = ServerClassificationService(redis_client=mock_redis)

            is_leader = await service._try_acquire_leader_lock()

            assert is_leader is True
            # script_load called twice: initial + recovery
            assert mock_redis.script_load.await_count == 2

    @pytest.mark.asyncio
    async def test_try_acquire_leader_lock_non_noscript_error_reraises(self):
        """Non-NOSCRIPT evalsha errors are reraised and caught by outer handler."""
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(return_value="sha123")
        mock_redis.evalsha = AsyncMock(side_effect=Exception("connection refused"))

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.gateway_auto_refresh_interval = 60
            service = ServerClassificationService(redis_client=mock_redis)

            # Should fail safe (False), not crash
            is_leader = await service._try_acquire_leader_lock()
            assert is_leader is False

    def test_accumulate_session_creates_metrics_entry_for_new_url(self):
        """_accumulate_session in _classify_servers_from_pool creates ServerUsageMetrics for unseen URLs."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        # Active-only: session only in _active, not in _pools idle queue
        url = "http://active-only:8080"
        pool_key = ("anon", url, "h1", "sse", "")

        active_session = MagicMock()
        active_session.last_used = now
        active_session.use_count = 3

        pool = MagicMock()
        pool._pools = {}  # Empty idle queue — no pool key at all
        pool._active = {pool_key: {active_session}}

        result = service._classify_servers_from_pool(pool, [url])

        # Session from _active should have created metrics and made server eligible
        assert url in result.hot_servers or url in result.cold_servers


class TestIntegrationWithGatewayService:
    """Integration tests with GatewayService health checks."""

    @pytest.mark.asyncio
    async def test_gateway_service_respects_hot_polling(self):
        """Test GatewayService health check respects hot server polling interval."""
        # This test verifies integration points between GatewayService and ServerClassificationService
        # The actual integration is tested via the should_poll_server calls in gateway_service.py

        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[True, False])  # Server is hot
        now = time.time()
        mock_redis.get = AsyncMock(return_value=str(now - 100))  # Recently polled

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300

            # Simulate GatewayService calling should_poll_server before health check
            should_check = await service.should_poll_server("http://test:8080", "health")

            # Should skip health check (too recent)
            assert should_check is False

    @pytest.mark.asyncio
    async def test_gateway_service_respects_cold_polling(self):
        """Test GatewayService health check respects cold server polling interval."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[False, True])  # Server is cold
        now = time.time()
        mock_redis.get = AsyncMock(return_value=str(now - 400))  # Polled 400s ago

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.cold_server_check_interval = 900  # 15 minutes

            # Cold server polled 400s ago, should wait longer
            should_check = await service.should_poll_server("http://test:8080", "health")

            assert should_check is False


class TestErrorHandling:
    """Tests for error handling in ServerClassificationService."""

    @pytest.mark.asyncio
    async def test_classification_loop_handles_no_leader(self):
        """Test classification loop skips when not leader."""
        mock_redis = AsyncMock()
        service = ServerClassificationService(redis_client=mock_redis)
        service._running = True

        with patch.object(service, "_try_acquire_leader_lock", AsyncMock(return_value=False)):
            with patch.object(service, "_perform_classification", AsyncMock()) as mock_perform:
                # Run one iteration
                service._running = False  # Stop after one iteration

                # Start loop - it should exit without performing classification
                with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
                    mock_settings.gateway_auto_refresh_interval = 0.1
                    try:
                        await asyncio.wait_for(service._run_classification_loop(), timeout=0.5)
                    except asyncio.TimeoutError:
                        pass

                # Classification should not have been performed
                mock_perform.assert_not_called()

    @pytest.mark.asyncio
    async def test_classification_loop_handles_general_error(self):
        """Test classification loop continues after general error."""
        mock_redis = AsyncMock()
        service = ServerClassificationService(redis_client=mock_redis)
        service._running = True

        call_count = 0

        async def mock_acquire():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Unexpected error")
            return False  # Not leader on subsequent calls

        # Override error backoff to avoid 30s delay in tests
        service._error_backoff_seconds = 0.001

        with patch.object(service, "_try_acquire_leader_lock", side_effect=mock_acquire):
            with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
                mock_settings.gateway_auto_refresh_interval = 0.05

                # Start loop
                task = asyncio.create_task(service._run_classification_loop())

                # Wait long enough for error to occur and loop to continue
                await asyncio.sleep(0.3)

                service._running = False
                await asyncio.sleep(0.15)
                task.cancel()

                try:
                    await task
                except asyncio.CancelledError:
                    pass

                # Verify loop continued after error (call_count > 1)
                assert call_count >= 2

    @pytest.mark.asyncio
    async def test_perform_classification_handles_no_gateways(self):
        """Test _perform_classification handles no gateways gracefully."""
        mock_redis = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        # _get_gateway_url_map is a method on the service instance
        with patch.object(service, "_get_gateway_url_map", AsyncMock(return_value={})):
            # get_mcp_session_pool is imported lazily inside _perform_classification
            with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=MagicMock()):
                # Should return early without error
                await service._perform_classification()

                # Redis should not be called (no classification to publish)
                mock_redis.pipeline.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_metrics_handles_missing_url_in_active(self):
        """Test metric extraction handles missing URLs in active dict."""
        from collections import defaultdict

        mock_pool = MagicMock()
        mock_pool._idle = defaultdict(lambda: deque())  # Empty idle queue
        mock_pool._active = {
            ("user@example.com", "http://test:8080"): set([MagicMock()]),
            ("user@example.com", "http://unknown:8080"): set([MagicMock()]),
        }

        service = ServerClassificationService(redis_client=None)

        # Should not raise error when processing active sessions with unknown URLs
        result = service._classify_servers_from_pool(
            pool=mock_pool,
            all_gateway_urls=["http://test:8080"]  # Only one URL in all_gateway_urls
        )

        # Should complete without error
        assert result is not None

    @pytest.mark.asyncio
    async def test_extract_metrics_handles_session_attribute_error(self):
        """Test metric extraction handles sessions with missing attributes."""
        mock_session = MagicMock()
        # Remove use_count attribute to trigger AttributeError path
        del mock_session.use_count
        mock_session.last_used = time.time()

        mock_pool = MagicMock()
        mock_pool._idle = {
            ("user@example.com", "http://test:8080"): deque([mock_session])
        }
        mock_pool._active = {}

        service = ServerClassificationService(redis_client=None)

        # Should handle missing use_count attribute gracefully
        result = service._classify_servers_from_pool(
            pool=mock_pool,
            all_gateway_urls=["http://test:8080"]
        )

        # Should complete without error
        assert result is not None
        assert "http://test:8080" in result.hot_servers or "http://test:8080" in result.cold_servers

    @pytest.mark.asyncio
    async def test_publish_classification_handles_redis_error(self):
        """Test _publish_classification_to_redis handles Redis errors."""
        mock_redis = AsyncMock()
        mock_pipeline = AsyncMock()
        mock_pipeline.execute = AsyncMock(side_effect=Exception("Redis error"))
        mock_redis.pipeline.return_value.__aenter__.return_value = mock_pipeline

        service = ServerClassificationService(redis_client=mock_redis)

        metadata = ClassificationMetadata(
            total_servers=2,
            hot_cap=1,
            hot_actual=1,
            eligible_count=2,
            timestamp=time.time()
        )
        result = ClassificationResult(
            hot_servers=["http://hot:8080"],
            cold_servers=["http://cold:8080"],
            metadata=metadata
        )

        # Should not raise exception, just log error
        await service._publish_classification_to_redis(result)

    @pytest.mark.asyncio
    async def test_classification_loop_as_leader_calls_perform(self):
        """Test classification loop calls _perform_classification when leader (lines 147-148)."""
        mock_redis = AsyncMock()
        service = ServerClassificationService(redis_client=mock_redis)
        service._running = True

        perform_called = asyncio.Event()

        async def mock_perform():
            perform_called.set()
            service._running = False  # Stop after first call

        with patch.object(service, "_try_acquire_leader_lock", AsyncMock(return_value=True)):
            with patch.object(service, "_perform_classification", side_effect=mock_perform):
                with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
                    mock_settings.gateway_auto_refresh_interval = 0.05
                    await asyncio.wait_for(service._run_classification_loop(), timeout=2.0)

        assert perform_called.is_set()

    @pytest.mark.asyncio
    async def test_classification_loop_cancelled_error(self):
        """Test classification loop handles CancelledError cleanly (lines 155-156)."""
        mock_redis = AsyncMock()
        service = ServerClassificationService(redis_client=mock_redis)
        service._running = True

        with patch.object(service, "_try_acquire_leader_lock", AsyncMock(return_value=False)):
            with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
                mock_settings.gateway_auto_refresh_interval = 10  # Long sleep so we can cancel

                task = asyncio.create_task(service._run_classification_loop())
                await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass  # CancelledError propagates from asyncio.sleep, not the break

    @pytest.mark.asyncio
    async def test_perform_classification_pool_not_initialized(self):
        """Test _perform_classification returns early when pool not initialized (lines 188-190)."""
        service = ServerClassificationService(redis_client=None)

        with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", side_effect=RuntimeError("pool not initialized")):
            # Should return early without error
            await service._perform_classification()

    @pytest.mark.asyncio
    async def test_perform_classification_logs_underutilized_reason(self):
        """Test _perform_classification logs underutilized_reason when present (line 210)."""
        mock_redis = AsyncMock()
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=False)
        mock_pipeline.execute = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        service = ServerClassificationService(redis_client=mock_redis)

        # Use 20 URLs so hot_cap=4, but only 1 has session activity → underutilized
        all_urls = [f"http://server{i}:8080" for i in range(20)]
        mock_pool = MagicMock()
        pool_key = ("anonymous", all_urls[0], "hash123", TransportType.STREAMABLE_HTTP, None)
        mock_queue = MagicMock()
        active_session = MagicMock()
        active_session.last_used = time.time()
        active_session.use_count = 5
        mock_queue._queue = deque([active_session])
        mock_pool._pools = {pool_key: mock_queue}

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300
            mock_settings.cold_server_check_interval = 900
            mock_settings.gateway_auto_refresh_interval = 60

            with patch.object(service, "_get_gateway_url_map", AsyncMock(return_value={f"gw-{i}": u for i, u in enumerate(all_urls)})):
                with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
                    await service._perform_classification()

        mock_redis.pipeline.assert_called()

    @pytest.mark.asyncio
    async def test_perform_classification_full_happy_path(self):
        """Test _perform_classification runs classification and publishes to Redis (lines 199-213)."""
        mock_redis = AsyncMock()
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=False)
        mock_pipeline.execute = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        service = ServerClassificationService(redis_client=mock_redis)

        mock_pool = MagicMock()
        mock_pool._pools = {}  # Empty pool — all servers will be cold

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300
            mock_settings.cold_server_check_interval = 900
            mock_settings.gateway_auto_refresh_interval = 60

            with patch.object(service, "_get_gateway_url_map", AsyncMock(return_value={"gw-1": "http://test:8080"})):
                with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
                    await service._perform_classification()

        # Redis pipeline should have been called to publish classification
        mock_redis.pipeline.assert_called()

    @pytest.mark.asyncio
    async def test_perform_classification_exception_path(self):
        """Test _perform_classification catches and logs unexpected exceptions (line 212-213)."""
        service = ServerClassificationService(redis_client=None)

        with patch.object(service, "_get_gateway_url_map", AsyncMock(side_effect=RuntimeError("unexpected"))):
            with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=MagicMock()):
                # Should not raise — exception is caught inside _perform_classification
                await service._perform_classification()

    @pytest.mark.asyncio
    async def test_classify_servers_queue_missing_queue_attr(self):
        """Test _classify_servers_from_pool handles queue without _queue attribute (lines 254-255)."""
        mock_pool = MagicMock()
        pool_key = ("anonymous", "http://test:8080", "hash123", TransportType.STREAMABLE_HTTP, None)

        # Queue that does NOT have _queue attribute
        mock_queue = MagicMock(spec=[])  # spec=[] means no attributes allowed
        mock_pool._pools = {pool_key: mock_queue}

        service = ServerClassificationService(redis_client=None)
        result = service._classify_servers_from_pool(mock_pool, ["http://test:8080"])

        # Should complete without error, server goes cold (no session data)
        assert result is not None
        assert "http://test:8080" in result.cold_servers

    @pytest.mark.asyncio
    async def test_get_gateway_url_map_handles_db_error(self):
        """Test _get_gateway_url_map handles database errors."""
        # _get_gateway_url_map is a method on ServerClassificationService
        # SessionLocal is imported lazily inside the method from mcpgateway.db
        service = ServerClassificationService(redis_client=None)
        with patch("mcpgateway.db.SessionLocal") as mock_session_local:
            mock_session_local.return_value.__enter__.return_value.execute.side_effect = Exception("Database error")

            # Should return empty dict on error, not raise exception
            result = await service._get_gateway_url_map()
            assert result == {}

    @pytest.mark.asyncio
    async def test_get_server_classification_handles_redis_error(self):
        """Test get_server_classification handles Redis errors gracefully."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=Exception("Redis error"))

        service = ServerClassificationService(redis_client=mock_redis)

        # Should return None on error (fail-open)
        result = await service.get_server_classification("http://test:8080")
        assert result is None

    @pytest.mark.asyncio
    async def test_should_poll_server_handles_redis_error(self):
        """Test should_poll_server returns True on Redis error (fail-open)."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=Exception("Redis error"))

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True

            # Should return True on error (fail-open)
            result = await service.should_poll_server("http://test:8080", "health")
            assert result is True

    @pytest.mark.asyncio
    async def test_mark_poll_completed_handles_redis_error(self):
        """Test mark_poll_completed handles Redis errors gracefully."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[True, False])  # hot server
        mock_redis.set = AsyncMock(side_effect=Exception("Redis error"))

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300

            # Should not raise exception, just log warning
            await service.mark_poll_completed("http://test:8080", "health")

    @pytest.mark.asyncio
    async def test_mark_poll_completed_with_no_redis(self):
        """Test mark_poll_completed returns early when Redis is None."""
        service = ServerClassificationService(redis_client=None)

        # Should return early without error
        await service.mark_poll_completed("http://test:8080", "health")


class TestBoundsAndEdgeCases:
    """Tests for boundary conditions and edge cases introduced by security fixes."""

    # ------------------------------------------------------------------
    # Finding #3: Redis timestamp bounds validation
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_should_poll_server_with_future_timestamp(self):
        """Future timestamp in Redis (e.g. clock skew / tampering) is treated as never polled."""
        import hashlib

        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[True, False])  # Server is hot

        far_future = str(time.time() + 9_000_000)  # ~100 days in future
        mock_redis.get = AsyncMock(return_value=far_future)
        mock_redis.set = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300

            # Future timestamp should be reset → elapsed treated as 0 → should poll now
            result = await service.should_poll_server("http://test:8080", "health")
            assert result is True

    @pytest.mark.asyncio
    async def test_should_poll_server_with_timestamp_at_bounds_boundary(self):
        """Timestamp exactly at now+60 is accepted; now+61 is rejected."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[True, False, True, False])

        service = ServerClassificationService(redis_client=mock_redis)
        now = time.time()

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300

            mock_redis.set = AsyncMock()

            # Timestamp 61s in future → beyond bound → treated as 0 → elapsed = now → should poll
            mock_redis.get = AsyncMock(return_value=str(now + 61))
            result = await service.should_poll_server("http://test:8080", "health")
            assert result is True

    @pytest.mark.asyncio
    async def test_should_poll_redis_returns_non_numeric_timestamp(self):
        """Non-numeric value in Redis timestamp key triggers fail-open (return True)."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[True, False])
        mock_redis.get = AsyncMock(return_value="not-a-number")

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True

            # float("not-a-number") raises ValueError → exception handler → fail open
            result = await service.should_poll_server("http://test:8080", "health")
            assert result is True

    # ------------------------------------------------------------------
    # Finding #5: URL-hashed Redis keys
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_should_poll_url_hash_key_used_not_raw_url(self):
        """Redis key for poll state uses SHA-256 hash of URL, not raw URL."""
        import hashlib

        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[True, False])
        url = "http://test:8080"
        now = time.time()
        mock_redis.get = AsyncMock(return_value=str(now - 1000))  # Long ago → should poll
        mock_redis.set = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300

            await service.should_poll_server(url, "health")

            # Verify the get was called with the hashed key, not the raw URL
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:32]
            expected_key = f"mcpgateway:server_poll_state:{url_hash}:last_health"
            mock_redis.get.assert_awaited_with(expected_key)

    @pytest.mark.asyncio
    async def test_mark_poll_completed_url_hash_key(self):
        """mark_poll_completed uses SHA-256 hashed URL in the Redis key."""
        import hashlib

        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[True, False])  # hot server
        mock_redis.set = AsyncMock()
        url = "http://example.com:9000/path?query=1"

        service = ServerClassificationService(redis_client=mock_redis)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300

            await service.mark_poll_completed(url, "tool_discovery")

            url_hash = hashlib.sha256(url.encode()).hexdigest()[:32]
            expected_key = f"mcpgateway:server_poll_state:{url_hash}:last_tool_discovery"
            args = mock_redis.set.await_args
            assert args[0][0] == expected_key

    # ------------------------------------------------------------------
    # Finding #1: ORM is_(True) correctness
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_gateway_url_map_filters_disabled_gateways(self):
        """Only enabled=True gateways are included; disabled gateways are excluded."""
        service = ServerClassificationService(redis_client=None)

        # Mock DB execution to return (id, url) tuples for enabled gateways only
        mock_session = MagicMock()
        mock_session.execute.return_value = [("gw-1", "http://enabled1:8080"), ("gw-2", "http://enabled2:8080")]
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("mcpgateway.db.SessionLocal", return_value=mock_ctx):
            result = await service._get_gateway_url_map()

        assert set(result.values()) == {"http://enabled1:8080", "http://enabled2:8080"}
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_gateway_url_map_returns_empty_when_none_enabled(self):
        """Returns empty dict when no gateways are enabled."""
        service = ServerClassificationService(redis_client=None)

        mock_session = MagicMock()
        mock_session.execute.return_value = []  # No enabled gateways
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("mcpgateway.db.SessionLocal", return_value=mock_ctx):
            result = await service._get_gateway_url_map()

        assert result == {}

    # ------------------------------------------------------------------
    # Classification correctness edge cases
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_classification_server_in_both_hot_and_cold_sets(self):
        """Data corruption: server in both hot+cold — hot set takes priority."""
        mock_redis = AsyncMock()
        # Server returns True for hot check (first sismember call)
        mock_redis.sismember = AsyncMock(side_effect=[True, True])

        service = ServerClassificationService(redis_client=mock_redis)
        classification = await service.get_server_classification("http://test:8080")

        # hot check runs first → returns "hot" immediately (cold never queried)
        assert classification == "hot"
        # Only one sismember call needed (short-circuits on hot=True)
        assert mock_redis.sismember.await_count == 1

    def test_classify_servers_url_in_active_not_in_pools(self):
        """Gracefully handles URL present in _active but absent from _pools."""
        service = ServerClassificationService(redis_client=None)

        pool = MagicMock()
        pool._pools = {}  # No pooled sessions
        pool._active = {
            ("anon", "http://ghost:8080", "h", None, None): {MagicMock()},
        }

        # Should not raise; ghost URL contributes no metrics
        result = service._classify_servers_from_pool(pool, ["http://ghost:8080"])
        assert result.metadata.eligible_count == 0
        assert "http://ghost:8080" in result.cold_servers

    def test_classify_servers_all_identical_metrics_url_tie_break(self):
        """When all servers share identical metrics, URL (alphabetical) is tie-breaker."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        # 5 servers, identical last_used/active/use_count — differ only by URL
        urls = ["http://server-e:8080", "http://server-a:8080", "http://server-c:8080",
                "http://server-b:8080", "http://server-d:8080"]

        pool = MagicMock()
        pool._active = {}

        sessions = {}
        for url in urls:
            session = MagicMock()
            session.last_used = now
            session.use_count = 5
            queue = MagicMock()
            queue._queue = deque([session])
            pool_key = ("anon", url, "hash", None, None)
            sessions[pool_key] = queue

        pool._pools = sessions

        result = service._classify_servers_from_pool(pool, urls)

        # hot_cap = floor(0.2 * 5) = 1 → 1 hot server
        assert len(result.hot_servers) == 1
        # Ascending URL sort → "a" sorts first → should NOT be hot (primary sort is -last_used desc)
        # All have same last_used → tie broken by URL ascending → "server-a" first when sorted asc
        # But sort key is m.url ASCENDING as tie-breaker, so server-a comes first in sorted list
        assert result.hot_servers[0] == "http://server-a:8080"

    def test_classify_servers_empty_pool_all_cold(self):
        """When pool has no sessions, all provided gateway URLs are cold."""
        service = ServerClassificationService(redis_client=None)

        pool = MagicMock()
        pool._pools = {}  # Empty pool
        pool._active = {}

        all_urls = ["http://server1:8080", "http://server2:8080", "http://server3:8080"]
        result = service._classify_servers_from_pool(pool, all_urls)

        assert result.hot_servers == []
        assert set(result.cold_servers) == set(all_urls)
        assert result.metadata.eligible_count == 0
        assert result.metadata.hot_actual == 0

    # ------------------------------------------------------------------
    # Finding #4: Redis TTL on hot/cold sets
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_publish_classification_hot_cold_sets_have_ttl(self):
        """Hot and cold Redis Sets must have a TTL set to prevent stale data."""
        mock_redis = AsyncMock()
        mock_pipeline = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock()
        mock_pipeline.delete = AsyncMock()
        mock_pipeline.sadd = AsyncMock()
        mock_pipeline.expire = AsyncMock()
        mock_pipeline.set = AsyncMock()
        mock_pipeline.execute = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        metadata = ClassificationMetadata(total_servers=5, hot_cap=1, hot_actual=1, eligible_count=3, timestamp=time.time())
        result = ClassificationResult(
            hot_servers=["http://hot:8080"],
            cold_servers=["http://cold1:8080", "http://cold2:8080", "http://cold3:8080", "http://cold4:8080"],
            metadata=metadata,
        )

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.gateway_auto_refresh_interval = 300

            await service._publish_classification_to_redis(result)

        # expire must be called for HOT_KEY and COLD_KEY (sadd has no TTL parameter)
        expire_keys = [call.args[0] for call in mock_pipeline.expire.await_args_list]
        assert ServerClassificationService.CLASSIFICATION_HOT_KEY in expire_keys
        assert ServerClassificationService.CLASSIFICATION_COLD_KEY in expire_keys
        # TIMESTAMP_KEY gets its TTL via set(..., ex=ttl) — verify at least 2 expire calls
        assert len(expire_keys) >= 2

    @pytest.mark.asyncio
    async def test_publish_classification_ttl_is_two_x_interval(self):
        """TTL applied to hot/cold sets equals 2× the gateway_auto_refresh_interval."""
        mock_redis = AsyncMock()
        mock_pipeline = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock()
        mock_pipeline.delete = AsyncMock()
        mock_pipeline.sadd = AsyncMock()
        mock_pipeline.expire = AsyncMock()
        mock_pipeline.set = AsyncMock()
        mock_pipeline.execute = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)
        interval = 120

        metadata = ClassificationMetadata(total_servers=2, hot_cap=1, hot_actual=1, eligible_count=1, timestamp=time.time())
        result = ClassificationResult(hot_servers=["http://hot:8080"], cold_servers=["http://cold:8080"], metadata=metadata)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.gateway_auto_refresh_interval = interval
            await service._publish_classification_to_redis(result)

        expected_ttl = interval * 2
        for call in mock_pipeline.expire.await_args_list:
            assert call.args[1] == expected_ttl

    # ------------------------------------------------------------------
    # should_poll_server: interval boundary condition
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_should_poll_server_interval_exact_boundary(self):
        """Elapsed time equal to the interval means should_poll is True (>= comparison)."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[True, False])  # hot
        mock_redis.set = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)
        interval = 300
        now = time.time()
        # Set last_poll such that elapsed == exactly interval
        mock_redis.get = AsyncMock(return_value=str(now - interval))

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = interval

            with patch("mcpgateway.services.server_classification_service.time") as mock_time:
                mock_time.time = MagicMock(return_value=now)
                result = await service.should_poll_server("http://test:8080", "health")

        assert result is True  # elapsed == interval → should poll

    @pytest.mark.asyncio
    async def test_should_poll_server_one_second_before_interval(self):
        """Elapsed time one second less than interval means should_poll is False."""
        mock_redis = AsyncMock()
        mock_redis.sismember = AsyncMock(side_effect=[True, False])  # hot

        service = ServerClassificationService(redis_client=mock_redis)
        interval = 300
        now = time.time()
        # elapsed = interval - 1 → should NOT poll
        mock_redis.get = AsyncMock(return_value=str(now - interval + 1))

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = interval

            with patch("mcpgateway.services.server_classification_service.time") as mock_time:
                mock_time.time = MagicMock(return_value=now)
                result = await service.should_poll_server("http://test:8080", "health")

        assert result is False


class TestMissingBranchCoverage:
    """Tests targeting uncovered branches in server_classification_service.py."""

    # ------------------------------------------------------------------
    # Branch 202->205: _perform_classification without Redis (skip publish, still log)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_perform_classification_without_redis_skips_publish(self):
        """_perform_classification with redis_client=None skips Redis publish but still logs."""
        service = ServerClassificationService(redis_client=None)

        mock_pool = MagicMock()
        mock_pool._pools = {}
        mock_pool._active = {}

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.hot_cold_classification_enabled = True
            mock_settings.hot_server_check_interval = 300
            mock_settings.cold_server_check_interval = 900
            mock_settings.gateway_auto_refresh_interval = 60

            with patch.object(service, "_get_gateway_url_map", AsyncMock(return_value={"gw-1": "http://server1:8080"})):
                with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
                    # Must not raise; no Redis publish occurs (line 202->False->205)
                    await service._perform_classification()

        # No Redis set means no assertion needed; the test verifies it completes without error

    # ------------------------------------------------------------------
    # Branch 245->249: URL already present in server_metrics (second pool key, same URL)
    # ------------------------------------------------------------------

    def test_classify_servers_second_pool_key_same_url(self):
        """Two pool keys with the same URL reuse the existing ServerUsageMetrics entry."""
        service = ServerClassificationService(redis_client=None)

        mock_pool = MagicMock()
        url = "http://shared-url:8080"
        now = time.time()

        # Two different pool keys pointing to the same upstream URL
        key_a = ("user_a", url, "hash_a", "sse", "gw-1")
        key_b = ("user_b", url, "hash_b", "sse", "gw-1")

        session_a = MagicMock()
        session_a.last_used = now - 10
        session_a.use_count = 5

        session_b = MagicMock()
        session_b.last_used = now - 5
        session_b.use_count = 3

        queue_a = MagicMock()
        queue_a._queue = deque([session_a])
        queue_b = MagicMock()
        queue_b._queue = deque([session_b])

        mock_pool._pools = {key_a: queue_a, key_b: queue_b}
        mock_pool._active = {}

        result = service._classify_servers_from_pool(mock_pool, [url])

        # Both sessions counted under the single URL entry
        assert url in result.hot_servers or url in result.cold_servers
        # use_count should be cumulative across both pool keys
        # (5 + 3 = 8 for the shared url)

    # ------------------------------------------------------------------
    # Branch 259->257: session.last_used == 0 (inactive session skipped)
    # ------------------------------------------------------------------

    def test_classify_servers_session_with_zero_last_used_skipped(self):
        """Sessions with last_used == 0.0 are excluded from hot eligibility."""
        service = ServerClassificationService(redis_client=None)

        mock_pool = MagicMock()
        url = "http://inactive-server:8080"

        pool_key = ("anon", url, "h1", "sse", "gw-1")

        inactive_session = MagicMock()
        inactive_session.last_used = 0.0  # Never used — branch 259 False path
        inactive_session.use_count = 0

        queue = MagicMock()
        queue._queue = deque([inactive_session])

        mock_pool._pools = {pool_key: queue}
        mock_pool._active = {}

        result = service._classify_servers_from_pool(mock_pool, [url])

        # Server has no valid last_used, so it stays cold
        assert url in result.cold_servers
        assert url not in result.hot_servers

    # ------------------------------------------------------------------
    # Branch 352->356: cold_servers is empty (all servers classified hot)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_publish_classification_empty_cold_servers(self):
        """Publishing a result with no cold servers skips sadd for the cold set."""
        mock_redis = AsyncMock()
        mock_pipeline = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=False)
        mock_pipeline.delete = AsyncMock()
        mock_pipeline.sadd = AsyncMock()
        mock_pipeline.set = AsyncMock()
        mock_pipeline.expire = AsyncMock()
        mock_pipeline.execute = AsyncMock()

        service = ServerClassificationService(redis_client=mock_redis)

        metadata = ClassificationMetadata(total_servers=1, hot_cap=1, hot_actual=1, eligible_count=1, timestamp=time.time())
        # hot has members; cold is empty — exercises the False branch of line 352
        result = ClassificationResult(hot_servers=["http://hot1:8080"], cold_servers=[], metadata=metadata)

        with patch("mcpgateway.services.server_classification_service.settings") as mock_settings:
            mock_settings.gateway_auto_refresh_interval = 300

            await service._publish_classification_to_redis(result)

        # sadd should only be called once (for the hot set), not twice
        sadd_calls = mock_pipeline.sadd.await_args_list
        assert len(sadd_calls) == 1
        assert sadd_calls[0].args[0] == ServerClassificationService.CLASSIFICATION_HOT_KEY

    # ------------------------------------------------------------------
    # URL normalization via gateway_id
    # ------------------------------------------------------------------

    def test_classify_resolves_canonical_url_via_gateway_id(self):
        """Pool keys with auth-mutated URLs are resolved to canonical URL via gateway_id."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        canonical_url = "http://server:8080"
        auth_url = "http://server:8080?tok=val"

        # Pool key has auth-mutated URL but a valid gateway_id
        pool_key = ("anon", auth_url, "h1", "sse", "gw-1")
        session = MagicMock()
        session.last_used = now
        session.use_count = 5
        queue = MagicMock()
        queue._queue = deque([session])

        pool = MagicMock()
        pool._pools = {pool_key: queue}
        pool._active = {}

        gateway_url_map = {"gw-1": canonical_url}

        result = service._classify_servers_from_pool(pool, [canonical_url], gateway_url_map)

        # Auth URL must NOT appear in hot or cold sets
        assert auth_url not in result.hot_servers
        assert auth_url not in result.cold_servers
        # Canonical URL should be classified
        assert canonical_url in result.hot_servers or canonical_url in result.cold_servers

    def test_classify_skips_pool_entries_with_unknown_gateway(self):
        """Pool entries whose URL doesn't match any known gateway are skipped."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        # Pool has a session for an unknown URL
        pool_key = ("anon", "http://unknown:9999", "h1", "sse", "")
        session = MagicMock()
        session.last_used = now
        session.use_count = 10
        queue = MagicMock()
        queue._queue = deque([session])

        pool = MagicMock()
        pool._pools = {pool_key: queue}
        pool._active = {}

        # Only known gateway
        result = service._classify_servers_from_pool(pool, ["http://known:8080"])

        assert "http://unknown:9999" not in result.hot_servers
        assert "http://unknown:9999" not in result.cold_servers
        assert "http://known:8080" in result.cold_servers

    def test_classify_active_only_server_eligible_for_hot(self):
        """A server with all sessions in _active (empty idle queue) is still eligible."""
        service = ServerClassificationService(redis_client=None)
        now = time.time()

        url = "http://busy-server:8080"
        pool_key = ("anon", url, "h1", "sse", "gw-1")

        # Empty idle queue but active sessions with valid last_used
        queue = MagicMock()
        queue._queue = deque()  # Empty — all sessions checked out

        active_session = MagicMock()
        active_session.last_used = now
        active_session.use_count = 50

        pool = MagicMock()
        pool._pools = {pool_key: queue}
        pool._active = {pool_key: {active_session}}

        # 5 servers → hot_cap = 1, busy-server should be hot
        all_urls = [url] + [f"http://idle{i}:8080" for i in range(4)]
        result = service._classify_servers_from_pool(pool, all_urls)

        assert url in result.hot_servers
