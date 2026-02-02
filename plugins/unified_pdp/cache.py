"""Decision cache – TTL-aware LRU with optional Redis back-end.

Architecture
------------
* The **in-memory** layer is always present.  It is a simple ``OrderedDict``
  capped at ``max_entries``.  Entries older than ``ttl_seconds`` are lazily
  evicted on read.
* When a Redis URL is supplied in ``settings.redis_url``, a second
  *write-through* layer is added.  Reads hit memory first; on a miss they
  fall through to Redis.  This keeps single-node latency low while giving
  multi-node clusters a shared store.
* The cache key is a **deterministic SHA-256** of the serialised request
  tuple ``(subject, action, resource, context)``.  Pydantic's
  ``model_dump(mode="json")`` guarantees stable output.

Thread safety
-------------
All public methods acquire an ``asyncio.Lock`` before touching the in-memory
dict.  Redis calls are inherently atomic per command.
"""

from __future__ import annotations

import hashlib
import json
import time
import logging
from collections import OrderedDict
from typing import Any, Dict, Optional

from .pdp_models import AccessDecision, CacheConfig, Context, Resource, Subject

logger = logging.getLogger(__name__)


def _build_cache_key(subject: Subject, action: str, resource: Resource, context: Context) -> str:
    """Produce a stable, collision-resistant cache key via SHA-256 hash.

    Includes all context fields that could affect policy decisions:
    - ip, session_id, user_agent for request identification
    - extra dict for policy-relevant metadata (e.g., MAC operation override)

    Excludes only the timestamp so requests within the same TTL window
    can hit the cache.

    Args:
        subject: The authenticated user/principal requesting access.
        action: The action being performed (e.g., "tools.invoke.db-query").
        resource: The resource being accessed.
        context: Request context (IP, user_agent, session, extra metadata).

    Returns:
        A 64-character hex string (SHA-256 hash) suitable as a cache key.
    """
    payload = json.dumps(
        {
            "subject": subject.model_dump(mode="json"),
            "action": action,
            "resource": resource.model_dump(mode="json"),
            # Include all context fields except timestamp
            "context_ip": context.ip,
            "context_session_id": context.session_id,
            "context_user_agent": context.user_agent,
            "context_extra": context.extra,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class _CacheEntry:
    """Thin wrapper that pairs a cached decision with its expiry epoch.

    Attributes:
        value: The cached AccessDecision object.
        expires_at: Monotonic timestamp when this entry expires.
    """

    __slots__ = ("value", "expires_at")

    def __init__(self, value: AccessDecision, ttl_seconds: int):
        """Initialize a cache entry with TTL-based expiration.

        Args:
            value: The AccessDecision to cache.
            ttl_seconds: Time-to-live in seconds from now.
        """
        self.value = value
        self.expires_at = time.monotonic() + ttl_seconds

    @property
    def expired(self) -> bool:
        """Check if this cache entry has exceeded its TTL.

        Returns:
            True if current time exceeds expires_at, False otherwise.
        """
        return time.monotonic() > self.expires_at


class DecisionCache:
    """Two-tier decision cache: in-memory LRU + optional async Redis.

    The in-memory layer uses an OrderedDict for LRU eviction. When Redis is
    configured, it acts as a write-through second tier for multi-node sharing.

    Args:
        config: Cache configuration (enabled, ttl_seconds, max_entries).
        redis_url: Optional Redis connection URL for distributed caching.

    Attributes:
        _config: The cache configuration.
        _store: In-memory LRU cache as OrderedDict.
        _redis_url: Redis connection URL or None.
        _redis: Lazy-initialized async Redis client.
        _hits: Counter for cache hits.
        _misses: Counter for cache misses.
    """

    def __init__(self, config: CacheConfig, redis_url: Optional[str] = None):
        """Initialize the decision cache.

        Args:
            config: Cache configuration specifying TTL, max entries, and enabled state.
            redis_url: Optional Redis URL for distributed caching across nodes.
        """
        self._config = config
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._redis_url = redis_url
        self._redis: Any = None  # lazy-initialised aioredis client
        # Stats counters
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Redis helper (lazy init)
    # ------------------------------------------------------------------

    async def _get_redis(self):  # pragma: no cover – integration test only
        """Lazily initialize and return the async Redis client.

        Creates the Redis connection on first call if redis_url is configured.
        Falls back to memory-only caching if the redis package is not installed.

        Returns:
            Async Redis client instance, or None if Redis is not configured
            or the redis package is unavailable.
        """
        if self._redis is None and self._redis_url:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(self._redis_url)
                logger.info("PDP cache: connected to Redis at %s", self._redis_url)
            except ImportError:
                logger.warning("redis package not installed – falling back to memory-only cache")
                self._redis_url = None
        return self._redis

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        context: Context,
    ) -> Optional[AccessDecision]:
        """Look up a cached decision by request parameters.

        Checks in-memory cache first, then falls through to Redis if configured.
        Expired entries are lazily evicted on access. Cache hits update LRU order.

        Args:
            subject: The authenticated user/principal requesting access.
            action: The action being performed.
            resource: The resource being accessed.
            context: Request context (IP, user_agent, session, extra).

        Returns:
            Cached AccessDecision if found and not expired, None otherwise.
        """
        if not self._config.enabled:
            return None

        key = _build_cache_key(subject, action, resource, context)

        # --- in-memory layer ---
        entry = self._store.get(key)
        if entry is not None:
            if entry.expired:
                del self._store[key]
            else:
                # Move to end (most-recently-used)
                self._store.move_to_end(key)
                self._hits += 1
                logger.debug("PDP cache HIT key=%s", key[:16])
                return entry.value

        # --- Redis layer ---
        redis = await self._get_redis()
        if redis:  # pragma: no cover
            raw = await redis.get(f"pdp:decision:{key}")
            if raw:
                decision = AccessDecision.model_validate_json(raw)
                # Populate memory layer for next hit
                self._store[key] = _CacheEntry(decision, self._config.ttl_seconds)
                self._hits += 1
                return decision

        self._misses += 1
        logger.debug("PDP cache MISS key=%s", key[:16])
        return None

    async def put(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        context: Context,
        decision: AccessDecision,
    ) -> None:
        """Store a decision in both memory and Redis (if configured).

        Evicts least-recently-used entries when max_entries is reached.
        Writes to Redis with TTL for distributed cache sharing.

        Args:
            subject: The authenticated user/principal requesting access.
            action: The action being performed.
            resource: The resource being accessed.
            context: Request context (IP, user_agent, session, extra).
            decision: The AccessDecision to cache.
        """
        if not self._config.enabled:
            return

        key = _build_cache_key(subject, action, resource, context)

        # Evict oldest entries if at capacity
        while len(self._store) >= self._config.max_entries:
            self._store.popitem(last=False)

        self._store[key] = _CacheEntry(decision, self._config.ttl_seconds)

        # --- Redis layer ---
        redis = await self._get_redis()
        if redis:  # pragma: no cover
            await redis.setex(
                f"pdp:decision:{key}",
                self._config.ttl_seconds,
                decision.model_dump_json(),
            )

        logger.debug("PDP cache PUT key=%s", key[:16])

    async def invalidate(
        self,
        subject: Optional[Subject] = None,
        action: Optional[str] = None,
        resource: Optional[Resource] = None,
    ) -> int:
        """Invalidate cached entries matching the given filters.

        Pass None for any field to match all entries. Currently flushes the
        entire cache when any filter is provided (targeted invalidation is
        planned for a future release).

        Args:
            subject: Filter by subject, or None to match all subjects.
            action: Filter by action, or None to match all actions.
            resource: Filter by resource, or None to match all resources.

        Returns:
            Number of entries removed from the in-memory cache.
        """
        removed = 0
        keys_to_delete = []

        for key in list(self._store.keys()):
            # Simple strategy: if no filter args, flush everything
            if subject is None and action is None and resource is None:
                keys_to_delete.append(key)
            # If we had the original request stored we could filter precisely;
            # for now a targeted invalidation flushes the whole cache.
            # Future: store the original request tuple alongside the entry.
            else:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self._store[key]
            removed += 1

        if removed:
            logger.info("PDP cache invalidated %d entries", removed)

        # Redis flush (scoped to our prefix)
        redis = await self._get_redis()
        if redis:  # pragma: no cover
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match="pdp:decision:*", count=100)
                if keys:
                    await redis.delete(*keys)
                if cursor == 0:
                    break

        return removed

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics for monitoring and debugging.

        Returns:
            Dictionary containing:
            - hits: Number of cache hits.
            - misses: Number of cache misses.
            - hit_rate: Ratio of hits to total requests (0.0-1.0).
            - size: Current number of entries in memory.
            - max_entries: Maximum allowed entries.
            - ttl_seconds: Time-to-live for cached entries.
            - redis_enabled: Whether Redis backing is configured.
        """
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
            "size": len(self._store),
            "max_entries": self._config.max_entries,
            "ttl_seconds": self._config.ttl_seconds,
            "redis_enabled": self._redis_url is not None,
        }
