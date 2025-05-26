# -*- coding: utf-8 -*-
"""Resource Cache Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module implements a simple in-memory cache with TTL expiration for caching
resource content in the MCP Gateway. Features:
- TTL-based expiration
- Maximum size limit with LRU eviction
- Thread-safe operations
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with expiration."""

    value: Any
    expires_at: float
    last_access: float


class ResourceCache:
    """Resource content cache with TTL expiration.

    Attributes:
        max_size: Maximum number of entries
        ttl: Time-to-live in seconds
        _cache: Cache storage
        _lock: Async lock for thread safety
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
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
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
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
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
        """Delete value from cache.

        Args:
            key: Cache key to delete
        """
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached entries."""
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
