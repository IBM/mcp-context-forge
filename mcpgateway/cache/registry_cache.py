# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/registry_cache.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

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
import asyncio
from dataclasses import dataclass
import hashlib
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


# Exception types that indicate a Redis connectivity problem (as opposed
# to a programming bug). These MUST be listed explicitly because redis-py's
# ConnectionError / TimeoutError do NOT inherit from the stdlib equivalents,
# so a bare `except ConnectionError` silently misses real Redis failures.
#
# The import is guarded because redis is an OPTIONAL dependency (see
# [project.optional-dependencies] redis in pyproject.toml); environments
# without the redis extra installed — e.g. the Playwright UI smoke job —
# must still be able to import this module. When redis is missing the
# tuples fall back to stdlib-only catches; the Redis code paths are never
# actually reached because `_get_redis_client()` returns None in that case.
#
# Aliased as `redis_exceptions` (not plain `redis`) to avoid shadowing the
# many `redis = await self._get_redis_client()` locals (pylint W0621).
# Module-level tuple literals so pylint statically resolves the types in
# except clauses (avoids E0712 catching-non-exception).
try:
    # Third-Party
    from redis import exceptions as redis_exceptions  # pylint: disable=import-error

    _REDIS_TIMEOUT_EXCEPTIONS = (asyncio.TimeoutError, redis_exceptions.TimeoutError)
    _REDIS_CONNECTION_EXCEPTIONS = (
        ConnectionError,
        OSError,
        redis_exceptions.ConnectionError,
        redis_exceptions.RedisError,
    )
except ImportError:
    _REDIS_TIMEOUT_EXCEPTIONS = (asyncio.TimeoutError,)
    _REDIS_CONNECTION_EXCEPTIONS = (ConnectionError, OSError)


@dataclass(frozen=True)
class _CircuitLease:
    """Opaque token describing a circuit-breaker admission decision.

    Returned by ``_acquire_probe_slot``. ``allowed`` gates whether the
    caller may execute the Redis operation. ``is_probe`` is True only for
    the single coroutine granted the exclusive half-open probe slot, which
    must be released in the finally path on cancellation or unexpected
    exit.
    """

    allowed: bool
    is_probe: bool


def _get_cleanup_timeout() -> float:
    """Cache-cleanup timeout (seconds) for pubsub / transport close operations.

    Returns a fixed 5s — well above typical close latency, bounded enough to
    keep shutdown deterministic when a connection is stuck. Previously read
    settings.mcp_session_pool_cleanup_timeout, which disappeared with the
    pool config (#4205). No deployment in the wild tuned this knob, so a
    constant is fine; if that changes we can re-introduce a dedicated
    setting under a neutral name.
    """
    return 5.0


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
            self._redis_operation_timeout = getattr(settings, "redis_operation_timeout", 0.5)
            self._redis_failure_threshold = getattr(settings, "redis_circuit_failure_threshold", 3)
            self._redis_circuit_open_duration = getattr(settings, "redis_circuit_open_duration", 30.0)
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
            self._redis_operation_timeout = 0.5
            self._redis_failure_threshold = 3
            self._redis_circuit_open_duration = 30.0

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

        # Circuit breaker state (threshold and cooldown come from settings above).
        self._redis_failure_count = 0
        self._redis_last_failure_time = 0.0
        self._redis_circuit_open = False
        # Guard used to gate the single half-open probe: while True, other
        # callers must treat the circuit as open (prevents thundering herd
        # when the cooldown expires on a still-down Redis).
        self._half_open_probe_in_flight = False
        # Lazy-init to avoid binding asyncio.Lock to whatever event loop
        # happens to exist at module-import time (singleton is created at
        # import). _ensure_circuit_lock() creates it on first async use.
        self._circuit_breaker_lock: Optional[asyncio.Lock] = None
        # scan_iter traversal on large keysets can legitimately exceed the
        # per-op timeout; give it 10x room with a 5s floor so delete+publish
        # aren't silently dropped. Exposed as an attribute so tests can tune
        # it without waiting for the production floor.
        self._scan_timeout = max(self._redis_operation_timeout * 10, 5.0)

        logger.info(
            f"RegistryCache initialized: enabled={self._enabled}, "
            f"tools_ttl={self._tools_ttl}s, prompts_ttl={self._prompts_ttl}s, "
            f"resources_ttl={self._resources_ttl}s, agents_ttl={self._agents_ttl}s, "
            f"catalog_ttl={self._catalog_ttl}s, redis_timeout={self._redis_operation_timeout}s"
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
        return hashlib.md5(filter_str.encode()).hexdigest()  # nosec B324

    def _ensure_circuit_lock(self) -> asyncio.Lock:
        """Create the asyncio.Lock lazily on first async use.

        Returns:
            asyncio.Lock: The singleton circuit-breaker lock bound to the
            current event loop.
        """
        if self._circuit_breaker_lock is None:
            self._circuit_breaker_lock = asyncio.Lock()
        return self._circuit_breaker_lock

    async def _acquire_probe_slot(self, operation_name: str) -> "_CircuitLease":
        """Check the circuit and reserve a probe slot if half-open.

        Args:
            operation_name: Name of the Redis operation, used for log output.

        Returns:
            A ``_CircuitLease`` describing whether the caller may proceed and
            whether it holds the exclusive half-open probe slot.
        """
        # Fast path: the steady-state happy case needs no lock. Stale reads
        # here are safe because a concurrent open is followed by a lock-held
        # transition that the next caller sees, and the actual Redis call's
        # failure would route into _record_failure anyway.
        if not self._redis_circuit_open:
            return _CircuitLease(allowed=True, is_probe=False)

        lock = self._ensure_circuit_lock()
        log_half_open = False
        async with lock:
            if not self._redis_circuit_open:
                return _CircuitLease(allowed=True, is_probe=False)
            if time.time() - self._redis_last_failure_time < self._redis_circuit_open_duration:
                lease = _CircuitLease(allowed=False, is_probe=False)
            elif self._half_open_probe_in_flight:
                lease = _CircuitLease(allowed=False, is_probe=False)
            else:
                self._half_open_probe_in_flight = True
                lease = _CircuitLease(allowed=True, is_probe=True)
                log_half_open = True
        if not lease.allowed:
            logger.debug("Redis circuit open, skipping %s", operation_name)
        elif log_half_open:
            logger.info("Redis circuit half-open, sending single probe via %s", operation_name)
        return lease

    async def _release_probe_slot(self) -> None:
        """Release the half-open probe slot unconditionally.

        Used by the cancellation/finally safety net in
        ``_redis_operation_with_timeout`` so that an outer task cancellation
        cannot strand the flag in the set position and permanently disable
        the circuit breaker.
        """
        lock = self._ensure_circuit_lock()
        async with lock:
            self._half_open_probe_in_flight = False

    async def _record_success(self, is_probe: bool) -> None:
        """Update breaker state after a successful Redis operation.

        Args:
            is_probe: True when the caller held the half-open probe slot.
                A successful probe closes the circuit; routine successes
                merely reset the accumulated failure count.

        A non-probe success that races against an already-open circuit MUST
        NOT zero the failure counter, otherwise the reachable state
        ``(circuit_open=True, failure_count=0)`` misrepresents cooldown
        progress to observers.
        """
        # Fast path: steady-state happy success needs no lock.
        if not is_probe and self._redis_failure_count == 0:
            return

        lock = self._ensure_circuit_lock()
        circuit_closed_now = False
        failures_cleared = 0
        async with lock:
            if is_probe:
                self._half_open_probe_in_flight = False
                if self._redis_circuit_open:
                    self._redis_circuit_open = False
                    circuit_closed_now = True
            elif self._redis_circuit_open:
                return
            if self._redis_failure_count > 0:
                failures_cleared = self._redis_failure_count
                self._redis_failure_count = 0
        if circuit_closed_now:
            logger.info("Redis circuit closed after successful probe")
        if failures_cleared > 0:
            logger.info("Redis recovered after %d failure(s)", failures_cleared)

    async def _record_failure(self, operation_name: str, error_msg: str, is_probe: bool) -> None:
        """Update breaker state after a Redis timeout or connection error.

        Args:
            operation_name: Name of the failing operation (for log messages).
            error_msg: Short description of the failure ("timeout after 0.5s",
                exception text, etc.).
            is_probe: True when the caller held the half-open probe slot;
                a probe failure keeps the circuit open and extends cooldown.
        """
        lock = self._ensure_circuit_lock()
        new_failure_count = 0
        circuit_opened_now = False
        async with lock:
            if is_probe:
                self._half_open_probe_in_flight = False
            self._redis_failure_count += 1
            self._redis_last_failure_time = time.time()
            new_failure_count = self._redis_failure_count
            if self._redis_failure_count >= self._redis_failure_threshold and not self._redis_circuit_open:
                self._redis_circuit_open = True
                circuit_opened_now = True
        logger.warning(
            "Redis %s failed: %s (failure %d/%d)",
            operation_name,
            error_msg,
            new_failure_count,
            self._redis_failure_threshold,
        )
        if circuit_opened_now:
            logger.error(
                "Redis circuit opened after %d failure(s). Will retry in %.1fs",
                new_failure_count,
                self._redis_circuit_open_duration,
            )

    async def _redis_operation_with_timeout(
        self,
        operation: Callable,
        *args,
        operation_name: str = "redis_op",
        timeout_override: Optional[float] = None,
        **kwargs,
    ) -> Optional[Any]:
        """Execute a Redis operation with per-call timeout and circuit breaker.

        Args:
            operation: Async callable to execute.
            *args: Positional arguments for operation.
            operation_name: Name for logging.
            timeout_override: Override the default per-operation timeout for
                legitimately slow operations (e.g. ``scan_iter`` on large
                keysets). Defaults to ``self._redis_operation_timeout``.
            **kwargs: Keyword arguments for operation.

        Returns:
            The operation result, or ``None`` on timeout/connection error.
            ``asyncio.CancelledError`` is re-raised after releasing the
            probe slot so outer task cancellation cannot permanently disable
            the breaker.

        Examples:
            >>> import asyncio
            >>> cache = RegistryCache()
            >>> async def mock_op():
            ...     return "result"
            >>> result = asyncio.run(cache._redis_operation_with_timeout(mock_op, operation_name="test"))
        """
        timeout = timeout_override if timeout_override is not None else self._redis_operation_timeout

        lease = await self._acquire_probe_slot(operation_name)
        if not lease.allowed:
            return None

        finished_cleanly = False
        try:
            try:
                result = await asyncio.wait_for(operation(*args, **kwargs), timeout=timeout)
            except _REDIS_TIMEOUT_EXCEPTIONS:
                await self._record_failure(operation_name, f"timeout after {timeout}s", lease.is_probe)
                finished_cleanly = True
                return None
            except _REDIS_CONNECTION_EXCEPTIONS as exc:
                await self._record_failure(operation_name, f"connection error: {exc}", lease.is_probe)
                finished_cleanly = True
                return None
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.exception("Unexpected error in Redis %s: %s", operation_name, exc)
                return None
            # Fall-through (try succeeded; all except branches returned).
            await self._record_success(lease.is_probe)
            finished_cleanly = True
            return result
        finally:
            # Safety net for CancelledError (BaseException) and any path
            # that bypassed the record_* calls above. Idempotent: releases
            # only if the slot is still held.
            if lease.is_probe and not finished_cleanly:
                await self._release_probe_slot()

    async def _get_redis_client(self):
        """Return the shared Redis client, or None if unavailable.

        The per-call ping was intentionally removed: wrapping ping in the
        circuit breaker on every cache operation hides a "half-up Redis"
        (accepts connections / PING but times out commands) because each
        request sees ping_success → failure_count reset → get/set failure →
        failure_count = 1, oscillating forever without tripping the breaker.
        The factory (``mcpgateway.utils.redis_client.get_redis_client``)
        pings on initial client creation; subsequent health is inferred from
        real-operation success/failure, which is the breaker's actual job.

        Returns:
            Redis client or None if the factory is unavailable.
        """
        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            client = await get_redis_client()
        except (ImportError, AttributeError) as e:
            if not self._redis_checked:
                logger.debug("RegistryCache: Redis client factory unavailable, using in-memory cache: %s", e)
            self._redis_checked = True
            self._redis_available = False
            return None
        except _REDIS_CONNECTION_EXCEPTIONS as e:
            await self._record_failure("factory", f"connection error: {e}", is_probe=False)
            self._redis_checked = True
            self._redis_available = False
            return None
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception("RegistryCache: Unexpected error from Redis factory, using in-memory cache: %s", e)
            self._redis_checked = True
            self._redis_available = False
            return None

        was_available = self._redis_available
        self._redis_checked = True
        self._redis_available = client is not None
        if client is not None and not was_available:
            logger.info("Redis connection restored")
        elif client is None and was_available:
            logger.warning("RegistryCache: Redis unavailable, using in-memory cache")
        return client

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
            >>> result = asyncio.run(cache.get("tools", "abc123"))  # doctest: +SKIP
        """
        if not self._enabled:
            return None

        cache_key = self._get_redis_key(cache_type, filters_hash)

        # Try Redis first
        redis = await self._get_redis_client()
        if redis:
            try:
                data = await self._redis_operation_with_timeout(redis.get, cache_key, operation_name="get")
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

                await self._redis_operation_with_timeout(redis.setex, cache_key, ttl, orjson.dumps(data), operation_name="setex")
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

                async def scan_keys():
                    """Collect Redis keys matching pattern, rejecting malformed entries.

                    Returns:
                        List of bytes/str keys, or None if any entry was not a
                        bytes/str (treated as an aborted scan; peer workers
                        must not receive a publish in that case or they would
                        drop L1 while stale L2 keys remain).
                    """
                    keys = []
                    async for key in redis.scan_iter(match=pattern):
                        if not isinstance(key, (bytes, str)):
                            logger.warning("RegistryCache: invalid SCAN key type %s; aborting invalidation", type(key).__name__)
                            return None
                        keys.append(key)
                    return keys

                keys_to_delete = await self._redis_operation_with_timeout(scan_keys, operation_name="scan_iter", timeout_override=self._scan_timeout)

                # Distinguish scan failure (None) from "scan found zero keys"
                # (empty list). On failure we must NOT publish, otherwise peer
                # workers drop L1 while stale L2 keys remain in this instance.
                if keys_to_delete is None:
                    logger.warning("RegistryCache: Redis scan failed for %s; skipping delete/publish", cache_type)
                    return

                if keys_to_delete:
                    # Redis DEL is variadic — one round trip instead of N.
                    await self._redis_operation_with_timeout(redis.delete, *keys_to_delete, operation_name="delete")

                await self._redis_operation_with_timeout(redis.publish, "mcpgw:cache:invalidate", f"registry:{cache_type}", operation_name="publish")
            except Exception as e:  # pylint: disable=broad-exception-caught
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
            Dictionary with hit/miss counts and hit rate.

        WARNING:
            ``redis_circuit_open`` and ``redis_failure_count`` are admin-only
            diagnostic signals. Do NOT surface them via public ``/health`` or
            ``/metrics`` endpoints — they reveal internal Redis failure topology
            that could aid attackers probing for cache-tier weaknesses.

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
            "redis_circuit_open": self._redis_circuit_open,
            "redis_failure_count": self._redis_failure_count,
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


# Upper bound on the in-memory revoked-JTI set.
#
# Prevents unbounded memory growth if a compromised Redis channel floods
# ``revoke:`` messages.  When the cap is reached new JTIs are still
# processed (cache eviction) but are not added to the local set;
# subsequent ``is_token_revoked()`` / ``get_auth_context()`` calls will
# fall through to the Redis check on L1 cache miss, so revocation is
# still enforced.
_MAX_REVOKED_JTIS = 100_000


class CacheInvalidationSubscriber:
    """Redis pubsub subscriber for cross-worker cache invalidation.

    This class subscribes to both 'mcpgw:cache:invalidate' and
    'mcpgw:auth:invalidate' Redis channels and processes invalidation
    messages from other workers, ensuring local in-memory caches stay
    synchronized in multi-worker deployments.

    Message formats handled:
        - registry:{cache_type} - Invalidate registry cache (tools, prompts, etc.)
        - tool_lookup:{name} - Invalidate specific tool lookup
        - tool_lookup:gateway:{gateway_id} - Invalidate all tools for a gateway
        - admin:{prefix} - Invalidate admin stats cache
        - user:{email} - Invalidate auth user cache
        - revoke:{jti} - Invalidate auth revocation cache
        - team:{email} - Invalidate auth team cache
        - role:{email}:{team_id} - Invalidate auth role cache
        - team_roles:{team_id} - Invalidate all roles for a team
        - teams:{email} - Invalidate auth teams list cache
        - membership:{email} - Invalidate auth team membership cache

    Examples:
        >>> subscriber = CacheInvalidationSubscriber()
        >>> # Start listening in background task:
        >>> # await subscriber.start()
        >>> # Stop when shutting down:
        >>> # await subscriber.stop()
    """

    def __init__(self) -> None:
        """Initialize the cache invalidation subscriber."""
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._pubsub: Optional[Any] = None
        self._channels = ["mcpgw:cache:invalidate", "mcpgw:auth:invalidate"]
        self._started = False

    async def start(self) -> None:
        """Start listening for cache invalidation messages.

        This creates a background task that subscribes to the Redis
        channel and processes invalidation messages.

        Examples:
            >>> import asyncio
            >>> subscriber = CacheInvalidationSubscriber()
            >>> # asyncio.run(subscriber.start())
        """
        if self._started:
            logger.debug("CacheInvalidationSubscriber already started")
            return

        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            redis = await get_redis_client()
            if not redis:
                logger.info("CacheInvalidationSubscriber: Redis unavailable, skipping cross-worker invalidation")
                return

            self._stop_event = asyncio.Event()
            self._pubsub = redis.pubsub()
            await self._pubsub.subscribe(*self._channels)  # pyright: ignore[reportOptionalMemberAccess]

            self._task = asyncio.create_task(self._listen_loop())
            self._started = True
            logger.info("CacheInvalidationSubscriber started on channels %s", self._channels)

        except Exception as e:
            logger.warning("CacheInvalidationSubscriber failed to start: %s", e)
            # Clean up partially created pubsub to prevent leaks
            # Use timeout to prevent blocking if pubsub doesn't close cleanly
            cleanup_timeout = _get_cleanup_timeout()
            if self._pubsub is not None:
                try:
                    try:
                        await asyncio.wait_for(self._pubsub.aclose(), timeout=cleanup_timeout)
                    except AttributeError:
                        await asyncio.wait_for(self._pubsub.close(), timeout=cleanup_timeout)
                except asyncio.TimeoutError:
                    logger.debug("Pubsub cleanup timed out - proceeding anyway")
                except Exception as cleanup_err:
                    logger.debug("Error during pubsub cleanup: %s", cleanup_err)
                self._pubsub = None

    async def stop(self) -> None:
        """Stop listening for cache invalidation messages.

        This cancels the background task and cleans up resources.

        Examples:
            >>> import asyncio
            >>> subscriber = CacheInvalidationSubscriber()
            >>> # asyncio.run(subscriber.stop())
        """
        if not self._started:
            return

        self._started = False

        if self._stop_event:
            self._stop_event.set()

        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None

        if self._pubsub:
            cleanup_timeout = _get_cleanup_timeout()
            try:
                await asyncio.wait_for(self._pubsub.unsubscribe(*self._channels), timeout=cleanup_timeout)
            except asyncio.TimeoutError:
                logger.debug("Pubsub unsubscribe timed out - proceeding anyway")
            except Exception as e:
                logger.debug("Error unsubscribing from pubsub: %s", e)
            try:
                try:
                    await asyncio.wait_for(self._pubsub.aclose(), timeout=cleanup_timeout)
                except AttributeError:
                    await asyncio.wait_for(self._pubsub.close(), timeout=cleanup_timeout)
            except asyncio.TimeoutError:
                logger.debug("Pubsub close timed out - proceeding anyway")
            except Exception as e:
                logger.debug("Error closing pubsub: %s", e)
            self._pubsub = None

        logger.info("CacheInvalidationSubscriber stopped")

    async def _listen_loop(self) -> None:
        """Background loop that listens for and processes invalidation messages.

        Raises:
            asyncio.CancelledError: If the task is cancelled during shutdown.
        """
        logger.debug("CacheInvalidationSubscriber listen loop started")
        try:
            while self._started and not (self._stop_event and self._stop_event.is_set()):
                if self._pubsub is None:
                    break
                try:
                    message = await asyncio.wait_for(
                        self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                        timeout=2.0,
                    )
                    if message and message.get("type") == "message":
                        data = message.get("data")
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        channel = message.get("channel", "")
                        if isinstance(channel, bytes):
                            channel = channel.decode("utf-8")
                        if data:
                            await self._process_invalidation(data, channel=channel)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.debug("CacheInvalidationSubscriber message error: %s", e)
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.debug("CacheInvalidationSubscriber listen loop cancelled")
            raise
        finally:
            logger.debug("CacheInvalidationSubscriber listen loop exited")

    _AUTH_PREFIXES = ("user:", "revoke:", "team_roles:", "teams:", "team:", "role:", "membership:")
    """Message prefixes that belong exclusively to the auth invalidation channel."""

    async def _process_invalidation(self, message: str, *, channel: str = "") -> None:  # pylint: disable=too-many-branches
        """Process a cache invalidation message.

        Args:
            message: The invalidation message in format 'type:identifier'
            channel: The Redis pubsub channel the message arrived on.
                     Used to enforce that auth-prefixed messages are only
                     accepted from ``mcpgw:auth:invalidate``.
        """
        logger.debug("CacheInvalidationSubscriber received on %s: %s", channel, message)

        # pylint: disable=protected-access
        # pyright: ignore[reportPrivateUsage]
        # We intentionally access protected members to clear local in-memory caches
        # without triggering another round of Redis pubsub invalidation messages
        try:
            if message.startswith("registry:"):
                # Handle registry cache invalidation (tools, prompts, resources, etc.)
                cache_type = message[len("registry:") :]
                cache = get_registry_cache()
                # Only clear local in-memory cache to avoid infinite loops
                prefix = cache._get_redis_key(cache_type)  # pyright: ignore[reportPrivateUsage]
                with cache._lock:  # pyright: ignore[reportPrivateUsage]
                    keys_to_remove = [k for k in cache._cache if k.startswith(prefix)]  # pyright: ignore[reportPrivateUsage]
                    for key in keys_to_remove:
                        cache._cache.pop(key, None)  # pyright: ignore[reportPrivateUsage]
                logger.debug("CacheInvalidationSubscriber: Cleared local registry:%s cache (%d keys)", cache_type, len(keys_to_remove))

            elif message.startswith("tool_lookup:gateway:"):
                # Handle gateway-wide tool lookup invalidation
                gateway_id = message[len("tool_lookup:gateway:") :]
                # First-Party
                from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache  # pylint: disable=import-outside-toplevel

                # Only clear local L1 cache
                with tool_lookup_cache._lock:  # pyright: ignore[reportPrivateUsage]
                    to_remove = [name for name, entry in tool_lookup_cache._cache.items() if entry.value.get("tool", {}).get("gateway_id") == gateway_id]  # pyright: ignore[reportPrivateUsage]
                    for name in to_remove:
                        tool_lookup_cache._cache.pop(name, None)  # pyright: ignore[reportPrivateUsage]
                logger.debug("CacheInvalidationSubscriber: Cleared local tool_lookup for gateway %s (%d keys)", gateway_id, len(to_remove))

            elif message.startswith("tool_lookup:"):
                # Handle specific tool lookup invalidation
                tool_name = message[len("tool_lookup:") :]
                # First-Party
                from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache  # pylint: disable=import-outside-toplevel

                # Only clear local L1 cache
                with tool_lookup_cache._lock:  # pyright: ignore[reportPrivateUsage]
                    tool_lookup_cache._cache.pop(tool_name, None)  # pyright: ignore[reportPrivateUsage]
                logger.debug("CacheInvalidationSubscriber: Cleared local tool_lookup:%s", tool_name)

            elif message.startswith("admin:"):
                # Handle admin stats cache invalidation
                prefix = message[len("admin:") :]
                # First-Party
                from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

                # Only clear local in-memory cache
                full_prefix = admin_stats_cache._get_redis_key(prefix)  # pyright: ignore[reportPrivateUsage]
                with admin_stats_cache._lock:  # pyright: ignore[reportPrivateUsage]
                    keys_to_remove = [k for k in admin_stats_cache._cache if k.startswith(full_prefix)]  # pyright: ignore[reportPrivateUsage]
                    for key in keys_to_remove:
                        admin_stats_cache._cache.pop(key, None)  # pyright: ignore[reportPrivateUsage]
                logger.debug("CacheInvalidationSubscriber: Cleared local admin:%s cache (%d keys)", prefix, len(keys_to_remove))

            elif message.startswith(self._AUTH_PREFIXES):
                if channel != "mcpgw:auth:invalidate":
                    logger.warning("CacheInvalidationSubscriber: Ignoring auth message on wrong channel %s: %s", channel, message)
                else:
                    self._process_auth_invalidation(message)

            else:
                logger.debug("CacheInvalidationSubscriber: Unknown message format: %s", message)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("CacheInvalidationSubscriber: Error processing '%s': %s", message, e)

    @staticmethod
    def _evict_keys(cache_dict: dict, predicate: "Callable[[str], bool]") -> int:
        """Remove all keys from *cache_dict* that satisfy *predicate*.

        Must be called while holding the owning cache's ``_lock``.

        Args:
            cache_dict: The dictionary to evict keys from.
            predicate: A callable that returns True for keys to remove.

        Returns:
            Number of keys removed.
        """
        keys = [k for k in cache_dict if predicate(k)]
        for k in keys:
            cache_dict.pop(k, None)
        return len(keys)

    def _process_auth_invalidation(self, message: str) -> None:  # pylint: disable=too-many-branches
        """Dispatch an auth-channel invalidation message to the local auth cache.

        Called from :meth:`_process_invalidation` for messages received on
        ``mcpgw:auth:invalidate``.

        Args:
            message: The invalidation message (e.g. ``user:alice@test.com``).
        """
        # pylint: disable=protected-access
        # First-Party
        from mcpgateway.cache.auth_cache import auth_cache  # pylint: disable=import-outside-toplevel

        # Dispatch auth message to the correct handler
        if message.startswith("user:"):
            email = message[len("user:") :]
            with auth_cache._lock:  # pyright: ignore[reportPrivateUsage]
                self._evict_keys(auth_cache._context_cache, lambda k: k.startswith(f"{email}:"))  # pyright: ignore[reportPrivateUsage]
                auth_cache._user_cache.pop(email, None)  # pyright: ignore[reportPrivateUsage]
                self._evict_keys(auth_cache._team_cache, lambda k: k.startswith(f"{email}:"))  # pyright: ignore[reportPrivateUsage]
            logger.debug("CacheInvalidationSubscriber: Cleared local auth user cache for %s", email)

        elif message.startswith("revoke:"):
            jti = message[len("revoke:") :]
            with auth_cache._lock:  # pyright: ignore[reportPrivateUsage]
                if len(auth_cache._revoked_jtis) < _MAX_REVOKED_JTIS:  # pyright: ignore[reportPrivateUsage]
                    auth_cache._revoked_jtis.add(jti)  # pyright: ignore[reportPrivateUsage]
                else:
                    logger.warning("CacheInvalidationSubscriber: _revoked_jtis at cap (%d), skipping add for jti=%s", _MAX_REVOKED_JTIS, jti[:8])
                auth_cache._revocation_cache.pop(jti, None)  # pyright: ignore[reportPrivateUsage]
                self._evict_keys(auth_cache._context_cache, lambda k: k.endswith(f":{jti}"))  # pyright: ignore[reportPrivateUsage]
            logger.debug("CacheInvalidationSubscriber: Cleared local auth revocation cache for jti=%s", jti[:8])

        elif message.startswith("team_roles:"):
            team_id = message[len("team_roles:") :]
            with auth_cache._lock:  # pyright: ignore[reportPrivateUsage]
                self._evict_keys(auth_cache._role_cache, lambda k: k.endswith(f":{team_id}"))  # pyright: ignore[reportPrivateUsage]
            logger.debug("CacheInvalidationSubscriber: Cleared local auth team_roles cache for team %s", team_id)

        elif message.startswith("teams:"):
            email = message[len("teams:") :]
            with auth_cache._lock:  # pyright: ignore[reportPrivateUsage]
                self._evict_keys(auth_cache._teams_list_cache, lambda k: k.startswith(f"{email}:"))  # pyright: ignore[reportPrivateUsage]
            logger.debug("CacheInvalidationSubscriber: Cleared local auth teams list cache for %s", email)

        elif message.startswith("team:"):
            email = message[len("team:") :]
            with auth_cache._lock:  # pyright: ignore[reportPrivateUsage]
                auth_cache._team_cache.pop(email, None)  # pyright: ignore[reportPrivateUsage]
                self._evict_keys(auth_cache._context_cache, lambda k: k.startswith(f"{email}:"))  # pyright: ignore[reportPrivateUsage]
            logger.debug("CacheInvalidationSubscriber: Cleared local auth team cache for %s", email)

        elif message.startswith("role:"):
            cache_key = message[len("role:") :]
            with auth_cache._lock:  # pyright: ignore[reportPrivateUsage]
                auth_cache._role_cache.pop(cache_key, None)  # pyright: ignore[reportPrivateUsage]
            logger.debug("CacheInvalidationSubscriber: Cleared local auth role cache for %s", cache_key)

        elif message.startswith("membership:"):
            user_email = message[len("membership:") :]
            with auth_cache._lock:  # pyright: ignore[reportPrivateUsage]
                self._evict_keys(auth_cache._team_cache, lambda k: k.startswith(f"{user_email}:"))  # pyright: ignore[reportPrivateUsage]
            logger.debug("CacheInvalidationSubscriber: Cleared local auth membership cache for %s", user_email)


# Global singleton for cache invalidation subscriber
_cache_invalidation_subscriber: Optional[CacheInvalidationSubscriber] = None


def get_cache_invalidation_subscriber() -> CacheInvalidationSubscriber:
    """Get or create the singleton CacheInvalidationSubscriber instance.

    Returns:
        CacheInvalidationSubscriber: The singleton instance

    Examples:
        >>> subscriber = get_cache_invalidation_subscriber()
        >>> isinstance(subscriber, CacheInvalidationSubscriber)
        True
    """
    global _cache_invalidation_subscriber  # pylint: disable=global-statement
    if _cache_invalidation_subscriber is None:
        _cache_invalidation_subscriber = CacheInvalidationSubscriber()
    return _cache_invalidation_subscriber
