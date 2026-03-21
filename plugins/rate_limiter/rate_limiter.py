# -*- coding: utf-8 -*-
"""Location: ./plugins/rate_limiter/rate_limiter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Rate Limiter Plugin.
Enforces simple in-memory rate limits by user, tenant, and/or tool.
Uses a fixed window keyed by second for simplicity and determinism.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, Optional

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


def _parse_rate(rate: str) -> tuple[int, int]:
    """Parse rate like '60/m', '10/s', '100/h' -> (count, window_seconds).

    Args:
        rate: Rate string in format 'count/unit' (e.g., '60/m', '10/s', '100/h').

    Returns:
        Tuple of (count, window_seconds) for the rate limit.

    Raises:
        ValueError: If the rate unit is not supported.
    """
    count_str, per = rate.split("/")
    count = int(count_str)
    per = per.strip().lower()
    if per in ("s", "sec", "second"):
        return count, 1
    if per in ("m", "min", "minute"):
        return count, 60
    if per in ("h", "hr", "hour"):
        return count, 3600
    raise ValueError(f"Unsupported rate unit: {per}")


class RateLimiterConfig(BaseModel):
    """Configuration for the rate limiter plugin.

    Attributes:
        by_user: Rate limit per user (e.g., '60/m').
        by_tenant: Rate limit per tenant (e.g., '600/m').
        by_tool: Per-tool rate limits (e.g., {'search': '10/m'}).
        backend: Storage backend — 'memory' (default, single-process) or 'redis' (shared).
        redis_url: Redis connection URL, required when backend='redis'.
        redis_key_prefix: Prefix for all Redis keys (default 'rl').
        redis_fallback: Fall back to in-process memory if Redis is unavailable (default True).
    """

    by_user: Optional[str] = Field(default=None, description="e.g. '60/m'")
    by_tenant: Optional[str] = Field(default=None, description="e.g. '600/m'")
    by_tool: Optional[Dict[str, str]] = Field(default=None, description="per-tool rates, e.g. {'search': '10/m'}")
    backend: str = Field(default="memory", description="'memory' or 'redis'")
    redis_url: Optional[str] = Field(default=None, description="Redis URL, e.g. 'redis://localhost:6379/0'")
    redis_key_prefix: str = Field(default="rl", description="Prefix for Redis keys")
    redis_fallback: bool = Field(default=True, description="Fall back to memory if Redis is unavailable")


@dataclass
class _Window:
    """Internal rate limiting window tracking.

    Attributes:
        window_start: Timestamp when the current window started.
        count: Number of requests in the current window.
    """

    window_start: int
    count: int


class MemoryBackend:
    """Thread-safe in-process rate limit store with TTL eviction.

    Uses an asyncio.Lock to make counter increments atomic within the event loop
    and a periodic background sweep to remove expired windows and bound memory growth.

    Attributes:
        _store: Mapping of win_key -> _Window tracking active rate limit windows.
        _lock: asyncio.Lock serialising reads and writes to _store.
        _sweep_interval: Seconds between background eviction sweeps.
        _sweep_task: Running asyncio.Task for the background sweep loop (or None).
    """

    def __init__(self, sweep_interval: float = 0.5) -> None:
        """Initialise the backend.

        Args:
            sweep_interval: How often (in seconds) the background sweep removes expired windows.
        """
        self._store: Dict[str, _Window] = {}
        self._lock = asyncio.Lock()
        self._sweep_interval = sweep_interval
        self._sweep_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    def _ensure_sweep_task(self) -> None:
        """Start the background sweep task if no running task exists."""
        if self._sweep_task is None or self._sweep_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._sweep_task = loop.create_task(self._sweep_loop())
            except RuntimeError:
                pass  # No running event loop yet (e.g. at module import time)

    async def _sweep_loop(self) -> None:
        """Periodically evict expired window entries."""
        while True:
            await asyncio.sleep(self._sweep_interval)
            await self._sweep()

    async def _sweep(self) -> None:
        """Remove all entries whose fixed window has expired."""
        now = int(time.time())
        async with self._lock:
            expired = [
                k for k, w in self._store.items()
                if now - w.window_start >= int(k.rsplit(":", 1)[-1])
            ]
            for k in expired:
                del self._store[k]

    async def allow(self, key: str, limit: Optional[str]) -> tuple[bool, int, int, dict[str, Any]]:
        """Check and increment the rate limit counter for key.

        Args:
            key: Composite key identifying the dimension (e.g. 'user:alice', 'tool:search').
            limit: Rate string (e.g. '60/m') or None for unlimited.

        Returns:
            Tuple of (allowed, limit_count, reset_timestamp, metadata).
        """
        self._ensure_sweep_task()

        if not limit:
            return True, 0, 0, {"limited": False}

        count, window_seconds = _parse_rate(limit)
        now = int(time.time())
        win_key = f"{key}:{window_seconds}"

        async with self._lock:
            wnd = self._store.get(win_key)

            if not wnd or now - wnd.window_start >= window_seconds:
                # New window
                reset_timestamp = now + window_seconds
                self._store[win_key] = _Window(window_start=now, count=1)
                return True, count, reset_timestamp, {"limited": True, "remaining": count - 1, "reset_in": window_seconds}

            reset_timestamp = wnd.window_start + window_seconds
            if wnd.count < count:
                # Within limit
                wnd.count += 1
                reset_in = window_seconds - (now - wnd.window_start)
                return True, count, reset_timestamp, {"limited": True, "remaining": count - wnd.count, "reset_in": reset_in}

            # Exceeded
            reset_in = window_seconds - (now - wnd.window_start)
            return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": reset_in}


class RedisBackend:
    """Shared rate limit store backed by Redis.

    Uses an atomic Lua script (INCR + EXPIRE) so counter increments are race-free
    even across multiple gateway processes or threads.  Native Redis key TTLs replace
    the in-process sweep, so memory is bounded automatically.

    Attributes:
        _url: Redis connection URL.
        _prefix: Key namespace prefix (e.g. 'rl').
        _fallback: Optional MemoryBackend used when Redis is unavailable.
        _client: Injected client (non-None overrides lazy init — used in tests).
        _real_client: Lazily initialised production redis.asyncio client.
    """

    # Lua script: atomically increment the counter and set TTL on first call.
    # Returns [current_count, ttl_remaining_seconds].
    _LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "rl",
        fallback: Optional[MemoryBackend] = None,
        _client: Any = None,
    ) -> None:
        """Initialise the Redis backend.

        Args:
            redis_url: Redis connection URL (e.g. 'redis://localhost:6379/0').
            key_prefix: Namespace prefix for all Redis keys.
            fallback: MemoryBackend to use when Redis is unreachable and redis_fallback=True.
            _client: Pre-built client for testing; skips lazy initialisation when set.
        """
        self._url = redis_url
        self._prefix = key_prefix
        self._fallback = fallback
        self._client = _client
        self._real_client: Any = None

    async def _get_client(self) -> Any:
        """Return the Redis client, lazily initialising the real one if needed."""
        if self._client is not None:
            return self._client
        if self._real_client is None:
            import redis.asyncio as aioredis  # noqa: PLC0415
            self._real_client = aioredis.from_url(self._url, decode_responses=False)
        return self._real_client

    async def allow(self, key: str, limit: Optional[str]) -> tuple[bool, int, int, dict[str, Any]]:
        """Check and increment the rate limit counter in Redis.

        Args:
            key: Composite key identifying the dimension (e.g. 'user:alice').
            limit: Rate string (e.g. '60/m') or None for unlimited.

        Returns:
            Tuple of (allowed, limit_count, reset_timestamp, metadata).
        """
        if not limit:
            return True, 0, 0, {"limited": False}

        count, window_seconds = _parse_rate(limit)
        redis_key = f"{self._prefix}:{key}:{window_seconds}"

        try:
            client = await self._get_client()
            result = await client.eval(self._LUA, 1, redis_key, window_seconds)
            current_count = int(result[0])
            ttl = int(result[1])
            now = int(time.time())
            reset_timestamp = now + max(ttl, 0)
            reset_in = max(ttl, 0)
            remaining = max(0, count - current_count)

            if current_count > count:
                return False, count, reset_timestamp, {"limited": True, "remaining": 0, "reset_in": reset_in}

            return True, count, reset_timestamp, {"limited": True, "remaining": remaining, "reset_in": reset_in}

        except Exception:
            logger.exception("RedisBackend.allow failed; %s", "falling back to memory" if self._fallback else "allowing request")
            if self._fallback is not None:
                return await self._fallback.allow(key, limit)
            return True, 0, 0, {"limited": False}


# Module-level backend instance shared across all plugin instances on this process.
_backend = MemoryBackend()

# Expose _store at module level so tests can inspect and clear it directly.
_store: Dict[str, _Window] = _backend._store


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


def _select_most_restrictive(
    results: list[tuple[bool, int, int, dict[str, Any]]]
) -> tuple[bool, int, int, int, dict[str, Any]]:
    """Select the most restrictive rate limit from multiple dimensions.

    Args:
        results: List of (allowed, limit, reset_timestamp, metadata) tuples from _allow().
        - allowed: True if the request is allowed
        - limit_count: The rate limit count (0 if unlimited)
        - reset_timestamp: Unix timestamp when the window resets (0 if unlimited)
        - metadata: Additional rate limiting information

    Returns:
        Tuple of (allowed, limit, remaining, reset_timestamp, metadata) representing
        the most restrictive limit. If any dimension is violated, allowed is False.
        The metadata includes aggregated information from all dimensions.
    """
    # Filter out unlimited results (limit == 0)
    limited_results = [(allowed, limit, reset_ts, meta) for allowed, limit, reset_ts, meta in results if limit > 0]

    if not limited_results:
        # All unlimited
        return True, 0, 0, 0, {"limited": False}

    # Separate violated and allowed dimensions
    violated = [(allowed, limit, reset_ts, meta) for allowed, limit, reset_ts, meta in limited_results if not allowed]
    allowed_dims = [(allowed, limit, reset_ts, meta) for allowed, limit, reset_ts, meta in limited_results if allowed]

    # If any dimension is violated, pick the one with shortest retry_after (resets soonest)
    if violated:
        most_restrictive = min(violated, key=lambda x: x[3].get("reset_in", float("inf")))
        _, limit, reset_ts, meta = most_restrictive
        remaining = meta.get("remaining", 0)
        retry_after = meta.get("reset_in", 0)

        # Aggregate metadata from all dimensions for observability
        aggregated_meta = {
            "limited": True,
            "remaining": remaining,
            "reset_in": retry_after,
            "dimensions": {
                "violated": [m for _, _, _, m in violated],
                "allowed": [m for _, _, _, m in allowed_dims],
            }
        }
        return False, limit, remaining, reset_ts, aggregated_meta

    # All dimensions allowed - find the most restrictive (lowest remaining)
    most_restrictive = min(allowed_dims, key=lambda x: x[3].get("remaining", float("inf")))
    _, limit, reset_ts, meta = most_restrictive
    remaining = meta.get("remaining", 0)
    retry_after = meta.get("reset_in", 0)

    # Aggregate metadata from all dimensions
    aggregated_meta = {
        "limited": True,
        "remaining": remaining,
        "reset_in": retry_after,
        "dimensions": {"allowed": [m for _, _, _, m in allowed_dims]},
    }
    return True, limit, remaining, reset_ts, aggregated_meta


class RateLimiterPlugin(Plugin):
    """Simple fixed-window rate limiter with per-user/tenant/tool buckets."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the rate limiter plugin.

        Args:
            config: Plugin configuration containing rate limit settings.

        Raises:
            ValueError: If any configured rate string is malformed or uses an unsupported unit.
        """
        super().__init__(config)
        self._cfg = RateLimiterConfig(**(config.config or {}))
        self._validate_config()
        if self._cfg.backend == "redis":
            fallback = _backend if self._cfg.redis_fallback else None
            self._rate_backend: MemoryBackend | RedisBackend = RedisBackend(
                redis_url=self._cfg.redis_url or "redis://localhost:6379/0",
                key_prefix=self._cfg.redis_key_prefix,
                fallback=fallback,
            )
        else:
            self._rate_backend = _backend

    def _validate_config(self) -> None:
        """Validate all configured rate strings and backend at startup.

        Parses every rate string (by_user, by_tenant, and all by_tool entries) so that
        malformed or unsupported values raise immediately at plugin initialisation rather
        than propagating a ValueError to callers at request time.

        Raises:
            ValueError: Collected error message listing every invalid rate string found.
        """
        errors: list[str] = []

        if self._cfg.backend not in ("memory", "redis"):
            errors.append(f"backend={self._cfg.backend!r}: must be 'memory' or 'redis'")

        for field, value in [("by_user", self._cfg.by_user), ("by_tenant", self._cfg.by_tenant)]:
            if value is not None:
                try:
                    _parse_rate(value)
                except ValueError as exc:
                    errors.append(f"{field}={value!r}: {exc}")

        if self._cfg.by_tool:
            for tool_name, rate in self._cfg.by_tool.items():
                try:
                    _parse_rate(rate)
                except ValueError as exc:
                    errors.append(f"by_tool[{tool_name!r}]={rate!r}: {exc}")

        if errors:
            raise ValueError("RateLimiterPlugin config errors: " + "; ".join(errors))

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Check rate limits before fetching a prompt.

        Args:
            payload: The prompt pre-fetch payload.
            context: Plugin execution context containing user and tenant information.

        Returns:
            PromptPrehookResult indicating whether to continue or block due to rate limit.
        """
        try:
            prompt = payload.prompt_id
            user = context.global_context.user or "anonymous"
            tenant = context.global_context.tenant_id or "default"

            # Check all dimensions
            results = [
                await self._rate_backend.allow(f"user:{user}", self._cfg.by_user),
                await self._rate_backend.allow(f"tenant:{tenant}", self._cfg.by_tenant),
            ]

            # Check per-prompt/tool limit if configured (keyed by prompt_id)
            by_tool_config = self._cfg.by_tool
            if by_tool_config and prompt in by_tool_config:  # pylint: disable=unsupported-membership-test
                results.append(await self._rate_backend.allow(f"tool:{prompt}", by_tool_config[prompt]))

            # Select most restrictive
            allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
            retry_after = meta.get("reset_in", 0)

            if not allowed:
                # Rate limit exceeded - include Retry-After header
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

            # Success - include informational headers (without Retry-After)
            if limit > 0:
                headers = _make_headers(limit, remaining, reset_ts, retry_after, include_retry_after=False)
                return PromptPrehookResult(metadata=meta, http_headers=headers)

            return PromptPrehookResult(metadata=meta)

        except Exception:
            logger.exception("RateLimiterPlugin.prompt_pre_fetch encountered an unexpected error; allowing request")
            return PromptPrehookResult()

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Check rate limits before invoking a tool.

        Args:
            payload: The tool pre-invoke payload containing tool name and arguments.
            context: Plugin execution context containing user and tenant information.

        Returns:
            ToolPreInvokeResult indicating whether to continue or block due to rate limit.
        """
        try:
            tool = payload.name
            user = context.global_context.user or "anonymous"
            tenant = context.global_context.tenant_id or "default"

            # Check all dimensions
            results = [
                await self._rate_backend.allow(f"user:{user}", self._cfg.by_user),
                await self._rate_backend.allow(f"tenant:{tenant}", self._cfg.by_tenant),
            ]

            # Check per-tool limit if configured
            by_tool_config = self._cfg.by_tool
            if by_tool_config and tool in by_tool_config:  # pylint: disable=unsupported-membership-test
                results.append(await self._rate_backend.allow(f"tool:{tool}", by_tool_config[tool]))

            # Select most restrictive
            allowed, limit, remaining, reset_ts, meta = _select_most_restrictive(results)
            retry_after = meta.get("reset_in", 0)

            if not allowed:
                # Rate limit exceeded - include Retry-After header
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

            # Success - include informational headers (without Retry-After)
            if limit > 0:
                headers = _make_headers(limit, remaining, reset_ts, retry_after, include_retry_after=False)
                return ToolPreInvokeResult(metadata=meta, http_headers=headers)

            return ToolPreInvokeResult(metadata=meta)

        except Exception:
            logger.exception("RateLimiterPlugin.tool_pre_invoke encountered an unexpected error; allowing request")
            return ToolPreInvokeResult()
