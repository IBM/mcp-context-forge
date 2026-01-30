# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/metrics_cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Metrics Aggregation In-Memory Cache.

Thread-safe in-memory cache for aggregated metrics with TTL expiration.
Metrics aggregation queries are expensive (scanning all metric rows) and
called frequently via /metrics and /admin/metrics endpoints. Caching
the aggregated results with a short TTL prevents redundant computation.

Performance Impact:
    - Before: Full aggregation queries on every /metrics request
    - After: 1 aggregation query per TTL period (default 10 seconds)

Examples:
    >>> from mcpgateway.cache.metrics_cache import MetricsCache
    >>> cache = MetricsCache(ttl_seconds=10)
    >>> cache.get("tools") is None
    True
    >>> cache.set("tools", {"total_executions": 100})
    >>> cache.get("tools")
    {'total_executions': 100}
    >>> cache.invalidate()
    >>> cache.get("tools") is None
    True
"""

# Standard
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MetricsCache:
    """Thread-safe in-memory cache for aggregated metrics with TTL.

    Stores aggregated metrics results keyed by entity type (tools, resources, etc.)
    to avoid repeated expensive aggregation queries.

    Attributes:
        ttl_seconds: Time-to-live in seconds before cache refresh
        _cache: Dict mapping cache keys to cached values
        _expiries: Dict mapping cache keys to expiry timestamps
        _lock: Threading lock for thread-safe operations

    Examples:
        >>> cache = MetricsCache(ttl_seconds=10)
        >>> cache.get("tools") is None
        True
        >>> cache.set("tools", {"total": 5})
        >>> cache.get("tools")
        {'total': 5}
    """

    def __init__(self, ttl_seconds: int = 10):
        """Initialize the metrics cache.

        Args:
            ttl_seconds: Time-to-live in seconds (default: 10).

        Examples:
            >>> cache = MetricsCache(ttl_seconds=15)
            >>> cache.ttl_seconds
            15
        """
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Any] = {}
        self._expiries: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._hit_count = 0
        self._miss_count = 0

    def get(self, key: str) -> Optional[Any]:
        """Get a cached value if it exists and hasn't expired.

        Args:
            key: Cache key (e.g., "tools", "resources", "top_tools")

        Returns:
            Cached value or None if not cached or expired.

        Examples:
            >>> cache = MetricsCache(ttl_seconds=10)
            >>> cache.get("missing") is None
            True
        """
        now = time.time()

        # Fast path: check without lock
        if key in self._expiries and now < self._expiries[key]:
            self._hit_count += 1
            return self._cache.get(key)

        self._miss_count += 1
        return None

    def set(self, key: str, value: Any) -> None:
        """Store a value in the cache.

        Args:
            key: Cache key
            value: Value to cache

        Examples:
            >>> cache = MetricsCache(ttl_seconds=10)
            >>> cache.set("tools", {"total": 5})
            >>> cache.get("tools")
            {'total': 5}
        """
        with self._lock:
            self._cache[key] = value
            self._expiries[key] = time.time() + self.ttl_seconds

    def invalidate(self, key: Optional[str] = None) -> None:
        """Invalidate cached values.

        Args:
            key: Specific key to invalidate. If None, invalidates all entries.

        Examples:
            >>> cache = MetricsCache(ttl_seconds=10)
            >>> cache.set("tools", {"total": 5})
            >>> cache.invalidate("tools")
            >>> cache.get("tools") is None
            True

            >>> cache.set("tools", {"total": 5})
            >>> cache.set("resources", {"total": 3})
            >>> cache.invalidate()
            >>> cache.get("tools") is None
            True
        """
        with self._lock:
            if key is not None:
                self._cache.pop(key, None)
                self._expiries.pop(key, None)
            else:
                self._cache.clear()
                self._expiries.clear()
            logger.debug(f"Metrics cache invalidated: {key or 'all'}")

    def stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dictionary with hit_count, miss_count, hit_rate, ttl_seconds, and cached_keys.

        Examples:
            >>> cache = MetricsCache(ttl_seconds=10)
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
            "cached_keys": list(self._cache.keys()),
        }


# Global singleton instance
metrics_cache = MetricsCache()
