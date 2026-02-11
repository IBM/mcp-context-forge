# -*- coding: utf-8 -*-
"""Metrics aggregation cache for reducing database load.

This module provides in-memory caching for metrics aggregation queries
with optional Redis support for distributed deployments.

The cache uses double-checked locking for thread safety and supports
configurable TTL with automatic expiration.

Redis support enables shared caching across multiple gateway instances,
solving metric fluctuation issues in multi-instance deployments.

See GitHub Issue #1734 and #2643 for details.
"""

# Future
from __future__ import annotations

# Standard
import json
import logging
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

try:
    # Third-Party
    from redis.asyncio import Redis
    from redis.exceptions import RedisError

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    Redis = None  # type: ignore
    RedisError = Exception  # type: ignore

try:
    # Third-Party
    from prometheus_client import Counter

    PROMETHEUS_AVAILABLE = True

    # Prometheus metrics for cache performance
    metrics_cache_hits_total = Counter("metrics_cache_hits_total", "Total number of metrics cache hits", ["backend"])

    metrics_cache_misses_total = Counter("metrics_cache_misses_total", "Total number of metrics cache misses", ["backend"])
except ImportError:
    PROMETHEUS_AVAILABLE = False
    metrics_cache_hits_total = None  # type: ignore  # pylint: disable=invalid-name
    metrics_cache_misses_total = None  # type: ignore  # pylint: disable=invalid-name


class MetricsCache:
    """Thread-safe cache for metrics aggregation results with Redis support.

    Supports both in-memory caching (single-instance) and Redis-based
    distributed caching (multi-instance deployments). Automatically falls
    back to local cache if Redis is unavailable.

    Uses double-checked locking to minimize lock contention while
    ensuring thread safety. Supports separate caches for different
    metric types (tools, resources, prompts, servers, a2a).

    Attributes:
        ttl_seconds: Time-to-live for cached entries in seconds.
        redis_client: Optional Redis client for distributed caching.
        use_redis: Whether Redis backend is enabled and available.

    Examples:
        >>> # Local cache (single instance)
        >>> cache = MetricsCache(ttl_seconds=10)
        >>> cache.get("tools") is None
        True
        >>> cache.set("tools", {"total": 100, "successful": 90})
        >>> cache.get("tools")
        {'total': 100, 'successful': 90}

        >>> # Redis cache (multi-instance)
        >>> from redis.asyncio import Redis
        >>> redis_client = Redis.from_url("redis://localhost:6379")
        >>> cache = MetricsCache(redis_client=redis_client, ttl_seconds=60)
        >>> cache.use_redis
        True
    """

    _NOT_CACHED = object()  # Sentinel to distinguish "not cached" from "cached None"

    def __init__(self, redis_client: Optional[Redis] = None, ttl_seconds: int = 10) -> None:
        """Initialize the metrics cache.

        Args:
            redis_client: Optional Redis client for distributed caching.
                         If None, uses in-memory cache only.
            ttl_seconds: Time-to-live for cached entries. Defaults to 10 seconds.
        """
        self._caches: Dict[str, Any] = {}
        self._expiries: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds
        self._total_hit_count = 0
        self._total_miss_count = 0
        self._redis_hit_count = 0
        self._redis_miss_count = 0
        self._local_hit_count = 0
        self._local_miss_count = 0
        self._sync_method_warned = False

        # Redis support
        self.redis_client = redis_client
        self.use_redis = redis_client is not None and REDIS_AVAILABLE

        if self.use_redis:
            logger.info("MetricsCache initialized with Redis backend for distributed caching")
        else:
            if redis_client is not None and not REDIS_AVAILABLE:
                logger.warning("Redis client provided but redis library not available, falling back to local cache")
            logger.info("MetricsCache initialized with local in-memory backend")

    async def get_async(self, metric_type: str) -> Optional[Dict[str, Any]]:
        """Get cached metrics for a specific type (async version for Redis).

        Tries Redis first if enabled, falls back to local cache.

        Args:
            metric_type: Type of metrics (tools, resources, prompts, servers, a2a).

        Returns:
            Cached metrics dictionary if valid, None if expired or not cached.

        Examples:
            >>> import asyncio
            >>> cache = MetricsCache()
            >>> asyncio.run(cache.get_async("tools")) is None
            True
        """
        # Try Redis first if enabled
        if self.use_redis:
            try:
                cache_key = f"metrics:{metric_type}"
                value = await self.redis_client.get(cache_key)
                if value:
                    self._total_hit_count += 1
                    self._redis_hit_count += 1
                    if PROMETHEUS_AVAILABLE:
                        metrics_cache_hits_total.labels(backend="redis").inc()
                    logger.debug("Metrics cache hit (Redis)", extra={"cache_key": metric_type, "cache_backend": "redis"})
                    return json.loads(value)
                self._total_miss_count += 1
                self._redis_miss_count += 1
                if PROMETHEUS_AVAILABLE:
                    metrics_cache_misses_total.labels(backend="redis").inc()
                logger.debug("Metrics cache miss (Redis)", extra={"cache_key": metric_type, "cache_backend": "redis"})
                return None
            except (RedisError, json.JSONDecodeError) as e:
                logger.warning(f"Redis get failed for key '{metric_type}', falling back to local cache: {e}", extra={"cache_key": metric_type, "error": str(e)})
                # Fall through to local cache

        # Local cache fallback
        now = time.time()
        cached = self._caches.get(metric_type, self._NOT_CACHED)
        expiry = self._expiries.get(metric_type, 0)

        if cached is not self._NOT_CACHED and now < expiry:
            self._total_hit_count += 1
            self._local_hit_count += 1
            if PROMETHEUS_AVAILABLE:
                metrics_cache_hits_total.labels(backend="local").inc()
            logger.debug("Metrics cache hit (local)", extra={"cache_key": metric_type, "cache_backend": "local"})
            return cached

        self._total_miss_count += 1
        self._local_miss_count += 1
        if PROMETHEUS_AVAILABLE:
            metrics_cache_misses_total.labels(backend="local").inc()
        logger.debug("Metrics cache miss (local)", extra={"cache_key": metric_type, "cache_backend": "local"})
        return None

    def get(self, metric_type: str) -> Optional[Dict[str, Any]]:
        """Get cached metrics for a specific type (sync version).

        For backward compatibility. Only uses local cache.
        Use get_async() for Redis support.

        Args:
            metric_type: Type of metrics (tools, resources, prompts, servers, a2a).

        Returns:
            Cached metrics dictionary if valid, None if expired or not cached.

        Warning:
            When Redis backend is active, this method only accesses local cache.
            Use get_async() for Redis-backed caching.

        Examples:
            >>> cache = MetricsCache()
            >>> cache.get("tools") is None
            True
            >>> cache.set("tools", {"total": 50})
            >>> cache.get("tools")
            {'total': 50}
        """
        if self.use_redis and not self._sync_method_warned:
            logger.warning(
                "Sync methods (get/set/invalidate) called with Redis backend active. " +
                "Only local cache will be used. Use async methods for Redis support. " +
                "This warning will only be shown once."
            )
            self._sync_method_warned = True

        now = time.time()
        cached = self._caches.get(metric_type, self._NOT_CACHED)
        expiry = self._expiries.get(metric_type, 0)

        if cached is not self._NOT_CACHED and now < expiry:
            self._total_hit_count += 1
            self._local_hit_count += 1
            if PROMETHEUS_AVAILABLE:
                metrics_cache_hits_total.labels(backend="local").inc()
            return cached

        self._total_miss_count += 1
        self._local_miss_count += 1
        if PROMETHEUS_AVAILABLE:
            metrics_cache_misses_total.labels(backend="local").inc()
        return None

    async def set_async(self, metric_type: str, value: Dict[str, Any]) -> None:
        """Set cached metrics for a specific type (async version for Redis).

        Writes to both Redis (if enabled) and local cache.

        Args:
            metric_type: Type of metrics (tools, resources, prompts, servers, a2a).
            value: Metrics dictionary to cache.

        Examples:
            >>> import asyncio
            >>> cache = MetricsCache(ttl_seconds=60)
            >>> asyncio.run(cache.set_async("tools", {"total": 100}))
        """
        # Try Redis first if enabled
        if self.use_redis:
            try:
                cache_key = f"metrics:{metric_type}"
                await self.redis_client.setex(cache_key, self._ttl_seconds, json.dumps(value))
                logger.debug("Metrics cache set (Redis)", extra={"cache_key": metric_type, "cache_backend": "redis", "ttl_seconds": self._ttl_seconds})
                # Also set in local cache for faster subsequent access
                with self._lock:
                    self._caches[metric_type] = value
                    self._expiries[metric_type] = time.time() + self._ttl_seconds
                return
            except (RedisError, TypeError, ValueError) as e:
                logger.warning(f"Redis set failed for key '{metric_type}', falling back to local cache: {e}", extra={"cache_key": metric_type, "error": str(e)})
                # Fall through to local cache

        # Local cache (fallback or primary)
        with self._lock:
            self._caches[metric_type] = value
            self._expiries[metric_type] = time.time() + self._ttl_seconds
            logger.debug("Metrics cache set (local)", extra={"cache_key": metric_type, "cache_backend": "local", "ttl_seconds": self._ttl_seconds})

    def set(self, metric_type: str, value: Dict[str, Any]) -> None:
        """Set cached metrics for a specific type (sync version).

        For backward compatibility. Only uses local cache.
        Use set_async() for Redis support.

        Args:
            metric_type: Type of metrics (tools, resources, prompts, servers, a2a).
            value: Metrics dictionary to cache.

        Warning:
            When Redis backend is active, this method only updates local cache.
            Use set_async() for Redis-backed caching.

        Examples:
            >>> cache = MetricsCache(ttl_seconds=60)
            >>> cache.set("tools", {"total": 100, "successful": 95})
            >>> cache.get("tools")
            {'total': 100, 'successful': 95}
        """
        if self.use_redis and not self._sync_method_warned:
            logger.warning(
                "Sync methods (get/set/invalidate) called with Redis backend active. " +
                "Only local cache will be used. Use async methods for Redis support. " +
                "This warning will only be shown once."
            )
            self._sync_method_warned = True

        with self._lock:
            self._caches[metric_type] = value
            self._expiries[metric_type] = time.time() + self._ttl_seconds

    async def invalidate_async(self, metric_type: Optional[str] = None) -> None:
        """Invalidate cached metrics (async version for Redis).

        Args:
            metric_type: Specific type to invalidate, or None to invalidate all.

        Examples:
            >>> import asyncio
            >>> cache = MetricsCache()
            >>> cache.set("tools", {"total": 100})
            >>> asyncio.run(cache.invalidate_async("tools"))
        """
        # Invalidate in Redis if enabled
        if self.use_redis:
            try:
                if metric_type is None:
                    # Delete all metrics:* keys using SCAN with batch delete
                    keys = [key async for key in self.redis_client.scan_iter("metrics:*")]
                    if keys:
                        await self.redis_client.delete(*keys)
                        logger.debug(f"Invalidated {len(keys)} metrics cache entries in Redis")
                else:
                    cache_key = f"metrics:{metric_type}"
                    await self.redis_client.delete(cache_key)
                    logger.debug(f"Invalidated metrics cache for '{metric_type}' in Redis")
            except RedisError as e:
                logger.warning(f"Redis invalidation failed: {e}", extra={"metric_type": metric_type, "error": str(e)})

        # Also invalidate local cache
        with self._lock:
            if metric_type is None:
                self._caches.clear()
                self._expiries.clear()
                logger.debug("Invalidated all metrics caches (local)")
            else:
                self._caches.pop(metric_type, None)
                self._expiries.pop(metric_type, None)
                logger.debug(f"Invalidated metrics cache for '{metric_type}' (local)")

    def invalidate(self, metric_type: Optional[str] = None) -> None:
        """Invalidate cached metrics (sync version).

        For backward compatibility. Only invalidates local cache.
        Use invalidate_async() for Redis support.

        Args:
            metric_type: Specific type to invalidate, or None to invalidate all.

        Warning:
            When Redis backend is active, this method only invalidates local cache.
            Use invalidate_async() for Redis-backed invalidation.

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
        if self.use_redis and not self._sync_method_warned:
            logger.warning(
                "Sync methods (get/set/invalidate) called with Redis backend active. "
                + "Only local cache will be used. Use async methods for Redis support. "
                + "This warning will only be shown once."
            )
            self._sync_method_warned = True

        with self._lock:
            if metric_type is None:
                self._caches.clear()
                self._expiries.clear()
                logger.debug("Invalidated all metrics caches (local)")
            else:
                self._caches.pop(metric_type, None)
                self._expiries.pop(metric_type, None)
                logger.debug(f"Invalidated metrics cache for '{metric_type}' (local)")

    async def invalidate_prefix_async(self, prefix: str) -> None:
        """Invalidate all cached metrics with keys starting with prefix (async version for Redis).

        Args:
            prefix: Key prefix to match for invalidation.
        """
        # Invalidate in Redis if enabled
        if self.use_redis:
            try:
                pattern = f"metrics:{prefix}*"
                keys = [key async for key in self.redis_client.scan_iter(pattern)]
                if keys:
                    await self.redis_client.delete(*keys)
                    logger.debug("Invalidated %d metrics cache entries with prefix '%s' in Redis", len(keys), prefix)
            except RedisError as e:
                logger.warning("Redis prefix invalidation failed for '%s': %s", prefix, e, extra={"prefix": prefix, "error": str(e)})

        # Also invalidate local cache
        with self._lock:
            keys_to_remove = [k for k in self._caches if k.startswith(prefix)]
            for key in keys_to_remove:
                self._caches.pop(key, None)
                self._expiries.pop(key, None)
            if keys_to_remove:
                logger.debug("Invalidated %d metrics cache entries with prefix '%s' (local)", len(keys_to_remove), prefix)

    def invalidate_prefix(self, prefix: str) -> None:
        """Invalidate all cached metrics with keys starting with prefix.

        Args:
            prefix: Key prefix to match for invalidation.

        Warning:
            When Redis backend is active, this method only invalidates local cache.
            Consider using invalidate_async() for Redis-backed invalidation.

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
        if self.use_redis and not self._sync_method_warned:
            logger.warning(
                "Sync methods (get/set/invalidate) called with Redis backend active. " +
                "Only local cache will be used. Use async methods for Redis support. " +
                "This warning will only be shown once."
            )
            self._sync_method_warned = True

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
            cached_types, backend info, and ttl_seconds.

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
        total = self._total_hit_count + self._total_miss_count
        now = time.time()
        cached_types = [k for k, v in self._caches.items() if v is not self._NOT_CACHED and self._expiries.get(k, 0) > now]

        stats = {
            "hit_count": self._total_hit_count,
            "miss_count": self._total_miss_count,
            "hit_rate": self._total_hit_count / total if total > 0 else 0.0,
            "cached_types": cached_types,
            "ttl_seconds": self._ttl_seconds,
            "backend": "redis" if self.use_redis else "local",
        }

        # Add Redis-specific stats if enabled
        if self.use_redis:
            redis_total = self._redis_hit_count + self._redis_miss_count
            stats.update(
                {
                    "redis_hit_count": self._redis_hit_count,
                    "redis_miss_count": self._redis_miss_count,
                    "redis_hit_rate": self._redis_hit_count / redis_total if redis_total > 0 else 0.0,
                }
            )

        # Add local cache stats
        local_total = self._local_hit_count + self._local_miss_count
        stats.update(
            {
                "local_hit_count": self._local_hit_count,
                "local_miss_count": self._local_miss_count,
                "local_hit_rate": self._local_hit_count / local_total if local_total > 0 else 0.0,
            }
        )

        return stats

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
        self._total_hit_count = 0
        self._total_miss_count = 0
        self._redis_hit_count = 0
        self._redis_miss_count = 0
        self._local_hit_count = 0
        self._local_miss_count = 0


def _create_metrics_cache() -> MetricsCache:
    """Create the metrics cache with settings from configuration.

    Automatically configures Redis backend if enabled in settings.

    Returns:
        MetricsCache instance configured with TTL and optional Redis backend.
    """
    try:
        # First-Party
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

        ttl = getattr(settings, "metrics_cache_ttl_seconds", 10)
        use_redis = getattr(settings, "metrics_cache_use_redis", False)
        redis_url = getattr(settings, "redis_url", None)

        # Initialize Redis client if enabled and URL provided
        redis_client = None
        if use_redis and redis_url and REDIS_AVAILABLE:
            try:
                redis_client = Redis.from_url(redis_url, decode_responses=True)
                # Sanitize URL to avoid logging credentials
                parsed = urlparse(redis_url)
                safe_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 6379}"
                logger.info(f"Metrics cache configured with Redis backend: {safe_url}")
            except (RedisError, ConnectionError, OSError, ValueError) as e:
                logger.warning(f"Failed to initialize Redis client for metrics cache: {e}")

        return MetricsCache(redis_client=redis_client, ttl_seconds=ttl)
    except ImportError:
        return MetricsCache(ttl_seconds=10)


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
