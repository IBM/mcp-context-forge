# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/cache/test_resource_cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for ResourceCache.
"""

# Standard
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
    assert len(cache) == 1


def test_get_missing(cache):
    """Test getting a missing key returns None."""
    assert cache.get("missing") is None


def test_expiration():
    """Test that cache entry expires after TTL."""
    # Use short TTL for faster test execution
    fast_cache = ResourceCache(max_size=3, ttl=0.1)
    fast_cache.set("foo", "bar")

    # Sleep for 0.15 seconds (50% longer than TTL) to ensure expiration
    time.sleep(0.15)

    # Entry should definitely be expired now
    assert len(fast_cache) == 1
    assert fast_cache.get("foo") is None
    # Entry should be deleted following get operation
    assert len(fast_cache) == 0


def test_lru_eviction(cache):
    """Test LRU eviction when max_size is reached."""
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    # Access 'a' to update its position in the ordered cache
    assert len(cache) == cache.max_size
    assert cache.get("a") == 1
    # Add another entry, should evict 'b' (least recently used) and keep cache length
    cache.set("d", 4)
    assert len(cache) == cache.max_size

    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.get("d") == 4


def test_delete(cache):
    """Test deleting a cache entry."""
    cache.set("foo", "bar")
    assert len(cache) == 1
    cache.delete("foo")
    assert len(cache) == 0
    assert cache.get("foo") is None


def test_clear(cache):
    """Test clearing the cache."""
    cache.set("foo", "bar")
    cache.set("baz", "qux")
    assert len(cache) == 2
    cache.clear()
    assert cache.get("foo") is None
    assert cache.get("baz") is None
    assert len(cache) == 0


@pytest.mark.asyncio
async def test_initialize_and_shutdown_logs(monkeypatch):
    """Test initialize and shutdown log and cleanup."""
    cache = ResourceCache(max_size=2, ttl=1)
    monkeypatch.setattr("mcpgateway.cache.resource_cache.logger", DummyLogger())
    await cache.initialize()
    cache.set("foo", "bar")
    await cache.shutdown()
    assert cache.get("foo") is None
    assert len(cache) == 0


def test_cleanup_once_removes_expired():
    """Test that _cleanup_once removes expired entries via heap-based cleanup."""
    cache = ResourceCache(max_size=2, ttl=0.1)
    cache.set("foo", "bar")
    cache.set("baz", "qux")

    # Verify entries exist before expiration
    assert len(cache) == 2
    assert cache.get("foo") == "bar"

    # Wait for TTL expiration
    time.sleep(0.15)

    # Entries still in cache (not yet cleaned)
    assert len(cache._cache) == 2

    # Trigger heap-based cleanup
    cache._cleanup_once()

    # Entries should be removed by cleanup
    assert len(cache) == 0
    assert cache.get("foo") is None
    assert cache.get("baz") is None


def test_cleanup_once_ignores_updated_entries():
    """Test that _cleanup_once skips entries that were updated after heap entry was created."""
    cache = ResourceCache(max_size=2, ttl=0.1)
    cache.set("foo", "bar")

    # Wait for original expiry
    time.sleep(0.15)

    # Update the entry with a new value (creates new heap entry with new expiry)
    cache.set("foo", "updated")

    # Cleanup should ignore the stale heap entry since timestamps don't match
    cache._cleanup_once()

    # Entry should still exist (was updated)
    assert cache.get("foo") == "updated"


def test_cleanup_once_ignores_deleted_entries():
    """Test that _cleanup_once handles entries deleted before cleanup runs."""
    cache = ResourceCache(max_size=2, ttl=0.1)
    cache.set("foo", "bar")

    # Delete entry before expiry
    cache.delete("foo")

    # Wait for original expiry time
    time.sleep(0.15)

    # Cleanup should handle missing entry gracefully
    cache._cleanup_once()  # Should not raise

    assert cache.get("foo") is None


def test_heap_compaction_bounds_memory():
    """Test that heap compaction triggers when heap grows too large."""
    cache = ResourceCache(max_size=3, ttl=60)

    # Repeatedly update the same key to create stale heap entries
    for i in range(10):
        cache.set("key1", i)

    # Heap should have 10 entries (one per set call), but cache has 1 entry
    assert len(cache._expiry_heap) == 10
    assert len(cache) == 1

    # Heap exceeds 2 * max_size (6), so compaction triggers
    cache._cleanup_once()

    # After compaction, heap should equal cache size
    assert len(cache._expiry_heap) == 1


def test_heap_compaction_preserves_valid_entries():
    """Test that heap compaction preserves all valid cache entries."""
    cache = ResourceCache(max_size=5, ttl=60)

    # Add entries and create stale heap entries via updates
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)

    # Update same keys multiple times to bloat heap beyond 2 * max_size (10)
    for _ in range(4):
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)

    # Heap has 15 entries (3 initial + 12 updates), exceeds 2 * 5 = 10
    assert len(cache._expiry_heap) == 15
    assert len(cache) == 3

    # Trigger compaction
    cache._cleanup_once()

    # After compaction, heap should only have 3 valid entries
    assert len(cache._expiry_heap) == 3
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert cache.get("c") == 3


class DummyLogger:
    def info(self, msg):
        pass

    def debug(self, msg):
        pass

    def error(self, msg):
        pass
