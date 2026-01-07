# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/registry_cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Registry Data Cache.

This module implements a thread-safe cache for registry data (tools, prompts,
resources, agents, servers, gateways) with Redis as the primary store and
in-memory fallback. It reduces database queries for list endpoints.

Performance Impact:
    - Before: 1-2 DB queries per list request
    - After: 0 DB queries (cache hit) per TTL period
    - Expected 95%+ cache hit rate under load

Examples:
    >>> from mcpgateway.cache.registry_cache import registry_cache
    >>> # Cache is used automatically by list endpoints
    >>> # Manual invalidation after tool update:
    >>> import asyncio
    >>> # asyncio.run(registry_cache.invalidate_tools())
"""

# Standard
from dataclasses import dataclass
import hashlib
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
        >>> entry = CacheEntry(value=["item1", "item2"], expiry=time.time() + 60)
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


@dataclass
class RegistryCacheConfig:
    """Configuration for registry cache TTLs.

    Attributes:
        enabled: Whether caching is enabled
        tools_ttl: TTL in seconds for tools list cache
        prompts_ttl: TTL in seconds for prompts list cache
        resources_ttl: TTL in seconds for resources list cache
        agents_ttl: TTL in seconds for agents list cache
        servers_ttl: TTL in seconds for servers list cache
        gateways_ttl: TTL in seconds for gateways list cache
        catalog_ttl: TTL in seconds for catalog servers list cache

    Examples:
        >>> config = RegistryCacheConfig()
        >>> config.tools_ttl
        20
    """

    enabled: bool = True
    tools_ttl: int = 20
    prompts_ttl: int = 15
    resources_ttl: int = 15
    agents_ttl: int = 20
    servers_ttl: int = 20
    gateways_ttl: int = 20
    catalog_ttl: int = 300


class RegistryCache:
    """Thread-safe registry cache with Redis and in-memory tiers.

    This cache reduces database load for list endpoints by caching:
    - Tools list
    - Prompts list
    - Resources list
    - A2A Agents list
    - Servers list
    - Gateways list
    - Catalog servers list

    The cache uses Redis as the primary store for distributed deployments
    and falls back to in-memory caching when Redis is unavailable.

    Examples:
        >>> cache = RegistryCache()
        >>> cache.stats()["hit_count"]
        0
    """

    def __init__(self, config: Optional[RegistryCacheConfig] = None):
        """Initialize the registry cache.

        Args:
            config: Cache configuration. If None, loads from settings.

        Examples:
            >>> cache = RegistryCache()
            >>> cache._enabled
            True
        """
        # Import settings lazily to avoid circular imports
        try:
            # First-Party
            from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

            self._enabled = getattr(settings, "registry_cache_enabled", True)
            self._tools_ttl = getattr(settings, "registry_cache_tools_ttl", 20)
            self._prompts_ttl = getattr(settings, "registry_cache_prompts_ttl", 15)
            self._resources_ttl = getattr(settings, "registry_cache_resources_ttl", 15)
            self._agents_ttl = getattr(settings, "registry_cache_agents_ttl", 20)
            self._servers_ttl = getattr(settings, "registry_cache_servers_ttl", 20)
            self._gateways_ttl = getattr(settings, "registry_cache_gateways_ttl", 20)
            self._catalog_ttl = getattr(settings, "registry_cache_catalog_ttl", 300)
            self._cache_prefix = getattr(settings, "cache_prefix", "mcpgw:")
        except ImportError:
            cfg = config or RegistryCacheConfig()
            self._enabled = cfg.enabled
            self._tools_ttl = cfg.tools_ttl
            self._prompts_ttl = cfg.prompts_ttl
            self._resources_ttl = cfg.resources_ttl
            self._agents_ttl = cfg.agents_ttl
            self._servers_ttl = cfg.servers_ttl
            self._gateways_ttl = cfg.gateways_ttl
            self._catalog_ttl = cfg.catalog_ttl
            self._cache_prefix = "mcpgw:"

        # In-memory cache (fallback when Redis unavailable)
        self._cache: Dict[str, CacheEntry] = {}

        # Thread safety
        self._lock = threading.Lock()

        # Redis availability (None = not checked yet)
        self._redis_checked = False
        self._redis_available = False

        # Statistics
        self._hit_count = 0
        self._miss_count = 0
        self._redis_hit_count = 0
        self._redis_miss_count = 0

        logger.info(
            f"RegistryCache initialized: enabled={self._enabled}, "
            f"tools_ttl={self._tools_ttl}s, prompts_ttl={self._prompts_ttl}s, "
            f"resources_ttl={self._resources_ttl}s, agents_ttl={self._agents_ttl}s, "
            f"catalog_ttl={self._catalog_ttl}s"
        )

    def _get_redis_key(self, cache_type: str, filters_hash: str = "") -> str:
        """Generate Redis key with proper prefix.

        Args:
            cache_type: Type of cache entry (tools, prompts, etc.)
            filters_hash: Hash of filter parameters

        Returns:
            Full Redis key with prefix

        Examples:
            >>> cache = RegistryCache()
            >>> cache._get_redis_key("tools", "abc123")
            'mcpgw:registry:tools:abc123'
        """
        if filters_hash:
            return f"{self._cache_prefix}registry:{cache_type}:{filters_hash}"
        return f"{self._cache_prefix}registry:{cache_type}"

    def hash_filters(self, **kwargs) -> str:
        """Generate a hash from filter parameters.

        Args:
            **kwargs: Filter parameters to hash

        Returns:
            MD5 hash of the filter parameters

        Examples:
            >>> cache = RegistryCache()
            >>> h = cache.hash_filters(include_inactive=False, tags=["api"])
            >>> len(h)
            32
        """
        # Sort keys for consistent hashing
        sorted_items = sorted(kwargs.items())
        filter_str = str(sorted_items)
        return hashlib.md5(filter_str.encode()).hexdigest()  # nosec B324 # noqa: DUO130

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
                logger.debug("RegistryCache: Redis client available")
            return client
        except Exception as e:
            if not self._redis_checked:
                self._redis_checked = True
                self._redis_available = False
                logger.debug(f"RegistryCache: Redis unavailable, using in-memory cache: {e}")
            return None

    async def get(self, cache_type: str, filters_hash: str = "") -> Optional[Any]:
        """Get cached data.

        Args:
            cache_type: Type of cache (tools, prompts, resources, agents, servers, gateways)
            filters_hash: Hash of filter parameters

        Returns:
            Cached data if found, None otherwise

        Examples:
            >>> import asyncio
            >>> cache = RegistryCache()
            >>> result = asyncio.run(cache.get("tools", "abc123"))
            >>> result is None  # Cache miss on fresh cache
            True
        """
        if not self._enabled:
            return None

        cache_key = self._get_redis_key(cache_type, filters_hash)

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
                logger.warning(f"RegistryCache Redis get failed: {e}")

        # Fall back to in-memory cache
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired():
                self._hit_count += 1
                return entry.value

        self._miss_count += 1
        return None

    async def set(self, cache_type: str, data: Any, filters_hash: str = "", ttl: Optional[int] = None) -> None:
        """Store data in cache.

        Args:
            cache_type: Type of cache (tools, prompts, resources, agents, servers, gateways)
            data: Data to cache (must be JSON-serializable)
            filters_hash: Hash of filter parameters
            ttl: TTL in seconds (uses default for cache_type if not specified)

        Examples:
            >>> import asyncio
            >>> cache = RegistryCache()
            >>> asyncio.run(cache.set("tools", [{"id": "1", "name": "tool1"}], "abc123"))
        """
        if not self._enabled:
            return

        # Determine TTL
        if ttl is None:
            ttl_map = {
                "tools": self._tools_ttl,
                "prompts": self._prompts_ttl,
                "resources": self._resources_ttl,
                "agents": self._agents_ttl,
                "servers": self._servers_ttl,
                "gateways": self._gateways_ttl,
                "catalog": self._catalog_ttl,
            }
            ttl = ttl_map.get(cache_type, 20)

        cache_key = self._get_redis_key(cache_type, filters_hash)

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Third-Party
                import orjson  # pylint: disable=import-outside-toplevel

                await redis.setex(cache_key, ttl, orjson.dumps(data))
            except Exception as e:
                logger.warning(f"RegistryCache Redis set failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._cache[cache_key] = CacheEntry(value=data, expiry=time.time() + ttl)

    async def invalidate(self, cache_type: str) -> None:
        """Invalidate all cached data for a cache type.

        Args:
            cache_type: Type of cache to invalidate (tools, prompts, etc.)

        Examples:
            >>> import asyncio
            >>> cache = RegistryCache()
            >>> asyncio.run(cache.invalidate("tools"))
        """
        logger.debug(f"RegistryCache: Invalidating {cache_type} cache")
        prefix = self._get_redis_key(cache_type)

        # Clear in-memory cache
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for key in keys_to_remove:
                self._cache.pop(key, None)

        # Clear Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                pattern = f"{prefix}*"
                async for key in redis.scan_iter(match=pattern):
                    await redis.delete(key)

                # Publish invalidation for other workers
                await redis.publish("mcpgw:cache:invalidate", f"registry:{cache_type}")
            except Exception as e:
                logger.warning(f"RegistryCache Redis invalidate failed: {e}")

    async def invalidate_tools(self) -> None:
        """Invalidate tools cache.

        Examples:
            >>> import asyncio
            >>> cache = RegistryCache()
            >>> asyncio.run(cache.invalidate_tools())
        """
        await self.invalidate("tools")

    async def invalidate_prompts(self) -> None:
        """Invalidate prompts cache.

        Examples:
            >>> import asyncio
            >>> cache = RegistryCache()
            >>> asyncio.run(cache.invalidate_prompts())
        """
        await self.invalidate("prompts")

    async def invalidate_resources(self) -> None:
        """Invalidate resources cache.

        Examples:
            >>> import asyncio
            >>> cache = RegistryCache()
            >>> asyncio.run(cache.invalidate_resources())
        """
        await self.invalidate("resources")

    async def invalidate_agents(self) -> None:
        """Invalidate agents cache.

        Examples:
            >>> import asyncio
            >>> cache = RegistryCache()
            >>> asyncio.run(cache.invalidate_agents())
        """
        await self.invalidate("agents")

    async def invalidate_servers(self) -> None:
        """Invalidate servers cache.

        Examples:
            >>> import asyncio
            >>> cache = RegistryCache()
            >>> asyncio.run(cache.invalidate_servers())
        """
        await self.invalidate("servers")

    async def invalidate_gateways(self) -> None:
        """Invalidate gateways cache.

        Examples:
            >>> import asyncio
            >>> cache = RegistryCache()
            >>> asyncio.run(cache.invalidate_gateways())
        """
        await self.invalidate("gateways")

    async def invalidate_catalog(self) -> None:
        """Invalidate catalog servers cache.

        Examples:
            >>> import asyncio
            >>> cache = RegistryCache()
            >>> asyncio.run(cache.invalidate_catalog())
        """
        await self.invalidate("catalog")

    def invalidate_all(self) -> None:
        """Invalidate all cached data synchronously.

        Examples:
            >>> cache = RegistryCache()
            >>> cache.invalidate_all()
        """
        with self._lock:
            self._cache.clear()
        logger.info("RegistryCache: All caches invalidated")

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with hit/miss counts and hit rate

        Examples:
            >>> cache = RegistryCache()
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
                "tools": self._tools_ttl,
                "prompts": self._prompts_ttl,
                "resources": self._resources_ttl,
                "agents": self._agents_ttl,
                "servers": self._servers_ttl,
                "gateways": self._gateways_ttl,
                "catalog": self._catalog_ttl,
            },
        }

    def reset_stats(self) -> None:
        """Reset hit/miss counters.

        Examples:
            >>> cache = RegistryCache()
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
_registry_cache: Optional[RegistryCache] = None


def get_registry_cache() -> RegistryCache:
    """Get or create the singleton RegistryCache instance.

    Returns:
        RegistryCache: The singleton registry cache instance

    Examples:
        >>> cache = get_registry_cache()
        >>> isinstance(cache, RegistryCache)
        True
    """
    global _registry_cache  # pylint: disable=global-statement
    if _registry_cache is None:
        _registry_cache = RegistryCache()
    return _registry_cache


# Convenience alias for direct import
registry_cache = get_registry_cache()
