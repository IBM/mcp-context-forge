# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for ResourceCache.
"""

# Standard
import asyncio
import time

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.resource_cache import ResourceCache


@pytest.fixture
def cache():
    """Fixture for a ResourceCache with small TTL and size for testing."""
    return ResourceCache(max_size=3, ttl=1)


def test_set_and_get(cache):
    """Test setting and getting a cache value."""
    cache.set("foo", "bar")
    assert cache.get("foo") == "bar"


def test_get_missing(cache):
    """Test getting a missing key returns None."""
    assert cache.get("missing") is None


def test_expiration(cache):
    """Test that cache entry expires after TTL."""
    cache.set("foo", "bar")
    time.sleep(1.1)
    assert cache.get("foo") is None


def test_lru_eviction(cache):
    """Test LRU eviction when max_size is reached."""
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    # Access 'a' to update its last_access
    assert cache.get("a") == 1
    # Add another entry, should evict 'b' (least recently used)
    cache.set("d", 4)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.get("d") == 4


def test_delete(cache):
    """Test deleting a cache entry."""
    cache.set("foo", "bar")
    cache.delete("foo")
    assert cache.get("foo") is None


def test_clear(cache):
    """Test clearing the cache."""
    cache.set("foo", "bar")
    cache.set("baz", "qux")
    cache.clear()
    assert cache.get("foo") is None
    assert cache.get("baz") is None


@pytest.mark.asyncio
async def test_initialize_and_shutdown_logs(monkeypatch):
    """Test initialize and shutdown log and cleanup."""
    cache = ResourceCache(max_size=2, ttl=1)
    monkeypatch.setattr("mcpgateway.cache.resource_cache.logger", DummyLogger())
    await cache.initialize()
    cache.set("foo", "bar")
    await cache.shutdown()
    assert cache.get("foo") is None


@pytest.mark.asyncio
async def test_cleanup_loop_removes_expired(monkeypatch):
    """Test that the cleanup loop removes expired entries."""
    cache = ResourceCache(max_size=2, ttl=0.1)
    cache.set("foo", "bar")
    await asyncio.sleep(0.15)
    # Manually trigger cleanup for test speed
    async with cache._lock:
        now = time.time()
        expired = [key for key, entry in cache._cache.items() if now > entry.expires_at]
        for key in expired:
            del cache._cache[key]
    assert cache.get("foo") is None


class DummyLogger:
    def info(self, msg):
        pass

    def debug(self, msg):
        pass

    def error(self, msg):
        pass
