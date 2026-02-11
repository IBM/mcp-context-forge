# -*- coding: utf-8 -*-
"""Tests for mcpgateway.cache.global_config_cache."""

# Standard
from unittest.mock import Mock

# Third-Party
import pytest

# First-Party
from mcpgateway.cache import global_config_cache as global_cache_module


def test_get_double_checked_lock_returns_refreshed_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover the lock re-check branch where another thread refreshed the cache."""
    cache = global_cache_module.GlobalConfigCache(ttl_seconds=60)
    fixed_now = 1234.0
    monkeypatch.setattr(global_cache_module.time, "time", lambda: fixed_now)

    cache._cache = cache._NOT_CACHED
    cache._expiry = 0

    refreshed = object()

    class _Lock:
        def __enter__(self):
            cache._cache = refreshed
            cache._expiry = fixed_now + 60
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    cache._lock = _Lock()

    db = Mock()
    result = cache.get(db)

    assert result is refreshed
    assert cache._hit_count == 1
    db.query.assert_not_called()

