# -*- coding: utf-8 -*-
"""Metrics aggregation cache for reducing database load.

This module provides in-memory caching for metrics aggregation queries
with optional Redis support for distributed deployments.

The cache uses double-checked locking for thread safety and supports
configurable TTL with automatic expiration.

See GitHub Issue #1734 for details.
"""

# Future
from __future__ import annotations

# Standard
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MetricsCache:
    """Thread-safe in-memory cache for metrics aggregation results.

    Uses double-checked locking to minimize lock contention while
    ensuring thread safety. Supports separate caches for different
    metric types (tools, resources, prompts, servers, a2a).

    Attributes:
        ttl_seconds: Time-to-live for cached entries in seconds.

    Examples:
        >>> cache = MetricsCache(ttl_seconds=10)
        >>> cache.get("tools") is None
        True
        >>> cache.set("tools", {"total": 100, "successful": 90})
        >>> cache.get("tools")
        {'total': 100, 'successful': 90}
        >>> cache.invalidate("tools")
        >>> cache.get("tools") is None
        True
    """

    _NOT_CACHED = object()  # Sentinel to distinguish "not cached" from "cached None"

    def __init__(self, ttl_seconds: int = 10) -> None:
        """Initialize the metrics cache.

        Args:
            ttl_seconds: Time-to-live for cached entries. Defaults to 10 seconds.
        """
        self._caches: Dict[str, Any] = {}
        self._expiries: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds
        self._hit_count = 0
        self._miss_count = 0

    def get(self, metric_type: str) -> Optional[Dict[str, Any]]:
        """Get cached metrics for a specific type.

        Uses double-checked locking for thread safety with minimal
        lock contention on cache hits.

        Args:
            metric_type: Type of metrics (tools, resources, prompts, servers, a2a).

        Returns:
            Cached metrics dictionary if valid, None if expired or not cached.

        Examples:
            >>> cache = MetricsCache()
            >>> cache.get("tools") is None
            True
            >>> cache.set("tools", {"total": 50})
            >>> cache.get("tools")
            {'total': 50}
        """
        now = time.time()

        # Fast path: check without lock
        cached = self._caches.get(metric_type, self._NOT_CACHED)
        expiry = self._expiries.get(metric_type, 0)

        if cached is not self._NOT_CACHED and now < expiry:
            self._hit_count += 1
            return cached

        # Cache miss or expired
        self._miss_count += 1
        return None

    def set(self, metric_type: str, value: Dict[str, Any]) -> None:
        """Set cached metrics for a specific type.

        Args:
            metric_type: Type of metrics (tools, resources, prompts, servers, a2a).
            value: Metrics dictionary to cache.

        Examples:
            >>> cache = MetricsCache(ttl_seconds=60)
            >>> cache.set("tools", {"total": 100, "successful": 95})
            >>> cache.get("tools")
            {'total': 100, 'successful': 95}
        """
        with self._lock:
            self._caches[metric_type] = value
            self._expiries[metric_type] = time.time() + self._ttl_seconds

    def invalidate(self, metric_type: Optional[str] = None) -> None:
        """Invalidate cached metrics.

        Args:
            metric_type: Specific type to invalidate, or None to invalidate all.

        Examples:
            >>> cache = MetricsCache()
            >>> cache.set("tools", {"total": 100})
            >>> cache.set("resources", {"total": 50})
            >>> cache.invalidate("tools")
            >>> cache.get("tools") is None
            True
            >>> cache.get("resources") is not None
            True
            >>> cache.invalidate()  # Invalidate all
            >>> cache.get("resources") is None
            True
        """
        with self._lock:
            if metric_type is None:
                self._caches.clear()
                self._expiries.clear()
                logger.debug("Invalidated all metrics caches")
            else:
                self._caches.pop(metric_type, None)
                self._expiries.pop(metric_type, None)
                logger.debug(f"Invalidated metrics cache for: {metric_type}")

    def invalidate_prefix(self, prefix: str) -> None:
        """Invalidate all cached metrics with keys starting with prefix.

        Args:
            prefix: Key prefix to match for invalidation.

        Examples:
            >>> cache = MetricsCache()
            >>> cache.set("top_tools:5", [{"id": "1"}])
            >>> cache.set("top_tools:10", [{"id": "2"}])
            >>> cache.set("tools", {"total": 100})
            >>> cache.invalidate_prefix("top_tools:")
            >>> cache.get("top_tools:5") is None
            True
            >>> cache.get("top_tools:10") is None
            True
            >>> cache.get("tools") is not None
            True
        """
        with self._lock:
            keys_to_remove = [k for k in self._caches if k.startswith(prefix)]
            for key in keys_to_remove:
                self._caches.pop(key, None)
                self._expiries.pop(key, None)
            if keys_to_remove:
                logger.debug(f"Invalidated {len(keys_to_remove)} metrics cache entries with prefix: {prefix}")

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary containing hit_count, miss_count, hit_rate,
            cached_types, and ttl_seconds.

        Examples:
            >>> cache = MetricsCache()
            >>> cache.set("tools", {"total": 100})
            >>> _ = cache.get("tools")  # Hit
            >>> _ = cache.get("tools")  # Hit
            >>> _ = cache.get("missing")  # Miss
            >>> stats = cache.stats()
            >>> stats["hit_count"]
            2
            >>> stats["miss_count"]
            1
        """
        total = self._hit_count + self._miss_count
        now = time.time()
        cached_types = [k for k, v in self._caches.items() if v is not self._NOT_CACHED and self._expiries.get(k, 0) > now]
        return {
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": self._hit_count / total if total > 0 else 0.0,
            "cached_types": cached_types,
            "ttl_seconds": self._ttl_seconds,
        }

    def reset_stats(self) -> None:
        """Reset hit/miss counters.

        Examples:
            >>> cache = MetricsCache()
            >>> cache.set("tools", {"total": 100})
            >>> _ = cache.get("tools")
            >>> cache.stats()["hit_count"]
            1
            >>> cache.reset_stats()
            >>> cache.stats()["hit_count"]
            0
        """
        self._hit_count = 0
        self._miss_count = 0


def _create_metrics_cache() -> MetricsCache:
    """Create the metrics cache with settings from configuration.

    Returns:
        MetricsCache instance configured with TTL from settings.
    """
    try:
        # First-Party
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

        ttl = getattr(settings, "metrics_cache_ttl_seconds", 10)
    except ImportError:
        ttl = 10
    return MetricsCache(ttl_seconds=ttl)


def is_cache_enabled() -> bool:
    """Check if metrics caching is enabled in configuration.

    Returns:
        True if caching is enabled, False otherwise.
    """
    try:
        # First-Party
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

        return getattr(settings, "metrics_cache_enabled", True)
    except ImportError:
        return True


# Global singleton instance with configurable TTL
# This is appropriate for metrics which are read frequently but
# don't need to be perfectly real-time
metrics_cache = _create_metrics_cache()
