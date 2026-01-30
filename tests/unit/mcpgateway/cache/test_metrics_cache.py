# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/cache/test_metrics_cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for MetricsCache.
"""

# Standard
import time

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.metrics_cache import MetricsCache


@pytest.fixture
def cache():
    """Fixture for a MetricsCache with default TTL."""
    return MetricsCache(ttl_seconds=10)


@pytest.fixture
def short_cache():
    """Fixture for a MetricsCache with short TTL for expiration tests."""
    return MetricsCache(ttl_seconds=0.1)


class TestMetricsCacheGet:
    """Tests for cache get behavior."""

    def test_get_missing_key_returns_none(self, cache):
        """Cache miss on a key that was never set returns None."""
        assert cache.get("nonexistent") is None

    def test_get_after_set_returns_value(self, cache):
        """Cache hit returns the stored value."""
        cache.set("tools", {"total_executions": 42})
        result = cache.get("tools")
        assert result == {"total_executions": 42}

    def test_get_returns_exact_object(self, cache):
        """Cache returns the same object that was stored."""
        data = {"total": 5, "nested": {"key": "value"}}
        cache.set("key", data)
        assert cache.get("key") is data

    def test_get_different_keys_independent(self, cache):
        """Different cache keys store independent values."""
        cache.set("tools", {"total": 10})
        cache.set("resources", {"total": 20})
        assert cache.get("tools") == {"total": 10}
        assert cache.get("resources") == {"total": 20}


class TestMetricsCacheExpiration:
    """Tests for TTL expiration behavior."""

    def test_entry_expires_after_ttl(self, short_cache):
        """Cached value expires and returns None after TTL."""
        short_cache.set("tools", {"total": 5})
        assert short_cache.get("tools") == {"total": 5}

        time.sleep(0.15)

        assert short_cache.get("tools") is None

    def test_entry_valid_before_ttl(self):
        """Cached value is still available within TTL window."""
        cache = MetricsCache(ttl_seconds=5)
        cache.set("tools", {"total": 5})
        assert cache.get("tools") == {"total": 5}

    def test_independent_expiry_per_key(self):
        """Each key has its own expiry timestamp."""
        cache = MetricsCache(ttl_seconds=0.1)
        cache.set("first", "value1")
        time.sleep(0.05)
        cache.set("second", "value2")
        time.sleep(0.06)

        # first should be expired (set 0.11s ago), second still valid (set 0.06s ago)
        assert cache.get("first") is None
        assert cache.get("second") == "value2"

    def test_overwrite_resets_expiry(self, short_cache):
        """Setting a key again resets its TTL."""
        short_cache.set("tools", {"v": 1})
        time.sleep(0.06)
        short_cache.set("tools", {"v": 2})
        time.sleep(0.06)

        # Only 0.06s since last set, still within 0.1s TTL
        assert short_cache.get("tools") == {"v": 2}


class TestMetricsCacheInvalidation:
    """Tests for cache invalidation."""

    def test_invalidate_single_key(self, cache):
        """Invalidating a specific key removes only that key."""
        cache.set("tools", {"total": 10})
        cache.set("resources", {"total": 20})

        cache.invalidate("tools")

        assert cache.get("tools") is None
        assert cache.get("resources") == {"total": 20}

    def test_invalidate_all(self, cache):
        """Invalidating without a key clears all entries."""
        cache.set("tools", {"total": 10})
        cache.set("resources", {"total": 20})
        cache.set("prompts", {"total": 30})

        cache.invalidate()

        assert cache.get("tools") is None
        assert cache.get("resources") is None
        assert cache.get("prompts") is None

    def test_invalidate_nonexistent_key_is_noop(self, cache):
        """Invalidating a key that doesn't exist does not raise."""
        cache.invalidate("nonexistent")

    def test_set_after_invalidate(self, cache):
        """Cache can be populated again after invalidation."""
        cache.set("tools", {"total": 10})
        cache.invalidate()
        assert cache.get("tools") is None

        cache.set("tools", {"total": 20})
        assert cache.get("tools") == {"total": 20}


class TestMetricsCacheStats:
    """Tests for cache statistics tracking."""

    def test_initial_stats(self, cache):
        """Fresh cache has zero hits and misses."""
        stats = cache.stats()
        assert stats["hit_count"] == 0
        assert stats["miss_count"] == 0
        assert stats["hit_rate"] == 0.0
        assert stats["ttl_seconds"] == 10
        assert stats["cached_keys"] == []

    def test_miss_increments_counter(self, cache):
        """Cache miss increments miss counter."""
        cache.get("missing")
        cache.get("also_missing")
        stats = cache.stats()
        assert stats["miss_count"] == 2
        assert stats["hit_count"] == 0

    def test_hit_increments_counter(self, cache):
        """Cache hit increments hit counter."""
        cache.set("tools", {"total": 5})
        cache.get("tools")
        cache.get("tools")
        stats = cache.stats()
        assert stats["hit_count"] == 2
        assert stats["miss_count"] == 0

    def test_hit_rate_calculation(self, cache):
        """Hit rate is correctly calculated as hits / total."""
        cache.set("tools", {"total": 5})
        cache.get("tools")  # hit
        cache.get("tools")  # hit
        cache.get("tools")  # hit
        cache.get("missing")  # miss
        stats = cache.stats()
        assert stats["hit_rate"] == 0.75

    def test_expired_entry_counts_as_miss(self, short_cache):
        """Accessing an expired entry increments the miss counter."""
        short_cache.set("tools", {"total": 5})
        short_cache.get("tools")  # hit

        time.sleep(0.15)

        short_cache.get("tools")  # miss (expired)
        stats = short_cache.stats()
        assert stats["hit_count"] == 1
        assert stats["miss_count"] == 1

    def test_cached_keys_reflects_state(self, cache):
        """cached_keys in stats lists currently stored keys."""
        cache.set("tools", {"total": 10})
        cache.set("resources", {"total": 20})
        stats = cache.stats()
        assert sorted(stats["cached_keys"]) == ["resources", "tools"]

    def test_stats_reflects_ttl(self):
        """TTL in stats matches the configured value."""
        cache = MetricsCache(ttl_seconds=42)
        assert cache.stats()["ttl_seconds"] == 42


class TestMetricsCacheConstructor:
    """Tests for constructor and configuration."""

    def test_default_ttl(self):
        """Default TTL is 10 seconds."""
        cache = MetricsCache()
        assert cache.ttl_seconds == 10

    def test_custom_ttl(self):
        """Custom TTL is respected."""
        cache = MetricsCache(ttl_seconds=60)
        assert cache.ttl_seconds == 60

    def test_ttl_of_one_second(self):
        """Minimum practical TTL works correctly."""
        cache = MetricsCache(ttl_seconds=1)
        cache.set("key", "value")
        assert cache.get("key") == "value"


class TestMetricsCacheConfigIntegration:
    """Tests for configuration integration."""

    def test_get_configured_ttl_returns_int(self):
        """_get_configured_ttl returns an integer."""
        from mcpgateway.cache.metrics_cache import _get_configured_ttl

        ttl = _get_configured_ttl()
        assert isinstance(ttl, int)
        assert ttl >= 1

    def test_global_singleton_uses_config(self):
        """The global metrics_cache singleton reads TTL from config."""
        from mcpgateway.cache.metrics_cache import metrics_cache

        assert metrics_cache.ttl_seconds >= 1

    def test_get_configured_ttl_fallback(self):
        """_get_configured_ttl falls back to 10 when settings unavailable."""
        from unittest.mock import patch

        from mcpgateway.cache.metrics_cache import _get_configured_ttl

        # The import happens inside _get_configured_ttl, so patch the import itself
        with patch.dict("sys.modules", {"mcpgateway.config": None}):
            ttl = _get_configured_ttl()
            assert ttl == 10
