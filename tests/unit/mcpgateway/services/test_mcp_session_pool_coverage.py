# -*- coding: utf-8 -*-
"""Additional coverage tests for MCP session pool service.

Targets missing lines to increase branch/line coverage above 70%.

Copyright 2026
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
    _get_cleanup_timeout,
    close_mcp_session_pool,
    get_mcp_session_pool,
    init_mcp_session_pool,
    register_gateway_capabilities_for_notifications,
    start_pool_notification_service,
    unregister_gateway_from_notifications,
)


# ---------------------------------------------------------------------------
# Lines 82-83, 88: _get_cleanup_timeout and TYPE_CHECKING import
# ---------------------------------------------------------------------------
class TestGetCleanupTimeout:
    """Cover _get_cleanup_timeout when settings attribute exists."""

    def test_cleanup_timeout_from_settings(self):
        """When settings.mcp_session_pool_cleanup_timeout exists, use it."""
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcp_session_pool_cleanup_timeout = 12.5
            assert _get_cleanup_timeout() == 12.5

    def test_cleanup_timeout_fallback_on_generic_exception(self):
        """When settings raises any exception, fall back to 5.0."""
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            # Make the attribute access raise an exception
            type(mock_settings).mcp_session_pool_cleanup_timeout = property(
                lambda self: (_ for _ in ()).throw(RuntimeError("config error"))
            )
            assert _get_cleanup_timeout() == 5.0


# ---------------------------------------------------------------------------
# Lines 417-420: _compute_identity_hash session affinity branch
# ---------------------------------------------------------------------------
class TestIdentityHashSessionAffinity:
    """Cover session affinity path in _compute_identity_hash."""

    def test_session_affinity_uses_x_mcp_session_id(self):
        """When session affinity is enabled & header present, uses session ID."""
        pool = MCPSessionPool()
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            result = pool._compute_identity_hash({"x-mcp-session-id": "abc123"})
            expected = hashlib.sha256(b"abc123").hexdigest()
            assert result == expected

    def test_session_affinity_disabled_skips(self):
        """When session affinity is disabled, falls through to header hash."""
        pool = MCPSessionPool()
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = False
            result = pool._compute_identity_hash({"x-mcp-session-id": "abc123", "Authorization": "Bearer tok"})
            session_hash = hashlib.sha256(b"abc123").hexdigest()
            assert result != session_hash


# ---------------------------------------------------------------------------
# Lines 518-520: is_valid_mcp_session_id
# ---------------------------------------------------------------------------
class TestIsValidMcpSessionId:
    """Cover is_valid_mcp_session_id static method."""

    def test_empty_string_invalid(self):
        assert MCPSessionPool.is_valid_mcp_session_id("") is False

    def test_none_invalid(self):
        assert MCPSessionPool.is_valid_mcp_session_id(None) is False

    def test_valid_id(self):
        assert MCPSessionPool.is_valid_mcp_session_id("abc-123_XYZ") is True

    def test_invalid_chars(self):
        assert MCPSessionPool.is_valid_mcp_session_id("abc 123!@#") is False

    def test_too_long(self):
        assert MCPSessionPool.is_valid_mcp_session_id("a" * 129) is False


# ---------------------------------------------------------------------------
# Lines 533-546, 551: _sanitize_redis_key_component, _session_mapping_redis_key, _pool_owner_key
# ---------------------------------------------------------------------------
class TestRedisKeyHelpers:
    """Cover Redis key helper methods."""

    def test_sanitize_redis_key_component_empty(self):
        pool = MCPSessionPool()
        assert pool._sanitize_redis_key_component("") == ""

    def test_sanitize_redis_key_component_special_chars(self):
        pool = MCPSessionPool()
        assert pool._sanitize_redis_key_component("hello:world/foo") == "hello_world_foo"

    def test_sanitize_redis_key_component_clean(self):
        pool = MCPSessionPool()
        assert pool._sanitize_redis_key_component("abc-123_XYZ") == "abc-123_XYZ"

    def test_session_mapping_redis_key(self):
        pool = MCPSessionPool()
        key = pool._session_mapping_redis_key("sess123", "http://example.com", "streamablehttp", "gw-1")
        assert key.startswith("mcpgw:session_mapping:")
        assert "sess123" in key

    def test_pool_owner_key(self):
        key = MCPSessionPool._pool_owner_key("sess123")
        assert key == "mcpgw:pool_owner:sess123"


# ---------------------------------------------------------------------------
# Lines 581-653: register_session_mapping
# ---------------------------------------------------------------------------
class TestRegisterSessionMapping:
    """Cover register_session_mapping edge cases."""

    @pytest.mark.asyncio
    async def test_register_session_mapping_affinity_disabled(self):
        """Should return early when affinity is disabled."""
        pool = MCPSessionPool()
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = False
            await pool.register_session_mapping("valid-id", "http://test:8080", "gw-1", "streamablehttp")

    @pytest.mark.asyncio
    async def test_register_session_mapping_invalid_session_id(self):
        """Should return early for invalid session IDs."""
        pool = MCPSessionPool()
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            await pool.register_session_mapping("invalid id!!", "http://test:8080", "gw-1", "streamablehttp")

    @pytest.mark.asyncio
    async def test_register_session_mapping_success_with_redis(self):
        """Happy path: local + Redis mapping + ownership registration."""
        pool = MCPSessionPool()
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
                await pool.register_session_mapping("validid123", "http://test:8080", "gw-1", "streamablehttp", user_email="user@test.com")

        assert len(pool._mcp_session_mapping) == 1
        mock_redis.setex.assert_awaited_once()
        mock_redis.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_session_mapping_ownership_already_claimed(self):
        """Should handle case where another worker already claimed ownership."""
        pool = MCPSessionPool()
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.set = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value=b"other-worker:1234")

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
                await pool.register_session_mapping("validid123", "http://test:8080", "gw-1", "streamablehttp")

        mock_redis.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_session_mapping_redis_failure(self):
        """Redis failure should be non-fatal."""
        pool = MCPSessionPool()

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, side_effect=Exception("Redis down")):
                await pool.register_session_mapping("validid123", "http://test:8080", "gw-1", "streamablehttp")

    @pytest.mark.asyncio
    async def test_register_session_mapping_no_redis(self):
        """Should work without Redis (local-only mapping)."""
        pool = MCPSessionPool()

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, return_value=None):
                await pool.register_session_mapping("validid123", "http://test:8080", "gw-1", "streamablehttp")

        assert len(pool._mcp_session_mapping) == 1


# ---------------------------------------------------------------------------
# Lines 702-741: acquire session affinity path (Redis lookup)
# ---------------------------------------------------------------------------
class TestAcquireSessionAffinity:
    """Cover acquire session affinity code paths."""

    @pytest.mark.asyncio
    async def test_acquire_session_affinity_local_hit(self):
        """When local mapping exists, use it."""
        pool = MCPSessionPool()
        url = "http://test:8080"
        mcp_session_id = "validid123"
        gateway_id = "gw-1"

        identity_hash = hashlib.sha256(mcp_session_id.encode()).hexdigest()
        mapping_key = (mcp_session_id, url, "streamablehttp", gateway_id)
        pool_key = ("anonymous", url, identity_hash, "streamablehttp", gateway_id)
        pool._mcp_session_mapping[mapping_key] = pool_key

        mock_session = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url=url,
            identity_key=identity_hash,
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            gateway_id=gateway_id,
        )

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            with patch.object(pool, "_create_session", new_callable=AsyncMock, return_value=mock_session):
                result = await pool.acquire(
                    url,
                    headers={"x-mcp-session-id": mcp_session_id},
                    gateway_id=gateway_id,
                )
        assert result is mock_session
        assert pool._session_affinity_local_hits == 1
        await pool.close_all()

    @pytest.mark.asyncio
    async def test_acquire_session_affinity_redis_hit(self):
        """When Redis mapping exists but local doesn't, use Redis."""
        pool = MCPSessionPool()
        url = "http://test:8080"
        mcp_session_id = "validid123"
        gateway_id = "gw-1"

        identity_hash = hashlib.sha256(mcp_session_id.encode()).hexdigest()

        import orjson

        redis_data = orjson.dumps({
            "user_hash": "anonymous",
            "url": url,
            "identity_hash": identity_hash,
            "transport_type": "streamablehttp",
            "gateway_id": gateway_id,
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=redis_data)

        mock_session = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url=url,
            identity_key=identity_hash,
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
            gateway_id=gateway_id,
        )

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
                # Also patch _get_pool_session_owner to return None so ownership check doesn't interfere
                with patch.object(pool, "_get_pool_session_owner", new_callable=AsyncMock, return_value=None):
                    with patch.object(pool, "_create_session", new_callable=AsyncMock, return_value=mock_session):
                        result = await pool.acquire(
                            url,
                            headers={"x-mcp-session-id": mcp_session_id},
                            gateway_id=gateway_id,
                        )
        assert result is mock_session
        assert pool._session_affinity_redis_hits == 1
        await pool.close_all()

    @pytest.mark.asyncio
    async def test_acquire_session_affinity_redis_failure(self):
        """Redis failure during affinity lookup should fall back gracefully."""
        pool = MCPSessionPool()
        url = "http://test:8080"

        mock_session = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url=url,
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
        )

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, side_effect=Exception("Redis down")):
                with patch.object(pool, "_create_session", new_callable=AsyncMock, return_value=mock_session):
                    result = await pool.acquire(url, headers={"x-mcp-session-id": "validid123"})
        assert result is mock_session
        await pool.close_all()


# ---------------------------------------------------------------------------
# Lines 804-813: acquire ownership check path
# ---------------------------------------------------------------------------
class TestAcquireOwnershipCheck:
    """Cover acquire ownership verification for session affinity."""

    @pytest.mark.asyncio
    async def test_acquire_session_owned_by_another_worker(self):
        """Should raise when session is owned by another worker."""
        pool = MCPSessionPool()
        url = "http://test:8080"

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            with patch.object(pool, "_get_pool_session_owner", new_callable=AsyncMock, return_value="other-worker:5678"):
                with patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "my-worker:1234"):
                    with pytest.raises(RuntimeError, match="Session owned by another worker"):
                        await pool.acquire(url, headers={"x-mcp-session-id": "validid123"})
        await pool.close_all()


# ---------------------------------------------------------------------------
# Lines 835->838: acquire CancelledError path
# ---------------------------------------------------------------------------
class TestAcquireCancelledError:
    """Cover CancelledError during session creation."""

    @pytest.mark.asyncio
    async def test_acquire_cancelled_error_does_not_record_failure(self):
        """CancelledError should release semaphore but not record failure."""
        pool = MCPSessionPool()
        url = "http://test:8080"

        with patch.object(pool, "_create_session", new_callable=AsyncMock, side_effect=asyncio.CancelledError()):
            with pytest.raises(asyncio.CancelledError):
                await pool.acquire(url)

        assert pool._failures.get(url, 0) == 0
        await pool.close_all()


# ---------------------------------------------------------------------------
# Lines 873->875, 875->877: release - closed pool or expired session
# ---------------------------------------------------------------------------
class TestReleaseEdgeCases:
    """Cover release edge cases."""

    @pytest.mark.asyncio
    async def test_release_when_pool_is_closed(self):
        """Release when pool._closed is True should close session."""
        pool = MCPSessionPool()
        url = "http://test:8080"

        pooled = PooledSession(
            session=MagicMock(),
            transport_context=MagicMock(),
            url=url,
            identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={},
        )

        pool_key = ("anonymous", url, "anonymous", "streamablehttp", "")
        await pool._get_or_create_pool(pool_key)
        pool._closed = True

        with patch.object(pool, "_close_session", new_callable=AsyncMock) as mock_close:
            await pool.release(pooled)

        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_release_semaphore_released_for_queue_full(self):
        """When queue is full on release, semaphore should be released."""
        pool = MCPSessionPool(max_sessions_per_key=1)
        url = "http://test:8080"
        pool_key = ("anonymous", url, "anonymous", "streamablehttp", "")
        pool._pools[pool_key] = asyncio.Queue(maxsize=1)
        pool._active[pool_key] = set()
        pool._semaphores[pool_key] = asyncio.Semaphore(1)
        pool._locks[pool_key] = asyncio.Lock()
        pool._pool_last_used[pool_key] = time.time()

        filler = PooledSession(
            session=MagicMock(), transport_context=MagicMock(),
            url=url, identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP, headers={},
        )
        pool._pools[pool_key].put_nowait(filler)

        pooled = PooledSession(
            session=MagicMock(), transport_context=MagicMock(),
            url=url, identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP, headers={},
        )

        with patch.object(pool, "_close_session", new_callable=AsyncMock):
            await pool.release(pooled)


# ---------------------------------------------------------------------------
# Lines 910, 935, 937->925, 946->939, 950-953, 956->925: _maybe_evict_idle_pool_keys
# ---------------------------------------------------------------------------
class TestEvictionBranches:
    """Cover eviction edge cases."""

    @pytest.mark.asyncio
    async def test_eviction_when_closed(self):
        """Eviction should short-circuit when pool is closed."""
        pool = MCPSessionPool()
        pool._closed = True
        await pool._maybe_evict_idle_pool_keys()

    @pytest.mark.asyncio
    async def test_eviction_skips_active_sessions(self):
        """Pools with active sessions should not be evicted."""
        pool = MCPSessionPool(idle_pool_eviction_seconds=0.01, session_ttl_seconds=0.01)
        pool._eviction_run_interval = 0

        url = "http://test:8080"
        pool_key = ("anonymous", url, "anonymous", "streamablehttp", "")
        await pool._get_or_create_pool(pool_key)
        pool._pool_last_used[pool_key] = time.time() - 1000

        active_session = MagicMock()
        pool._active[pool_key].add(active_session)

        pool._last_eviction_run = 0
        await pool._maybe_evict_idle_pool_keys()

        assert pool_key in pool._pools

    @pytest.mark.asyncio
    async def test_eviction_valid_session_put_back(self):
        """Valid sessions in idle pools should be kept."""
        pool = MCPSessionPool(idle_pool_eviction_seconds=0.01, session_ttl_seconds=9999)
        pool._eviction_run_interval = 0

        url = "http://test:8080"
        pool_key = ("anonymous", url, "anonymous", "streamablehttp", "")
        await pool._get_or_create_pool(pool_key)
        pool._pool_last_used[pool_key] = time.time() - 1000

        valid_session = PooledSession(
            session=MagicMock(), transport_context=MagicMock(),
            url=url, identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP, headers={},
            created_at=time.time(),
            last_used=time.time(),
        )
        pool._pools[pool_key].put_nowait(valid_session)

        pool._last_eviction_run = 0
        await pool._maybe_evict_idle_pool_keys()

        assert pool._pools[pool_key].qsize() == 1


# ---------------------------------------------------------------------------
# Lines 992-993: _validate_session TTL expiry
# ---------------------------------------------------------------------------
class TestValidateSessionTTL:
    """Cover TTL-based validation failure."""

    @pytest.mark.asyncio
    async def test_validate_session_ttl_expired(self):
        """Session older than TTL should be invalid."""
        pool = MCPSessionPool(session_ttl_seconds=1.0)
        pooled = PooledSession(
            session=MagicMock(), transport_context=MagicMock(),
            url="http://test:8080", identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP, headers={},
            created_at=time.time() - 100,
            last_used=time.time(),
        )
        result = await pool._validate_session(pooled)
        assert result is False


# ---------------------------------------------------------------------------
# Lines 1030-1032: _run_health_check_chain list_resources
# ---------------------------------------------------------------------------
class TestHealthCheckListResources:
    """Cover list_resources health check independently."""

    @pytest.mark.asyncio
    async def test_health_check_list_resources_only(self):
        """list_resources as sole check method."""
        pool = MCPSessionPool(health_check_methods=["list_resources"])
        pooled = PooledSession(
            session=MagicMock(), transport_context=MagicMock(),
            url="http://test:8080", identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP, headers={},
        )
        pooled.session.list_resources = AsyncMock(return_value=[])
        result = await pool._run_health_check_chain(pooled)
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_timeout_continues_to_next(self):
        """Timeout on one method should continue to next."""
        pool = MCPSessionPool(health_check_methods=["ping", "skip"])
        pooled = PooledSession(
            session=MagicMock(), transport_context=MagicMock(),
            url="http://test:8080", identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP, headers={},
        )
        pooled.session.send_ping = AsyncMock(side_effect=asyncio.TimeoutError())
        result = await pool._run_health_check_chain(pooled)
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_all_timeout_returns_false(self):
        """When all methods timeout, should return False and increment failures."""
        pool = MCPSessionPool(health_check_methods=["ping"])
        pooled = PooledSession(
            session=MagicMock(), transport_context=MagicMock(),
            url="http://test:8080", identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP, headers={},
        )
        pooled.session.send_ping = AsyncMock(side_effect=asyncio.TimeoutError())
        result = await pool._run_health_check_chain(pooled)
        assert result is False
        assert pool._health_check_failures == 1


# ---------------------------------------------------------------------------
# Lines 1100, 1111, 1121: _create_session header stripping and SSE with httpx factory
# ---------------------------------------------------------------------------
class TestCreateSessionHeaderStripping:
    """Cover header stripping in _create_session."""

    @pytest.mark.asyncio
    async def test_create_session_strips_mcp_session_headers(self):
        """x-mcp-session-id and mcp-session-id headers should be stripped."""
        pool = MCPSessionPool()

        transport_ctx = MagicMock()
        transport_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
        transport_ctx.__aexit__ = AsyncMock(return_value=None)

        session_instance = MagicMock()
        session_instance.__aenter__ = AsyncMock(return_value=None)
        session_instance.__aexit__ = AsyncMock(return_value=None)
        session_instance.initialize = AsyncMock(return_value=None)

        with patch("mcpgateway.services.mcp_session_pool.streamablehttp_client", return_value=transport_ctx):
            with patch("mcpgateway.services.mcp_session_pool.ClientSession", return_value=session_instance):
                pooled = await pool._create_session(
                    "http://test:8080",
                    {"x-mcp-session-id": "should-be-stripped", "mcp-session-id": "also-stripped", "Authorization": "Bearer tok"},
                    TransportType.STREAMABLE_HTTP,
                    None,
                )

        assert "x-mcp-session-id" not in pooled.headers
        assert "mcp-session-id" not in pooled.headers
        assert "Authorization" in pooled.headers

    @pytest.mark.asyncio
    async def test_create_session_sse_with_httpx_factory(self):
        """SSE with httpx_client_factory should pass factory to sse_client."""
        pool = MCPSessionPool()
        httpx_factory = MagicMock()

        transport_ctx = MagicMock()
        transport_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        transport_ctx.__aexit__ = AsyncMock(return_value=None)

        session_instance = MagicMock()
        session_instance.__aenter__ = AsyncMock(return_value=None)
        session_instance.__aexit__ = AsyncMock(return_value=None)
        session_instance.initialize = AsyncMock(return_value=None)

        with patch("mcpgateway.services.mcp_session_pool.sse_client", return_value=transport_ctx) as mock_sse:
            with patch("mcpgateway.services.mcp_session_pool.ClientSession", return_value=session_instance):
                pooled = await pool._create_session(
                    "http://test:8080",
                    None,
                    TransportType.SSE,
                    httpx_factory,
                    timeout=5.0,
                )

        mock_sse.assert_called_once()
        call_kwargs = mock_sse.call_args[1]
        assert call_kwargs["httpx_client_factory"] is httpx_factory

    @pytest.mark.asyncio
    async def test_create_session_streamablehttp_without_factory(self):
        """STREAMABLE_HTTP without factory should call streamablehttp_client without it."""
        pool = MCPSessionPool()

        transport_ctx = MagicMock()
        transport_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
        transport_ctx.__aexit__ = AsyncMock(return_value=None)

        session_instance = MagicMock()
        session_instance.__aenter__ = AsyncMock(return_value=None)
        session_instance.__aexit__ = AsyncMock(return_value=None)
        session_instance.initialize = AsyncMock(return_value=None)

        with patch("mcpgateway.services.mcp_session_pool.streamablehttp_client", return_value=transport_ctx) as mock_sh:
            with patch("mcpgateway.services.mcp_session_pool.ClientSession", return_value=session_instance):
                pooled = await pool._create_session(
                    "http://test:8080",
                    None,
                    TransportType.STREAMABLE_HTTP,
                    None,
                    timeout=5.0,
                )

        assert pooled.transport_type == TransportType.STREAMABLE_HTTP
        mock_sh.assert_called_once()
        assert "httpx_client_factory" not in mock_sh.call_args[1]


# ---------------------------------------------------------------------------
# Lines 1155: _create_session CancelledError path
# ---------------------------------------------------------------------------
class TestCreateSessionCancelledError:
    """Cover CancelledError during session initialization."""

    @pytest.mark.asyncio
    async def test_create_session_cancelled_error_cleanup(self):
        """CancelledError should trigger cleanup in finally block."""
        pool = MCPSessionPool()

        transport_ctx = MagicMock()
        transport_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        transport_ctx.__aexit__ = AsyncMock(return_value=None)

        session_instance = MagicMock()
        session_instance.__aenter__ = AsyncMock(return_value=None)
        session_instance.__aexit__ = AsyncMock(return_value=None)
        session_instance.initialize = AsyncMock(side_effect=asyncio.CancelledError())

        with patch("mcpgateway.services.mcp_session_pool.sse_client", return_value=transport_ctx):
            with patch("mcpgateway.services.mcp_session_pool.ClientSession", return_value=session_instance):
                with pytest.raises(asyncio.CancelledError):
                    await pool._create_session("http://test:8080", None, TransportType.SSE, None)

        session_instance.__aexit__.assert_awaited()
        transport_ctx.__aexit__.assert_awaited()


# ---------------------------------------------------------------------------
# Lines 1167->1173, 1171-1172, 1177-1178: _create_session finally cleanup exceptions
# ---------------------------------------------------------------------------
class TestCreateSessionCleanupErrors:
    """Cover cleanup error paths in _create_session finally block."""

    @pytest.mark.asyncio
    async def test_create_session_cleanup_with_session_exit_error(self):
        """Session __aexit__ error during cleanup should be swallowed."""
        pool = MCPSessionPool()

        transport_ctx = MagicMock()
        transport_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        transport_ctx.__aexit__ = AsyncMock(return_value=None)

        session_instance = MagicMock()
        session_instance.__aenter__ = AsyncMock(return_value=None)
        session_instance.__aexit__ = AsyncMock(side_effect=RuntimeError("cleanup boom"))
        session_instance.initialize = AsyncMock(side_effect=RuntimeError("init boom"))

        with patch("mcpgateway.services.mcp_session_pool.sse_client", return_value=transport_ctx):
            with patch("mcpgateway.services.mcp_session_pool.ClientSession", return_value=session_instance):
                with pytest.raises(RuntimeError, match="Failed to create MCP session"):
                    await pool._create_session("http://test:8080", None, TransportType.SSE, None)

    @pytest.mark.asyncio
    async def test_create_session_cleanup_with_transport_exit_error(self):
        """Transport __aexit__ error during cleanup should be swallowed."""
        pool = MCPSessionPool()

        transport_ctx = MagicMock()
        transport_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        transport_ctx.__aexit__ = AsyncMock(side_effect=RuntimeError("transport cleanup boom"))

        session_instance = MagicMock()
        session_instance.__aenter__ = AsyncMock(return_value=None)
        session_instance.__aexit__ = AsyncMock(return_value=None)
        session_instance.initialize = AsyncMock(side_effect=RuntimeError("init boom"))

        with patch("mcpgateway.services.mcp_session_pool.sse_client", return_value=transport_ctx):
            with patch("mcpgateway.services.mcp_session_pool.ClientSession", return_value=session_instance):
                with pytest.raises(RuntimeError, match="Failed to create MCP session"):
                    await pool._create_session("http://test:8080", None, TransportType.SSE, None)


# ---------------------------------------------------------------------------
# Lines 1224-1227: _close_session Redis cleanup
# ---------------------------------------------------------------------------
class TestCloseSessionRedisCleanup:
    """Cover _close_session Redis cleanup path."""

    @pytest.mark.asyncio
    async def test_close_session_with_session_affinity_header(self):
        """Should attempt to clean up pool owner in Redis."""
        pool = MCPSessionPool()

        class DummyScope:
            def __init__(self):
                self.cancelled_caught = False
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        pooled = PooledSession(
            session=MagicMock(), transport_context=MagicMock(),
            url="http://test:8080", identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP,
            headers={"x-mcp-session-id": "validid123"},
        )
        pooled.session.__aexit__ = AsyncMock(return_value=None)
        pooled.transport_context.__aexit__ = AsyncMock(return_value=None)

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            with patch("mcpgateway.services.mcp_session_pool.anyio.move_on_after", return_value=DummyScope()):
                with patch.object(pool, "_cleanup_pool_session_owner", new_callable=AsyncMock) as mock_cleanup:
                    await pool._close_session(pooled)
        mock_cleanup.assert_awaited_once_with("validid123")


# ---------------------------------------------------------------------------
# Lines 1237-1253: _cleanup_pool_session_owner
# ---------------------------------------------------------------------------
class TestCleanupPoolSessionOwner:
    """Cover _cleanup_pool_session_owner."""

    @pytest.mark.asyncio
    async def test_cleanup_owner_we_own(self):
        """Should delete key when we own it."""
        pool = MCPSessionPool()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"myworker:1")
        mock_redis.delete = AsyncMock()

        with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
            with patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "myworker:1"):
                await pool._cleanup_pool_session_owner("validid123")

        mock_redis.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_owner_not_ours(self):
        """Should NOT delete key when another worker owns it."""
        pool = MCPSessionPool()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"other-worker:2")
        mock_redis.delete = AsyncMock()

        with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
            with patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "myworker:1"):
                await pool._cleanup_pool_session_owner("validid123")

        mock_redis.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_owner_no_redis(self):
        """Should handle no Redis gracefully."""
        pool = MCPSessionPool()
        with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, return_value=None):
            await pool._cleanup_pool_session_owner("validid123")

    @pytest.mark.asyncio
    async def test_cleanup_owner_redis_error(self):
        """Should handle Redis errors gracefully."""
        pool = MCPSessionPool()
        with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, side_effect=Exception("Redis down")):
            await pool._cleanup_pool_session_owner("validid123")

    @pytest.mark.asyncio
    async def test_cleanup_owner_no_owner_key(self):
        """Should handle missing owner key gracefully."""
        pool = MCPSessionPool()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
            await pool._cleanup_pool_session_owner("validid123")


# ---------------------------------------------------------------------------
# Lines 1271-1272: close_all QueueEmpty during drain
# ---------------------------------------------------------------------------
class TestCloseAllQueueEmpty:
    """Cover close_all edge cases."""

    @pytest.mark.asyncio
    async def test_close_all_with_pooled_sessions(self):
        """close_all should drain and close all pooled sessions."""
        pool = MCPSessionPool()
        url = "http://test:8080"
        pool_key = ("anonymous", url, "anonymous", "streamablehttp", "")
        pool._pools[pool_key] = asyncio.Queue(maxsize=2)
        pool._active[pool_key] = set()
        pool._semaphores[pool_key] = asyncio.Semaphore(2)
        pool._locks[pool_key] = asyncio.Lock()

        s1 = PooledSession(
            session=MagicMock(), transport_context=MagicMock(),
            url=url, identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP, headers={},
        )
        pool._pools[pool_key].put_nowait(s1)

        with patch.object(pool, "_close_session", new_callable=AsyncMock):
            await pool.close_all()

        assert pool._closed is True
        assert len(pool._pools) == 0

    @pytest.mark.asyncio
    async def test_close_all_with_active_sessions(self):
        """close_all should close active sessions."""
        pool = MCPSessionPool()
        url = "http://test:8080"
        pool_key = ("anonymous", url, "anonymous", "streamablehttp", "")
        pool._pools[pool_key] = asyncio.Queue(maxsize=2)
        pool._active[pool_key] = set()
        pool._semaphores[pool_key] = asyncio.Semaphore(2)
        pool._locks[pool_key] = asyncio.Lock()

        active_s = MagicMock()
        pool._active[pool_key].add(active_s)

        with patch.object(pool, "_close_session", new_callable=AsyncMock) as mock_close:
            await pool.close_all()

        mock_close.assert_awaited()


# ---------------------------------------------------------------------------
# Lines 1286-1291: close_all RPC listener cancellation
# ---------------------------------------------------------------------------
class TestCloseAllRpcListener:
    """Cover RPC listener task cancellation in close_all."""

    @pytest.mark.asyncio
    async def test_close_all_cancels_rpc_listener(self):
        """close_all should cancel the RPC listener task."""
        pool = MCPSessionPool()

        # Create a real asyncio.Task that we can cancel
        async def never_ending():
            await asyncio.sleep(9999)

        task = asyncio.create_task(never_ending())
        pool._rpc_listener_task = task

        await pool.close_all()

        assert task.cancelled()
        assert pool._rpc_listener_task is None


# ---------------------------------------------------------------------------
# Lines 1308-1342: register_pool_session_owner
# ---------------------------------------------------------------------------
class TestRegisterPoolSessionOwner:
    """Cover register_pool_session_owner."""

    @pytest.mark.asyncio
    async def test_register_owner_affinity_disabled(self):
        """Should return early when affinity is disabled."""
        pool = MCPSessionPool()
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = False
            await pool.register_pool_session_owner("validid123")

    @pytest.mark.asyncio
    async def test_register_owner_invalid_session_id(self):
        """Should return early for invalid session IDs."""
        pool = MCPSessionPool()
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            await pool.register_pool_session_owner("invalid id!!")

    @pytest.mark.asyncio
    async def test_register_owner_redis_success(self):
        """Should register ownership in Redis."""
        pool = MCPSessionPool()
        mock_redis = AsyncMock()
        mock_redis.eval = AsyncMock(return_value=1)

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
                await pool.register_pool_session_owner("validid123")

        mock_redis.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_owner_redis_failure(self):
        """Redis failure should be non-fatal."""
        pool = MCPSessionPool()
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            mock_settings.mcpgateway_session_affinity_ttl = 300
            with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, side_effect=Exception("Redis down")):
                await pool.register_pool_session_owner("validid123")


# ---------------------------------------------------------------------------
# Lines 1353-1372: _get_pool_session_owner
# ---------------------------------------------------------------------------
class TestGetPoolSessionOwner:
    """Cover _get_pool_session_owner."""

    @pytest.mark.asyncio
    async def test_get_owner_affinity_disabled(self):
        """Should return None when affinity is disabled."""
        pool = MCPSessionPool()
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = False
            result = await pool._get_pool_session_owner("validid123")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_owner_invalid_session_id(self):
        """Should return None for invalid session IDs."""
        pool = MCPSessionPool()
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            result = await pool._get_pool_session_owner("invalid id!!")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_owner_found(self):
        """Should return worker ID when found in Redis."""
        pool = MCPSessionPool()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"worker-1:1234")

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
                result = await pool._get_pool_session_owner("validid123")
        assert result == "worker-1:1234"

    @pytest.mark.asyncio
    async def test_get_owner_not_found(self):
        """Should return None when not found in Redis."""
        pool = MCPSessionPool()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
                result = await pool._get_pool_session_owner("validid123")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_owner_redis_failure(self):
        """Redis failure should return None."""
        pool = MCPSessionPool()
        with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
            mock_settings.mcpgateway_session_affinity_enabled = True
            with patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock, side_effect=Exception("Redis down")):
                result = await pool._get_pool_session_owner("validid123")
        assert result is None


# ---------------------------------------------------------------------------
# Lines 1678: get_streamable_http_session_owner
# ---------------------------------------------------------------------------
class TestGetStreamableHttpSessionOwner:
    """Cover public wrapper for session owner lookup."""

    @pytest.mark.asyncio
    async def test_get_streamable_http_session_owner(self):
        """Should delegate to _get_pool_session_owner."""
        pool = MCPSessionPool()
        with patch.object(pool, "_get_pool_session_owner", new_callable=AsyncMock, return_value="worker-1:1234") as mock_get:
            result = await pool.get_streamable_http_session_owner("validid123")
        assert result == "worker-1:1234"
        mock_get.assert_awaited_once_with("validid123")


# ---------------------------------------------------------------------------
# Lines 1979-1980: close_mcp_session_pool notification service cleanup
# ---------------------------------------------------------------------------
class TestClosePoolNotificationCleanup:
    """Cover close_mcp_session_pool notification cleanup branches."""

    @pytest.mark.asyncio
    async def test_close_pool_notification_import_error(self):
        """ImportError in notification service should be silently handled."""
        init_mcp_session_pool(enable_notifications=False)

        with patch("mcpgateway.services.notification_service.close_notification_service", side_effect=ImportError("no module")):
            await close_mcp_session_pool()

    @pytest.mark.asyncio
    async def test_close_pool_notification_runtime_error(self):
        """RuntimeError in notification service should be silently handled."""
        init_mcp_session_pool(enable_notifications=False)

        with patch("mcpgateway.services.notification_service.close_notification_service", side_effect=RuntimeError("not init")):
            await close_mcp_session_pool()


# ---------------------------------------------------------------------------
# Lines 1991-2001: start_pool_notification_service
# ---------------------------------------------------------------------------
class TestStartPoolNotificationService:
    """Cover start_pool_notification_service."""

    @pytest.mark.asyncio
    async def test_start_notification_service_success(self):
        """Should initialize notification service."""
        mock_svc = MagicMock()
        mock_svc.initialize = AsyncMock()

        with patch("mcpgateway.services.notification_service.get_notification_service", return_value=mock_svc):
            await start_pool_notification_service(gateway_service=MagicMock())

        mock_svc.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_notification_service_runtime_error(self):
        """RuntimeError should be handled gracefully."""
        with patch("mcpgateway.services.notification_service.get_notification_service", side_effect=RuntimeError("not init")):
            await start_pool_notification_service()


# ---------------------------------------------------------------------------
# Lines 2013-2022: register_gateway_capabilities_for_notifications
# ---------------------------------------------------------------------------
class TestRegisterGatewayCapabilities:
    """Cover register_gateway_capabilities_for_notifications."""

    def test_register_capabilities_success(self):
        """Should register capabilities with notification service."""
        mock_svc = MagicMock()
        with patch("mcpgateway.services.notification_service.get_notification_service", return_value=mock_svc):
            register_gateway_capabilities_for_notifications("gw-1", {"tools": True})
        mock_svc.register_gateway_capabilities.assert_called_once_with("gw-1", {"tools": True})

    def test_register_capabilities_runtime_error(self):
        """RuntimeError should be silently handled."""
        with patch("mcpgateway.services.notification_service.get_notification_service", side_effect=RuntimeError("not init")):
            register_gateway_capabilities_for_notifications("gw-1", {"tools": True})


# ---------------------------------------------------------------------------
# Lines 2033-2042: unregister_gateway_from_notifications
# ---------------------------------------------------------------------------
class TestUnregisterGateway:
    """Cover unregister_gateway_from_notifications."""

    def test_unregister_gateway_success(self):
        """Should unregister gateway from notification service."""
        mock_svc = MagicMock()
        with patch("mcpgateway.services.notification_service.get_notification_service", return_value=mock_svc):
            unregister_gateway_from_notifications("gw-1")
        mock_svc.unregister_gateway.assert_called_once_with("gw-1")

    def test_unregister_gateway_runtime_error(self):
        """RuntimeError should be silently handled."""
        with patch("mcpgateway.services.notification_service.get_notification_service", side_effect=RuntimeError("not init")):
            unregister_gateway_from_notifications("gw-1")


# ---------------------------------------------------------------------------
# Lines 1918->1943, 1938: init_mcp_session_pool with notification service
# ---------------------------------------------------------------------------
class TestInitPoolWithNotifications:
    """Cover init_mcp_session_pool with notification service enabled."""

    @pytest.mark.asyncio
    async def test_init_with_notifications_enabled(self):
        """Should auto-create notification service when enabled."""
        mock_notification_svc = MagicMock()
        mock_notification_svc.create_message_handler = MagicMock(return_value=MagicMock())

        with patch("mcpgateway.services.notification_service.init_notification_service", return_value=mock_notification_svc):
            pool = init_mcp_session_pool(enable_notifications=True)

        assert pool._message_handler_factory is not None

        # Test that the default handler factory works
        handler = pool._message_handler_factory("http://test:8080", "gw-1")
        mock_notification_svc.create_message_handler.assert_called_once_with("gw-1", "http://test:8080")

        # Test handler factory with None gateway_id (falls back to URL)
        mock_notification_svc.create_message_handler.reset_mock()
        handler = pool._message_handler_factory("http://test:8080", None)
        mock_notification_svc.create_message_handler.assert_called_once_with("http://test:8080", "http://test:8080")

        await close_mcp_session_pool()

    @pytest.mark.asyncio
    async def test_init_with_custom_handler_factory(self):
        """When custom handler factory provided, should not auto-create notifications."""
        custom_factory = MagicMock()
        pool = init_mcp_session_pool(enable_notifications=True, message_handler_factory=custom_factory)

        assert pool._message_handler_factory is custom_factory
        await close_mcp_session_pool()


# ---------------------------------------------------------------------------
# Session context manager error handling
# ---------------------------------------------------------------------------
class TestSessionContextManagerEdgeCases:
    """Cover session context manager exception handling."""

    @pytest.mark.asyncio
    async def test_session_context_manager_releases_on_exception(self):
        """Session should be released even if body raises."""
        pool = MCPSessionPool()

        mock_session = PooledSession(
            session=MagicMock(), transport_context=MagicMock(),
            url="http://test:8080", identity_key="anonymous",
            transport_type=TransportType.STREAMABLE_HTTP, headers={},
        )

        with patch.object(pool, "_create_session", new_callable=AsyncMock, return_value=mock_session):
            with patch.object(pool, "release", new_callable=AsyncMock) as mock_release:
                with pytest.raises(ValueError, match="test error"):
                    async with pool.session("http://test:8080") as pooled:
                        raise ValueError("test error")

        mock_release.assert_awaited_once_with(mock_session)
        await pool.close_all()


# ---------------------------------------------------------------------------
# get_metrics with session affinity metrics
# ---------------------------------------------------------------------------
class TestGetMetricsWithAffinity:
    """Cover get_metrics session affinity metrics."""

    def test_get_metrics_with_affinity_data(self):
        """Metrics should include session affinity data."""
        pool = MCPSessionPool()
        pool._session_affinity_local_hits = 5
        pool._session_affinity_redis_hits = 3
        pool._session_affinity_misses = 2
        pool._forwarded_requests = 1
        pool._forwarded_request_failures = 0
        pool._forwarded_request_timeouts = 0

        metrics = pool.get_metrics()
        affinity = metrics["session_affinity"]
        assert affinity["local_hits"] == 5
        assert affinity["redis_hits"] == 3
        assert affinity["misses"] == 2
        assert affinity["hit_rate"] == 0.8
        assert affinity["forwarded_requests"] == 1

    def test_get_metrics_with_pool_data(self):
        """Metrics should include per-pool data."""
        pool = MCPSessionPool()
        pool_key = ("anonymous", "http://test:8080", "anonymous", "streamablehttp", "gw-1")
        pool._pools[pool_key] = asyncio.Queue(maxsize=10)
        pool._active[pool_key] = set()

        metrics = pool.get_metrics()
        assert len(metrics["pools"]) == 1

    def test_get_metrics_circuit_breakers(self):
        """Metrics should include circuit breaker data."""
        pool = MCPSessionPool()
        pool._failures["http://test:8080"] = 3
        pool._circuit_open_until["http://test:8080"] = time.time() + 60

        metrics = pool.get_metrics()
        assert "http://test:8080" in metrics["circuit_breakers"]
        assert metrics["circuit_breakers"]["http://test:8080"]["failures"] == 3
