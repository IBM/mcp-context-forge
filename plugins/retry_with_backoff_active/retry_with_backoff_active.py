# -*- coding: utf-8 -*-
"""Location: ./plugins/retry_with_backoff_active/plugin.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Retry with Backoff (Active) Plugin.

Uses the retry_delay_ms field on PluginResult to ask the gateway to
re-execute the tool after a computed delay.  The gateway owns the sleep
and the retry loop (see tool_service.py); this plugin owns the failure
detection and the delay calculation.

Hooks: tool_post_invoke
"""

# Future
from __future__ import annotations

# Standard
import logging
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Dict

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-tool runtime state
# ---------------------------------------------------------------------------

@dataclass
class _ToolRetryState:
    """Mutable retry state for a single tool."""

    consecutive_failures: int = 0
    last_failure_at: float = 0.0


# Module-level dict — one entry per tool name, shared across requests within
# the same process.  Fine for asyncio (single-threaded event loop).
_STATE: Dict[str, _ToolRetryState] = {}


def _get_state(tool: str) -> _ToolRetryState:
    if tool not in _STATE:
        _STATE[tool] = _ToolRetryState()
    return _STATE[tool]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class RetryConfig(BaseModel):
    """Per-plugin configuration, read from config.yaml under the plugin's config: key."""

    max_retries: int = Field(default=3, ge=0, description="Max consecutive retries before giving up")
    backoff_base_ms: int = Field(default=200, ge=1, description="Initial backoff in milliseconds")
    max_backoff_ms: int = Field(default=5000, ge=1, description="Ceiling for computed backoff in milliseconds")
    retry_on_status: list[int] = Field(
        default_factory=lambda: [429, 500, 502, 503, 504],
        description="HTTP-style status codes in tool result that count as transient failures",
    )
    jitter: bool = Field(default=True, description="Apply full-jitter to avoid thundering-herd")
    tool_overrides: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-tool config overrides; key = tool name, value = subset of above fields",
    )


def _cfg_for(cfg: RetryConfig, tool: str) -> RetryConfig:
    """Return config merged with any per-tool overrides."""
    overrides = cfg.tool_overrides.get(tool)
    if not overrides:
        return cfg
    merged = cfg.model_dump()
    merged.update(overrides)
    merged.pop("tool_overrides", None)
    return RetryConfig(**merged)


# ---------------------------------------------------------------------------
# Backoff calculation
# ---------------------------------------------------------------------------

def _compute_delay_ms(attempt: int, cfg: RetryConfig) -> int:
    """Return jittered exponential backoff delay in milliseconds.

    Uses full-jitter: random value between 0 and min(cap, base * 2^attempt).
    This prevents thundering-herd when many tools fail at the same time.
    """
    cap = cfg.max_backoff_ms
    base = cfg.backoff_base_ms
    ceiling = min(cap, base * (2 ** attempt))
    if cfg.jitter:
        return math.ceil(random.uniform(0, ceiling))
    return ceiling


# ---------------------------------------------------------------------------
# Failure detection
# ---------------------------------------------------------------------------

def _is_failure(result: Any, cfg: RetryConfig) -> bool:
    """Return True if the tool result should trigger a retry.

    Checks:
      - isError flag (MCP standard)
      - HTTP-style status code fields matching retry_on_status
    """
    if not isinstance(result, dict):
        return False
    if result.get("isError") is True:
        return True
    status = result.get("status_code") or result.get("statusCode") or result.get("status")
    if isinstance(status, int) and status in cfg.retry_on_status:
        return True
    return False


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class RetryWithBackoffPlugin(Plugin):
    """Active retry-with-backoff plugin.

    On failure, returns retry_delay_ms > 0 in PluginResult to ask the
    gateway to re-invoke the tool after the computed delay.
    On success, resets the per-tool failure counter.
    """

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        raw_cfg = RetryConfig(**(config.config or {}))

        # Clamp max_retries to the gateway hard ceiling
        ceiling = get_settings().max_tool_retries
        if raw_cfg.max_retries > ceiling:
            log.warning(
                "retry_with_backoff_active: max_retries=%d exceeds gateway ceiling=%d, clamping",
                raw_cfg.max_retries,
                ceiling,
            )
            raw_cfg = raw_cfg.model_copy(update={"max_retries": ceiling})

        # Clamp per-tool overrides too
        for tool_name, overrides in raw_cfg.tool_overrides.items():
            if overrides.get("max_retries", 0) > ceiling:
                log.warning(
                    "retry_with_backoff_active: tool_overrides[%s].max_retries=%d exceeds ceiling=%d, clamping",
                    tool_name, overrides["max_retries"], ceiling,
                )
                overrides["max_retries"] = ceiling

        self._cfg = raw_cfg

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Detect failure and return retry_delay_ms > 0 to request a retry."""
        tool = payload.name
        cfg = _cfg_for(self._cfg, tool)
        st = _get_state(tool)
        result = payload.result

        if _is_failure(result, cfg):
            st.consecutive_failures += 1
            st.last_failure_at = time.monotonic()

            if st.consecutive_failures <= cfg.max_retries:
                delay_ms = _compute_delay_ms(st.consecutive_failures - 1, cfg)
                log.debug(
                    "retry_with_backoff_active: tool=%s failure=%d/%d delay_ms=%d",
                    tool, st.consecutive_failures, cfg.max_retries, delay_ms,
                )
                return ToolPostInvokeResult(retry_delay_ms=delay_ms)

            # Max retries exhausted — give up, return result as-is
            log.warning(
                "retry_with_backoff_active: tool=%s exhausted %d retries, returning failure",
                tool, cfg.max_retries,
            )
            return ToolPostInvokeResult(retry_delay_ms=0)

        # Success — reset failure counter
        if st.consecutive_failures > 0:
            log.debug("retry_with_backoff_active: tool=%s recovered after %d failure(s)", tool, st.consecutive_failures)
        st.consecutive_failures = 0
        st.last_failure_at = 0.0
        return ToolPostInvokeResult(retry_delay_ms=0)
