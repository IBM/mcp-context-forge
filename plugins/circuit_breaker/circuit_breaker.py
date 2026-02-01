# -*- coding: utf-8 -*-
"""Location: ./plugins/circuit_breaker/circuit_breaker.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Circuit Breaker Plugin.

Trips a per-tool breaker on high error rate or consecutive failures.
Blocks calls during cooldown; resets after cooldown elapses.

Hooks: tool_pre_invoke, tool_post_invoke
"""

# Future
from __future__ import annotations

# Standard
from collections import deque
from dataclasses import dataclass
import time
from typing import Any, Deque, Dict

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)


@dataclass
class _ToolState:
    """Per-tool circuit breaker state.

    Attributes:
        failures: Deque of failure timestamps within the window.
        calls: Deque of call timestamps within the window.
        consecutive_failures: Count of consecutive failures.
        open_until: Unix timestamp when breaker closes; 0 if closed.
        half_open: True if breaker is in half-open state (testing recovery).
        half_open_in_flight: True if a probe request is currently in progress.
        half_open_started: Timestamp when probe started (for stale probe detection).
    """

    failures: Deque[float]
    calls: Deque[float]
    consecutive_failures: int
    open_until: float  # epoch when breaker closes; 0 if closed
    half_open: bool = False  # half-open state for recovery testing
    half_open_in_flight: bool = False  # True when a probe request is in progress
    half_open_started: float = 0.0  # timestamp when probe started


class CircuitBreakerConfig(BaseModel):
    """Configuration for circuit breaker plugin.

    Attributes:
        error_rate_threshold: Fraction of failures that triggers breaker (0-1).
        window_seconds: Time window for calculating error rate.
        min_calls: Minimum calls required before evaluating error rate.
        consecutive_failure_threshold: Number of consecutive failures that opens breaker.
        cooldown_seconds: Duration to keep breaker open after tripping.
        tool_overrides: Per-tool configuration overrides.
    """

    error_rate_threshold: float = 0.5  # fraction in [0,1]
    window_seconds: int = 60
    min_calls: int = 10
    consecutive_failure_threshold: int = 5
    cooldown_seconds: int = 60
    tool_overrides: Dict[str, Dict[str, Any]] = {}


_STATE: Dict[str, _ToolState] = {}


def _now() -> float:
    """Get current Unix timestamp.

    Returns:
        Current time in seconds since epoch.
    """
    return time.time()


def _get_state(tool: str) -> _ToolState:
    """Get or create circuit breaker state for a tool.

    Args:
        tool: Tool name.

    Returns:
        Circuit breaker state for the tool.
    """
    st = _STATE.get(tool)
    if not st:
        st = _ToolState(failures=deque(), calls=deque(), consecutive_failures=0, open_until=0.0, half_open=False, half_open_in_flight=False, half_open_started=0.0)
        _STATE[tool] = st
    return st


def _cfg_for(cfg: CircuitBreakerConfig, tool: str) -> CircuitBreakerConfig:
    """Get effective configuration for a tool, merging overrides if present.

    Args:
        cfg: Base circuit breaker configuration.
        tool: Tool name.

    Returns:
        Effective configuration with tool-specific overrides applied.
    """
    if tool in cfg.tool_overrides:
        merged = {**cfg.model_dump(), **cfg.tool_overrides[tool]}
        return CircuitBreakerConfig(**merged)
    return cfg


def _is_error(result: Any) -> bool:
    """Determine if a tool result represents an error.

    Args:
        result: Tool invocation result.

    Returns:
        True if result indicates an error, False otherwise.
    """
    # ToolResult has is_error; when serialized with by_alias=True it becomes isError
    try:
        if hasattr(result, "is_error"):
            return bool(getattr(result, "is_error"))
        if isinstance(result, dict):
            # Check both snake_case (direct) and camelCase (serialized with by_alias=True)
            if "is_error" in result:
                return bool(result.get("is_error"))
            if "isError" in result:
                return bool(result.get("isError"))
    except Exception:
        pass
    return False


class CircuitBreakerPlugin(Plugin):
    """Circuit breaker plugin to prevent cascading failures by tripping on high error rates."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the circuit breaker plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = CircuitBreakerConfig(**(config.config or {}))

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Check circuit breaker state before tool invocation.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            Result blocking invocation if circuit is open, or allowing it to proceed.
        """
        tool = payload.name
        st = _get_state(tool)
        cfg = _cfg_for(self._cfg, tool)
        now = _now()

        # Check if a probe request is already in flight during half-open state
        # Only block if we're actually in half-open state (st.half_open is True)
        # This prevents wedging if a later plugin blocks after we set half_open_in_flight
        if st.half_open and st.half_open_in_flight:
            # Check for stale probe (probe started but never completed)
            # If probe has been in flight longer than cooldown, reset and allow new probe
            probe_timeout = max(1, int(cfg.cooldown_seconds))
            if st.half_open_started and (now - st.half_open_started) > probe_timeout:
                # Stale probe detected - reset half-open state and reopen circuit
                st.half_open = False
                st.half_open_in_flight = False
                st.half_open_started = 0.0
                st.open_until = now + probe_timeout  # Reopen circuit
            else:
                # Another probe is already testing the circuit - block this request
                return ToolPreInvokeResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Circuit half-open",
                        description=f"Probe request in progress for tool '{tool}'",
                        code="CIRCUIT_HALF_OPEN_PROBE_IN_FLIGHT",
                        details={"retry_after_seconds": 1.0},
                    ),
                )

        # Check if cooldown has elapsed - transition to half-open state
        if st.open_until and now >= st.open_until:
            # Transition to half-open state (allow one test request)
            st.half_open = True
            st.half_open_in_flight = True  # Mark probe as in-flight
            st.half_open_started = now  # Record when probe started for stale detection
            st.open_until = 0.0  # Reset open_until so we allow this request through
            # Note: consecutive_failures is NOT reset yet - that happens on successful call

        # If still in open state (cooldown not elapsed), block the request
        if st.open_until and now < st.open_until:
            retry_after_seconds = max(0.0, st.open_until - now)
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Circuit open",
                    description=f"Breaker open for tool '{tool}' until {int(st.open_until)}",
                    code="CIRCUIT_OPEN",
                    details={
                        "open_until": st.open_until,
                        "retry_after_seconds": round(retry_after_seconds, 1),
                    },
                ),
            )

        # Record call timestamp for rate calculations in post hook context
        context.set_state("cb_call_time", now)
        # Track if this is a half-open test request
        context.set_state("cb_half_open_test", st.half_open)
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Update circuit breaker state after tool invocation and trip if thresholds exceeded.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with circuit breaker metrics metadata.
        """
        tool = payload.name
        st = _get_state(tool)
        cfg = _cfg_for(self._cfg, tool)
        now = _now()

        # Housekeeping: evict old entries
        window = max(1, int(cfg.window_seconds))
        cutoff = now - window
        while st.calls and st.calls[0] < cutoff:
            st.calls.popleft()
        while st.failures and st.failures[0] < cutoff:
            st.failures.popleft()

        # Record this call
        start_time = context.get_state("cb_call_time", now)
        st.calls.append(start_time)

        # Determine if this is an error:
        # 1. Check is_error on the result
        # 2. Check for timeout flag in context (set by tool_service on timeout)
        error = _is_error(payload.result)
        timeout_occurred = context.get_state("cb_timeout_failure", False)
        if timeout_occurred:
            error = True

        # Check if this was a half-open test request
        was_half_open_test = context.get_state("cb_half_open_test", False)

        if error:
            st.failures.append(start_time)
            st.consecutive_failures += 1

            # If this was a half-open test request that failed, immediately reopen the circuit
            if was_half_open_test:
                st.half_open = False
                st.half_open_in_flight = False  # Clear probe in-flight flag
                st.half_open_started = 0.0  # Clear probe start time
                st.open_until = now + max(1, int(cfg.cooldown_seconds))
                try:
                    from mcpgateway.services.metrics import circuit_breaker_open_counter
                    circuit_breaker_open_counter.labels(tool_name=tool).inc()
                except Exception:
                    pass
        else:
            # Success - reset consecutive failures
            st.consecutive_failures = 0

            # If this was a half-open test request that succeeded, fully close the circuit
            if was_half_open_test:
                st.half_open = False
                st.half_open_in_flight = False  # Clear probe in-flight flag
                st.half_open_started = 0.0  # Clear probe start time
                # Don't reset the window - keep tracking for ongoing health

        # Evaluate breaker (only if not already open from half-open failure)
        calls = len(st.calls)
        failure_rate = (len(st.failures) / calls) if calls > 0 else 0.0
        should_open = False

        if not st.open_until:  # Only evaluate if not already open
            if calls >= max(1, int(cfg.min_calls)) and failure_rate >= cfg.error_rate_threshold:
                should_open = True
            if st.consecutive_failures >= max(1, int(cfg.consecutive_failure_threshold)):
                should_open = True

            if should_open:
                st.open_until = now + max(1, int(cfg.cooldown_seconds))
                try:
                    from mcpgateway.services.metrics import circuit_breaker_open_counter
                    circuit_breaker_open_counter.labels(tool_name=tool).inc()
                except Exception:
                    pass

        # Compute retry_after_seconds for metadata
        retry_after_seconds = max(0.0, st.open_until - now) if st.open_until else 0.0

        return ToolPostInvokeResult(
            metadata={
                "circuit_calls_in_window": calls,
                "circuit_failures_in_window": len(st.failures),
                "circuit_failure_rate": round(failure_rate, 3),
                "circuit_consecutive_failures": st.consecutive_failures,
                "circuit_open_until": st.open_until or 0.0,
                "circuit_half_open": st.half_open,
                "circuit_retry_after_seconds": round(retry_after_seconds, 1),
            }
        )
