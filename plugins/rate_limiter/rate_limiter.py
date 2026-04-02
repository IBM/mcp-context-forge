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

Security contract — fail-open on error:
  Both hook methods (prompt_pre_fetch, tool_pre_invoke) catch all unexpected
  exceptions and allow the request through.  This is a deliberate design
  choice: an internal engine failure (Rust panic, Redis timeout, config bug)
  must never block legitimate traffic.  The trade-off is that a sustained
  engine failure silently disables rate limiting until the error is resolved.
  Operators should monitor for rate-limiter error logs and treat them as
  high-priority alerts.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from dataclasses import dataclass
import logging
import math
import os
import threading
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
# Optional Rust engine — Python backend is the fallback when unavailable
# ---------------------------------------------------------------------------

_RATE_LIMITER_FORCE_PYTHON = os.environ.get("RATE_LIMITER_FORCE_PYTHON", "").strip().lower() in ("1", "true", "yes")
_RateLimiterEngine: Any = None  # Assigned below when the Rust extension is available.

if _RATE_LIMITER_FORCE_PYTHON:
    _RUST_AVAILABLE = False
else:
    try:
        # Third-Party
        from rate_limiter_rust.rate_limiter_rust import RateLimiterEngine as _RateLimiterEngine  # type: ignore[import]

        _RUST_AVAILABLE = True
    except ImportError:
        _RUST_AVAILABLE = False


class RustRateLimiterEngine:
    """Thin Python wrapper around the PyO3 RateLimiterEngine.

    Exposes evaluate_many() / evaluate_many_async() as pure-Python methods so
    tests can patch them with unittest.mock (PyO3 C extension methods are
    read-only and cannot be patched directly). Pattern mirrors RustPIIDetector
    in plugins/pii_filter/pii_filter_rust.py.
    """

    def __init__(self, config: dict) -> None:
        """Initialise the Rust engine with the given config dict.

        Args:
            config: Engine configuration dict with keys ``by_user``, ``by_tenant``,
                ``by_tool``, ``algorithm``, ``backend``, and optionally ``redis_url``
                and ``redis_key_prefix``.
        """
        self._engine = _RateLimiterEngine(config)

    def evaluate_many(self, checks: List[Tuple[str, int, int]], now_unix: int) -> Any:
        """Delegate to the PyO3 engine (ARCH-01: single call per hook).

        Args:
            checks: List of ``(key, limit_count, window_nanos)`` tuples.
            now_unix: Current Unix timestamp in whole seconds.

        Returns:
            An ``EvalResult`` with the most restrictive outcome across all dimensions.
        """
        return self._engine.evaluate_many(checks, now_unix)

    async def evaluate_many_async(self, checks: List[Tuple[str, int, int]], now_unix: int) -> Any:
        """Delegate to the PyO3 async engine for Redis-backed calls.

        Args:
            checks: List of ``(key, limit_count, window_nanos)`` tuples.
            now_unix: Current Unix timestamp in whole seconds.

        Returns:
            An ``EvalResult`` with the most restrictive outcome across all dimensions.
        """
        return await self._engine.evaluate_many_async(checks, now_unix)

    def check(self, user: str, tenant: Optional[str], tool: str, now_unix: int, include_retry_after: bool) -> Tuple[bool, dict, dict]:
        """High-level check: returns (allowed, headers_dict, meta_dict).

        Builds dimension keys internally, evaluates, and returns pre-built
        dicts — eliminates per-attribute PyO3 boundary crossings.

        Args:
            user: Normalised user identity string.
            tenant: Tenant identifier, or ``None`` to skip the tenant dimension.
            tool: Lowercased tool or prompt name.
            now_unix: Current Unix timestamp in whole seconds.
            include_retry_after: Whether to include ``Retry-After`` in headers.

        Returns:
            Tuple of ``(allowed, headers_dict, meta_dict)``.
        """
        return self._engine.check(user, tenant, tool, now_unix, include_retry_after)

    async def check_async(self, user: str, tenant: Optional[str], tool: str, now_unix: int, include_retry_after: bool) -> Tuple[bool, dict, dict]:
        """Async variant of check() for Redis-backed deployments.

        Args:
            user: Normalised user identity string.
            tenant: Tenant identifier, or ``None`` to skip the tenant dimension.
            tool: Lowercased tool or prompt name.
            now_unix: Current Unix timestamp in whole seconds.
            include_retry_after: Whether to include ``Retry-After`` in headers.

        Returns:
            Tuple of ``(allowed, headers_dict, meta_dict)``.
        """
        return await self._engine.check_async(user, tenant, tool, now_unix, include_retry_after)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALGORITHM_FIXED_WINDOW = "fixed_window"
ALGORITHM_SLIDING_WINDOW = "sliding_window"
ALGORITHM_TOKEN_BUCKET = "token_bucket"  # nosec B105
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
    if count <= 0:
        raise ValueError(f"Invalid rate string {rate!r}: count must be > 0, got {count}")
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

    Args:
        user: Raw user context value from ``PluginContext.global_context.user``.

    Returns:
        Normalised identity string with colons replaced by underscores.
    """
    if isinstance(user, dict):
        identity = user.get("email") or user.get("id") or user.get("sub") or ""
        identity = str(identity).strip()
    elif user is None:
        identity = ""
    else:
        identity = str(user).strip()
    identity = identity if identity else "anonymous"
    # Replace colons to prevent collision with namespace delimiters (user:/tenant:/tool:).
    return identity.replace(":", "_")


def _select_most_restrictive(results: list[tuple[bool, int, int, dict[str, Any]]]) -> tuple[bool, int, int, int, dict[str, Any]]:
    """Select the most restrictive rate limit from multiple dimensions.

    Multi-dimension aggregation contract:
      - Any blocked dimension → overall result is blocked.
      - Among blocked dimensions: the one with the **lowest** retry_after
        (soonest unblock) determines the Retry-After header.  This signals
        the next state change — the caller learns when at least one dimension
        will re-open, even if other dimensions remain blocked longer.  An
        alternative (max) would guarantee success on retry but delays the
        first attempt and hides which dimension unblocked.  This is a
        deliberate product-level choice shared by both the Python and Rust
        implementations.
      - Among allowed dimensions: the one with the fewest remaining requests
        determines the header values (closest to exhaustion).

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
    # "limited" means rate limits are *configured and evaluated*, not that
    # the request was blocked.  Matches the Rust engine (engine.rs build_meta_dict).
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
    window_seconds: int = 0


@dataclass
class _Bucket:
    """Token bucket state: current token count and when tokens were last refilled."""

    tokens: float
    last_refill: float
    window: int = 3600  # window in seconds, used by sweep for eviction threshold


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
        """Check and increment the fixed-window counter for *key*.

        Args:
            lock: Async lock serialising access to the window store.
            key: Rate-limit dimension key (e.g. ``"user:alice"``).
            count: Maximum allowed requests per window.
            window: Window duration in seconds.

        Returns:
            Tuple of ``(allowed, limit, reset_timestamp, metadata)``.
        """
        now = int(time.time())
        win_key = f"{key}:{window}"

        async with lock:
            wnd = self._store.get(win_key)

            if not wnd or now - wnd.window_start >= window:
                reset_timestamp = now + window
                self._store[win_key] = _Window(window_start=now, count=1, window_seconds=window)
                return True, count, reset_timestamp, {"limited": True, "remaining": count - 1, "reset_in": window}

            reset_timestamp = wnd.window_start + window
            reset_in = window - (now - wnd.window_start)

            if wnd.count < count:
                wnd.count += 1
                return True, count, reset_timestamp, {"limited": True, "remaining": count - wnd.count, "reset_in": reset_in}

            return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": reset_in}

    async def sweep(self, lock: asyncio.Lock) -> None:
        """Evict all fixed windows whose duration has elapsed.

        Args:
            lock: Async lock serialising access to the window store.
        """
        now = int(time.time())
        async with lock:
            expired = [k for k, w in self._store.items() if now - w.window_start >= w.window_seconds]
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
        self._store: Dict[str, Tuple[List[float], int]] = {}

    async def allow(self, lock: asyncio.Lock, key: str, count: int, window: int) -> Tuple[bool, int, int, Dict[str, Any]]:
        """Check the sliding-window log for *key* and record the request if allowed.

        Args:
            lock: Async lock serialising access to the timestamp store.
            key: Rate-limit dimension key.
            count: Maximum allowed requests per window.
            window: Window duration in seconds.

        Returns:
            Tuple of ``(allowed, limit, reset_timestamp, metadata)``.
        """
        now = time.time()
        cutoff = now - window
        win_key = f"{key}:{window}"

        async with lock:
            entry = self._store.get(win_key)
            timestamps = entry[0] if entry else []
            # Drop timestamps outside the current window
            timestamps = [t for t in timestamps if t > cutoff]

            current = len(timestamps)
            reset_timestamp = int(timestamps[0] + window) if timestamps else int(now + window)
            reset_in = max(0, int(reset_timestamp - now))

            if current >= count:
                self._store[win_key] = (timestamps, window)
                # Ensure Retry-After is at least 1 so clients do not retry immediately
                # when the oldest timestamp + window truncates to int(now).
                return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": max(1, reset_in)}

            timestamps.append(now)
            self._store[win_key] = (timestamps, window)
            remaining = count - len(timestamps)
            return True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": reset_in}

    async def sweep(self, lock: asyncio.Lock) -> None:
        """Evict keys whose entire timestamp list is outside the current window.

        Args:
            lock: Async lock serialising access to the timestamp store.
        """
        now = time.time()
        async with lock:
            stale = [k for k, (ts, window) in self._store.items() if not ts or all(t <= now - window for t in ts)]
            for k in stale:
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
        """Consume one token from *key*'s bucket, refilling proportionally to elapsed time.

        Args:
            lock: Async lock serialising access to the bucket store.
            key: Rate-limit dimension key.
            count: Bucket capacity (max tokens).
            window: Refill period in seconds (tokens refill at ``count / window`` per second).

        Returns:
            Tuple of ``(allowed, limit, reset_timestamp, metadata)``.
        """
        now = time.time()
        refill_rate = count / window  # tokens per second

        async with lock:
            bucket = self._store.get(key)

            if bucket is None:
                # First request — start with a full bucket minus this request.
                # Use tokens_needed / refill_rate for time_to_full — consistent
                # with the subsequent-request path and the Redis Lua script.
                self._store[key] = _Bucket(tokens=count - 1, last_refill=now, window=window)
                tokens_needed = 1  # consumed 1 from a full bucket
                time_to_full = max(1, int(tokens_needed / refill_rate)) if tokens_needed > 0 else 0
                reset_timestamp = int(now + time_to_full)
                return True, count, reset_timestamp, {"limited": True, "remaining": count - 1, "reset_in": time_to_full}

            # Refill tokens based on elapsed time
            elapsed = now - bucket.last_refill
            bucket.tokens = min(count, bucket.tokens + elapsed * refill_rate)
            bucket.last_refill = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                remaining = int(bucket.tokens)
                # Time until bucket would be full again.
                # Use max(1, ...) so sub-second refill times round up to a future
                # integer timestamp — mirrors the same guard in the Redis path.
                tokens_needed = count - bucket.tokens
                time_to_full = max(1, int(tokens_needed / refill_rate)) if tokens_needed > 0 else 0
                reset_timestamp = int(now + time_to_full)
                return True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": time_to_full}

            # No tokens — calculate when next token arrives (ceiling division
            # matches the Redis Lua path which uses math.ceil).
            time_to_next = max(1, math.ceil((1.0 - bucket.tokens) / refill_rate))
            reset_timestamp = int(now + time_to_next)
            return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": time_to_next}

    async def sweep(self, lock: asyncio.Lock) -> None:
        """Evict buckets that are full (no active limiting).

        Args:
            lock: Async lock serialising access to the bucket store.
        """
        async with lock:
            now = time.time()
            full = []
            for k, bucket in self._store.items():
                elapsed = now - bucket.last_refill
                if elapsed > max(3600, 2 * bucket.window):  # inactive beyond window or 1h
                    full.append(k)
            for k in full:
                del self._store[k]


def _make_algorithm(name: str) -> FixedWindowAlgorithm | SlidingWindowAlgorithm | TokenBucketAlgorithm:
    """Instantiate the named algorithm strategy.

    Args:
        name: Algorithm name (``fixed_window``, ``sliding_window``, or ``token_bucket``).

    Returns:
        Algorithm instance for the requested algorithm.

    Raises:
        ValueError: If *name* is not a recognised algorithm.
    """
    if name == ALGORITHM_FIXED_WINDOW:
        return FixedWindowAlgorithm()
    if name == ALGORITHM_SLIDING_WINDOW:
        return SlidingWindowAlgorithm()
    if name == ALGORITHM_TOKEN_BUCKET:
        return TokenBucketAlgorithm()
    raise ValueError(f"Unknown algorithm {name!r}: expected one of {VALID_ALGORITHMS}")


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
        """Initialise the backend with the given algorithm and sweep interval.

        Args:
            algorithm: Counting strategy instance.
            sweep_interval: Seconds between background eviction sweeps.
        """
        self._algorithm = algorithm
        self._lock: Optional[asyncio.Lock] = None
        self._sweep_interval = sweep_interval
        self._sweep_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._parsed_cache: Dict[str, tuple[int, int]] = {}  # rate_str → (count, window)

    def _ensure_lock(self) -> asyncio.Lock:
        """Lazily create the asyncio.Lock on first use within a running event loop.

        This avoids binding the lock to the wrong loop on Python 3.11 when the
        plugin is instantiated outside an async context.

        Returns:
            The shared asyncio.Lock instance for this backend.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _ensure_sweep_task(self) -> None:
        """Start the background sweep task if it is not already running."""
        if self._sweep_task is None or self._sweep_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._sweep_task = loop.create_task(self._sweep_loop())
            except RuntimeError:
                logger.warning("MemoryBackend: no running event loop; sweep task not started — expired entries will not be evicted")

    async def _sweep_loop(self) -> None:
        """Periodically invoke the algorithm's sweep to evict expired entries."""
        while True:
            await asyncio.sleep(self._sweep_interval)
            await self._algorithm.sweep(self._ensure_lock())

    async def allow(self, key: str, limit: Optional[str]) -> tuple[bool, int, int, dict[str, Any]]:
        """Check the rate limit for *key* against *limit* using the in-process algorithm.

        Args:
            key: Rate-limit dimension key (e.g. ``"user:alice"``).
            limit: Rate string (e.g. ``"60/m"``), or ``None`` to skip.

        Returns:
            Tuple of ``(allowed, limit_count, reset_timestamp, metadata)``.
        """
        self._ensure_sweep_task()
        if not limit:
            return True, 0, 0, {"limited": False}
        parsed = self._parsed_cache.get(limit)
        if parsed is None:
            parsed = _parse_rate(limit)
            self._parsed_cache[limit] = parsed
        count, window = parsed
        return await self._algorithm.allow(self._ensure_lock(), key, count, window)


class RedisBackend:
    """Shared rate limit backend backed by Redis.

    Supports all three algorithms via atomic Lua scripts — one round-trip per
    check with no race conditions.

    .. important:: **Dual Lua-script invariant (rolling-upgrade compatibility)**

       The Rust engine (``plugins_rust/rate_limiter/src/redis_backend.rs``)
       contains its own copies of the batch Lua scripts and uses the same
       Redis key format (``{prefix}:{dimension_key}:{window_seconds}``).
       Both implementations **must** produce identical keys and compatible
       counter semantics so that gateway instances running the Rust backend
       and instances still on the Python fallback share the same Redis
       counters during a rolling upgrade.

       If you change a Lua script or the key format here, you **must** make
       the corresponding change in the Rust backend (and vice-versa), and
       validate with the ``test_redis_key_format_parity_*`` tests.

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
    # NOTE: Lua uses floating-point arithmetic for token refill (tokens + elapsed * rate),
    # while the in-memory Rust backend uses integer milli-token math (u128).  Under sustained
    # high-frequency traffic the two may diverge by ±1 token due to float precision loss.
    # This is acceptable for rate limiting — the behavioral contract is identical.
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

    # LIMITATION: Batch scripts pass multiple KEYS (one per dimension) in a
    # single EVAL/EVALSHA call.  In Redis Cluster, all keys in a single script
    # must hash to the same slot.  The key format `{prefix}:{dim}:{window}`
    # does NOT use hash tags, so these scripts will fail on Redis Cluster.
    # Use standalone Redis or Sentinel for multi-dimension batch evaluation.

    # Batch fixed window: N keys, N windows in ARGV.
    # KEYS: [key1..keyN]  ARGV: [window1..windowN]
    # Returns: [[count1,ttl1], ..., [countN,ttlN]]
    _LUA_BATCH_FIXED = """
local results = {}
for i = 1, #KEYS do
    local current = redis.call('INCR', KEYS[i])
    if current == 1 then
        redis.call('EXPIRE', KEYS[i], ARGV[i])
    end
    local ttl = redis.call('TTL', KEYS[i])
    results[i] = {current, ttl}
end
return results
"""

    # Batch sliding window: N keys.
    # KEYS: [key1..keyN]  ARGV: [now, window1, limit1, member1, window2, limit2, member2, ...]
    # Returns: [[allowed,count,oldest_ts], ...]
    _LUA_BATCH_SLIDING = """
local now = tonumber(ARGV[1])
local results = {}
for i = 1, #KEYS do
    local base = 1 + (i-1)*3 + 1
    local window = tonumber(ARGV[base])
    local limit  = tonumber(ARGV[base+1])
    local member = ARGV[base+2]
    local cutoff = now - window
    redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', cutoff)
    local count = tonumber(redis.call('ZCARD', KEYS[i]))
    redis.call('EXPIRE', KEYS[i], window + 1)
    if count >= limit then
        local oldest = redis.call('ZRANGE', KEYS[i], 0, 0, 'WITHSCORES')
        local oldest_ts = 0
        if #oldest > 0 then oldest_ts = tonumber(oldest[2]) end
        results[i] = {0, count, oldest_ts}
    else
        redis.call('ZADD', KEYS[i], now, member)
        count = count + 1
        local oldest = redis.call('ZRANGE', KEYS[i], 0, 0, 'WITHSCORES')
        local oldest_ts = 0
        if #oldest > 0 then oldest_ts = tonumber(oldest[2]) end
        results[i] = {1, count, oldest_ts}
    end
end
return results
"""

    # Batch token bucket: N keys.
    # KEYS: [key1..keyN]  ARGV: [now, capacity1, rate1, capacity2, rate2, ...]
    # Returns: [[allowed,remaining,time_to_next], ...]
    _LUA_BATCH_TOKEN_BUCKET = """
local now = tonumber(ARGV[1])
local results = {}
for i = 1, #KEYS do
    local base = 1 + (i-1)*2 + 1
    local capacity = tonumber(ARGV[base])
    local rate = tonumber(ARGV[base+1])
    local data = redis.call('HMGET', KEYS[i], 'tokens', 'last_refill')
    local tokens = tonumber(data[1])
    local last_refill = tonumber(data[2])
    if tokens == nil then
        tokens = capacity - 1
        redis.call('HSET', KEYS[i], 'tokens', tokens, 'last_refill', now)
        local ttl = math.ceil(capacity / rate) + 1
        redis.call('EXPIRE', KEYS[i], ttl)
        results[i] = {1, math.floor(tokens), 0}
    else
        local elapsed = now - last_refill
        tokens = math.min(capacity, tokens + elapsed * rate)
        local allowed, time_to_next
        if tokens >= 1.0 then
            tokens = tokens - 1.0
            allowed = 1
            time_to_next = 0
        else
            allowed = 0
            time_to_next = math.ceil((1.0 - tokens) / rate)
        end
        redis.call('HSET', KEYS[i], 'tokens', tokens, 'last_refill', now)
        local ttl = math.ceil((capacity - tokens) / rate) + 1
        redis.call('EXPIRE', KEYS[i], ttl)
        results[i] = {allowed, math.floor(tokens), time_to_next}
    end
end
return results
"""

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "rl",
        algorithm_name: str = ALGORITHM_FIXED_WINDOW,
        fallback: Optional[MemoryBackend] = None,
        _client: Any = None,
    ) -> None:
        """Initialise the Redis backend with connection URL, key prefix, algorithm, and optional fallback.

        Args:
            redis_url: Redis connection URL (e.g. ``"redis://localhost:6379/0"``).
            key_prefix: Namespace prefix for all Redis keys.
            algorithm_name: Counting algorithm name (``fixed_window``, ``sliding_window``, or ``token_bucket``).
            fallback: Optional in-memory backend used when Redis is unavailable.
            _client: Injected Redis client for testing; ``None`` for production.
        """
        self._url = redis_url
        self._prefix = key_prefix
        self._algorithm_name = algorithm_name
        self._fallback = fallback
        self._client = _client
        self._real_client: Any = None
        # REDIS-02: SHA cache for EVALSHA — loaded once at first use, never on request path.
        self._sha_fixed: Optional[str] = None
        self._sha_sliding: Optional[str] = None
        self._sha_token_bucket: Optional[str] = None
        self._sha_batch_fixed: Optional[str] = None
        self._sha_batch_sliding: Optional[str] = None
        self._sha_batch_token_bucket: Optional[str] = None
        self._scripts_loaded: bool = False
        self._script_load_lock: Optional[asyncio.Lock] = None

    async def _get_client(self) -> Any:
        """Return the Redis client, lazily initialising a real connection if needed.

        Returns:
            An async Redis client instance.
        """
        if self._client is not None:
            return self._client
        if self._real_client is None:
            # Third-Party
            import redis.asyncio as aioredis  # noqa: PLC0415

            self._real_client = aioredis.from_url(self._url, decode_responses=True, max_connections=50, socket_timeout=5, socket_connect_timeout=5)
        return self._real_client

    async def _ensure_scripts_loaded(self, client: Any) -> None:
        """REDIS-02: Load all Lua scripts once via SCRIPT LOAD and cache their SHAs.

        Subsequent calls are no-ops once all SHAs are cached. EVALSHA is then used on
        every request path instead of EVAL — O(1) SHA lookup vs. re-parsing the script.
        Only caches the result when `script_load` returns a real string SHA (guards
        against test mock clients that return Mock objects).

        Uses an asyncio.Lock to serialise the one-time loading and prevent
        duplicate SCRIPT LOAD round-trips under concurrent coroutines.

        Args:
            client: Async Redis client instance.
        """
        if self._scripts_loaded:
            return
        if self._script_load_lock is None:
            self._script_load_lock = asyncio.Lock()
        async with self._script_load_lock:
            if self._scripts_loaded:
                return
            pairs = (
                ("_sha_fixed", self._LUA_FIXED),
                ("_sha_sliding", self._LUA_SLIDING),
                ("_sha_token_bucket", self._LUA_TOKEN_BUCKET),
                ("_sha_batch_fixed", self._LUA_BATCH_FIXED),
                ("_sha_batch_sliding", self._LUA_BATCH_SLIDING),
                ("_sha_batch_token_bucket", self._LUA_BATCH_TOKEN_BUCKET),
            )
            for attr, script in pairs:
                if getattr(self, attr) is None:
                    result = await client.script_load(script)
                    if isinstance(result, str):
                        setattr(self, attr, result)
            self._scripts_loaded = True

    async def _evalsha(self, client: Any, sha: Optional[str], script: str, numkeys: int, *args: Any) -> Any:
        """REDIS-02: Execute via EVALSHA when SHA is cached; fall back to EVAL otherwise.

        Falls back to EVAL when:
        - sha is None (script not yet loaded — first call before Redis responds, or test mock)
        - NOSCRIPT error (Redis restarted and flushed its script cache)
        After a NOSCRIPT fallback, reloads the SHA so the next call uses EVALSHA again.

        Args:
            client: Async Redis client instance.
            sha: Cached script SHA, or ``None`` if not yet loaded.
            script: Full Lua script text (used as EVAL fallback).
            numkeys: Number of Redis keys passed to the script.
            *args: Positional arguments passed as KEYS and ARGV to the script.

        Returns:
            Raw result from the Redis EVALSHA or EVAL call.

        Raises:
            Exception: Re-raised from Redis if the error is not a NOSCRIPT error.
        """
        if sha is None:
            return await client.eval(script, numkeys, *args)
        try:
            return await client.evalsha(sha, numkeys, *args)
        except Exception as exc:
            if "NOSCRIPT" in str(exc):
                logger.warning("EVALSHA cache miss (NOSCRIPT); falling back to EVAL and reloading SHA")
                # Allow _ensure_scripts_loaded to bulk-reload all SHAs next request.
                self._scripts_loaded = False
                result = await client.eval(script, numkeys, *args)
                try:
                    new_sha = await client.script_load(script)
                    if isinstance(new_sha, str):
                        for attr, s in (
                            ("_sha_fixed", self._LUA_FIXED),
                            ("_sha_sliding", self._LUA_SLIDING),
                            ("_sha_token_bucket", self._LUA_TOKEN_BUCKET),
                            ("_sha_batch_fixed", self._LUA_BATCH_FIXED),
                            ("_sha_batch_sliding", self._LUA_BATCH_SLIDING),
                            ("_sha_batch_token_bucket", self._LUA_BATCH_TOKEN_BUCKET),
                        ):
                            if s.strip() == script.strip():
                                setattr(self, attr, new_sha)
                                break
                except Exception:
                    logger.warning("EVALSHA SHA reload failed; subsequent calls will fall back to EVAL", exc_info=True)
                return result
            raise

    async def allow(self, key: str, limit: Optional[str]) -> tuple[bool, int, int, dict[str, Any]]:
        """Check the rate limit for *key* against *limit* using an atomic Redis Lua script.

        Args:
            key: Rate-limit dimension key (e.g. ``"user:alice"``).
            limit: Rate string (e.g. ``"60/m"``), or ``None`` to skip.

        Returns:
            Tuple of ``(allowed, limit_count, reset_timestamp, metadata)``.
        """
        if not limit:
            return True, 0, 0, {"limited": False}

        count, window_seconds = _parse_rate(limit)
        redis_key = f"{self._prefix}:{key}:{window_seconds}"

        try:
            client = await self._get_client()
            await self._ensure_scripts_loaded(client)

            if self._algorithm_name == ALGORITHM_SLIDING_WINDOW:
                return await self._allow_sliding(client, redis_key, count, window_seconds)
            if self._algorithm_name == ALGORITHM_TOKEN_BUCKET:
                return await self._allow_token_bucket(client, redis_key, count, window_seconds)
            return await self._allow_fixed(client, redis_key, count, window_seconds)

        except Exception:
            logger.exception("RedisBackend.allow failed; %s", "falling back to memory" if self._fallback else "allowing request")
            if self._fallback is not None:
                return await self._fallback.allow(key, limit)
            return True, 0, 0, {"limited": False, "error": True}

    async def _allow_fixed(self, client: Any, redis_key: str, count: int, window_seconds: int) -> tuple[bool, int, int, dict[str, Any]]:
        """Run the fixed-window Lua script and return the allow/block decision.

        Args:
            client: Async Redis client instance.
            redis_key: Fully-qualified Redis key for this dimension.
            count: Maximum allowed requests per window.
            window_seconds: Window duration in seconds.

        Returns:
            Tuple of ``(allowed, limit, reset_timestamp, metadata)``.
        """
        result = await self._evalsha(client, self._sha_fixed, self._LUA_FIXED, 1, redis_key, window_seconds)
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
        """Run the sliding-window Lua script and return the allow/block decision.

        Args:
            client: Async Redis client instance.
            redis_key: Fully-qualified Redis key for this dimension.
            count: Maximum allowed requests per window.
            window_seconds: Window duration in seconds.

        Returns:
            Tuple of ``(allowed, limit, reset_timestamp, metadata)``.
        """
        now = time.time()
        unique_member = f"{now}:{uuid.uuid4().hex}"
        result = await self._evalsha(client, self._sha_sliding, self._LUA_SLIDING, 1, redis_key, now, window_seconds, count, unique_member)
        allowed_int = int(result[0])
        current_count = int(result[1])
        oldest_ts = float(result[2]) if result[2] else now
        reset_timestamp = int(oldest_ts + window_seconds)
        reset_in = max(0, int(reset_timestamp - now))
        remaining = max(0, count - current_count)

        if not allowed_int:
            return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": max(1, reset_in)}
        return True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": reset_in}

    async def _allow_token_bucket(self, client: Any, redis_key: str, count: int, window_seconds: int) -> tuple[bool, int, int, dict[str, Any]]:
        """Run the token-bucket Lua script and return the allow/block decision.

        Args:
            client: Async Redis client instance.
            redis_key: Fully-qualified Redis key for this dimension.
            count: Bucket capacity (max tokens).
            window_seconds: Refill period in seconds.

        Returns:
            Tuple of ``(allowed, limit, reset_timestamp, metadata)``.
        """
        now = time.time()
        refill_rate = count / window_seconds  # tokens per second
        result = await self._evalsha(client, self._sha_token_bucket, self._LUA_TOKEN_BUCKET, 1, redis_key, count, refill_rate, now)
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

    async def allow_many(self, checks: List[Tuple[str, str]]) -> List[tuple[bool, int, int, dict[str, Any]]]:
        """Batch all dimension checks into a single Redis eval call (REDIS-01, REDIS-03).

        Args:
            checks: List of (dimension_key, rate_str) pairs, e.g. [("user:alice", "10/s")].

        Returns:
            One (allowed, limit, reset_timestamp, metadata) tuple per input check.
        """
        no_limit: tuple[bool, int, int, dict[str, Any]] = (True, 0, 0, {"limited": False})
        active_indices = [i for i, (_, limit) in enumerate(checks) if limit]
        if not active_indices:
            return [no_limit] * len(checks)

        active = [checks[i] for i in active_indices]
        parsed: List[Tuple[str, int, int]] = [(key, *_parse_rate(limit)) for key, limit in active]  # type: ignore[misc]
        redis_keys = [f"{self._prefix}:{key}:{window}" for key, _count, window in parsed]

        try:
            client = await self._get_client()
            await self._ensure_scripts_loaded(client)
            if self._algorithm_name == ALGORITHM_SLIDING_WINDOW:
                active_results = await self._allow_many_sliding(client, parsed, redis_keys)
            elif self._algorithm_name == ALGORITHM_TOKEN_BUCKET:
                active_results = await self._allow_many_token_bucket(client, parsed, redis_keys)
            else:
                active_results = await self._allow_many_fixed(client, parsed, redis_keys)

        except Exception:
            logger.exception("RedisBackend.allow_many failed; %s", "falling back to memory" if self._fallback else "allowing request")
            if self._fallback is not None:
                active_results = [await self._fallback.allow(key, limit) for key, limit in active]
            else:
                no_limit_error: tuple[bool, int, int, dict[str, Any]] = (True, 0, 0, {"limited": False, "error": True})
                active_results = [no_limit_error] * len(active)

        # Map active results back to the full input list.
        results: List[tuple[bool, int, int, dict[str, Any]]] = [no_limit] * len(checks)
        for idx, result in zip(active_indices, active_results):
            results[idx] = result
        return results

    async def _allow_many_fixed(self, client: Any, parsed: List[Tuple[str, int, int]], redis_keys: List[str]) -> List[tuple[bool, int, int, dict[str, Any]]]:
        """Batch fixed-window: one eval call for all N dimensions.

        Args:
            client: Async Redis client instance.
            parsed: List of ``(dimension_key, count, window_seconds)`` tuples.
            redis_keys: Pre-built Redis keys corresponding to *parsed*.

        Returns:
            One ``(allowed, limit, reset_timestamp, metadata)`` tuple per dimension.
        """
        argv = [str(window) for _, _, window in parsed]
        raw = await self._evalsha(client, self._sha_batch_fixed, self._LUA_BATCH_FIXED, len(parsed), *redis_keys, *argv)
        now = int(time.time())
        results = []
        for i, (_key, count, _window) in enumerate(parsed):
            current_count = int(raw[i][0])
            ttl = int(raw[i][1])
            reset_timestamp = now + max(ttl, 0)
            reset_in = max(ttl, 0)
            remaining = max(0, count - current_count)
            if current_count > count:
                results.append((False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": reset_in}))
            else:
                results.append((True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": reset_in}))
        return results

    async def _allow_many_sliding(self, client: Any, parsed: List[Tuple[str, int, int]], redis_keys: List[str]) -> List[tuple[bool, int, int, dict[str, Any]]]:
        """Batch sliding-window: one eval call for all N dimensions.

        Args:
            client: Async Redis client instance.
            parsed: List of ``(dimension_key, count, window_seconds)`` tuples.
            redis_keys: Pre-built Redis keys corresponding to *parsed*.

        Returns:
            One ``(allowed, limit, reset_timestamp, metadata)`` tuple per dimension.
        """
        now = time.time()
        argv: List[Any] = [now]
        for _key, count, window in parsed:
            argv += [window, count, f"{now}:{uuid.uuid4().hex}"]
        raw = await self._evalsha(client, self._sha_batch_sliding, self._LUA_BATCH_SLIDING, len(parsed), *redis_keys, *argv)
        results = []
        for i, (_key, count, window) in enumerate(parsed):
            allowed_int = int(raw[i][0])
            current_count = int(raw[i][1])
            oldest_ts = float(raw[i][2]) if raw[i][2] else now
            reset_timestamp = int(oldest_ts + window)
            reset_in = max(0, int(reset_timestamp - now))
            remaining = max(0, count - current_count)
            if not allowed_int:
                results.append((False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": max(1, reset_in)}))
            else:
                results.append((True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": reset_in}))
        return results

    async def _allow_many_token_bucket(self, client: Any, parsed: List[Tuple[str, int, int]], redis_keys: List[str]) -> List[tuple[bool, int, int, dict[str, Any]]]:
        """Batch token-bucket: one eval call for all N dimensions.

        Args:
            client: Async Redis client instance.
            parsed: List of ``(dimension_key, count, window_seconds)`` tuples.
            redis_keys: Pre-built Redis keys corresponding to *parsed*.

        Returns:
            One ``(allowed, limit, reset_timestamp, metadata)`` tuple per dimension.
        """
        now = time.time()
        argv: List[Any] = [now]
        for _key, count, window in parsed:
            refill_rate = count / window
            argv += [count, refill_rate]
        raw = await self._evalsha(client, self._sha_batch_token_bucket, self._LUA_BATCH_TOKEN_BUCKET, len(parsed), *redis_keys, *argv)
        results = []
        for i, (_key, count, window) in enumerate(parsed):
            refill_rate = count / window
            allowed_int = int(raw[i][0])
            remaining = int(raw[i][1])
            time_to_next = int(raw[i][2])
            if not allowed_int:
                reset_timestamp = int(now + time_to_next)
                results.append((False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": time_to_next}))
            else:
                tokens_needed = count - remaining
                time_to_full = max(1, int(tokens_needed / refill_rate)) if tokens_needed > 0 else 0
                reset_timestamp = int(now + time_to_full)
                results.append((True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": time_to_full}))
        return results


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
        """Initialise the plugin, parse config, and set up the rate limiting backend.

        Args:
            config: Plugin configuration from the plugin framework.
        """
        super().__init__(config)
        self._cfg = RateLimiterConfig(**(config.config or {}))
        self._rust_consecutive_failures: int = 0
        self._rust_failure_lock = threading.Lock()
        self._rust_disabled_at: Optional[float] = None  # monotonic time when engine was disabled
        self._rust_recovery_interval: float = 60.0  # seconds before attempting re-enable
        self._failopen_error_count: int = 0  # total fail-open events for observability
        self._validate_config()

        # Pre-compute normalised by_tool keys once — used on every hook call.
        self._normalised_by_tool: Dict[str, str] = {k.strip().lower(): v for k, v in self._cfg.by_tool.items()} if self._cfg.by_tool else {}

        # Rust engine — handles both memory and Redis backends when available.
        # For Redis: Rust owns the connection and fires batch Lua scripts directly,
        # keeping the shared counter semantics required for multi-instance deployments.
        # Pre-parse limits here so the hot path never does string parsing (IFACE-01).
        self._rust_engine: Optional[Any] = None
        if _RUST_AVAILABLE:
            try:
                rust_config: Dict[str, Any] = {
                    "by_user": self._cfg.by_user,
                    "by_tenant": self._cfg.by_tenant,
                    "by_tool": self._cfg.by_tool or {},
                    "algorithm": self._cfg.algorithm,
                    "backend": self._cfg.backend,
                }
                if self._cfg.backend == "redis":
                    rust_config["redis_url"] = self._cfg.redis_url
                    rust_config["redis_key_prefix"] = self._cfg.redis_key_prefix
                self._rust_engine = RustRateLimiterEngine(rust_config)
                self._rust_config = rust_config  # kept for recovery re-init
                # Pre-parsed (count, window_nanos) for each dimension — used to build
                # the checks list passed to evaluate_many() on every hook call.
                self._rust_by_user: Optional[Tuple[int, int]] = self._parse_rate_nanos(self._cfg.by_user) if self._cfg.by_user else None
                self._rust_by_tenant: Optional[Tuple[int, int]] = self._parse_rate_nanos(self._cfg.by_tenant) if self._cfg.by_tenant else None
                self._rust_by_tool: Dict[str, Tuple[int, int]] = {k.strip().lower(): self._parse_rate_nanos(v) for k, v in (self._cfg.by_tool or {}).items()}
                logger.debug("Rate limiter using Rust engine (backend=%s, algorithm=%s)", self._cfg.backend, self._cfg.algorithm)
            except Exception:
                logger.error("Failed to initialise Rust rate limiter engine; falling back to Python backend", exc_info=True)
                self._rust_engine = None

        algorithm = _make_algorithm(self._cfg.algorithm)

        if self._cfg.backend == "redis":
            fallback_backend = MemoryBackend(_make_algorithm(self._cfg.algorithm)) if self._cfg.redis_fallback else None
            self._rate_backend: MemoryBackend | RedisBackend = RedisBackend(
                redis_url=self._cfg.redis_url,
                key_prefix=self._cfg.redis_key_prefix,
                algorithm_name=self._cfg.algorithm,
                fallback=fallback_backend,
            )
        else:
            self._rate_backend = MemoryBackend(algorithm)

    def _validate_config(self) -> None:
        """Validate rate strings and algorithm/backend settings; raise ValueError on error.

        Raises:
            ValueError: If any rate string is malformed or settings are invalid.
        """
        errors: list[str] = []

        if self._cfg.algorithm not in VALID_ALGORITHMS:
            errors.append(f"algorithm={self._cfg.algorithm!r}: must be one of {VALID_ALGORITHMS}")

        if self._cfg.backend not in ("memory", "redis"):
            errors.append(f"backend={self._cfg.backend!r}: must be 'memory' or 'redis'")

        if self._cfg.backend == "redis" and not self._cfg.redis_url:
            errors.append("redis_url is required when backend='redis'")

        for field_name, value in [("by_user", self._cfg.by_user), ("by_tenant", self._cfg.by_tenant)]:
            if value is not None:
                try:
                    _parse_rate(value)
                except ValueError as exc:
                    errors.append(f"{field_name}={value!r}: {exc}")

        if self._cfg.by_tool:
            normalised_keys: set[str] = set()
            for tool_name, rate in self._cfg.by_tool.items():
                try:
                    _parse_rate(rate)
                except ValueError as exc:
                    errors.append(f"by_tool[{tool_name!r}]={rate!r}: {exc}")
                norm_key = tool_name.strip().lower()
                if norm_key in normalised_keys:
                    errors.append(f"by_tool has duplicate key after normalisation: {tool_name!r} -> {norm_key!r}")
                normalised_keys.add(norm_key)

        if errors:
            raise ValueError("RateLimiterPlugin config errors: " + "; ".join(errors))

    @staticmethod
    def _parse_rate_nanos(rate: str) -> Tuple[int, int]:
        """Parse a rate string and return (count, window_nanos).

        Args:
            rate: Rate string (e.g. ``"60/m"``).

        Returns:
            Tuple of ``(count, window_nanos)``.
        """
        count, window_secs = _parse_rate(rate)
        return count, window_secs * 1_000_000_000

    def _build_rust_checks(self, user: str, tenant: Optional[str], tool: str) -> List[Tuple[str, int, int]]:
        """Build the checks list for evaluate_many() from the current request context.

        Python extracts context; Rust engine does all rate math (ARCH-03).
        None tenant is excluded — no check added (CORR-04).

        Args:
            user: Normalised user identity string.
            tenant: Tenant identifier, or ``None`` to skip the tenant dimension.
            tool: Lowercased tool or prompt name.

        Returns:
            List of ``(key, limit_count, window_nanos)`` tuples for active dimensions.
        """
        checks: List[Tuple[str, int, int]] = []
        if self._rust_by_user:
            count, window_nanos = self._rust_by_user
            checks.append((f"user:{user}", count, window_nanos))
        if tenant and self._rust_by_tenant:
            count, window_nanos = self._rust_by_tenant
            checks.append((f"tenant:{tenant}", count, window_nanos))
        if tool in self._rust_by_tool:
            count, window_nanos = self._rust_by_tool[tool]
            checks.append((f"tool:{tool}", count, window_nanos))
        return checks

    def _rust_to_plugin_headers(self, result: Any, include_retry_after: bool) -> dict[str, str]:
        """Convert an EvalResult to HTTP rate-limit headers (CORR-02).

        Args:
            result: Rust ``EvalResult`` instance.
            include_retry_after: Whether to include ``Retry-After`` in the headers.

        Returns:
            Dictionary of HTTP rate-limit headers.
        """
        retry_after = result.retry_after if result.retry_after is not None else 0
        return _make_headers(result.limit, result.remaining, result.reset_timestamp, retry_after, include_retry_after)

    def _rust_to_plugin_meta(self, result: Any) -> dict[str, Any]:
        """Convert a Rust EvalResult into the same metadata shape as the Python path.

        Args:
            result: Rust ``EvalResult`` instance.

        Returns:
            Plugin metadata dict with ``limited``, ``remaining``, ``reset_in``, and ``dimensions``.
        """

        def _dimension_meta(dim: Any) -> dict[str, Any]:
            """Convert a single Rust dimension result into Python plugin metadata.

            Args:
                dim: Rust ``EvalDimension`` instance.

            Returns:
                Metadata dict for a single dimension.
            """
            reset_in = dim.retry_after if dim.retry_after is not None else max(0, int(dim.reset_timestamp) - int(time.time()))
            return {
                "limited": True,
                "remaining": int(dim.remaining),
                "reset_in": reset_in,
            }

        reset_in = result.retry_after if result.retry_after is not None else max(0, int(result.reset_timestamp) - int(time.time()))
        meta: dict[str, Any] = {
            "limited": True,
            "remaining": int(result.remaining),
            "reset_in": reset_in,
        }
        if not result.allowed:
            meta["dimensions"] = {
                "violated": [_dimension_meta(dim) for dim in result.violated_dimensions],
                "allowed": [_dimension_meta(dim) for dim in result.allowed_dimensions],
            }
        elif result.allowed_dimensions:
            meta["dimensions"] = {
                "allowed": [_dimension_meta(dim) for dim in result.allowed_dimensions],
            }
        return meta

    def _should_fallback_to_python_redis(self) -> bool:
        """Return True when Redis-backed Rust errors should drop to Python fallback.

        Returns:
            Whether the Python Redis backend is available as a fallback.
        """
        return self._cfg.backend == "redis" and self._cfg.redis_fallback and isinstance(self._rate_backend, RedisBackend)

    def _should_use_async_rust_redis(self) -> bool:
        """Return True when the Rust Redis fast path should use the async bridge.

        Returns:
            Whether the backend is Redis (requiring the async code path).
        """
        return self._cfg.backend == "redis"

    async def _check_rust_fast_path(self, user: str, tenant: Optional[str], entity: str, hook_name: str) -> Optional[Tuple[bool, Optional[Dict[str, str]], Dict[str, Any]]]:
        """Attempt rate evaluation via the Rust engine (ARCH-01).

        Args:
            user: Normalised user identity string.
            tenant: Tenant identifier, or ``None`` to skip the tenant dimension.
            entity: Lowercased tool or prompt name.
            hook_name: Hook identifier for logging.

        Returns:
            The ``(allowed, headers, meta)`` tuple on success, or ``None`` to
            fall through to the Python path.
        """
        try:
            now_unix = int(time.time())
            if self._should_use_async_rust_redis():
                allowed, headers, meta = await self._rust_engine.check_async(user, tenant, entity, now_unix, True)
            else:
                allowed, headers, meta = self._rust_engine.check(user, tenant, entity, now_unix, True)
        except Exception:
            with self._rust_failure_lock:
                self._rust_consecutive_failures += 1
                failures = self._rust_consecutive_failures
            if failures >= 10:
                logger.error(
                    "Rust rate limiter disabled after %d consecutive failures during %s; will attempt recovery in %.0fs",
                    failures,
                    hook_name,
                    self._rust_recovery_interval,
                    exc_info=True,
                )
                self._rust_engine = None
                self._rust_disabled_at = time.monotonic()
            else:
                logger.warning(
                    "Rust rate limiter failed during %s (%d/%d before disable); %s",
                    hook_name,
                    failures,
                    10,
                    "falling back to Python Redis backend" if self._should_fallback_to_python_redis() else "falling through to Python path",
                    exc_info=True,
                )
            return None

        with self._rust_failure_lock:
            self._rust_consecutive_failures = 0
        if meta.get("limited") is False:
            return True, None, meta
        if not allowed:
            return False, headers, meta
        headers.pop("Retry-After", None)
        return True, headers, meta

    def _maybe_recover_rust_engine(self) -> None:
        """Attempt to re-initialise the Rust engine after a timed backoff."""
        if self._rust_disabled_at is None or not _RUST_AVAILABLE:
            return
        if time.monotonic() - self._rust_disabled_at < self._rust_recovery_interval:
            return
        try:
            self._rust_engine = RustRateLimiterEngine(self._rust_config)
            with self._rust_failure_lock:
                self._rust_consecutive_failures = 0
            self._rust_disabled_at = None
            logger.info("Rust rate limiter engine recovered after backoff")
        except Exception:
            # Push the next recovery attempt out by another interval.
            self._rust_disabled_at = time.monotonic()
            logger.warning("Rust rate limiter recovery failed; will retry in %.0fs", self._rust_recovery_interval, exc_info=True)

    async def _check_python_fallback(self, user: str, tenant: Optional[str], entity: str) -> Tuple[bool, Optional[Dict[str, str]], Dict[str, Any]]:
        """Rate evaluation via the Python backend (ARCH-05: fallback).

        Args:
            user: Normalised user identity string.
            tenant: Tenant identifier, or ``None`` to skip the tenant dimension.
            entity: Lowercased tool or prompt name.

        Returns:
            Tuple of ``(allowed, headers, meta)``.
        """
        checks: List[Tuple[str, str]] = []
        if self._cfg.by_user:
            checks.append((f"user:{user}", self._cfg.by_user))
        if tenant and self._cfg.by_tenant:
            checks.append((f"tenant:{tenant}", self._cfg.by_tenant))
        if self._normalised_by_tool and entity in self._normalised_by_tool:
            checks.append((f"tool:{entity}", self._normalised_by_tool[entity]))

        if not checks:
            return True, None, {"limited": False}

        if isinstance(self._rate_backend, RedisBackend):
            results = await self._rate_backend.allow_many(checks)
        else:
            results = [await self._rate_backend.allow(key, limit) for key, limit in checks]

        allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
        retry_after = meta.get("reset_in", 0)

        if not allowed:
            headers = _make_headers(limit, remaining, reset_ts, retry_after, include_retry_after=True)
            return False, headers, meta

        if limit > 0:
            headers = _make_headers(limit, remaining, reset_ts, retry_after, include_retry_after=False)
            return True, headers, meta

        return True, None, meta

    async def _check_rate_limit(self, user: str, tenant: Optional[str], entity: str, hook_name: str) -> Tuple[bool, Optional[Dict[str, str]], Dict[str, Any]]:
        """Core rate-limit evaluation shared by prompt_pre_fetch and tool_pre_invoke.

        Args:
            user: Normalised user identity string.
            tenant: Tenant identifier, or ``None`` to skip the tenant dimension.
            entity: Lowercased tool or prompt name.
            hook_name: Hook identifier for logging (e.g. ``"tool_pre_invoke"``).

        Returns:
            Tuple of ``(allowed, headers, meta)`` where *headers* is ``None``
            when no limits are configured and includes ``Retry-After`` only when blocked.
        """
        if self._rust_engine is None and self._rust_disabled_at is not None:
            self._maybe_recover_rust_engine()

        if self._rust_engine is not None:
            result = await self._check_rust_fast_path(user, tenant, entity, hook_name)
            if result is not None:
                return result

        return await self._check_python_fallback(user, tenant, entity)

    async def _dispatch_hook(self, entity: str, context: PluginContext, hook_name: str, entity_label: str, result_cls: type) -> Any:
        """Shared rate-limit dispatch for both hook methods.

        Extracts user/tenant from *context*, evaluates limits for *entity*,
        and returns the appropriate *result_cls* instance.  Fail-open on any
        unexpected error (see module docstring "Security contract").

        Args:
            entity: Lowercased tool or prompt name being rate-limited.
            context: Plugin context carrying user, tenant, and request state.
            hook_name: Hook identifier for logging (e.g. ``"tool_pre_invoke"``).
            entity_label: Human-readable label for error messages (``"tool"`` or ``"prompt"``).
            result_cls: Result class to instantiate (``ToolPreInvokeResult`` or ``PromptPrehookResult``).

        Returns:
            An instance of *result_cls*, either allowing the request or containing a violation.
        """
        try:
            user = _extract_user_identity(context.global_context.user)
            tenant = str(context.global_context.tenant_id).strip() if context.global_context.tenant_id else None

            allowed, headers, meta = await self._check_rate_limit(user, tenant, entity, hook_name)

            if not allowed:
                return result_cls(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Rate limit exceeded",
                        description=f"Rate limit exceeded for {entity_label} '{entity}'",
                        code="RATE_LIMIT",
                        details=meta,
                        http_status_code=429,
                        http_headers=headers,
                    ),
                )
            if headers:
                return result_cls(metadata=meta, http_headers=headers)
            return result_cls(metadata=meta)

        except Exception:
            # Deliberate fail-open: engine errors must not block legitimate traffic.
            # See module docstring "Security contract — fail-open on error".
            self._failopen_error_count += 1
            logger.exception("RateLimiterPlugin.%s encountered an unexpected error; allowing request (failopen_errors=%d)", hook_name, self._failopen_error_count)
            return result_cls()

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Enforce rate limits before a prompt is fetched.

        Args:
            payload: Prompt prehook payload containing the prompt identifier.
            context: Plugin context carrying user, tenant, and request state.

        Returns:
            Result allowing the request or containing a rate-limit violation.
        """
        return await self._dispatch_hook(payload.prompt_id.strip().lower(), context, "prompt_pre_fetch", "prompt", PromptPrehookResult)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Enforce rate limits before a tool is invoked.

        Args:
            payload: Tool pre-invoke payload containing the tool name.
            context: Plugin context carrying user, tenant, and request state.

        Returns:
            Result allowing the request or containing a rate-limit violation.
        """
        return await self._dispatch_hook(payload.name.strip().lower(), context, "tool_pre_invoke", "tool", ToolPreInvokeResult)
