# -*- coding: utf-8 -*-
"""Tool lookup cache (tool name -> tool config) with L1 memory + L2 Redis.

This cache targets the hot-path tool lookup in ToolService.invoke_tool by
avoiding a DB query per tool invocation. It uses a per-worker in-memory
cache with TTL and optional Redis backing for distributed deployments.
"""

# Future
from __future__ import annotations

# Standard
from collections import OrderedDict
from dataclasses import dataclass
import logging
import threading
import time
from typing import Any, Dict, Optional

# Third-Party
import orjson

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with value and expiry timestamp."""

    value: Dict[str, Any]
    expiry: float

    def is_expired(self) -> bool:
        """Return True if the cache entry has expired.

        Returns:
            True if expired, otherwise False.
        """
        return time.time() >= self.expiry


class ToolLookupCache:
    """Two-tier cache for tool lookups by name.

    L1: in-memory LRU/TTL per worker.
    L2: Redis (optional, shared across workers).
    """

    def __init__(self) -> None:
        """Initialize cache settings and in-memory structures."""
        try:
            # First-Party
            from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

            self._enabled = getattr(settings, "tool_lookup_cache_enabled", True)
            self._ttl_seconds = getattr(settings, "tool_lookup_cache_ttl_seconds", 60)
            self._negative_ttl_seconds = getattr(settings, "tool_lookup_cache_negative_ttl_seconds", 10)
            self._l1_maxsize = getattr(settings, "tool_lookup_cache_l1_maxsize", 10000)
            self._l2_enabled = getattr(settings, "tool_lookup_cache_l2_enabled", True) and settings.cache_type == "redis"
            self._cache_prefix = getattr(settings, "cache_prefix", "mcpgw:")
        except ImportError:
            self._enabled = True
            self._ttl_seconds = 60
            self._negative_ttl_seconds = 10
            self._l1_maxsize = 10000
            self._l2_enabled = False
            self._cache_prefix = "mcpgw:"

        self._cache: "OrderedDict[str, CacheEntry]" = OrderedDict()
        self._lock = threading.Lock()

        self._redis_checked = False
        self._redis_available = False

        self._l1_hit_count = 0
        self._l1_miss_count = 0
        self._l2_hit_count = 0
        self._l2_miss_count = 0

        logger.info(
            "ToolLookupCache initialized: enabled=%s l1_max=%s ttl=%ss l2_enabled=%s",
            self._enabled,
            self._l1_maxsize,
            self._ttl_seconds,
            self._l2_enabled,
        )

    @property
    def enabled(self) -> bool:
        """Return True if the cache is enabled.

        Returns:
            True if enabled, otherwise False.
        """
        return self._enabled

    def _redis_key(self, name: str) -> str:
        """Build the Redis key for a tool name.

        Args:
            name: Tool name.

        Returns:
            Redis key for the tool lookup entry.
        """
        return f"{self._cache_prefix}tool_lookup:{name}"

    def _gateway_set_key(self, gateway_id: str) -> str:
        """Build the Redis set key for tools in a gateway.

        Args:
            gateway_id: Gateway ID.

        Returns:
            Redis set key for gateway tool names.
        """
        return f"{self._cache_prefix}tool_lookup:gateway:{gateway_id}"

    async def _get_redis_client(self):
        """Return a Redis client if L2 is enabled and available.

        Returns:
            Redis client instance or None.
        """
        if not self._l2_enabled:
            return None
        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            client = await get_redis_client()
            if client and not self._redis_checked:
                self._redis_checked = True
                self._redis_available = True
            return client
        except Exception:
            if not self._redis_checked:
                self._redis_checked = True
                self._redis_available = False
            return None

    def _get_l1(self, name: str) -> Optional[Dict[str, Any]]:
        """Fetch a cached payload from L1 if present and not expired.

        Args:
            name: Tool name.

        Returns:
            Cached payload dict or None.
        """
        with self._lock:
            entry = self._cache.get(name)
            if entry and not entry.is_expired():
                # LRU: move to end on hit
                self._cache.move_to_end(name)
                self._l1_hit_count += 1
                return entry.value
            if entry:
                self._cache.pop(name, None)
            self._l1_miss_count += 1
        return None

    def _set_l1(self, name: str, value: Dict[str, Any], ttl: int) -> None:
        """Store a payload in the L1 cache with TTL.

        Args:
            name: Tool name.
            value: Payload to cache.
            ttl: Time to live in seconds.
        """
        with self._lock:
            if name in self._cache:
                self._cache.pop(name, None)
            elif len(self._cache) >= self._l1_maxsize:
                self._cache.popitem(last=False)
            self._cache[name] = CacheEntry(value=value, expiry=time.time() + ttl)

    async def get(self, name: str) -> Optional[Dict[str, Any]]:
        """Get cached payload for a tool name, checking L1 then L2.

        Args:
            name: Tool name.

        Returns:
            Cached payload dict or None.
        """
        if not self._enabled:
            return None

        cached = self._get_l1(name)
        if cached is not None:
            return cached

        redis = await self._get_redis_client()
        if not redis:
            return None

        try:
            data = await redis.get(self._redis_key(name))
            if data:
                self._l2_hit_count += 1
                payload = orjson.loads(data)
                self._set_l1(name, payload, self._ttl_seconds)
                return payload
            self._l2_miss_count += 1
        except Exception as exc:
            logger.debug("ToolLookupCache Redis get failed: %s", exc)
        return None

    async def set(self, name: str, payload: Dict[str, Any], ttl: Optional[int] = None, gateway_id: Optional[str] = None) -> None:
        """Store a payload in cache and update gateway index if provided.

        Args:
            name: Tool name.
            payload: Payload to cache.
            ttl: Time to live in seconds (defaults to configured TTL).
            gateway_id: Gateway ID for invalidation set tracking.
        """
        if not self._enabled:
            return

        effective_ttl = ttl if ttl is not None else self._ttl_seconds
        self._set_l1(name, payload, effective_ttl)

        redis = await self._get_redis_client()
        if not redis:
            return

        try:
            await redis.setex(self._redis_key(name), effective_ttl, orjson.dumps(payload))
            if gateway_id:
                set_key = self._gateway_set_key(gateway_id)
                await redis.sadd(set_key, name)
                await redis.expire(set_key, max(effective_ttl, self._ttl_seconds))
        except Exception as exc:
            logger.debug("ToolLookupCache Redis set failed: %s", exc)

    async def set_negative(self, name: str, status: str) -> None:
        """Store a negative cache entry for a tool name.

        Args:
            name: Tool name.
            status: Negative status (missing, inactive, offline).
        """
        payload = {"status": status}
        await self.set(name=name, payload=payload, ttl=self._negative_ttl_seconds)

    async def invalidate(self, name: str, gateway_id: Optional[str] = None) -> None:
        """Invalidate a tool cache entry by name.

        Args:
            name: Tool name.
            gateway_id: Gateway ID for invalidation set tracking.
        """
        if not self._enabled:
            return

        with self._lock:
            self._cache.pop(name, None)

        redis = await self._get_redis_client()
        if not redis:
            return

        try:
            await redis.delete(self._redis_key(name))
            if gateway_id:
                await redis.srem(self._gateway_set_key(gateway_id), name)
            await redis.publish("mcpgw:cache:invalidate", f"tool_lookup:{name}")
        except Exception as exc:
            logger.debug("ToolLookupCache Redis invalidate failed: %s", exc)

    async def invalidate_gateway(self, gateway_id: str) -> None:
        """Invalidate all cached tools for a gateway.

        Args:
            gateway_id: Gateway ID.
        """
        if not self._enabled:
            return

        # L1 invalidation by gateway_id
        with self._lock:
            to_remove = [name for name, entry in self._cache.items() if entry.value.get("tool", {}).get("gateway_id") == gateway_id]
            for name in to_remove:
                self._cache.pop(name, None)

        redis = await self._get_redis_client()
        if not redis:
            return

        set_key = self._gateway_set_key(gateway_id)
        try:
            tool_names = await redis.smembers(set_key)
            if tool_names:
                keys = [self._redis_key(name.decode() if isinstance(name, bytes) else name) for name in tool_names]
                await redis.delete(*keys)
            await redis.delete(set_key)
            await redis.publish("mcpgw:cache:invalidate", f"tool_lookup:gateway:{gateway_id}")
        except Exception as exc:
            logger.debug("ToolLookupCache Redis invalidate_gateway failed: %s", exc)

    def invalidate_all_local(self) -> None:
        """Clear all L1 cache entries."""
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        """Return cache hit/miss statistics and configuration.

        Returns:
            Cache stats and settings.
        """
        total_l1 = self._l1_hit_count + self._l1_miss_count
        total_l2 = self._l2_hit_count + self._l2_miss_count
        return {
            "enabled": self._enabled,
            "l1_hit_count": self._l1_hit_count,
            "l1_miss_count": self._l1_miss_count,
            "l1_hit_rate": self._l1_hit_count / total_l1 if total_l1 > 0 else 0.0,
            "l2_hit_count": self._l2_hit_count,
            "l2_miss_count": self._l2_miss_count,
            "l2_hit_rate": self._l2_hit_count / total_l2 if total_l2 > 0 else 0.0,
            "l1_size": len(self._cache),
            "l1_maxsize": self._l1_maxsize,
            "ttl_seconds": self._ttl_seconds,
            "negative_ttl_seconds": self._negative_ttl_seconds,
            "l2_enabled": self._l2_enabled,
            "redis_available": self._redis_available,
        }

    def reset_stats(self) -> None:
        """Reset hit/miss counters."""
        self._l1_hit_count = 0
        self._l1_miss_count = 0
        self._l2_hit_count = 0
        self._l2_miss_count = 0


tool_lookup_cache = ToolLookupCache()
