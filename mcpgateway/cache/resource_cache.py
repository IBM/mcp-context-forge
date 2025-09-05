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
    >>> cache = ResourceCache(max_size=2, ttl=1)
    >>> cache.set('a', 1)
    >>> cache.get('a')
    1
    >>> import time
    >>> time.sleep(1.1)  # Wait for TTL expiration
    >>> cache.get('a') is None  # doctest: +SKIP
    True
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
from dataclasses import dataclass
import time
from typing import Any, Dict, Optional

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
    last_access: float


class ResourceCache:
    """
    Resource content cache with TTL expiration.

    Attributes:
        max_size: Maximum number of entries
        ttl: Time-to-live in seconds
        _cache: Cache storage
        _lock: Async lock for thread safety

    Examples:
        >>> from mcpgateway.cache.resource_cache import ResourceCache
        >>> cache = ResourceCache(max_size=2, ttl=1)
        >>> cache.set('a', 1)
        >>> cache.get('a')
        1
        >>> import time
        >>> time.sleep(1.5)  # Use 1.5s to ensure expiration
        >>> cache.get('a') is None  # doctest: +SKIP
        True
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
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

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
            >>> cache = ResourceCache(max_size=2, ttl=1)
            >>> cache.set('a', 1)
            >>> cache.get('a')
            1
            >>> # Test expiration by using a very short TTL
            >>> short_cache = ResourceCache(max_size=2, ttl=0.1)
            >>> short_cache.set('b', 2)
            >>> short_cache.get('b')
            2
            >>> import time
            >>> time.sleep(0.2)  # Sleep longer than TTL (0.1s) to ensure expiration
            >>> short_cache.get('b') is None
            True
        """
        if key not in self._cache:
            return None

        entry = self._cache[key]
        now = time.time()

        # Check expiration
        if now > entry.expires_at:
            del self._cache[key]
            return None

        # Update access time
        entry.last_access = now
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
        now = time.time()

        # Check size limit
        if len(self._cache) >= self.max_size:
            # Remove least recently used
            lru_key = min(self._cache.keys(), key=lambda k: self._cache[k].last_access)
            del self._cache[lru_key]

        # Add new entry
        self._cache[key] = CacheEntry(value=value, expires_at=now + self.ttl, last_access=now)

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
        self._cache.pop(key, None)

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
        self._cache.clear()

    async def _cleanup_loop(self) -> None:
        """Background task to clean expired entries."""
        while True:
            try:
                async with self._lock:
                    now = time.time()
                    expired = [key for key, entry in self._cache.items() if now > entry.expires_at]
                    for key in expired:
                        del self._cache[key]

                    if expired:
                        logger.debug(f"Cleaned {len(expired)} expired cache entries")

            except Exception as e:
                logger.error(f"Cache cleanup error: {e}")

            await asyncio.sleep(60)  # Run every minute
