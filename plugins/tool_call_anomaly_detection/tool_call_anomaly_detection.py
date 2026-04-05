# -*- coding: utf-8 -*-
"""Location: ./plugins/tool_call_anomaly_detection/tool_call_anomaly_detection.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Anuj Shrivastava

Tool Call Anomaly Detection Plugin.

Learns baseline tool-calling patterns per user/agent and flags behavioral
anomalies in real time — burst invocations, access to unfamiliar tools,
off-hours activity, and unusual argument fingerprints.

Applies database activity monitoring concepts to agentic MCP tool calls
flowing through the gateway.

Hooks: tool_pre_invoke, tool_post_invoke
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Literal, Set

from pydantic import BaseModel, Field, model_validator

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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class AnomalyDetectionConfig(BaseModel):
    """Configuration for tool call anomaly detection.

    Attributes:
        learning_window_seconds: Seconds of baseline learning before enforcement.
        burst_window_seconds: Sliding window for burst detection.
        burst_threshold: Max tool calls within burst window before flagging.
        novelty_score_weight: Weight for novel-tool-access scoring (0-1).
        burst_score_weight: Weight for burst-rate scoring (0-1).
        frequency_score_weight: Weight for abnormal frequency scoring (0-1).
        block_threshold: Composite risk score (0-1) above which to block.
        warn_threshold: Composite risk score (0-1) above which to warn.
        max_history_per_user: Maximum call records kept per user for baselines.
        off_hours_start: UTC hour marking start of off-hours (0-23).
        off_hours_end: UTC hour marking end of off-hours (0-23).
        off_hours_score_bonus: Additional risk score during off-hours.
        action: What to do on threshold breach — "warn" or "block".
    """

    learning_window_seconds: int = Field(default=3600, ge=0)
    burst_window_seconds: int = Field(default=60, ge=1)
    burst_threshold: int = Field(default=20, ge=1)
    novelty_score_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    burst_score_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    frequency_score_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    block_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    warn_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    max_history_per_user: int = Field(default=1000, ge=10)
    off_hours_start: int = Field(default=22, ge=0, le=23)
    off_hours_end: int = Field(default=6, ge=0, le=23)
    off_hours_score_bonus: float = Field(default=0.15, ge=0.0, le=1.0)
    action: Literal["warn", "block"] = Field(default="warn")

    @model_validator(mode="after")
    def _check_thresholds(self) -> "AnomalyDetectionConfig":
        """Ensure warn_threshold <= block_threshold."""
        if self.warn_threshold > self.block_threshold:
            msg = f"warn_threshold ({self.warn_threshold}) must be <= block_threshold ({self.block_threshold})"
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# In-memory user baseline (lightweight, no external deps)
# ---------------------------------------------------------------------------

class _CallRecord:
    """A single tool-call observation."""

    __slots__ = ("tool_name", "timestamp", "arg_keys")

    def __init__(self, tool_name: str, timestamp: float, arg_keys: frozenset[str]) -> None:
        self.tool_name = tool_name
        self.timestamp = timestamp
        self.arg_keys = arg_keys


class _UserBaseline:
    """Per-user accumulated baseline statistics."""

    __slots__ = (
        "first_seen",
        "known_tools",
        "known_arg_signatures",
        "call_history",
        "tool_counts",
    )

    def __init__(self) -> None:
        self.first_seen: float = time.time()
        self.known_tools: Set[str] = set()
        self.known_arg_signatures: Dict[str, Set[frozenset[str]]] = defaultdict(set)
        self.call_history: List[_CallRecord] = []
        self.tool_counts: Dict[str, int] = defaultdict(int)

    @property
    def total_calls(self) -> int:
        """Return total number of tool calls observed."""
        return sum(self.tool_counts.values())


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class ToolCallAnomalyDetectionPlugin(Plugin):
    """Detects anomalous tool-calling behaviour per user/agent.

    During the learning window the plugin only observes and builds baselines.
    After the window, every tool call is scored for risk and optionally
    blocked or annotated with metadata.
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialise plugin with anomaly detection configuration."""
        super().__init__(config)
        self._cfg = AnomalyDetectionConfig(**(config.config or {}))
        self._baselines: Dict[str, _UserBaseline] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_user_id(self, context: PluginContext) -> str:
        """Extract user identifier from the plugin context."""
        gc = context.global_context
        if isinstance(gc.user, dict):
            return gc.user.get("email", gc.user.get("sub", "anonymous"))
        return gc.user or "anonymous"

    def _get_baseline(self, user_id: str) -> _UserBaseline:
        """Return the baseline for *user_id*, creating one if needed."""
        if user_id not in self._baselines:
            self._baselines[user_id] = _UserBaseline()
        return self._baselines[user_id]

    def _is_learning(self, baseline: _UserBaseline) -> bool:
        """Check whether the baseline is still in the learning window."""
        return (time.time() - baseline.first_seen) < self._cfg.learning_window_seconds

    def _prune_history(self, baseline: _UserBaseline) -> None:
        """Trim call history to the configured maximum."""
        if len(baseline.call_history) > self._cfg.max_history_per_user:
            baseline.call_history = baseline.call_history[-self._cfg.max_history_per_user:]

    def _is_off_hours(self) -> bool:
        """Return True if the current UTC hour falls within the off-hours window."""
        import datetime  # noqa: E402 — deferred import (stdlib, lightweight)
        hour = datetime.datetime.now(datetime.timezone.utc).hour
        start, end = self._cfg.off_hours_start, self._cfg.off_hours_end
        if start > end:  # overnight span, e.g. 22–06
            return hour >= start or hour < end
        return start <= hour < end

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_novelty(self, tool_name: str, arg_keys: frozenset[str], baseline: _UserBaseline) -> float:
        """Score how novel this tool call is for the user."""
        if tool_name not in baseline.known_tools:
            return 1.0  # never-seen tool
        known_sigs = baseline.known_arg_signatures.get(tool_name, set())
        if known_sigs and arg_keys not in known_sigs:
            return 0.5  # known tool, unknown argument shape
        return 0.0

    def _score_burst(self, baseline: _UserBaseline, now: float) -> float:
        """Score burst rate within the sliding window."""
        window_start = now - self._cfg.burst_window_seconds
        recent = sum(1 for r in baseline.call_history if r.timestamp >= window_start)
        if recent >= self._cfg.burst_threshold:
            return min(1.0, recent / self._cfg.burst_threshold)
        return recent / max(1, self._cfg.burst_threshold) * 0.5

    def _score_frequency(self, tool_name: str, baseline: _UserBaseline) -> float:
        """Score how far this tool's usage deviates from the user's normal distribution."""
        total = baseline.total_calls
        if total < 10:
            return 0.0  # not enough data
        tool_fraction = baseline.tool_counts.get(tool_name, 0) / total
        if tool_fraction < 0.01:
            return 0.6  # rarely used tool — moderate anomaly
        return 0.0

    def _composite_score(
        self, novelty: float, burst: float, frequency: float, *, off_hours: bool
    ) -> float:
        """Compute the weighted composite risk score."""
        cfg = self._cfg
        raw = (
            novelty * cfg.novelty_score_weight
            + burst * cfg.burst_score_weight
            + frequency * cfg.frequency_score_weight
        )
        if off_hours:
            raw += cfg.off_hours_score_bonus
        return min(1.0, raw)

    # ------------------------------------------------------------------
    # Record keeping
    # ------------------------------------------------------------------

    def _record_call(
        self, user_id: str, tool_name: str, arg_keys: frozenset[str], now: float
    ) -> None:
        """Record a tool call in the user's baseline."""
        baseline = self._get_baseline(user_id)
        baseline.known_tools.add(tool_name)
        baseline.known_arg_signatures[tool_name].add(arg_keys)
        baseline.tool_counts[tool_name] += 1
        baseline.call_history.append(_CallRecord(tool_name, now, arg_keys))
        self._prune_history(baseline)

    # ------------------------------------------------------------------
    # Hook implementations
    # ------------------------------------------------------------------

    async def tool_pre_invoke(
        self, payload: ToolPreInvokePayload, context: PluginContext
    ) -> ToolPreInvokeResult:
        """Evaluate risk score before tool execution.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            Result that may block the call if risk is too high.
        """
        now = time.time()
        user_id = self._get_user_id(context)
        tool_name = payload.name
        arg_keys = frozenset((payload.args or {}).keys())
        baseline = self._get_baseline(user_id)

        # During learning window, just observe
        if self._is_learning(baseline):
            self._record_call(user_id, tool_name, arg_keys, now)
            return ToolPreInvokeResult(
                metadata={"anomaly_mode": "learning", "anomaly_user": user_id},
            )

        # Score the call
        off_hours = self._is_off_hours()
        novelty = self._score_novelty(tool_name, arg_keys, baseline)
        burst = self._score_burst(baseline, now)
        frequency = self._score_frequency(tool_name, baseline)
        risk_score = self._composite_score(novelty, burst, frequency, off_hours=off_hours)

        meta: Dict[str, Any] = {
            "anomaly_risk_score": round(risk_score, 4),
            "anomaly_novelty": round(novelty, 4),
            "anomaly_burst": round(burst, 4),
            "anomaly_frequency": round(frequency, 4),
            "anomaly_off_hours": off_hours,
            "anomaly_user": user_id,
            "anomaly_tool": tool_name,
        }

        # Save for post_invoke enrichment
        context.set_state("anomaly_meta", meta)
        context.set_state("anomaly_risk_score", risk_score)

        if risk_score >= self._cfg.block_threshold and self._cfg.action == "block":
            logger.warning(
                "Anomaly detection: blocking tool call %s for user %s (risk=%.2f)",
                tool_name,
                user_id,
                risk_score,
            )
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Anomalous tool call detected",
                    description=(
                        f"Tool '{tool_name}' call by '{user_id}' scored "
                        f"{risk_score:.2f} risk (threshold {self._cfg.block_threshold})"
                    ),
                    code="ANOMALY_BLOCKED",
                    details=meta,
                ),
            )

        # Record only after allowing — blocked calls should not train the baseline
        self._record_call(user_id, tool_name, arg_keys, now)

        if risk_score >= self._cfg.warn_threshold:
            logger.info(
                "Anomaly detection: elevated risk for tool %s by user %s (risk=%.2f)",
                tool_name,
                user_id,
                risk_score,
            )

        return ToolPreInvokeResult(metadata=meta)

    async def tool_post_invoke(
        self, payload: ToolPostInvokePayload, context: PluginContext
    ) -> ToolPostInvokeResult:
        """Enrich post-invoke metadata with anomaly context.

        Args:
            payload: Tool result payload.
            context: Plugin execution context.

        Returns:
            Result with anomaly metadata attached.
        """
        meta = context.get_state("anomaly_meta", {})
        return ToolPostInvokeResult(metadata=meta)
