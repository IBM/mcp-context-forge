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


def _allow(key: str, limit: Optional[str]) -> tuple[bool, dict[str, Any]]:
    """Check if a request is allowed under the rate limit.

    Args:
        key: Unique key for the rate limit (e.g., 'user:alice', 'tool:search').
        limit: Rate limit string (e.g., '60/m') or None to allow unlimited.

    Returns:
        Tuple of (allowed, metadata) where allowed is True if the request is allowed,
        and metadata contains rate limiting information.
    """
    if not limit:
        return True, {"limited": False}
    count, window_seconds = _parse_rate(limit)
    now = int(time.time())
    win_key = f"{key}:{window_seconds}"
    wnd = _store.get(win_key)
    if not wnd or now - wnd.window_start >= window_seconds:
        _store[win_key] = _Window(window_start=now, count=1)
        return True, {"limited": True, "remaining": count - 1, "reset_in": window_seconds}
    if wnd.count < count:
        wnd.count += 1
        return True, {"limited": True, "remaining": count - wnd.count, "reset_in": window_seconds - (now - wnd.window_start)}
    # exceeded
    return False, {"limited": True, "remaining": 0, "reset_in": window_seconds - (now - wnd.window_start)}


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

        ok_u, meta_u = _allow(f"user:{user}", self._cfg.by_user)
        if not ok_u:
            return PromptPrehookResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Rate limit exceeded",
                    description=f"User {user} rate limit exceeded",
                    code="RATE_LIMIT",
                    details=meta_u,
                ),
            )

        ok_t, meta_t = _allow(f"tenant:{tenant}", self._cfg.by_tenant)
        if not ok_t:
            return PromptPrehookResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Rate limit exceeded",
                    description=f"Tenant {tenant} rate limit exceeded",
                    code="RATE_LIMIT",
                    details=meta_t,
                ),
            )

        meta = {"by_user": meta_u, "by_tenant": meta_t}
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

        meta: dict[str, Any] = {}
        ok_u, meta_u = _allow(f"user:{user}", self._cfg.by_user)
        ok_t, meta_t = _allow(f"tenant:{tenant}", self._cfg.by_tenant)
        ok_tool = True
        meta_tool: dict[str, Any] | None = None
        by_tool_config = self._cfg.by_tool
        if hasattr(by_tool_config, "__contains__"):
            if tool in by_tool_config:  # pylint: disable=unsupported-membership-test
                ok_tool, meta_tool = _allow(f"tool:{tool}", by_tool_config[tool])
        meta.update({"by_user": meta_u, "by_tenant": meta_t})
        if meta_tool is not None:
            meta["by_tool"] = meta_tool

        if not (ok_u and ok_t and ok_tool):
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Rate limit exceeded",
                    description=f"Rate limit exceeded for {'tool ' + tool if not ok_tool else ('user' if not ok_u else 'tenant')}",
                    code="RATE_LIMIT",
                    details=meta,
                ),
            )
        return ToolPreInvokeResult(metadata=meta)
