# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/resource_cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Resource Cache Implementation.
This module implements a simple in-memory cache with TTL expiration for caching
resource content in the MCP Gateway. Features:
- TTL-based expiration
- Maximum size limit with LRU eviction
- Thread-safe operations

Examples:
    >>> from mcpgateway.cache.resource_cache import ResourceCache
    >>> from unittest.mock import patch
    >>> cache = ResourceCache(max_size=2, ttl=1)
    >>> cache.set('a', 1)
    >>> cache.get('a')
    1

    Test TTL expiration using mocked time (no actual sleep):

    >>> with patch("time.time") as mock_time:
    ...     mock_time.return_value = 1000
    ...     cache2 = ResourceCache(max_size=2, ttl=1)
    ...     cache2.set('x', 100)
    ...     cache2.get('x')  # Before expiration
    ...     mock_time.return_value = 1002  # Advance past TTL
    ...     cache2.get('x') is None  # After expiration
    100
    True

    Test LRU eviction:

    >>> cache.set('a', 1)
    >>> cache.set('b', 2)
    >>> cache.set('c', 3)  # LRU eviction
    >>> sorted(cache._cache.keys())
    ['b', 'c']
    >>> cache.delete('b')
    >>> cache.get('b') is None
    True
    >>> cache.clear()
    >>> cache.get('a') is None
    True
"""

# Standard
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import heapq
import threading
import time
from typing import Any, Optional

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with expiration."""

    value: Any
    expires_at: float


class ResourceCache:
    """
    Resource content cache with TTL expiration.

    Attributes:
        max_size: Maximum number of entries
        ttl: Time-to-live in seconds
        _cache: Cache storage
        _lock: Threading lock for thread safety

    Examples:
        >>> from mcpgateway.cache.resource_cache import ResourceCache
        >>> from unittest.mock import patch
        >>> cache = ResourceCache(max_size=2, ttl=1)
        >>> cache.set('a', 1)
        >>> cache.get('a')
        1

        Test TTL expiration using mocked time (no actual sleep):

        >>> with patch("time.time") as mock_time:
        ...     mock_time.return_value = 1000
        ...     cache2 = ResourceCache(max_size=2, ttl=1)
        ...     cache2.set('x', 100)
        ...     cache2.get('x')  # Before expiration
        ...     mock_time.return_value = 1002  # Advance past TTL
        ...     cache2.get('x') is None  # After expiration
        100
        True

        Test LRU eviction:

        >>> cache.set('a', 1)
        >>> cache.set('b', 2)
        >>> cache.set('c', 3)  # LRU eviction
        >>> sorted(cache._cache.keys())
        ['b', 'c']
        >>> cache.delete('b')
        >>> cache.get('b') is None
        True
        >>> cache.clear()
        >>> cache.get('a') is None
        True
    """

    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        """Initialize cache.

        Args:
            max_size: Maximum number of entries
            ttl: Time-to-live in seconds
        """
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        # Use a threading lock for thread-safe operations across sync methods
        # and the background cleanup thread.
        self._lock = threading.Lock()
        # Min-heap of (expires_at, key) for efficient expiration cleanup
        self._expiry_heap: list[tuple[float, str]] = []

    async def initialize(self) -> None:
        """Initialize cache service."""
        logger.info("Initializing resource cache")
        # Start cleanup task
        asyncio.create_task(self._cleanup_loop())

    async def shutdown(self) -> None:
        """Shutdown cache service."""
        logger.info("Shutting down resource cache")
        self.clear()

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired

        Examples:
            >>> from mcpgateway.cache.resource_cache import ResourceCache
            >>> from unittest.mock import patch

            >>> # Normal get
            >>> cache = ResourceCache(max_size=2, ttl=1)
            >>> cache.set('a', 1)
            >>> cache.get('a')
            1

            >>> # Test expiration deterministically using mock time
            >>> with patch("time.time") as mock_time:
            ...     mock_time.return_value = 1000
            ...     short_cache = ResourceCache(max_size=2, ttl=0.1)
            ...     short_cache.set('b', 2)
            ...     short_cache.get('b')
            ...     # Advance time past TTL
            ...     mock_time.return_value = 1000.2
            ...     short_cache.get('b') is None
            2
            True
        """
        with self._lock:
            if key not in self._cache:
                return None

            entry = self._cache[key]
            now = time.time()

            # Check expiration
            if now > entry.expires_at:
                del self._cache[key]
                return None

            self._cache.move_to_end(key)

            return entry.value

    def set(self, key: str, value: Any) -> None:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache

        Examples:
            >>> from mcpgateway.cache.resource_cache import ResourceCache
            >>> cache = ResourceCache(max_size=2, ttl=1)
            >>> cache.set('a', 1)
            >>> cache.get('a')
            1
        """
        expires_at = time.time() + self.ttl
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            elif len(self._cache) >= self.max_size:
                # Evict LRU
                self._cache.popitem(last=False)

            # Add / update entry
            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)
            # Push expiry into heap; stale heap entries are ignored later
            heapq.heappush(self._expiry_heap, (expires_at, key))

    def delete(self, key: str) -> None:
        """
        Delete value from cache.

        Args:
            key: Cache key to delete

        Examples:
            >>> from mcpgateway.cache.resource_cache import ResourceCache
            >>> cache = ResourceCache()
            >>> cache.set('a', 1)
            >>> cache.delete('a')
            >>> cache.get('a') is None
            True
        """
        with self._lock:
            self._cache.pop(key, None)
            # We don't remove entries from the heap here; they'll be ignored
            # by the cleanup when popped if missing or timestamp differs.

    def clear(self) -> None:
        """
        Clear all cached entries.

        Examples:
            >>> from mcpgateway.cache.resource_cache import ResourceCache
            >>> cache = ResourceCache()
            >>> cache.set('a', 1)
            >>> cache.clear()
            >>> cache.get('a') is None
            True
        """
        with self._lock:
            self._cache.clear()
            self._expiry_heap.clear()

    async def _cleanup_loop(self) -> None:
        """Background task to clean expired entries efficiently.

        Uses a min-heap of expiration timestamps to avoid scanning the
        entire cache on each run. The actual cleanup work runs under the
        same threading lock as sync methods by delegating to a thread via
        `asyncio.to_thread` so we don't block the event loop.
        """

        async def _run_once() -> None:
            """Execute a single cleanup pass, catching and logging any errors."""
            try:
                await asyncio.to_thread(self._cleanup_once)
            except Exception as e:
                logger.error(f"Cache cleanup error: {e}")

        while True:
            await _run_once()
            await asyncio.sleep(60)  # Run every minute

    def _cleanup_once(self) -> None:
        """Synchronous cleanup routine executed in a thread.

        Pops entries from the expiry heap until the next non-expired
        timestamp is reached. Each popped entry is validated against
        the current cache entry to avoid removing updated entries.
        Also compacts the heap if it grows too large relative to cache size.
        """
        now = time.time()
        removed = 0
        needs_compaction = False

        with self._lock:
            while self._expiry_heap and self._expiry_heap[0][0] <= now:
                expires_at, key = heapq.heappop(self._expiry_heap)
                entry = self._cache.get(key)
                # If entry is present and timestamps match, remove it
                if entry is not None and entry.expires_at == expires_at:
                    del self._cache[key]
                    removed += 1

            # Check if heap needs compaction (done outside lock)
            needs_compaction = len(self._expiry_heap) > 2 * self.max_size

        if removed:
            logger.debug(f"Cleaned {removed} expired cache entries")

        # Compact heap outside the main lock to minimize contention
        if needs_compaction:
            self._compact_heap()

    def _compact_heap(self) -> None:
        """Rebuild the expiry heap with only valid (current) entries.

        Called when heap grows too large due to stale entries from
        key updates or deletions. Minimizes lock contention by doing
        the O(n) heapify outside the lock.
        """
        # Snapshot current entries under lock (fast dict iteration)
        with self._lock:
            entries = [(entry.expires_at, key) for key, entry in self._cache.items()]
            old_size = len(self._expiry_heap)
            # Track max expiry in snapshot to identify entries added during compaction
            max_snapshot_expiry = max((e[0] for e in entries), default=0.0)

        # Build heap outside lock - O(n) work doesn't block get/set
        heapq.heapify(entries)

        # Swap back under lock, preserving entries added during compaction
        with self._lock:
            # Keep heap entries with expiry > max_snapshot_expiry (added via set() during compaction)
            new_entries = [(exp, k) for exp, k in self._expiry_heap if exp > max_snapshot_expiry]
            self._expiry_heap = entries
            for entry in new_entries:
                heapq.heappush(self._expiry_heap, entry)

        logger.debug(f"Compacted expiry heap: {old_size} -> {len(self._expiry_heap)} entries")

    def __len__(self) -> int:
        """
        Get the number of entries in cache.

        Args:
            None

        Returns:
            int: Number of entries in cache

        Examples:
            >>> from mcpgateway.cache.resource_cache import ResourceCache
            >>> cache = ResourceCache(max_size=2, ttl=1)
            >>> cache.set('a', 1)
            >>> len(cache)
            1
        """
        with self._lock:
            return len(self._cache)
