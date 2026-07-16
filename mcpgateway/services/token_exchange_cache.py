# -*- coding: utf-8 -*-
# mcpgateway/services/token_exchange_cache.py
"""Location: ./mcpgateway/services/token_exchange_cache.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

Cache for RFC 8693 exchanged tokens: Redis with in-memory TTL fallback.
"""

# Standard
import asyncio
from collections import OrderedDict
import hashlib
import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class TokenExchangeCache:
    """Stores exchanged tokens keyed by gateway+user+audience with TTL.

    Uses Redis when ``redis_url`` is provided and reachable; otherwise an
    in-process bounded LRU dict.

    Performance:
      * P3 — a cache hit is a single Redis ``GET``: the serve-until deadline is
        embedded in the stored value (``"<serve_until>:<token>"``), so no
        separate ``TTL`` round-trip is needed.
      * P2 — the skew window is clamped to half the token lifetime, so
        short-lived tokens (``expires_in`` < ``skew``) are still served for
        ~half their life instead of being instantly uncacheable.
      * P4 — ``set_failure``/``is_failed`` provide a short negative cache so an
        IdP outage does not trigger a retry storm.
      * P1 — ``lock()`` returns a per-key ``asyncio.Lock`` for single-flight
        exchange (per process; a distributed lock is Phase 2).

    SECURITY (M1): cached values are bearer tokens, stored under a dedicated
    ``token_exchange:`` namespace with TTL. Deployments that do not fully trust
    Redis should treat this cache as in-boundary or enable at-rest encryption
    (Phase 2). Never log a cached value.
    """

    def __init__(self, redis_url: Optional[str] = None, skew_seconds: int = 300, max_entries: int = 10000, redis_breaker_threshold: int = 3, redis_breaker_cooldown: int = 30) -> None:
        """Initialize the cache.

        Args:
            redis_url: Redis connection URL, or ``None`` to use the in-memory backend only.
            skew_seconds: Seconds before hard expiry to stop serving a cached token.
            max_entries: Maximum number of entries kept in any in-memory store (LRU eviction).
            redis_breaker_threshold: Consecutive Redis errors before the breaker opens.
            redis_breaker_cooldown: Seconds Redis stays disabled once the breaker opens.
        """
        self._skew = skew_seconds
        self._max_entries = max_entries
        self._mem: "OrderedDict[str, Tuple[str, float]]" = OrderedDict()  # key -> (token, serve_until_epoch)
        self._neg: "OrderedDict[str, float]" = OrderedDict()  # key -> neg_until_epoch
        self._locks: "OrderedDict[str, asyncio.Lock]" = OrderedDict()  # key -> asyncio.Lock (single-flight)
        self._redis = None
        # L5 circuit breaker: after N consecutive Redis errors, stop calling Redis for a
        # cooldown and log ONCE — avoids a per-request WARNING flood during a Redis outage.
        self._redis_breaker_threshold = redis_breaker_threshold
        self._redis_breaker_cooldown = redis_breaker_cooldown
        self._redis_fail_count = 0
        self._redis_disabled_until = 0.0
        if redis_url:
            try:
                # Third-Party
                import redis.asyncio as aioredis  # pylint: disable=import-outside-toplevel

                # health_check_interval + a bounded pool avoid stale conns / exhaustion under load (P6).
                self._redis = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True, health_check_interval=30, max_connections=50)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("TokenExchangeCache: Redis unavailable, using memory fallback: %s", e)
                self._redis = None

    @staticmethod
    def _key(gateway_id: str, user_email: str, audience: str) -> str:
        """Build the namespaced cache key for a gateway/user/audience tuple.

        Each component is hashed independently (rather than joined with a bare
        ``:``) before being combined, so no attacker-controlled value (e.g. a
        ``target_audience`` containing ``:``) can shift the component boundary
        and collide with a different {gateway, user, audience} tuple — a hex
        digest never contains the join delimiter, so the combination is
        unambiguous by construction.

        Args:
            gateway_id: Identifier of the target gateway.
            user_email: Email of the user the token was exchanged on behalf of.
            audience: Target audience of the exchanged token.

        Returns:
            A namespaced cache key string.
        """
        parts = (gateway_id or "", user_email or "", audience or "")
        hashed = ":".join(hashlib.sha256(part.encode("utf-8")).hexdigest() for part in parts)
        return f"token_exchange:{hashed}"

    def _redis_live(self) -> bool:
        """Return True if Redis should be used (configured and breaker not open). L5.

        Returns:
            True if Redis is configured and the circuit breaker is not currently open.
        """
        if self._redis is None:
            return False
        if self._redis_disabled_until and time.time() < self._redis_disabled_until:
            return False
        return True

    def _note_redis_ok(self) -> None:
        """Reset the circuit breaker failure count after a successful Redis call."""
        self._redis_fail_count = 0
        self._redis_disabled_until = 0.0

    def _note_redis_failure(self, op: str, e: Exception) -> None:
        """Count a Redis error; open the breaker and log ONCE at the threshold (L5).

        Args:
            op: Name of the Redis operation that failed (for logging).
            e: The exception raised by the Redis client.
        """
        self._redis_fail_count += 1
        if self._redis_fail_count == self._redis_breaker_threshold:
            self._redis_disabled_until = time.time() + self._redis_breaker_cooldown
            logger.warning(
                "TokenExchangeCache: Redis disabled for %ss after %d consecutive errors (last op=%s): %s",
                self._redis_breaker_cooldown,
                self._redis_fail_count,
                op,
                e,
            )
        else:
            logger.debug("TokenExchangeCache redis %s failed (%d): %s", op, self._redis_fail_count, e)

    def _serve_window(self, expires_in: int) -> int:
        """Return seconds the token may be served, clamping skew to half lifetime (P2).

        Args:
            expires_in: Token lifetime in seconds as returned by the token endpoint.

        Returns:
            The number of seconds the cached token may be served before being treated as a miss.
        """
        effective_skew = min(self._skew, max(0, expires_in // 2))
        return max(int(expires_in) - effective_skew, 1)

    def lock(self, gateway_id: str, user_email: str, audience: str) -> "asyncio.Lock":
        """Return the single-flight lock for this key, creating it on first use.

        The lock registry is bounded (G7): an unbounded dict of locks is the same
        memory-pressure DoS class as the token map. Idle (unlocked) locks are
        evicted oldest-first once capacity is exceeded; a held lock is skipped so
        an in-flight exchange is never disturbed.

        Args:
            gateway_id: Identifier of the target gateway.
            user_email: Email of the user the token was exchanged on behalf of.
            audience: Target audience of the exchanged token.

        Returns:
            The ``asyncio.Lock`` instance associated with this key.
        """
        key = self._key(gateway_id, user_email, audience)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
        self._locks[key] = lock
        self._locks.move_to_end(key)
        if len(self._locks) > self._max_entries:
            for k in list(self._locks):
                if k == key:
                    continue
                if not self._locks[k].locked():
                    del self._locks[k]
                if len(self._locks) <= self._max_entries:
                    break
        return lock

    async def get(self, gateway_id: str, user_email: str, audience: str) -> Optional[str]:
        """Return a cached token if present and still inside its serve window.

        Args:
            gateway_id: Identifier of the target gateway.
            user_email: Email of the user the token was exchanged on behalf of.
            audience: Target audience of the exchanged token.

        Returns:
            The cached token string, or ``None`` on a miss, expiry, or malformed entry.
        """
        key = self._key(gateway_id, user_email, audience)
        if self._redis_live():
            assert self._redis is not None  # nosec B101 (type-narrowing only)
            try:
                raw = await self._redis.get(key)  # single round-trip (P3)
                self._note_redis_ok()
            except Exception as e:  # pragma: no cover
                self._note_redis_failure("get", e)  # L5; fall through to memory
            else:
                raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if raw_str and ":" in raw_str:
                    try:  # G10: malformed value -> miss, not a Redis failure
                        serve_until_s, token = raw_str.split(":", 1)
                        return token if float(serve_until_s) > time.time() else None
                    except ValueError:
                        return None
                return None
        entry = self._mem.get(key)
        if not entry:
            return None
        token, serve_until = entry
        if serve_until <= time.time():
            self._mem.pop(key, None)
            return None
        return token

    async def set(self, gateway_id: str, user_email: str, audience: str, token: str, expires_in: int) -> None:
        """Cache an exchanged token. Hard TTL is ``expires_in``; serve window clamps skew.

        Args:
            gateway_id: Identifier of the target gateway.
            user_email: Email of the user the token was exchanged on behalf of.
            audience: Target audience of the exchanged token.
            token: The exchanged access token to cache.
            expires_in: Token lifetime in seconds as returned by the token endpoint.
        """
        key = self._key(gateway_id, user_email, audience)
        serve_window = self._serve_window(expires_in)
        serve_until = time.time() + serve_window
        if self._redis_live():
            assert self._redis is not None  # nosec B101 (type-narrowing only)
            try:
                await self._redis.set(key, f"{serve_until}:{token}", ex=max(int(expires_in), 1))
                self._note_redis_ok()
                return
            except Exception as e:  # pragma: no cover
                self._note_redis_failure("set", e)  # L5; fall through to memory
        # Bounded LRU (M2): refresh recency, then evict oldest over capacity.
        self._mem[key] = (token, serve_until)
        self._mem.move_to_end(key)
        while len(self._mem) > self._max_entries:
            self._mem.popitem(last=False)

    async def invalidate(self, gateway_id: str, user_email: str, audience: str) -> None:
        """Remove a cached token, e.g. after an upstream 401.

        Args:
            gateway_id: Identifier of the target gateway.
            user_email: Email of the user the token was exchanged on behalf of.
            audience: Target audience of the exchanged token.
        """
        key = self._key(gateway_id, user_email, audience)
        if self._redis_live():
            assert self._redis is not None  # nosec B101 (type-narrowing only)
            try:
                await self._redis.delete(key)
                self._note_redis_ok()
            except Exception as e:  # pragma: no cover
                self._note_redis_failure("delete", e)  # L5
        self._mem.pop(key, None)

    async def is_failed(self, gateway_id: str, user_email: str, audience: str) -> bool:
        """Return True if a recent exchange failure is within its negative-cache TTL (P4).

        Args:
            gateway_id: Identifier of the target gateway.
            user_email: Email of the user the token was exchanged on behalf of.
            audience: Target audience of the exchanged token.

        Returns:
            True if a failure was recorded recently and the negative-cache TTL has not lapsed.
        """
        key = self._key(gateway_id, user_email, audience) + ":neg"
        if self._redis_live():
            assert self._redis is not None  # nosec B101 (type-narrowing only)
            try:
                result = await self._redis.get(key) is not None
                self._note_redis_ok()
                return result
            except Exception as e:  # pragma: no cover
                self._note_redis_failure("neg-get", e)  # L5; fall through to memory
        neg_until = self._neg.get(key)
        if neg_until is None:
            return False
        if neg_until <= time.time():
            self._neg.pop(key, None)
            return False
        return True

    async def set_failure(self, gateway_id: str, user_email: str, audience: str, ttl: int = 10) -> None:
        """Record a short-lived exchange failure to short-circuit a retry storm (P4).

        Args:
            gateway_id: Identifier of the target gateway.
            user_email: Email of the user the token was exchanged on behalf of.
            audience: Target audience of the exchanged token.
            ttl: Seconds the failure should be remembered.
        """
        key = self._key(gateway_id, user_email, audience) + ":neg"
        if self._redis_live():
            assert self._redis is not None  # nosec B101 (type-narrowing only)
            try:
                await self._redis.set(key, "1", ex=max(int(ttl), 1))
                self._note_redis_ok()
                return
            except Exception as e:  # pragma: no cover
                self._note_redis_failure("neg-set", e)  # L5; fall through to memory
        self._neg[key] = time.time() + ttl
        while len(self._neg) > self._max_entries:
            self._neg.popitem(last=False)
