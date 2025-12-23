# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/a2a_stats_cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

A2A Agent Statistics In-Memory Cache.

This module implements a thread-safe in-memory cache for A2A agent counts with TTL expiration.
Since aggregate agent counts (total, active) are queried frequently but change rarely,
caching these values eliminates thousands of redundant database queries under load.

Performance Impact:
    - Before: 2 COUNT queries per /metrics call (10,000+ queries under load)
    - After: 1 combined query per TTL period (default 30 seconds)

Security Considerations:
    - Stale count window: Changes take up to TTL to propagate
    - Mitigation: Invalidation is called after agent mutations
    - Cache poisoning: Not applicable (populated from DB only)
    - Information leakage: Not applicable (stores counts only)

Examples:
    >>> from unittest.mock import Mock, patch
    >>> from mcpgateway.cache.a2a_stats_cache import A2AStatsCache

    >>> # Test cache miss and hit
    >>> cache = A2AStatsCache(ttl_seconds=30)
    >>> mock_db = Mock()
    >>> mock_result = Mock()
    >>> mock_result.total = 5
    >>> mock_result.active = 3
    >>> mock_db.execute.return_value.one.return_value = mock_result

    >>> # First call - cache miss, queries DB
    >>> result = cache.get_counts(mock_db)
    >>> result == {"total": 5, "active": 3}
    True
    >>> mock_db.execute.return_value.one.call_count
    1

    >>> # Second call - cache hit, no DB query
    >>> result = cache.get_counts(mock_db)
    >>> mock_db.execute.return_value.one.call_count
    1

    >>> # After invalidation - queries DB again
    >>> cache.invalidate()
    >>> result = cache.get_counts(mock_db)
    >>> mock_db.execute.return_value.one.call_count
    2
"""

# Standard
import logging
import threading
import time
from typing import Dict

# Use standard logging to avoid circular imports with services
logger = logging.getLogger(__name__)


class A2AStatsCache:
    """
    Thread-safe in-memory cache for A2A agent statistics with TTL.

    This cache stores aggregate counts (total agents, active agents) to avoid
    repeated COUNT queries on the a2a_agents table. These counts are queried
    frequently via the /metrics endpoint but change only when agents are
    created, toggled, or deleted.

    Attributes:
        ttl_seconds: Time-to-live in seconds before cache refresh
        _cache: Cached statistics dict (or sentinel _NOT_CACHED)
        _expiry: Timestamp when cache expires
        _lock: Threading lock for thread-safe operations

    Examples:
        >>> from unittest.mock import Mock
        >>> cache = A2AStatsCache(ttl_seconds=30)
        >>> mock_db = Mock()
        >>> mock_result = Mock()
        >>> mock_result.total = 0
        >>> mock_result.active = 0
        >>> mock_db.execute.return_value.one.return_value = mock_result

        >>> # Returns counts when no agents exist
        >>> result = cache.get_counts(mock_db)
        >>> result == {"total": 0, "active": 0}
        True
    """

    # Sentinel value to distinguish "not cached" from "cached with 0 agents"
    _NOT_CACHED = object()

    def __init__(self, ttl_seconds: int = 30):
        """
        Initialize the A2A stats cache.

        Args:
            ttl_seconds: Time-to-live in seconds (default: 30).
                        After this duration, the cache will refresh from DB.

        Examples:
            >>> cache = A2AStatsCache(ttl_seconds=15)
            >>> cache.ttl_seconds
            15
        """
        self.ttl_seconds = ttl_seconds
        self._cache = self._NOT_CACHED  # Use sentinel to distinguish from cached empty
        self._expiry: float = 0
        self._lock = threading.Lock()
        self._hit_count = 0
        self._miss_count = 0

    def get_counts(self, db) -> Dict[str, int]:
        """
        Get A2A agent counts from cache or database.

        Uses a double-checked locking pattern for thread safety with minimal
        lock contention on the hot path (cache hit).

        This method combines what was previously 2 separate COUNT queries into
        a single query with conditional aggregation.

        Args:
            db: SQLAlchemy database session

        Returns:
            Dict with 'total' and 'active' agent counts

        Examples:
            >>> from unittest.mock import Mock
            >>> cache = A2AStatsCache(ttl_seconds=30)
            >>> mock_db = Mock()
            >>> mock_result = Mock()
            >>> mock_result.total = 10
            >>> mock_result.active = 7
            >>> mock_db.execute.return_value.one.return_value = mock_result
            >>> cache.get_counts(mock_db)
            {'total': 10, 'active': 7}
        """
        now = time.time()

        # Fast path: cache hit (no lock needed for read)
        # Use sentinel check to properly cache zero counts
        if now < self._expiry and self._cache is not self._NOT_CACHED:
            self._hit_count += 1
            return self._cache

        # Slow path: cache miss or expired - acquire lock
        with self._lock:
            # Double-check after acquiring lock (another thread may have refreshed)
            if now < self._expiry and self._cache is not self._NOT_CACHED:
                self._hit_count += 1
                return self._cache

            # Import here to avoid circular imports
            # Third-Party
            from sqlalchemy import case, func, select  # pylint: disable=import-outside-toplevel

            # First-Party
            from mcpgateway.db import A2AAgent  # pylint: disable=import-outside-toplevel

            # Single query with conditional aggregation (replaces 2 separate queries)
            result = db.execute(
                select(
                    func.count(A2AAgent.id).label("total"),  # pylint: disable=not-callable
                    func.sum(case((A2AAgent.enabled.is_(True), 1), else_=0)).label("active"),
                )
            ).one()

            self._cache = {
                "total": result.total or 0,
                "active": int(result.active or 0),
            }
            self._expiry = now + self.ttl_seconds
            self._miss_count += 1

            logger.debug(f"A2A stats cache refreshed: {self._cache} (TTL: {self.ttl_seconds}s)")

            return self._cache

    def invalidate(self) -> None:
        """
        Invalidate the cache, forcing a refresh on next access.

        Call this method after creating, toggling, or deleting A2A agents
        to ensure changes propagate immediately.

        Examples:
            >>> cache = A2AStatsCache(ttl_seconds=30)
            >>> cache._expiry = time.time() + 1000  # Set future expiry
            >>> cache.invalidate()
            >>> cache._expiry
            0
        """
        with self._lock:
            self._cache = self._NOT_CACHED
            self._expiry = 0
            logger.info("A2A stats cache invalidated")

    def stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dictionary with hit_count, miss_count, hit_rate, ttl_seconds, and is_cached

        Examples:
            >>> cache = A2AStatsCache(ttl_seconds=30)
            >>> cache._hit_count = 90
            >>> cache._miss_count = 10
            >>> stats = cache.stats()
            >>> stats["hit_rate"]
            0.9
        """
        total = self._hit_count + self._miss_count
        return {
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": self._hit_count / total if total > 0 else 0.0,
            "ttl_seconds": self.ttl_seconds,
            "is_cached": self._cache is not self._NOT_CACHED and time.time() < self._expiry,
        }


# Global singleton instance
# This is the primary interface for accessing cached A2A stats
a2a_stats_cache = A2AStatsCache()
