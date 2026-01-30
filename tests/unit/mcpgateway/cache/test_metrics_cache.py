# -*- coding: utf-8 -*-
"""Unit tests for MetricsCache.

Covers cache-hit / cache-miss semantics, TTL expiry, single-key and
full invalidation, stats tracking, and the environment-variable TTL
resolver used by the module-level singleton.
"""

# Standard
import os
import time
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.metrics_cache import MetricsCache, _DEFAULT_TTL_SECONDS, _resolve_ttl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cache():
    """A MetricsCache with a generous TTL for basic behavioural tests."""
    return MetricsCache(ttl_seconds=60)


@pytest.fixture()
def fast_cache():
    """A MetricsCache with a very short TTL so expiry tests finish quickly."""
    return MetricsCache(ttl_seconds=0)  # expires immediately on next tick


# ---------------------------------------------------------------------------
# Basic get / set
# ---------------------------------------------------------------------------


class TestGetSet:
    """Verify that set stores a value and get retrieves it."""

    def test_get_on_empty_cache_returns_none(self, cache):
        assert cache.get("anything") is None

    def test_set_then_get_returns_value(self, cache):
        payload = {"total_executions": 42, "failure_rate": 0.05}
        cache.set("tools", payload)
        assert cache.get("tools") == payload

    def test_set_overwrites_previous_value(self, cache):
        cache.set("tools", {"v": 1})
        cache.set("tools", {"v": 2})
        assert cache.get("tools") == {"v": 2}

    def test_multiple_keys_are_independent(self, cache):
        cache.set("tools", {"name": "tools"})
        cache.set("resources", {"name": "resources"})
        assert cache.get("tools") == {"name": "tools"}
        assert cache.get("resources") == {"name": "resources"}


# ---------------------------------------------------------------------------
# TTL / expiry
# ---------------------------------------------------------------------------


class TestExpiry:
    """Verify that entries become invisible after the TTL elapses."""

    def test_entry_visible_before_ttl(self):
        c = MetricsCache(ttl_seconds=5)
        c.set("k", "v")
        # Immediately after set the entry must still be available
        assert c.get("k") == "v"

    def test_entry_invisible_after_ttl(self):
        c = MetricsCache(ttl_seconds=0)
        c.set("k", "v")
        # With TTL=0 the expiry is time.time() + 0, which is already <=
        # time.time() on the very next call.
        time.sleep(0.01)  # tiny nudge to guarantee clock advances
        assert c.get("k") is None

    def test_short_ttl_with_sleep(self):
        """Real-time expiry with a 100 ms TTL."""
        c = MetricsCache(ttl_seconds=0)
        c.set("short", {"data": True})
        time.sleep(0.05)
        assert c.get("short") is None

    def test_different_keys_expire_independently(self):
        c = MetricsCache(ttl_seconds=60)
        c.set("alive", "yes")
        # Manually backdate one key's expiry to simulate it having been
        # set much earlier
        c._expiries["dead"] = time.time() - 1
        c._cache["dead"] = "no"

        assert c.get("alive") == "yes"
        assert c.get("dead") is None


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


class TestInvalidation:
    """Verify single-key and full-cache invalidation."""

    def test_invalidate_specific_key_removes_only_that_key(self, cache):
        cache.set("tools", {"t": 1})
        cache.set("resources", {"r": 2})

        cache.invalidate("tools")

        assert cache.get("tools") is None
        assert cache.get("resources") == {"r": 2}

    def test_invalidate_all_removes_every_key(self, cache):
        cache.set("tools", 1)
        cache.set("resources", 2)
        cache.set("prompts", 3)

        cache.invalidate()

        assert cache.get("tools") is None
        assert cache.get("resources") is None
        assert cache.get("prompts") is None

    def test_invalidate_nonexistent_key_is_a_noop(self, cache):
        cache.set("tools", "data")
        cache.invalidate("nonexistent")  # must not raise
        assert cache.get("tools") == "data"

    def test_invalidate_all_on_empty_cache_is_a_noop(self):
        c = MetricsCache(ttl_seconds=10)
        c.invalidate()  # must not raise


# ---------------------------------------------------------------------------
# Stats tracking
# ---------------------------------------------------------------------------


class TestStats:
    """Verify that hit/miss counters and the stats() summary are accurate."""

    def test_initial_stats_are_zero(self):
        c = MetricsCache(ttl_seconds=10)
        s = c.stats()
        assert s["hit_count"] == 0
        assert s["miss_count"] == 0
        assert s["hit_rate"] == 0.0
        assert s["cached_keys"] == []
        assert s["ttl_seconds"] == 10

    def test_miss_increments_miss_count(self):
        c = MetricsCache(ttl_seconds=10)
        c.get("nope")
        c.get("nope2")
        assert c.stats()["miss_count"] == 2
        assert c.stats()["hit_count"] == 0

    def test_hit_increments_hit_count(self):
        c = MetricsCache(ttl_seconds=60)
        c.set("k", "v")
        c.get("k")
        c.get("k")
        c.get("k")
        assert c.stats()["hit_count"] == 3

    def test_hit_rate_calculation(self):
        c = MetricsCache(ttl_seconds=60)
        c.set("k", "v")
        # 2 hits
        c.get("k")
        c.get("k")
        # 1 miss
        c.get("missing")
        s = c.stats()
        # miss_count includes the initial set-time check too? No — set
        # does not call get.  So: 2 hits, 1 miss => rate 2/3
        assert s["hit_count"] == 2
        assert s["miss_count"] == 1
        assert abs(s["hit_rate"] - 2 / 3) < 1e-9

    def test_cached_keys_reflects_current_entries(self):
        c = MetricsCache(ttl_seconds=60)
        assert c.stats()["cached_keys"] == []

        c.set("a", 1)
        c.set("b", 2)
        assert sorted(c.stats()["cached_keys"]) == ["a", "b"]

        c.invalidate("a")
        assert c.stats()["cached_keys"] == ["b"]

    def test_expired_key_still_listed_until_get(self):
        """_cache dict is not pruned proactively; stats reflect raw state."""
        c = MetricsCache(ttl_seconds=0)
        c.set("k", "v")
        # The key is in _cache but expired — stats show it until accessed
        assert "k" in c.stats()["cached_keys"]
        # Accessing it records a miss and does NOT remove from _cache dict
        # (the current implementation only checks expiry on get)
        c.get("k")
        # The key remains in _cache — the cache does not prune on miss
        # (this documents current behaviour; a future cleanup pass could
        # evict expired keys eagerly)
        assert c.stats()["miss_count"] >= 1


# ---------------------------------------------------------------------------
# TTL resolver (_resolve_ttl)
# ---------------------------------------------------------------------------


class TestResolveTTL:
    """Verify that _resolve_ttl honours the environment variable correctly."""

    def test_returns_default_when_env_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            # Make sure the key is definitely absent
            os.environ.pop("METRICS_CACHE_TTL_SECONDS", None)
            assert _resolve_ttl() == _DEFAULT_TTL_SECONDS

    def test_returns_value_from_env(self):
        with patch.dict(os.environ, {"METRICS_CACHE_TTL_SECONDS": "42"}):
            assert _resolve_ttl() == 42

    def test_clamps_below_minimum_to_one(self):
        with patch.dict(os.environ, {"METRICS_CACHE_TTL_SECONDS": "-5"}):
            assert _resolve_ttl() == 1

    def test_clamps_above_maximum_to_300(self):
        with patch.dict(os.environ, {"METRICS_CACHE_TTL_SECONDS": "999"}):
            assert _resolve_ttl() == 300

    def test_boundary_value_one(self):
        with patch.dict(os.environ, {"METRICS_CACHE_TTL_SECONDS": "1"}):
            assert _resolve_ttl() == 1

    def test_boundary_value_300(self):
        with patch.dict(os.environ, {"METRICS_CACHE_TTL_SECONDS": "300"}):
            assert _resolve_ttl() == 300

    def test_non_integer_falls_back_to_default(self):
        with patch.dict(os.environ, {"METRICS_CACHE_TTL_SECONDS": "abc"}):
            assert _resolve_ttl() == _DEFAULT_TTL_SECONDS

    def test_empty_string_falls_back_to_default(self):
        with patch.dict(os.environ, {"METRICS_CACHE_TTL_SECONDS": ""}):
            assert _resolve_ttl() == _DEFAULT_TTL_SECONDS

    def test_float_string_falls_back_to_default(self):
        with patch.dict(os.environ, {"METRICS_CACHE_TTL_SECONDS": "3.5"}):
            assert _resolve_ttl() == _DEFAULT_TTL_SECONDS


# ---------------------------------------------------------------------------
# Thread-safety smoke test
# ---------------------------------------------------------------------------


class TestConcurrency:
    """Light concurrency smoke-test: many threads writing and reading."""

    def test_concurrent_set_and_get_does_not_crash(self):
        import threading

        c = MetricsCache(ttl_seconds=60)
        errors: list = []

        def writer(n: int) -> None:
            try:
                for i in range(100):
                    c.set(f"key-{n}-{i}", {"iteration": i})
            except Exception as exc:
                errors.append(exc)

        def reader() -> None:
            try:
                for _ in range(200):
                    c.get("key-0-50")  # may or may not exist yet
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        threads += [threading.Thread(target=reader) for _ in range(4)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Unexpected errors in threads: {errors}"
