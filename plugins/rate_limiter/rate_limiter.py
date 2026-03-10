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
from dataclasses import dataclass
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
    """

    by_user: Optional[str] = Field(default=None, description="e.g. '60/m'")
    by_tenant: Optional[str] = Field(default=None, description="e.g. '600/m'")
    by_tool: Optional[Dict[str, str]] = Field(default=None, description="per-tool rates, e.g. {'search': '10/m'}")


@dataclass
class _Window:
    """Internal rate limiting window tracking.

    Attributes:
        window_start: Timestamp when the current window started.
        count: Number of requests in the current window.
    """

    window_start: int
    count: int


_store: Dict[str, _Window] = {}


def _allow(key: str, limit: Optional[str]) -> tuple[bool, int, int, dict[str, Any]]:
    """Check if a request is allowed under the rate limit.

    Args:
        key: Unique key for the rate limit (e.g., 'user:alice', 'tool:search').
        limit: Rate limit string (e.g., '60/m') or None to allow unlimited.

    Returns:
        Tuple of (allowed, limit_count, reset_timestamp, metadata) where:
        - allowed: True if the request is allowed
        - limit_count: The rate limit count (0 if unlimited)
        - reset_timestamp: Unix timestamp when the window resets (0 if unlimited)
        - metadata: Additional rate limiting information
    """
    if not limit:
        return True, 0, 0, {"limited": False}
    count, window_seconds = _parse_rate(limit)
    now = int(time.time())
    win_key = f"{key}:{window_seconds}"
    wnd = _store.get(win_key)

    if not wnd or now - wnd.window_start >= window_seconds:
        # New window
        reset_timestamp = now + window_seconds
        _store[win_key] = _Window(window_start=now, count=1)
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
        """
        super().__init__(config)
        self._cfg = RateLimiterConfig(**(config.config or {}))

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Check rate limits before fetching a prompt.

        Args:
            payload: The prompt pre-fetch payload.
            context: Plugin execution context containing user and tenant information.

        Returns:
            PromptPrehookResult indicating whether to continue or block due to rate limit.
        """
        user = context.global_context.user or "anonymous"
        tenant = context.global_context.tenant_id or "default"

        # Check all dimensions
        results = [
            _allow(f"user:{user}", self._cfg.by_user),
            _allow(f"tenant:{tenant}", self._cfg.by_tenant),
        ]

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
                    description=f"Rate limit exceeded for user {user} or tenant {tenant}",
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

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Check rate limits before invoking a tool.

        Args:
            payload: The tool pre-invoke payload containing tool name and arguments.
            context: Plugin execution context containing user and tenant information.

        Returns:
            ToolPreInvokeResult indicating whether to continue or block due to rate limit.
        """
        tool = payload.name
        user = context.global_context.user or "anonymous"
        tenant = context.global_context.tenant_id or "default"

        # Check all dimensions
        results = [
            _allow(f"user:{user}", self._cfg.by_user),
            _allow(f"tenant:{tenant}", self._cfg.by_tenant),
        ]

        # Check per-tool limit if configured
        by_tool_config = self._cfg.by_tool
        if by_tool_config:
            if hasattr(by_tool_config, "__contains__") and tool in by_tool_config:  # pylint: disable=unsupported-membership-test
                results.append(_allow(f"tool:{tool}", by_tool_config[tool]))

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
                    description=f"Rate limit exceeded for tool {tool}, user {user}, or tenant {tenant}",
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
