# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/admin_stats_cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Admin Statistics Cache.

This module implements a thread-safe cache for admin dashboard statistics
with Redis as the primary store and in-memory fallback. It caches system
stats, observability stats, and other frequently-accessed admin data.

Performance Impact:
    - Before: 10+ COUNT queries per dashboard load
    - After: 0 queries (cache hit) per TTL period
    - Expected 1000+ queries/hour eliminated

Examples:
    >>> from mcpgateway.cache.admin_stats_cache import admin_stats_cache
    >>> # Cache is used automatically by admin endpoints
    >>> import asyncio
    >>> # asyncio.run(admin_stats_cache.invalidate_system_stats())
"""

# Standard
from dataclasses import dataclass
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with value and expiry timestamp.

    Examples:
        >>> import time
        >>> entry = CacheEntry(value={"total": 100}, expiry=time.time() + 60)
        >>> entry.is_expired()
        False
    """

    value: Any
    expiry: float

    def is_expired(self) -> bool:
        """Check if this cache entry has expired.

        Returns:
            bool: True if the entry has expired, False otherwise.
        """
        return time.time() >= self.expiry


class AdminStatsCache:
    """Thread-safe admin statistics cache with Redis and in-memory tiers.

    This cache reduces database load for admin dashboard by caching:
    - System stats (entity counts)
    - Observability stats (trace/span counts)
    - User/team listings
    - Other admin-related aggregations

    The cache uses Redis as the primary store for distributed deployments
    and falls back to in-memory caching when Redis is unavailable.

    Examples:
        >>> cache = AdminStatsCache()
        >>> cache.stats()["hit_count"]
        0
    """

    def __init__(
        self,
        system_ttl: Optional[int] = None,
        observability_ttl: Optional[int] = None,
        users_ttl: Optional[int] = None,
        teams_ttl: Optional[int] = None,
        tags_ttl: Optional[int] = None,
        plugins_ttl: Optional[int] = None,
        performance_ttl: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        """Initialize the admin stats cache.

        Args:
            system_ttl: TTL for system stats cache in seconds (default: 60)
            observability_ttl: TTL for observability stats in seconds (default: 30)
            users_ttl: TTL for user listings in seconds (default: 30)
            teams_ttl: TTL for team listings in seconds (default: 60)
            tags_ttl: TTL for tags listing in seconds (default: 120)
            plugins_ttl: TTL for plugin stats in seconds (default: 120)
            performance_ttl: TTL for performance aggregates in seconds (default: 60)
            enabled: Whether caching is enabled (default: True)

        Examples:
            >>> cache = AdminStatsCache(system_ttl=120)
            >>> cache._system_ttl
            120
        """
        # Import settings lazily to avoid circular imports
        try:
            # First-Party
            from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

            self._system_ttl = system_ttl or getattr(settings, "admin_stats_cache_system_ttl", 60)
            self._observability_ttl = observability_ttl or getattr(settings, "admin_stats_cache_observability_ttl", 30)
            self._users_ttl = users_ttl or getattr(settings, "admin_stats_cache_users_ttl", 30)
            self._teams_ttl = teams_ttl or getattr(settings, "admin_stats_cache_teams_ttl", 60)
            self._tags_ttl = tags_ttl or getattr(settings, "admin_stats_cache_tags_ttl", 120)
            self._plugins_ttl = plugins_ttl or getattr(settings, "admin_stats_cache_plugins_ttl", 120)
            self._performance_ttl = performance_ttl or getattr(settings, "admin_stats_cache_performance_ttl", 60)
            self._enabled = enabled if enabled is not None else getattr(settings, "admin_stats_cache_enabled", True)
            self._cache_prefix = getattr(settings, "cache_prefix", "mcpgw:")
        except ImportError:
            self._system_ttl = system_ttl or 60
            self._observability_ttl = observability_ttl or 30
            self._users_ttl = users_ttl or 30
            self._teams_ttl = teams_ttl or 60
            self._tags_ttl = tags_ttl or 120
            self._plugins_ttl = plugins_ttl or 120
            self._performance_ttl = performance_ttl or 60
            self._enabled = enabled if enabled is not None else True
            self._cache_prefix = "mcpgw:"

        # In-memory cache (fallback when Redis unavailable)
        self._cache: Dict[str, CacheEntry] = {}

        # Thread safety
        self._lock = threading.Lock()

        # Redis availability
        self._redis_checked = False
        self._redis_available = False

        # Statistics
        self._hit_count = 0
        self._miss_count = 0
        self._redis_hit_count = 0
        self._redis_miss_count = 0

        logger.info(f"AdminStatsCache initialized: enabled={self._enabled}, " f"system_ttl={self._system_ttl}s, observability_ttl={self._observability_ttl}s, tags_ttl={self._tags_ttl}s")

    def _get_redis_key(self, key_type: str, identifier: str = "") -> str:
        """Generate Redis key with proper prefix.

        Args:
            key_type: Type of cache entry (system, observability, users, teams)
            identifier: Optional identifier suffix

        Returns:
            Full Redis key with prefix

        Examples:
            >>> cache = AdminStatsCache()
            >>> cache._get_redis_key("system", "comprehensive")
            'mcpgw:admin:system:comprehensive'
        """
        if identifier:
            return f"{self._cache_prefix}admin:{key_type}:{identifier}"
        return f"{self._cache_prefix}admin:{key_type}"

    async def _get_redis_client(self):
        """Get Redis client if available.

        Returns:
            Redis client or None if unavailable.
        """
        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            client = await get_redis_client()
            if client and not self._redis_checked:
                self._redis_checked = True
                self._redis_available = True
                logger.debug("AdminStatsCache: Redis client available")
            return client
        except Exception as e:
            if not self._redis_checked:
                self._redis_checked = True
                self._redis_available = False
                logger.debug(f"AdminStatsCache: Redis unavailable, using in-memory cache: {e}")
            return None

    async def get_system_stats(self) -> Optional[Dict[str, Any]]:
        """Get cached system statistics.

        Returns:
            Cached system stats or None on cache miss

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> result = asyncio.run(cache.get_system_stats())
            >>> result is None  # Cache miss on fresh cache
            True
        """
        if not self._enabled:
            return None

        cache_key = self._get_redis_key("system", "comprehensive")

        # Try Redis first
        redis = await self._get_redis_client()
        if redis:
            try:
                data = await redis.get(cache_key)
                if data:
                    # Third-Party
                    import orjson  # pylint: disable=import-outside-toplevel

                    self._hit_count += 1
                    self._redis_hit_count += 1
                    return orjson.loads(data)
                self._redis_miss_count += 1
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis get failed: {e}")

        # Fall back to in-memory cache
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired():
                self._hit_count += 1
                return entry.value

        self._miss_count += 1
        return None

    async def set_system_stats(self, stats: Dict[str, Any]) -> None:
        """Store system statistics in cache.

        Args:
            stats: System statistics dictionary

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.set_system_stats({"tools": 10, "prompts": 5}))
        """
        if not self._enabled:
            return

        cache_key = self._get_redis_key("system", "comprehensive")

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Third-Party
                import orjson  # pylint: disable=import-outside-toplevel

                await redis.setex(cache_key, self._system_ttl, orjson.dumps(stats))
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis set failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._cache[cache_key] = CacheEntry(value=stats, expiry=time.time() + self._system_ttl)

    async def get_observability_stats(self, hours: int = 24) -> Optional[Dict[str, Any]]:
        """Get cached observability statistics.

        Args:
            hours: Time range in hours for stats

        Returns:
            Cached observability stats or None on cache miss

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> result = asyncio.run(cache.get_observability_stats(24))
            >>> result is None
            True
        """
        if not self._enabled:
            return None

        cache_key = self._get_redis_key("observability", str(hours))

        # Try Redis first
        redis = await self._get_redis_client()
        if redis:
            try:
                data = await redis.get(cache_key)
                if data:
                    # Third-Party
                    import orjson  # pylint: disable=import-outside-toplevel

                    self._hit_count += 1
                    self._redis_hit_count += 1
                    return orjson.loads(data)
                self._redis_miss_count += 1
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis get failed: {e}")

        # Fall back to in-memory cache
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired():
                self._hit_count += 1
                return entry.value

        self._miss_count += 1
        return None

    async def set_observability_stats(self, stats: Dict[str, Any], hours: int = 24) -> None:
        """Store observability statistics in cache.

        Args:
            stats: Observability statistics dictionary
            hours: Time range in hours for stats

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.set_observability_stats({"total_traces": 100}, 24))
        """
        if not self._enabled:
            return

        cache_key = self._get_redis_key("observability", str(hours))

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Third-Party
                import orjson  # pylint: disable=import-outside-toplevel

                await redis.setex(cache_key, self._observability_ttl, orjson.dumps(stats))
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis set failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._cache[cache_key] = CacheEntry(value=stats, expiry=time.time() + self._observability_ttl)

    async def get_users_list(self, limit: int, offset: int) -> Optional[Any]:
        """Get cached users list.

        Args:
            limit: Page size
            offset: Page offset

        Returns:
            Cached users list or None on cache miss

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> result = asyncio.run(cache.get_users_list(100, 0))
            >>> result is None
            True
        """
        if not self._enabled:
            return None

        cache_key = self._get_redis_key("users", f"{limit}:{offset}")

        # Try Redis first
        redis = await self._get_redis_client()
        if redis:
            try:
                data = await redis.get(cache_key)
                if data:
                    # Third-Party
                    import orjson  # pylint: disable=import-outside-toplevel

                    self._hit_count += 1
                    self._redis_hit_count += 1
                    return orjson.loads(data)
                self._redis_miss_count += 1
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis get failed: {e}")

        # Fall back to in-memory cache
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired():
                self._hit_count += 1
                return entry.value

        self._miss_count += 1
        return None

    async def set_users_list(self, users: Any, limit: int, offset: int) -> None:
        """Store users list in cache.

        Args:
            users: Users list data
            limit: Page size
            offset: Page offset

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.set_users_list([{"email": "test@example.com"}], 100, 0))
        """
        if not self._enabled:
            return

        cache_key = self._get_redis_key("users", f"{limit}:{offset}")

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Third-Party
                import orjson  # pylint: disable=import-outside-toplevel

                await redis.setex(cache_key, self._users_ttl, orjson.dumps(users))
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis set failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._cache[cache_key] = CacheEntry(value=users, expiry=time.time() + self._users_ttl)

    async def get_teams_list(self, limit: int, offset: int) -> Optional[Any]:
        """Get cached teams list.

        Args:
            limit: Page size
            offset: Page offset

        Returns:
            Cached teams list or None on cache miss

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> result = asyncio.run(cache.get_teams_list(100, 0))
            >>> result is None
            True
        """
        if not self._enabled:
            return None

        cache_key = self._get_redis_key("teams", f"{limit}:{offset}")

        # Try Redis first
        redis = await self._get_redis_client()
        if redis:
            try:
                data = await redis.get(cache_key)
                if data:
                    # Third-Party
                    import orjson  # pylint: disable=import-outside-toplevel

                    self._hit_count += 1
                    self._redis_hit_count += 1
                    return orjson.loads(data)
                self._redis_miss_count += 1
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis get failed: {e}")

        # Fall back to in-memory cache
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired():
                self._hit_count += 1
                return entry.value

        self._miss_count += 1
        return None

    async def set_teams_list(self, teams: Any, limit: int, offset: int) -> None:
        """Store teams list in cache.

        Args:
            teams: Teams list data
            limit: Page size
            offset: Page offset

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.set_teams_list([{"id": "team1", "name": "Team 1"}], 100, 0))
        """
        if not self._enabled:
            return

        cache_key = self._get_redis_key("teams", f"{limit}:{offset}")

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Third-Party
                import orjson  # pylint: disable=import-outside-toplevel

                await redis.setex(cache_key, self._teams_ttl, orjson.dumps(teams))
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis set failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._cache[cache_key] = CacheEntry(value=teams, expiry=time.time() + self._teams_ttl)

    async def get_tags(self, entity_types_hash: str) -> Optional[Any]:
        """Get cached tags listing.

        Args:
            entity_types_hash: Hash of entity types filter

        Returns:
            Cached tags list or None on cache miss

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> result = asyncio.run(cache.get_tags("all"))
            >>> result is None
            True
        """
        if not self._enabled:
            return None

        cache_key = self._get_redis_key("tags", entity_types_hash)

        # Try Redis first
        redis = await self._get_redis_client()
        if redis:
            try:
                data = await redis.get(cache_key)
                if data:
                    # Third-Party
                    import orjson  # pylint: disable=import-outside-toplevel

                    self._hit_count += 1
                    self._redis_hit_count += 1
                    return orjson.loads(data)
                self._redis_miss_count += 1
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis get failed: {e}")

        # Fall back to in-memory cache
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired():
                self._hit_count += 1
                return entry.value

        self._miss_count += 1
        return None

    async def set_tags(self, tags: Any, entity_types_hash: str) -> None:
        """Store tags listing in cache.

        Args:
            tags: Tags list data
            entity_types_hash: Hash of entity types filter

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.set_tags([{"name": "api", "count": 10}], "all"))
        """
        if not self._enabled:
            return

        cache_key = self._get_redis_key("tags", entity_types_hash)

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Third-Party
                import orjson  # pylint: disable=import-outside-toplevel

                await redis.setex(cache_key, self._tags_ttl, orjson.dumps(tags))
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis set failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._cache[cache_key] = CacheEntry(value=tags, expiry=time.time() + self._tags_ttl)

    async def get_plugin_stats(self) -> Optional[Dict[str, Any]]:
        """Get cached plugin statistics.

        Returns:
            Cached plugin stats or None on cache miss

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> result = asyncio.run(cache.get_plugin_stats())
            >>> result is None
            True
        """
        if not self._enabled:
            return None

        cache_key = self._get_redis_key("plugins", "stats")

        # Try Redis first
        redis = await self._get_redis_client()
        if redis:
            try:
                data = await redis.get(cache_key)
                if data:
                    # Third-Party
                    import orjson  # pylint: disable=import-outside-toplevel

                    self._hit_count += 1
                    self._redis_hit_count += 1
                    return orjson.loads(data)
                self._redis_miss_count += 1
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis get failed: {e}")

        # Fall back to in-memory cache
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired():
                self._hit_count += 1
                return entry.value

        self._miss_count += 1
        return None

    async def set_plugin_stats(self, stats: Dict[str, Any]) -> None:
        """Store plugin statistics in cache.

        Args:
            stats: Plugin statistics dictionary

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.set_plugin_stats({"total_plugins": 5}))
        """
        if not self._enabled:
            return

        cache_key = self._get_redis_key("plugins", "stats")

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Third-Party
                import orjson  # pylint: disable=import-outside-toplevel

                await redis.setex(cache_key, self._plugins_ttl, orjson.dumps(stats))
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis set failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._cache[cache_key] = CacheEntry(value=stats, expiry=time.time() + self._plugins_ttl)

    async def get_performance_history(self, cache_key_suffix: str) -> Optional[Dict[str, Any]]:
        """Get cached performance aggregates.

        Args:
            cache_key_suffix: Cache key suffix with filter params

        Returns:
            Cached performance data or None on cache miss

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> result = asyncio.run(cache.get_performance_history("hourly:168"))
            >>> result is None
            True
        """
        if not self._enabled:
            return None

        cache_key = self._get_redis_key("performance", cache_key_suffix)

        # Try Redis first
        redis = await self._get_redis_client()
        if redis:
            try:
                data = await redis.get(cache_key)
                if data:
                    # Third-Party
                    import orjson  # pylint: disable=import-outside-toplevel

                    self._hit_count += 1
                    self._redis_hit_count += 1
                    return orjson.loads(data)
                self._redis_miss_count += 1
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis get failed: {e}")

        # Fall back to in-memory cache
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired():
                self._hit_count += 1
                return entry.value

        self._miss_count += 1
        return None

    async def set_performance_history(self, data: Dict[str, Any], cache_key_suffix: str) -> None:
        """Store performance aggregates in cache.

        Args:
            data: Performance data dictionary
            cache_key_suffix: Cache key suffix with filter params

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.set_performance_history({"aggregates": []}, "hourly:168"))
        """
        if not self._enabled:
            return

        cache_key = self._get_redis_key("performance", cache_key_suffix)

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Third-Party
                import orjson  # pylint: disable=import-outside-toplevel

                await redis.setex(cache_key, self._performance_ttl, orjson.dumps(data))
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis set failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._cache[cache_key] = CacheEntry(value=data, expiry=time.time() + self._performance_ttl)

    async def invalidate_system_stats(self) -> None:
        """Invalidate system stats cache.

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.invalidate_system_stats())
        """
        logger.debug("AdminStatsCache: Invalidating system stats cache")
        await self._invalidate_prefix("system")

    async def invalidate_observability_stats(self) -> None:
        """Invalidate observability stats cache.

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.invalidate_observability_stats())
        """
        logger.debug("AdminStatsCache: Invalidating observability stats cache")
        await self._invalidate_prefix("observability")

    async def invalidate_users(self) -> None:
        """Invalidate users cache.

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.invalidate_users())
        """
        logger.debug("AdminStatsCache: Invalidating users cache")
        await self._invalidate_prefix("users")

    async def invalidate_teams(self) -> None:
        """Invalidate teams cache.

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.invalidate_teams())
        """
        logger.debug("AdminStatsCache: Invalidating teams cache")
        await self._invalidate_prefix("teams")

    async def invalidate_tags(self) -> None:
        """Invalidate tags cache.

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.invalidate_tags())
        """
        logger.debug("AdminStatsCache: Invalidating tags cache")
        await self._invalidate_prefix("tags")

    async def invalidate_plugins(self) -> None:
        """Invalidate plugins cache.

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.invalidate_plugins())
        """
        logger.debug("AdminStatsCache: Invalidating plugins cache")
        await self._invalidate_prefix("plugins")

    async def invalidate_performance(self) -> None:
        """Invalidate performance cache.

        Examples:
            >>> import asyncio
            >>> cache = AdminStatsCache()
            >>> asyncio.run(cache.invalidate_performance())
        """
        logger.debug("AdminStatsCache: Invalidating performance cache")
        await self._invalidate_prefix("performance")

    async def _invalidate_prefix(self, prefix: str) -> None:
        """Invalidate all cache entries with given prefix.

        Args:
            prefix: Cache key prefix to invalidate
        """
        full_prefix = self._get_redis_key(prefix)

        # Clear in-memory cache
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(full_prefix)]
            for key in keys_to_remove:
                self._cache.pop(key, None)

        # Clear Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                pattern = f"{full_prefix}*"
                async for key in redis.scan_iter(match=pattern):
                    await redis.delete(key)

                # Publish invalidation for other workers
                await redis.publish("mcpgw:cache:invalidate", f"admin:{prefix}")
            except Exception as e:
                logger.warning(f"AdminStatsCache Redis invalidate failed: {e}")

    def invalidate_all(self) -> None:
        """Invalidate all cached data synchronously.

        Examples:
            >>> cache = AdminStatsCache()
            >>> cache.invalidate_all()
        """
        with self._lock:
            self._cache.clear()
        logger.info("AdminStatsCache: All caches invalidated")

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with hit/miss counts and hit rate

        Examples:
            >>> cache = AdminStatsCache()
            >>> stats = cache.stats()
            >>> "hit_count" in stats
            True
        """
        total = self._hit_count + self._miss_count
        redis_total = self._redis_hit_count + self._redis_miss_count

        return {
            "enabled": self._enabled,
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": self._hit_count / total if total > 0 else 0.0,
            "redis_hit_count": self._redis_hit_count,
            "redis_miss_count": self._redis_miss_count,
            "redis_hit_rate": self._redis_hit_count / redis_total if redis_total > 0 else 0.0,
            "redis_available": self._redis_available,
            "cache_size": len(self._cache),
            "ttls": {
                "system": self._system_ttl,
                "observability": self._observability_ttl,
                "users": self._users_ttl,
                "teams": self._teams_ttl,
                "tags": self._tags_ttl,
                "plugins": self._plugins_ttl,
                "performance": self._performance_ttl,
            },
        }

    def reset_stats(self) -> None:
        """Reset hit/miss counters.

        Examples:
            >>> cache = AdminStatsCache()
            >>> cache._hit_count = 100
            >>> cache.reset_stats()
            >>> cache._hit_count
            0
        """
        self._hit_count = 0
        self._miss_count = 0
        self._redis_hit_count = 0
        self._redis_miss_count = 0


# Global singleton instance
_admin_stats_cache: Optional[AdminStatsCache] = None


def get_admin_stats_cache() -> AdminStatsCache:
    """Get or create the singleton AdminStatsCache instance.

    Returns:
        AdminStatsCache: The singleton admin stats cache instance

    Examples:
        >>> cache = get_admin_stats_cache()
        >>> isinstance(cache, AdminStatsCache)
        True
    """
    global _admin_stats_cache  # pylint: disable=global-statement
    if _admin_stats_cache is None:
        _admin_stats_cache = AdminStatsCache()
    return _admin_stats_cache


# Convenience alias for direct import
admin_stats_cache = get_admin_stats_cache()
