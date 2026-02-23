# -*- coding: utf-8 -*-
"""Tests for mcpgateway.cache.metrics_cache."""

# Standard
import builtins
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cache import metrics_cache as metrics_cache_module

try:
    from redis.exceptions import RedisError
except ImportError:
    RedisError = Exception  # type: ignore

# First-Party
from mcpgateway.cache.metrics_cache import MetricsCache


def test_create_metrics_cache_import_error_falls_back_to_default_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002 - match __import__ signature
        if name == "mcpgateway.config":
            raise ImportError("boom")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    cache = metrics_cache_module._create_metrics_cache()
    assert cache._ttl_seconds == 10


def test_is_cache_enabled_import_error_defaults_to_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002 - match __import__ signature
        if name == "mcpgateway.config":
            raise ImportError("boom")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    assert metrics_cache_module.is_cache_enabled() is True


class TestMetricsCacheLocal:
    """Tests for local (non-Redis) cache behavior."""

    def test_init_local_cache(self):
        """Test initialization without Redis."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)
        assert cache.use_redis is False
        assert cache.redis_client is None
        assert cache._ttl_seconds == 10

    def test_set_and_get_local(self):
        """Test basic set/get operations with local cache."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)
        test_data = {"total": 100, "successful": 95}

        cache.set("tools", test_data)
        result = cache.get("tools")

        assert result == test_data

    def test_get_nonexistent_local(self):
        """Test getting non-existent key returns None."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)
        assert cache.get("nonexistent") is None

    def test_expiration_local(self):
        """Test cache expiration with local cache."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)
        cache.set("tools", {"total": 100})

        # Should be cached
        assert cache.get("tools") is not None

        # Simulate time passing beyond TTL
        cache._expiries["tools"] = time.time() - 1
        assert cache.get("tools") is None

    def test_invalidate_specific_local(self):
        """Test invalidating specific cache entry."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)
        cache.set("tools", {"total": 100})
        cache.set("resources", {"total": 50})

        cache.invalidate("tools")

        assert cache.get("tools") is None
        assert cache.get("resources") is not None

    def test_invalidate_all_local(self):
        """Test invalidating all cache entries."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)
        cache.set("tools", {"total": 100})
        cache.set("resources", {"total": 50})

        cache.invalidate()

        assert cache.get("tools") is None
        assert cache.get("resources") is None

    def test_invalidate_prefix_local(self):
        """Test prefix-based invalidation."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)
        cache.set("top_tools:5", [{"id": "1"}])
        cache.set("top_tools:10", [{"id": "2"}])
        cache.set("tools", {"total": 100})

        cache.invalidate_prefix("top_tools:")

        assert cache.get("top_tools:5") is None
        assert cache.get("top_tools:10") is None
        assert cache.get("tools") is not None

    def test_stats_local(self):
        """Test cache statistics tracking."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)
        cache.set("tools", {"total": 100})

        # Generate hits and misses
        cache.get("tools")  # Hit
        cache.get("tools")  # Hit
        cache.get("missing")  # Miss

        stats = cache.stats()
        assert stats["hit_count"] == 2
        assert stats["miss_count"] == 1
        assert stats["hit_rate"] == 2/3
        assert stats["backend"] == "local"
        assert "tools" in stats["cached_types"]

    def test_reset_stats_local(self):
        """Test resetting statistics."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)
        cache.set("tools", {"total": 100})
        cache.get("tools")

        assert cache.stats()["hit_count"] == 1

        cache.reset_stats()

        stats = cache.stats()
        assert stats["hit_count"] == 0
        assert stats["miss_count"] == 0
        assert stats["local_hit_count"] == 0
        assert stats["local_miss_count"] == 0


class TestMetricsCacheRedis:
    """Tests for Redis-backed cache behavior."""

    def test_init_redis_cache(self):
        """Test initialization with Redis client."""
        mock_redis = MagicMock()
        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        assert cache.use_redis is True
        assert cache.redis_client is mock_redis
        assert cache._ttl_seconds == 60

    async def test_get_async_redis_hit(self):
        """Test async get with Redis hit."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({"total": 100})

        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)
        result = await cache.get_async("tools")

        assert result == {"total": 100}
        mock_redis.get.assert_called_once_with("metrics:tools")

    async def test_get_async_redis_miss(self):
        """Test async get with Redis miss."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)
        result = await cache.get_async("tools")

        assert result is None
        mock_redis.get.assert_called_once_with("metrics:tools")

    async def test_set_async_redis(self):
        """Test async set with Redis."""
        mock_redis = AsyncMock()
        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        test_data = {"total": 100, "successful": 95}
        await cache.set_async("tools", test_data)

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "metrics:tools"
        assert call_args[0][1] == 60
        assert json.loads(call_args[0][2]) == test_data

    async def test_invalidate_async_specific_redis(self):
        """Test async invalidation of specific key."""
        mock_redis = AsyncMock()
        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        await cache.invalidate_async("tools")

        mock_redis.delete.assert_called_once_with("metrics:tools")

    async def test_invalidate_async_all_redis_with_scan(self):
        """Test async invalidation of all keys using SCAN with batch delete."""
        mock_redis = AsyncMock()

        # Mock scan_iter to return keys
        async def mock_scan_iter(pattern):
            for key in ["metrics:tools", "metrics:resources", "metrics:prompts"]:
                yield key

        mock_redis.scan_iter = mock_scan_iter
        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        await cache.invalidate_async(None)

        # Should have called delete once with all keys (batch delete)
        mock_redis.delete.assert_called_once_with("metrics:tools", "metrics:resources", "metrics:prompts")

    async def test_redis_fallback_on_error(self):
        """Test fallback to local cache on Redis error."""
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = RedisError("Redis connection failed")

        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        # Should fall back to local cache (which is empty)
        result = await cache.get_async("tools")
        assert result is None

    async def test_redis_stats_tracking(self):
        """Test separate Redis and local stats tracking."""
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = [
            json.dumps({"total": 100}),  # Redis hit
            None,  # Redis miss
        ]

        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        await cache.get_async("tools")  # Redis hit
        await cache.get_async("missing")  # Redis miss

        stats = cache.stats()
        assert stats["redis_hit_count"] == 1
        assert stats["redis_miss_count"] == 1
        assert stats["hit_count"] == 1
        assert stats["miss_count"] == 1

    async def test_set_async_also_populates_local_cache(self):
        """Test that set_async writes to both Redis and local cache."""
        mock_redis = AsyncMock()
        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        test_data = {"total": 100, "successful": 95}
        await cache.set_async("tools", test_data)

        # Local cache should also have the value
        assert cache._caches.get("tools") == test_data
        assert "tools" in cache._expiries

    async def test_get_async_fallback_with_populated_local_cache(self):
        """Test fallback to local cache when Redis errors but local has data."""
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = RedisError("Redis connection failed")

        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        # Populate local cache first
        test_data = {"total": 100}
        cache._caches["tools"] = test_data
        cache._expiries["tools"] = time.time() + 60

        # Should fall back to local cache and return the data
        result = await cache.get_async("tools")
        assert result == test_data

    async def test_invalidate_async_clears_local_cache_on_redis_error(self):
        """Test that invalidate_async clears local cache even if Redis fails."""
        mock_redis = AsyncMock()
        mock_redis.delete.side_effect = RedisError("Redis connection failed")

        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        # Populate local cache
        cache._caches["tools"] = {"total": 100}
        cache._expiries["tools"] = time.time() + 60

        # Invalidate should clear local cache despite Redis error
        await cache.invalidate_async("tools")

        assert "tools" not in cache._caches
        assert "tools" not in cache._expiries

    async def test_invalidate_prefix_async_redis(self):
        """Test async prefix invalidation with Redis scan + batch delete."""
        mock_redis = AsyncMock()

        # Mock scan_iter to return matching keys
        async def mock_scan_iter(pattern):
            for key in ["metrics:top_tools:5", "metrics:top_tools:10"]:
                yield key

        mock_redis.scan_iter = mock_scan_iter
        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        # Populate local cache
        cache._caches["top_tools:5"] = [{"id": "1"}]
        cache._caches["top_tools:10"] = [{"id": "2"}]
        cache._caches["tools"] = {"total": 100}
        cache._expiries["top_tools:5"] = time.time() + 60
        cache._expiries["top_tools:10"] = time.time() + 60
        cache._expiries["tools"] = time.time() + 60

        await cache.invalidate_prefix_async("top_tools:")

        # Should have called delete with matched keys
        mock_redis.delete.assert_called_once_with("metrics:top_tools:5", "metrics:top_tools:10")
        # Local cache should also be cleared for matching keys
        assert "top_tools:5" not in cache._caches
        assert "top_tools:10" not in cache._caches
        # Non-matching key should remain
        assert cache._caches.get("tools") == {"total": 100}

    async def test_invalidate_prefix_async_redis_error_fallback(self):
        """Test that invalidate_prefix_async clears local cache even if Redis fails."""
        mock_redis = AsyncMock()

        # Make scan_iter raise an error
        async def mock_scan_iter(pattern):
            raise RedisError("Redis connection failed")
            yield  # Make it an async generator  # noqa: RUF027

        mock_redis.scan_iter = mock_scan_iter
        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        # Populate local cache
        cache._caches["top_tools:5"] = [{"id": "1"}]
        cache._expiries["top_tools:5"] = time.time() + 60

        # Should still clear local cache despite Redis error
        await cache.invalidate_prefix_async("top_tools:")

        assert "top_tools:5" not in cache._caches
        assert "top_tools:5" not in cache._expiries


class TestMetricsCacheSyncAsyncSeparation:
    """Tests for sync/async method separation with Redis."""

    def test_sync_methods_warn_once_with_redis(self, caplog):
        """Test that sync methods log warning only once when Redis is active."""
        mock_redis = MagicMock()
        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        # Call multiple sync methods
        cache.get("tools")
        cache.set("tools", {"total": 100})
        cache.invalidate("resources")
        cache.invalidate_prefix("top_")

        # Should only have one warning
        warnings = [r for r in caplog.records if "Sync methods" in r.message and "Redis backend active" in r.message]
        assert len(warnings) == 1
        assert "This warning will only be shown once" in warnings[0].message

    def test_sync_methods_work_with_redis_local_fallback(self):
        """Test that sync methods work with Redis active (local fallback)."""
        mock_redis = MagicMock()
        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        # Should work using local cache
        cache.set("tools", {"total": 100})
        result = cache.get("tools")
        assert result == {"total": 100}

        cache.invalidate("tools")
        assert cache.get("tools") is None

    def test_sync_methods_work_without_redis(self):
        """Test that sync methods work normally without Redis."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)

        # Should not raise or warn
        cache.set("tools", {"total": 100})
        result = cache.get("tools")
        assert result == {"total": 100}

        cache.invalidate("tools")
        assert cache.get("tools") is None


class TestMetricsCacheFactory:
    """Tests for cache factory function."""

    @patch("mcpgateway.cache.metrics_cache.REDIS_AVAILABLE", True)
    @patch("mcpgateway.cache.metrics_cache.Redis")
    @patch("mcpgateway.config.settings")
    def test_create_with_redis_enabled(self, mock_settings, mock_redis_class):
        """Test factory creates Redis-backed cache when configured."""
        mock_settings.metrics_cache_ttl_seconds = 30
        mock_settings.metrics_cache_use_redis = True
        mock_settings.redis_url = "redis://localhost:6379"

        mock_redis_instance = MagicMock()
        mock_redis_class.from_url.return_value = mock_redis_instance

        from mcpgateway.cache.metrics_cache import _create_metrics_cache
        cache = _create_metrics_cache()

        assert cache.use_redis is True
        assert cache._ttl_seconds == 30
        mock_redis_class.from_url.assert_called_once_with(
            "redis://localhost:6379",
            decode_responses=True
        )

    @patch("mcpgateway.config.settings")
    def test_create_without_redis(self, mock_settings):
        """Test factory creates local cache when Redis disabled."""
        mock_settings.metrics_cache_ttl_seconds = 15
        mock_settings.metrics_cache_use_redis = False
        mock_settings.redis_url = None

        from mcpgateway.cache.metrics_cache import _create_metrics_cache
        cache = _create_metrics_cache()

        assert cache.use_redis is False
        assert cache._ttl_seconds == 15

    @patch("mcpgateway.cache.metrics_cache.REDIS_AVAILABLE", True)
    @patch("mcpgateway.cache.metrics_cache.Redis")
    @patch("mcpgateway.config.settings")
    def test_create_redis_connection_failure(self, mock_settings, mock_redis_class):
        """Test factory handles Redis connection failure gracefully."""
        mock_settings.metrics_cache_ttl_seconds = 30
        mock_settings.metrics_cache_use_redis = True
        mock_settings.redis_url = "redis://localhost:6379"

        # Simulate connection failure
        mock_redis_class.from_url.side_effect = ConnectionError("Connection refused")

        from mcpgateway.cache.metrics_cache import _create_metrics_cache
        cache = _create_metrics_cache()

        # Should fall back to local cache
        assert cache.use_redis is False


class TestMetricsCacheSingleton:
    """Tests for module-level singleton and is_cache_enabled()."""

    @patch("mcpgateway.config.settings")
    def test_is_cache_enabled_returns_true_when_enabled(self, mock_settings):
        """Test is_cache_enabled() returns True when cache is enabled."""
        mock_settings.metrics_cache_enabled = True

        from mcpgateway.cache.metrics_cache import is_cache_enabled
        assert is_cache_enabled() is True

    @patch("mcpgateway.config.settings")
    def test_is_cache_enabled_returns_false_when_disabled(self, mock_settings):
        """Test is_cache_enabled() returns False when cache is disabled."""
        mock_settings.metrics_cache_enabled = False

        from mcpgateway.cache.metrics_cache import is_cache_enabled
        assert is_cache_enabled() is False

    def test_metrics_cache_singleton_exists(self):
        """Test that metrics_cache singleton is accessible."""
        from mcpgateway.cache.metrics_cache import metrics_cache

        assert metrics_cache is not None
        assert isinstance(metrics_cache, MetricsCache)


class TestMetricsCacheResetStats:
    """Tests for reset_stats() completeness."""

    def test_reset_stats_resets_all_counters(self):
        """Test that reset_stats() resets all 6 counters."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)

        # Manually set all counters
        cache._total_hit_count = 10
        cache._total_miss_count = 5
        cache._redis_hit_count = 3
        cache._redis_miss_count = 2
        cache._local_hit_count = 7
        cache._local_miss_count = 3

        cache.reset_stats()

        # All should be zero
        assert cache._total_hit_count == 0
        assert cache._total_miss_count == 0
        assert cache._redis_hit_count == 0
        assert cache._redis_miss_count == 0
        assert cache._local_hit_count == 0
        assert cache._local_miss_count == 0

    def test_stats_consistency_after_reset(self):
        """Test that stats remain consistent after reset."""
        cache = MetricsCache(redis_client=None, ttl_seconds=10)
        cache.set("tools", {"total": 100})
        cache.get("tools")  # Hit
        cache.get("missing")  # Miss

        cache.reset_stats()

        stats = cache.stats()
        assert stats["hit_count"] == 0
        assert stats["miss_count"] == 0
        assert stats["local_hit_count"] == 0
        assert stats["local_miss_count"] == 0
        assert stats["hit_rate"] == 0.0


class TestMetricsCacheRedisUnavailable:
    """Tests for when Redis library is not available."""

    def test_redis_client_provided_but_not_available(self, monkeypatch):
        """Test warning when redis_client provided but REDIS_AVAILABLE is False."""
        monkeypatch.setattr(metrics_cache_module, "REDIS_AVAILABLE", False)
        mock_redis = MagicMock()

        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=10)

        assert cache.use_redis is False

    @pytest.mark.asyncio
    async def test_set_async_redis_error_falls_through_to_local(self):
        """Test that set_async falls through to local cache on Redis error."""
        mock_redis = AsyncMock()
        mock_redis.setex.side_effect = RedisError("Connection refused")

        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)
        test_data = {"total": 100}

        await cache.set_async("tools", test_data)

        # Should have fallen back to local cache
        assert cache._caches.get("tools") == test_data

    def test_sync_invalidate_warns_with_redis(self, caplog):
        """Test that sync invalidate() warns when Redis is active (first call)."""
        mock_redis = MagicMock()
        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        cache.invalidate("tools")

        warnings = [r for r in caplog.records if "Sync methods" in r.message]
        assert len(warnings) == 1

    def test_sync_invalidate_prefix_warns_with_redis(self, caplog):
        """Test that sync invalidate_prefix() warns when Redis is active (first call)."""
        mock_redis = MagicMock()
        cache = MetricsCache(redis_client=mock_redis, ttl_seconds=60)

        cache.invalidate_prefix("top_")

        warnings = [r for r in caplog.records if "Sync methods" in r.message]
        assert len(warnings) == 1
