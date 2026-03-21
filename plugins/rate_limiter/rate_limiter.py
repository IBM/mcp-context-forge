# -*- coding: utf-8 -*-
"""Location: ./plugins/rate_limiter/rate_limiter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Rate Limiter Plugin.
Enforces rate limits by user, tenant, and/or tool using a pluggable algorithm:
  - fixed_window  : simple counter per time bucket (default)
  - sliding_window: rolling timestamp log, prevents burst at window boundary
  - token_bucket  : token refill model, allows short controlled bursts

All three algorithms support both memory and Redis backends with identical
semantics. The Redis backend uses atomic Lua scripts for each algorithm —
one round-trip per check with no race conditions.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALGORITHM_FIXED_WINDOW = "fixed_window"
ALGORITHM_SLIDING_WINDOW = "sliding_window"
ALGORITHM_TOKEN_BUCKET = "token_bucket"
VALID_ALGORITHMS = (ALGORITHM_FIXED_WINDOW, ALGORITHM_SLIDING_WINDOW, ALGORITHM_TOKEN_BUCKET)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_rate(rate: str) -> tuple[int, int]:
    """Parse rate like '60/m', '10/s', '100/h' -> (count, window_seconds).

    Args:
        rate: Rate string in format 'count/unit' (e.g., '60/m', '10/s', '100/h').

    Returns:
        Tuple of (count, window_seconds) for the rate limit.

    Raises:
        ValueError: If the rate string is malformed or the unit is not supported.
    """
    try:
        count_str, per = rate.split("/", maxsplit=1)
        count = int(count_str)
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid rate string {rate!r}: expected '<count>/<unit>' e.g. '60/m'")
    per = per.strip().lower()
    if per in ("s", "sec", "second"):
        return count, 1
    if per in ("m", "min", "minute"):
        return count, 60
    if per in ("h", "hr", "hour"):
        return count, 3600
    raise ValueError(f"Invalid rate string {rate!r}: unsupported unit {per!r}, expected s/m/h")


def _make_headers(limit: int, remaining: int, reset_timestamp: int, retry_after: int, include_retry_after: bool = True) -> dict[str, str]:
    """Create RFC-compliant rate limit headers.

    Args:
        limit: The rate limit count.
        remaining: Number of requests remaining in the current window.
        reset_timestamp: Unix timestamp when the window resets.
        retry_after: Seconds until the window resets (for Retry-After header).
        include_retry_after: Whether to include Retry-After header (only for violations).

    Returns:
        Dictionary of HTTP headers for rate limiting.
    """
    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_timestamp),
    }
    if include_retry_after:
        headers["Retry-After"] = str(retry_after)
    return headers


def _extract_user_identity(user: Any) -> str:
    """Return a stable, normalised string identity from a user context value.

    Handles three cases:
    - dict (production JWT context): extract ``email`` → ``id`` → ``sub`` fallback
    - string: strip whitespace; empty/whitespace-only falls back to 'anonymous'
    - None / falsy: 'anonymous'
    """
    if isinstance(user, dict):
        identity = user.get("email") or user.get("id") or user.get("sub") or ""
        identity = str(identity).strip()
    elif user is None:
        identity = ""
    else:
        identity = str(user).strip()
    return identity if identity else "anonymous"


def _select_most_restrictive(
    results: list[tuple[bool, int, int, dict[str, Any]]]
) -> tuple[bool, int, int, int, dict[str, Any]]:
    """Select the most restrictive rate limit from multiple dimensions.

    Args:
        results: List of (allowed, limit, reset_timestamp, metadata) tuples.

    Returns:
        Tuple of (allowed, limit, remaining, reset_timestamp, metadata).
    """
    limited_results = [(allowed, limit, reset_ts, meta) for allowed, limit, reset_ts, meta in results if limit > 0]

    if not limited_results:
        return True, 0, 0, 0, {"limited": False}

    violated = [(allowed, limit, reset_ts, meta) for allowed, limit, reset_ts, meta in limited_results if not allowed]
    allowed_dims = [(allowed, limit, reset_ts, meta) for allowed, limit, reset_ts, meta in limited_results if allowed]

    if violated:
        # Pick the violated dimension that will unblock soonest — its reset_in is the
        # Retry-After value the client should use to know when to retry.
        soonest_reset = min(violated, key=lambda x: x[3].get("reset_in", float("inf")))
        _, limit, reset_ts, meta = soonest_reset
        remaining = meta.get("remaining", 0)
        retry_after = meta.get("reset_in", 0)
        aggregated_meta = {
            "limited": True,
            "remaining": remaining,
            "reset_in": retry_after,
            "dimensions": {
                "violated": [m for _, _, _, m in violated],
                "allowed": [m for _, _, _, m in allowed_dims],
            },
        }
        return False, limit, remaining, reset_ts, aggregated_meta

    # All dimensions are within limit — surface the tightest one (fewest remaining
    # requests) so headers reflect the dimension the caller is closest to exhausting.
    tightest = min(allowed_dims, key=lambda x: x[3].get("remaining", float("inf")))
    _, limit, reset_ts, meta = tightest
    remaining = meta.get("remaining", 0)
    retry_after = meta.get("reset_in", 0)
    aggregated_meta = {
        "limited": True,
        "remaining": remaining,
        "reset_in": retry_after,
        "dimensions": {"allowed": [m for _, _, _, m in allowed_dims]},
    }
    return True, limit, remaining, reset_ts, aggregated_meta


# ---------------------------------------------------------------------------
# Algorithm strategies — each owns its own store and counting logic
# ---------------------------------------------------------------------------


@dataclass
class _Window:
    """Fixed window state: when the window started and how many requests so far."""

    window_start: int
    count: int


@dataclass
class _Bucket:
    """Token bucket state: current token count and when tokens were last refilled."""

    tokens: float
    last_refill: float


class FixedWindowAlgorithm:
    """Fixed-window counter.

    Time is divided into fixed slots of `window_seconds`. A counter resets at
    each slot boundary. Simple and cheap — O(1) memory per key — but allows
    up to 2× the limit when requests straddle a window boundary.
    """

    def __init__(self) -> None:
        """Initialise with an empty window store."""
        self._store: Dict[str, _Window] = {}

    async def allow(self, lock: asyncio.Lock, key: str, count: int, window: int) -> Tuple[bool, int, int, Dict[str, Any]]:
        """Check and increment the fixed-window counter for *key*."""
        now = int(time.time())
        win_key = f"{key}:{window}"

        async with lock:
            wnd = self._store.get(win_key)

            if not wnd or now - wnd.window_start >= window:
                reset_timestamp = now + window
                self._store[win_key] = _Window(window_start=now, count=1)
                return True, count, reset_timestamp, {"limited": True, "remaining": count - 1, "reset_in": window}

            reset_timestamp = wnd.window_start + window
            reset_in = window - (now - wnd.window_start)

            if wnd.count < count:
                wnd.count += 1
                return True, count, reset_timestamp, {"limited": True, "remaining": count - wnd.count, "reset_in": reset_in}

            return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": reset_in}

    async def sweep(self, lock: asyncio.Lock) -> None:
        """Evict all fixed windows whose duration has elapsed."""
        now = int(time.time())
        async with lock:
            expired = [k for k, w in self._store.items() if now - w.window_start >= int(k.rsplit(":", 1)[-1])]
            for k in expired:
                del self._store[k]


class SlidingWindowAlgorithm:
    """Sliding-window log.

    Stores a list of request timestamps per key. On each request, timestamps
    older than `window_seconds` are dropped and the remaining count is checked
    against the limit. Prevents burst at window boundaries at the cost of
    O(requests-in-window) memory per key.
    """

    def __init__(self) -> None:
        """Initialise with an empty timestamp store."""
        self._store: Dict[str, List[float]] = {}

    async def allow(self, lock: asyncio.Lock, key: str, count: int, window: int) -> Tuple[bool, int, int, Dict[str, Any]]:
        """Check the sliding-window log for *key* and record the request if allowed."""
        now = time.time()
        cutoff = now - window

        async with lock:
            timestamps = self._store.get(key, [])
            # Drop timestamps outside the current window
            timestamps = [t for t in timestamps if t > cutoff]

            current = len(timestamps)
            reset_timestamp = int(timestamps[0] + window) if timestamps else int(now + window)
            reset_in = max(0, int(reset_timestamp - now))

            if current >= count:
                self._store[key] = timestamps
                return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": reset_in}

            timestamps.append(now)
            self._store[key] = timestamps
            remaining = count - len(timestamps)
            return True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": reset_in}

    async def sweep(self, lock: asyncio.Lock) -> None:
        """Evict keys whose timestamp list is empty (no recent requests)."""
        async with lock:
            # We don't know window per key here — just remove empty lists
            # (full eviction happens naturally as timestamps age out on next allow())
            empty = [k for k, ts in self._store.items() if not ts]
            for k in empty:
                del self._store[k]


class TokenBucketAlgorithm:
    """Token bucket.

    Each key starts with `count` tokens. Tokens refill at a steady rate of
    `count / window_seconds` per second. Each request consumes one token.
    If no token is available the request is blocked.

    Allows short controlled bursts (up to `count` tokens at once) while
    enforcing the average rate over time. O(1) memory per key.
    """

    def __init__(self) -> None:
        """Initialise with an empty bucket store."""
        self._store: Dict[str, _Bucket] = {}

    async def allow(self, lock: asyncio.Lock, key: str, count: int, window: int) -> Tuple[bool, int, int, Dict[str, Any]]:
        """Consume one token from *key*'s bucket, refilling proportionally to elapsed time."""
        now = time.time()
        refill_rate = count / window  # tokens per second

        async with lock:
            bucket = self._store.get(key)

            if bucket is None:
                # First request — start with a full bucket minus this request
                self._store[key] = _Bucket(tokens=count - 1, last_refill=now)
                time_to_full = window
                reset_timestamp = int(now + time_to_full)
                return True, count, reset_timestamp, {"limited": True, "remaining": count - 1, "reset_in": time_to_full}

            # Refill tokens based on elapsed time
            elapsed = now - bucket.last_refill
            bucket.tokens = min(count, bucket.tokens + elapsed * refill_rate)
            bucket.last_refill = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                remaining = int(bucket.tokens)
                # Time until bucket would be full again
                tokens_needed = count - bucket.tokens
                time_to_full = int(tokens_needed / refill_rate)
                reset_timestamp = int(now + time_to_full)
                return True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": time_to_full}

            # No tokens — calculate when next token arrives
            time_to_next = int((1.0 - bucket.tokens) / refill_rate) + 1
            reset_timestamp = int(now + time_to_next)
            return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": time_to_next}

    async def sweep(self, lock: asyncio.Lock) -> None:
        """Evict buckets that are full (no active limiting)."""
        async with lock:
            now = time.time()
            full = []
            for k, bucket in self._store.items():
                elapsed = now - bucket.last_refill
                if elapsed > 3600:  # inactive for over an hour
                    full.append(k)
            for k in full:
                del self._store[k]


def _make_algorithm(name: str) -> FixedWindowAlgorithm | SlidingWindowAlgorithm | TokenBucketAlgorithm:
    """Instantiate the named algorithm strategy."""
    if name == ALGORITHM_SLIDING_WINDOW:
        return SlidingWindowAlgorithm()
    if name == ALGORITHM_TOKEN_BUCKET:
        return TokenBucketAlgorithm()
    return FixedWindowAlgorithm()


# ---------------------------------------------------------------------------
# Backends — own the lock, sweep scheduler, and external connection
# ---------------------------------------------------------------------------


class MemoryBackend:
    """In-process rate limit backend.

    Owns the asyncio.Lock and background sweep scheduler. Delegates all
    counting logic to the injected Algorithm strategy.

    Attributes:
        _algorithm: The counting strategy (fixed_window, sliding_window, token_bucket).
        _lock: asyncio.Lock serialising reads and writes to the algorithm's store.
        _sweep_interval: Seconds between background eviction sweeps.
        _sweep_task: Running asyncio.Task for the background sweep loop.
    """

    def __init__(self, algorithm: FixedWindowAlgorithm | SlidingWindowAlgorithm | TokenBucketAlgorithm, sweep_interval: float = 0.5) -> None:
        """Initialise the backend with the given algorithm and sweep interval."""
        self._algorithm = algorithm
        self._lock = asyncio.Lock()
        self._sweep_interval = sweep_interval
        self._sweep_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    def _ensure_sweep_task(self) -> None:
        """Start the background sweep task if it is not already running."""
        if self._sweep_task is None or self._sweep_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._sweep_task = loop.create_task(self._sweep_loop())
            except RuntimeError:
                pass

    async def _sweep_loop(self) -> None:
        """Periodically invoke the algorithm's sweep to evict expired entries."""
        while True:
            await asyncio.sleep(self._sweep_interval)
            await self._algorithm.sweep(self._lock)

    async def allow(self, key: str, limit: Optional[str]) -> tuple[bool, int, int, dict[str, Any]]:
        """Check the rate limit for *key* against *limit* using the in-process algorithm."""
        self._ensure_sweep_task()
        if not limit:
            return True, 0, 0, {"limited": False}
        count, window = _parse_rate(limit)
        return await self._algorithm.allow(self._lock, key, count, window)


class RedisBackend:
    """Shared rate limit backend backed by Redis.

    Supports all three algorithms via atomic Lua scripts — one round-trip per
    check with no race conditions.

    Attributes:
        _url: Redis connection URL.
        _prefix: Key namespace prefix.
        _algorithm_name: Which algorithm to use.
        _fallback: Optional MemoryBackend used when Redis is unavailable.
    """

    # Fixed window: atomic INCR + EXPIRE. Returns [count, ttl].
    _LUA_FIXED = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""

    # Sliding window: remove expired entries, check count, ZADD only if allowed.
    # ARGV: [now_float, window_seconds, limit_int, unique_member]
    # Returns [allowed_int, current_count, oldest_timestamp_or_0].
    # Fix: check count before ZADD (blocked requests must not inflate the set).
    # Fix: use a unique member (ARGV[4]) so simultaneous requests with identical
    #      timestamps do not collapse into a single sorted-set entry.
    _LUA_SLIDING = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now - window
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
local count = tonumber(redis.call('ZCARD', KEYS[1]))
redis.call('EXPIRE', KEYS[1], window + 1)
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
local oldest_ts = 0
if #oldest > 0 then oldest_ts = tonumber(oldest[2]) end
if count >= limit then
    return {0, count, oldest_ts}
end
redis.call('ZADD', KEYS[1], now, member)
count = count + 1
oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
oldest_ts = 0
if #oldest > 0 then oldest_ts = tonumber(oldest[2]) end
return {1, count, oldest_ts}
"""

    # Token bucket: HMGET {tokens, last_refill}, refill proportionally, consume 1.
    # ARGV: [capacity, refill_rate_per_sec, now_as_float]
    # Returns [allowed_int, remaining_floor, time_to_next_token_seconds].
    _LUA_TOKEN_BUCKET = """
local data = redis.call('HMGET', KEYS[1], 'tokens', 'last_refill')
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])
local now      = tonumber(ARGV[3])

local tokens      = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    tokens = capacity - 1
    redis.call('HSET', KEYS[1], 'tokens', tokens, 'last_refill', now)
    local ttl = math.ceil(capacity / rate) + 1
    redis.call('EXPIRE', KEYS[1], ttl)
    return {1, math.floor(tokens), 0}
end

local elapsed = now - last_refill
tokens = math.min(capacity, tokens + elapsed * rate)

local allowed
local time_to_next = 0
if tokens >= 1.0 then
    tokens  = tokens - 1.0
    allowed = 1
else
    allowed      = 0
    time_to_next = math.ceil((1.0 - tokens) / rate)
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'last_refill', now)
local ttl = math.ceil((capacity - tokens) / rate) + 1
redis.call('EXPIRE', KEYS[1], ttl)

return {allowed, math.floor(tokens), time_to_next}
"""

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "rl",
        algorithm_name: str = ALGORITHM_FIXED_WINDOW,
        fallback: Optional[MemoryBackend] = None,
        _client: Any = None,
    ) -> None:
        """Initialise the Redis backend with connection URL, key prefix, algorithm, and optional fallback."""
        self._url = redis_url
        self._prefix = key_prefix
        self._algorithm_name = algorithm_name
        self._fallback = fallback
        self._client = _client
        self._real_client: Any = None

    async def _get_client(self) -> Any:
        """Return the Redis client, lazily initialising a real connection if needed."""
        if self._client is not None:
            return self._client
        if self._real_client is None:
            import redis.asyncio as aioredis  # noqa: PLC0415
            self._real_client = aioredis.from_url(self._url, decode_responses=False)
        return self._real_client

    async def allow(self, key: str, limit: Optional[str]) -> tuple[bool, int, int, dict[str, Any]]:
        """Check the rate limit for *key* against *limit* using an atomic Redis Lua script."""
        if not limit:
            return True, 0, 0, {"limited": False}

        count, window_seconds = _parse_rate(limit)
        redis_key = f"{self._prefix}:{key}:{window_seconds}"

        try:
            client = await self._get_client()

            if self._algorithm_name == ALGORITHM_SLIDING_WINDOW:
                return await self._allow_sliding(client, redis_key, count, window_seconds)
            if self._algorithm_name == ALGORITHM_TOKEN_BUCKET:
                return await self._allow_token_bucket(client, redis_key, count, window_seconds)
            return await self._allow_fixed(client, redis_key, count, window_seconds)

        except Exception:
            logger.exception("RedisBackend.allow failed; %s", "falling back to memory" if self._fallback else "allowing request")
            if self._fallback is not None:
                return await self._fallback.allow(key, limit)
            return True, 0, 0, {"limited": False}

    async def _allow_fixed(self, client: Any, redis_key: str, count: int, window_seconds: int) -> tuple[bool, int, int, dict[str, Any]]:
        """Run the fixed-window Lua script and return the allow/block decision."""
        result = await client.eval(self._LUA_FIXED, 1, redis_key, window_seconds)
        current_count = int(result[0])
        ttl = int(result[1])
        now = int(time.time())
        reset_timestamp = now + max(ttl, 0)
        reset_in = max(ttl, 0)
        remaining = max(0, count - current_count)

        if current_count > count:
            return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": reset_in}
        return True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": reset_in}

    async def _allow_sliding(self, client: Any, redis_key: str, count: int, window_seconds: int) -> tuple[bool, int, int, dict[str, Any]]:
        """Run the sliding-window Lua script and return the allow/block decision."""
        now = time.time()
        unique_member = f"{now}:{uuid.uuid4().hex}"
        result = await client.eval(self._LUA_SLIDING, 1, redis_key, now, window_seconds, count, unique_member)
        allowed_int = int(result[0])
        current_count = int(result[1])
        oldest_ts = float(result[2]) if result[2] else now
        reset_timestamp = int(oldest_ts + window_seconds)
        reset_in = max(0, int(reset_timestamp - now))
        remaining = max(0, count - current_count)

        if not allowed_int:
            return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": reset_in}
        return True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": reset_in}

    async def _allow_token_bucket(self, client: Any, redis_key: str, count: int, window_seconds: int) -> tuple[bool, int, int, dict[str, Any]]:
        """Run the token-bucket Lua script and return the allow/block decision."""
        now = time.time()
        refill_rate = count / window_seconds  # tokens per second
        result = await client.eval(self._LUA_TOKEN_BUCKET, 1, redis_key, count, refill_rate, now)
        allowed_int = int(result[0])
        remaining = int(result[1])
        time_to_next = int(result[2])

        if not allowed_int:
            reset_timestamp = int(now + time_to_next)
            return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": time_to_next}

        # Compute time-to-full consistent with the memory backend: tokens_needed / refill_rate.
        # Use max(1, ...) so sub-second refill times round up to a future integer timestamp.
        tokens_needed = count - remaining
        time_to_full = max(1, int(tokens_needed / refill_rate)) if tokens_needed > 0 else 0
        reset_timestamp = int(now + time_to_full)
        return True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": time_to_full}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class RateLimiterConfig(BaseModel):
    """Configuration for the rate limiter plugin.

    Attributes:
        by_user: Rate limit per user (e.g., '60/m').
        by_tenant: Rate limit per tenant (e.g., '600/m').
        by_tool: Per-tool rate limits (e.g., {'search': '10/m'}).
        algorithm: Counting algorithm — 'fixed_window', 'sliding_window', or 'token_bucket'.
        backend: Storage backend — 'memory' (default) or 'redis'.
        redis_url: Redis connection URL, required when backend='redis'.
        redis_key_prefix: Prefix for all Redis keys (default 'rl').
        redis_fallback: Fall back to in-process memory if Redis is unavailable (default True).
    """

    by_user: Optional[str] = Field(default=None, description="e.g. '60/m'")
    by_tenant: Optional[str] = Field(default=None, description="e.g. '600/m'")
    by_tool: Optional[Dict[str, str]] = Field(default=None, description="per-tool rates, e.g. {'search': '10/m'}")
    algorithm: str = Field(default=ALGORITHM_FIXED_WINDOW, description="'fixed_window', 'sliding_window', or 'token_bucket'")
    backend: str = Field(default="memory", description="'memory' or 'redis'")
    redis_url: Optional[str] = Field(default=None, description="Redis URL, e.g. 'redis://localhost:6379/0'")
    redis_key_prefix: str = Field(default="rl", description="Prefix for Redis keys")
    redis_fallback: bool = Field(default=True, description="Fall back to memory if Redis is unavailable")


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class RateLimiterPlugin(Plugin):
    """Rate limiter with pluggable algorithm (fixed_window, sliding_window, token_bucket)."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialise the plugin, parse config, and set up the rate limiting backend."""
        super().__init__(config)
        self._cfg = RateLimiterConfig(**(config.config or {}))
        self._validate_config()

        algorithm = _make_algorithm(self._cfg.algorithm)

        if self._cfg.backend == "redis":
            fallback_backend = MemoryBackend(_make_algorithm(self._cfg.algorithm)) if self._cfg.redis_fallback else None
            self._rate_backend: MemoryBackend | RedisBackend = RedisBackend(
                redis_url=self._cfg.redis_url or "redis://localhost:6379/0",
                key_prefix=self._cfg.redis_key_prefix,
                algorithm_name=self._cfg.algorithm,
                fallback=fallback_backend,
            )
        else:
            self._rate_backend = MemoryBackend(algorithm)

    def _validate_config(self) -> None:
        """Validate rate strings and algorithm/backend settings; raise ValueError on error."""
        errors: list[str] = []

        if self._cfg.algorithm not in VALID_ALGORITHMS:
            errors.append(f"algorithm={self._cfg.algorithm!r}: must be one of {VALID_ALGORITHMS}")

        for field_name, value in [("by_user", self._cfg.by_user), ("by_tenant", self._cfg.by_tenant)]:
            if value is not None:
                try:
                    _parse_rate(value)
                except ValueError as exc:
                    errors.append(f"{field_name}={value!r}: {exc}")

        if self._cfg.by_tool:
            for tool_name, rate in self._cfg.by_tool.items():
                try:
                    _parse_rate(rate)
                except ValueError as exc:
                    errors.append(f"by_tool[{tool_name!r}]={rate!r}: {exc}")

        if errors:
            raise ValueError("RateLimiterPlugin config errors: " + "; ".join(errors))

        # Pre-compute normalised by_tool keys once — used on every hook call.
        self._normalised_by_tool: Dict[str, str] = (
            {k.strip().lower(): v for k, v in self._cfg.by_tool.items()}
            if self._cfg.by_tool
            else {}
        )

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Enforce rate limits before a prompt is fetched."""
        try:
            prompt = payload.prompt_id.strip().lower()
            user = _extract_user_identity(context.global_context.user)
            tenant = (str(context.global_context.tenant_id).strip() if context.global_context.tenant_id else "") or "default"

            results = [
                await self._rate_backend.allow(f"user:{user}", self._cfg.by_user),
                await self._rate_backend.allow(f"tenant:{tenant}", self._cfg.by_tenant),
            ]

            if self._normalised_by_tool and prompt in self._normalised_by_tool:
                results.append(await self._rate_backend.allow(f"tool:{prompt}", self._normalised_by_tool[prompt]))

            allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
            retry_after = meta.get("reset_in", 0)

            if not allowed:
                headers = _make_headers(limit, remaining, reset_ts, retry_after, include_retry_after=True)
                return PromptPrehookResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Rate limit exceeded",
                        description=f"Rate limit exceeded for prompt '{prompt}'",
                        code="RATE_LIMIT",
                        details=meta,
                        http_status_code=429,
                        http_headers=headers,
                    ),
                )

            if limit > 0:
                headers = _make_headers(limit, remaining, reset_ts, retry_after, include_retry_after=False)
                return PromptPrehookResult(metadata=meta, http_headers=headers)

            return PromptPrehookResult(metadata=meta)

        except Exception:
            logger.exception("RateLimiterPlugin.prompt_pre_fetch encountered an unexpected error; allowing request")
            return PromptPrehookResult()

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Enforce rate limits before a tool is invoked."""
        try:
            tool = payload.name.strip().lower()
            user = _extract_user_identity(context.global_context.user)
            tenant = (str(context.global_context.tenant_id).strip() if context.global_context.tenant_id else "") or "default"

            results = [
                await self._rate_backend.allow(f"user:{user}", self._cfg.by_user),
                await self._rate_backend.allow(f"tenant:{tenant}", self._cfg.by_tenant),
            ]

            if self._normalised_by_tool and tool in self._normalised_by_tool:
                results.append(await self._rate_backend.allow(f"tool:{tool}", self._normalised_by_tool[tool]))

            allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
            retry_after = meta.get("reset_in", 0)

            if not allowed:
                headers = _make_headers(limit, remaining, reset_ts, retry_after, include_retry_after=True)
                return ToolPreInvokeResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Rate limit exceeded",
                        description=f"Rate limit exceeded for tool '{tool}'",
                        code="RATE_LIMIT",
                        details=meta,
                        http_status_code=429,
                        http_headers=headers,
                    ),
                )

            if limit > 0:
                headers = _make_headers(limit, remaining, reset_ts, retry_after, include_retry_after=False)
                return ToolPreInvokeResult(metadata=meta, http_headers=headers)

            return ToolPreInvokeResult(metadata=meta)

        except Exception:
            logger.exception("RateLimiterPlugin.tool_pre_invoke encountered an unexpected error; allowing request")
            return ToolPreInvokeResult()
