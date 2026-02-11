# -*- coding: utf-8 -*-
"""Tests for mcpgateway.cache.a2a_stats_cache."""

# Standard
from unittest.mock import Mock

# Third-Party
import pytest

# First-Party
from mcpgateway.cache import a2a_stats_cache as a2a_cache_module


def test_get_counts_double_checked_lock_returns_refreshed_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover the "cache refreshed by another thread while waiting for lock" branch."""
    cache = a2a_cache_module.A2AStatsCache(ttl_seconds=30)
    fixed_now = 1234.0
    monkeypatch.setattr(a2a_cache_module.time, "time", lambda: fixed_now)

    # Ensure we take the slow path (miss) before acquiring the lock.
    cache._cache = cache._NOT_CACHED
    cache._expiry = 0

    refreshed = {"total": 1, "active": 1}

    class _Lock:
        def __enter__(self):
            # Simulate another thread having refreshed the cache just before we acquired the lock.
            cache._cache = refreshed
            cache._expiry = fixed_now + 60
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    cache._lock = _Lock()

    db = Mock()
    result = cache.get_counts(db)

    assert result == refreshed
    assert cache._hit_count == 1
    db.execute.assert_not_called()

