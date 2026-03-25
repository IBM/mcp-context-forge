# -*- coding: utf-8 -*-
"""Location: ./plugins/retry_with_backoff/retry_with_backoff.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Retry with Backoff Plugin.

Uses the retry_delay_ms field on PluginResult to ask the gateway to
re-execute the tool after a computed delay.  The gateway owns the sleep
and the retry loop (see tool_service.py); this plugin owns the failure
detection and the delay calculation.

Hooks: tool_post_invoke
"""

# Future
from __future__ import annotations

# Standard
import json
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
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional Rust accelerator
#
# If the compiled extension is installed, one RetryStateManager instance is
# shared for the lifetime of the process.  If it's absent (e.g. dev machine
# without the Rust toolchain, or a pure-Python wheel), the plugin silently
# falls back to the Python implementation below.
#
# The try/except ImportError pattern is the standard Python idiom for
# optional compiled extensions.  It imposes zero cost when Rust IS present
# (the import succeeds and _RUST is set once at module load), and makes the
# plugin fully portable when it is NOT.
# ---------------------------------------------------------------------------
try:
    from retry_with_backoff_rust import RetryStateManager as _RustRetryStateManager
    _RUST: _RustRetryStateManager | None = _RustRetryStateManager()
    log.debug("retry_with_backoff: Rust extension loaded (%s)", _RUST.ping())
except ImportError:
    _RUST = None
    log.debug("retry_with_backoff: Rust extension not available, using Python fallback")


# ---------------------------------------------------------------------------
# Per-tool runtime state
# ---------------------------------------------------------------------------

@dataclass
class _ToolRetryState:
    """Mutable retry state for a single tool."""

    consecutive_failures: int = 0
    last_failure_at: float = 0.0


# Module-level dict — one entry per (tool_name, request_id).
# Each independent tool invocation gets its own fresh state; retries of the
# same invocation share state because the gateway passes the same global_context
# (and therefore the same request_id) on every retry attempt.
_STATE: Dict[str, _ToolRetryState] = {}


def _get_state(tool: str, request_id: str) -> _ToolRetryState:
    key = f"{tool}:{request_id}"
    if key not in _STATE:
        _STATE[key] = _ToolRetryState()
    return _STATE[key]


def _del_state(tool: str, request_id: str) -> None:
    _STATE.pop(f"{tool}:{request_id}", None)


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
    check_text_content: bool = Field(
        default=False,
        description=(
            "Parse text content as JSON and check for status_code when structuredContent is absent. "
            "Enable only for tools on older MCP servers (pre-2025 spec) that return HTTP-style error "
            "dicts in text content instead of raising exceptions. OFF by default because it can "
            "false-positive on tools that legitimately return status codes as informational data."
        ),
    )
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

    The plugin receives result = ToolResult.model_dump(by_alias=True), which has
    the shape: {"content": [...], "isError": bool, "structuredContent": {...}}.

    Three failure signals are checked, in order:

    1. Outer ``isError`` — set to True by the gateway when the tool raises an
       exception. Works on ALL MCP spec versions. This is the recommended way
       for tools to signal retryable failures.

    2. ``structuredContent.status_code`` — when a tool returns a plain dict, the
       gateway places it in structuredContent (MCP spec 2025-03-26+ only). Older
       servers leave structuredContent=None and this check silently does nothing.

    3. Text content JSON parsing (opt-in, ``check_text_content: true``) — for
       tools on older MCP servers that return HTTP-style error dicts as serialized
       JSON in text content instead of raising exceptions. Disabled by default
       because it can false-positive on tools that legitimately return status codes
       as informational data (e.g. a monitoring tool reporting downstream statuses).
    """
    if not isinstance(result, dict):
        return False

    # Signal 1: outer MCP-level isError (tool raised an exception).
    # Works on all MCP spec versions — the recommended retry signal.
    if result.get("isError") is True:
        return True

    # Signal 2: structuredContent — only populated on MCP spec 2025-03-26+.
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        if structured.get("isError") is True:
            return True
        sc_status = structured.get("status_code")
        if isinstance(sc_status, int) and sc_status in cfg.retry_on_status:
            return True

    # Signal 3: opt-in text content parsing for older MCP servers.
    # Only runs when structuredContent was absent (None) — not a double-check.
    if cfg.check_text_content and structured is None:
        for item in result.get("content", []):
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            try:
                parsed = json.loads(item["text"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if not isinstance(parsed, dict):
                continue
            if parsed.get("isError") is True:
                return True
            txt_status = parsed.get("status_code")
            if isinstance(txt_status, int) and txt_status in cfg.retry_on_status:
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
                "retry_with_backoff: max_retries=%d exceeds gateway ceiling=%d, clamping",
                raw_cfg.max_retries,
                ceiling,
            )
            raw_cfg = raw_cfg.model_copy(update={"max_retries": ceiling})

        # Clamp per-tool overrides too
        for tool_name, overrides in raw_cfg.tool_overrides.items():
            if overrides.get("max_retries", 0) > ceiling:
                log.warning(
                    "retry_with_backoff: tool_overrides[%s].max_retries=%d exceeds ceiling=%d, clamping",
                    tool_name, overrides["max_retries"], ceiling,
                )
                overrides["max_retries"] = ceiling

        self._cfg = raw_cfg

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Detect failure and return retry_delay_ms > 0 to request a retry.

        Also attaches retry_policy metadata on every response so downstream
        clients and orchestrators can observe the active policy.
        """
        tool = payload.name
        cfg = _cfg_for(self._cfg, tool)
        request_id = context.global_context.request_id
        result = payload.result

        retry_policy_meta = {
            "retry_policy": {
                "max_retries": cfg.max_retries,
                "backoff_base_ms": cfg.backoff_base_ms,
                "max_backoff_ms": cfg.max_backoff_ms,
                "retry_on_status": cfg.retry_on_status,
            }
        }

        # ------------------------------------------------------------------
        # Fast path: delegate to Rust when the extension is available and
        # check_text_content is off (Rust handles signals 1 and 2 only).
        #
        # We pre-extract the two typed signals Python-side before crossing
        # the FFI boundary.  Passing a raw PyDict into Rust would be slower
        # and require more PyO3 boilerplate.  Two attribute lookups in Python
        # are cheap and keep the Rust code purely typed.
        # ------------------------------------------------------------------
        if _RUST is not None and not cfg.check_text_content:
            is_error: bool = isinstance(result, dict) and result.get("isError") is True
            status_code: int | None = None
            if isinstance(result, dict):
                structured = result.get("structuredContent")
                if isinstance(structured, dict):
                    if structured.get("isError") is True:
                        is_error = True
                    sc = structured.get("status_code")
                    if isinstance(sc, int):
                        status_code = sc

            should_retry, delay_ms = _RUST.check_and_update(
                tool, request_id, is_error, status_code,
                cfg.max_retries, cfg.backoff_base_ms, cfg.max_backoff_ms,
                cfg.jitter, cfg.retry_on_status,
            )
            if should_retry:
                log.debug(
                    "retry_with_backoff (rust): tool=%s delay_ms=%d",
                    tool, delay_ms,
                )
            else:
                log.debug("retry_with_backoff (rust): tool=%s success/exhausted", tool)
            return ToolPostInvokeResult(retry_delay_ms=delay_ms, metadata=retry_policy_meta)

        # ------------------------------------------------------------------
        # Python fallback path — used when:
        #   * Rust extension is not installed, OR
        #   * check_text_content=True (signal 3 requires Python dict parsing)
        # This path is identical to the pre-Rust implementation.
        # ------------------------------------------------------------------
        st = _get_state(tool, request_id)

        if _is_failure(result, cfg):
            st.consecutive_failures += 1
            st.last_failure_at = time.monotonic()

            if st.consecutive_failures <= cfg.max_retries:
                delay_ms = _compute_delay_ms(st.consecutive_failures - 1, cfg)
                log.debug(
                    "retry_with_backoff: tool=%s failure=%d/%d delay_ms=%d",
                    tool, st.consecutive_failures, cfg.max_retries, delay_ms,
                )
                return ToolPostInvokeResult(retry_delay_ms=delay_ms, metadata=retry_policy_meta)

            # Max retries exhausted — give up, clean up state for this invocation.
            log.warning(
                "retry_with_backoff: tool=%s exhausted %d retries, returning failure",
                tool, cfg.max_retries,
            )
            _del_state(tool, request_id)
            return ToolPostInvokeResult(retry_delay_ms=0, metadata=retry_policy_meta)

        # Success — log recovery, clean up state for this invocation.
        if st.consecutive_failures > 0:
            log.debug("retry_with_backoff: tool=%s recovered after %d failure(s)", tool, st.consecutive_failures)
        _del_state(tool, request_id)
        return ToolPostInvokeResult(retry_delay_ms=0, metadata=retry_policy_meta)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Attach retry policy metadata after resource fetch."""
        return ResourcePostFetchResult(
            metadata={
                "retry_policy": {
                    "max_retries": self._cfg.max_retries,
                    "backoff_base_ms": self._cfg.backoff_base_ms,
                    "max_backoff_ms": self._cfg.max_backoff_ms,
                    "retry_on_status": self._cfg.retry_on_status,
                }
            }
        )
