# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_tool_call_anomaly_detection.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Anuj Shrivastava

Unit tests for tool call anomaly detection plugin.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)
from mcpgateway.plugins.framework.hooks.tools import ToolHookType
from plugins.tool_call_anomaly_detection.tool_call_anomaly_detection import (
    AnomalyDetectionConfig,
    ToolCallAnomalyDetectionPlugin,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> PluginConfig:
    return PluginConfig(
        name="ToolCallAnomalyDetection",
        kind="plugins.tool_call_anomaly_detection.tool_call_anomaly_detection.ToolCallAnomalyDetectionPlugin",
        hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
        priority=200,
        config=overrides,
    )


def _make_context(user: str = "alice@example.com") -> PluginContext:
    return PluginContext(
        global_context=GlobalContext(
            request_id="req-001",
            server_id="srv-001",
            user=user,
        )
    )


def _pre_payload(name: str = "db_query", args: dict | None = None) -> ToolPreInvokePayload:
    return ToolPreInvokePayload(name=name, args=args or {"query": "SELECT 1"})


def _post_payload(name: str = "db_query") -> ToolPostInvokePayload:
    return ToolPostInvokePayload(name=name, result={"content": [{"type": "text", "text": "ok"}]})


# ---------------------------------------------------------------------------
# Tests — learning mode
# ---------------------------------------------------------------------------

class TestLearningPhase:
    """Tests for the baseline learning window."""

    @pytest.mark.asyncio
    async def test_learning_mode_always_allows(self):
        plugin = ToolCallAnomalyDetectionPlugin(_make_config(learning_window_seconds=9999))
        ctx = _make_context()

        result = await plugin.tool_pre_invoke(_pre_payload(), ctx)

        assert result.continue_processing is True
        assert result.metadata["anomaly_mode"] == "learning"

    @pytest.mark.asyncio
    async def test_learning_builds_baseline(self):
        plugin = ToolCallAnomalyDetectionPlugin(_make_config(learning_window_seconds=9999))
        ctx = _make_context()

        await plugin.tool_pre_invoke(_pre_payload("tool_a"), ctx)
        await plugin.tool_pre_invoke(_pre_payload("tool_b"), ctx)

        baseline = plugin._baselines["alice@example.com"]
        assert "tool_a" in baseline.known_tools
        assert "tool_b" in baseline.known_tools
        assert baseline.total_calls == 2


# ---------------------------------------------------------------------------
# Tests — detection mode
# ---------------------------------------------------------------------------

class TestDetectionPhase:
    """Tests after learning window expires."""

    def _build_trained_plugin(self, **config_overrides) -> ToolCallAnomalyDetectionPlugin:
        """Create a plugin that has already passed learning phase."""
        cfg = _make_config(learning_window_seconds=0, **config_overrides)
        plugin = ToolCallAnomalyDetectionPlugin(cfg)
        # Seed a baseline so first_seen is in the past
        baseline = plugin._get_baseline("alice@example.com")
        baseline.first_seen = time.time() - 7200
        baseline.known_tools.update({"db_query", "list_files", "search"})
        baseline.known_arg_signatures["db_query"].add(frozenset(["query"]))
        baseline.known_arg_signatures["list_files"].add(frozenset(["path"]))
        baseline.known_arg_signatures["search"].add(frozenset(["term"]))
        for tool in ("db_query", "list_files", "search"):
            baseline.tool_counts[tool] = 50
        return plugin

    @pytest.mark.asyncio
    async def test_known_tool_low_risk(self):
        plugin = self._build_trained_plugin()
        ctx = _make_context()

        result = await plugin.tool_pre_invoke(_pre_payload("db_query", {"query": "SELECT 1"}), ctx)

        assert result.continue_processing is True
        assert result.metadata["anomaly_risk_score"] < 0.5

    @pytest.mark.asyncio
    async def test_novel_tool_raises_risk(self):
        plugin = self._build_trained_plugin()
        ctx = _make_context()

        result = await plugin.tool_pre_invoke(_pre_payload("delete_everything", {"confirm": "yes"}), ctx)

        assert result.continue_processing is True
        assert result.metadata["anomaly_novelty"] == 1.0
        assert result.metadata["anomaly_risk_score"] >= 0.35

    @pytest.mark.asyncio
    async def test_burst_detection(self):
        plugin = self._build_trained_plugin(burst_threshold=5, burst_window_seconds=60)
        ctx = _make_context()

        for _ in range(6):
            result = await plugin.tool_pre_invoke(_pre_payload("db_query", {"query": "x"}), ctx)
            ctx = _make_context()  # fresh context per call

        assert result.metadata["anomaly_burst"] > 0

    @pytest.mark.asyncio
    async def test_block_action(self):
        plugin = self._build_trained_plugin(
            action="block",
            block_threshold=0.3,  # low threshold for testing
        )
        ctx = _make_context()

        # Novel tool should trigger block
        result = await plugin.tool_pre_invoke(_pre_payload("hack_the_planet", {"target": "all"}), ctx)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "ANOMALY_BLOCKED"

    @pytest.mark.asyncio
    async def test_warn_does_not_block(self):
        plugin = self._build_trained_plugin(
            action="warn",
            warn_threshold=0.1,
        )
        ctx = _make_context()

        result = await plugin.tool_pre_invoke(_pre_payload("unknown_tool"), ctx)

        assert result.continue_processing is True
        assert result.metadata["anomaly_risk_score"] >= 0.1

    @pytest.mark.asyncio
    async def test_post_invoke_returns_metadata(self):
        plugin = self._build_trained_plugin()
        ctx = _make_context()

        await plugin.tool_pre_invoke(_pre_payload("db_query", {"query": "x"}), ctx)
        post_result = await plugin.tool_post_invoke(_post_payload("db_query"), ctx)

        assert "anomaly_risk_score" in post_result.metadata


# ---------------------------------------------------------------------------
# Tests — off hours
# ---------------------------------------------------------------------------

class TestOffHours:
    @pytest.mark.asyncio
    async def test_off_hours_bonus(self):
        plugin = ToolCallAnomalyDetectionPlugin(
            _make_config(
                learning_window_seconds=0,
                off_hours_start=0,
                off_hours_end=23,  # always off-hours
                off_hours_score_bonus=0.15,
            )
        )
        baseline = plugin._get_baseline("alice@example.com")
        baseline.first_seen = time.time() - 7200
        baseline.known_tools.add("db_query")
        baseline.known_arg_signatures["db_query"].add(frozenset(["query"]))
        baseline.tool_counts["db_query"] = 50

        ctx = _make_context()
        result = await plugin.tool_pre_invoke(_pre_payload("db_query", {"query": "x"}), ctx)

        assert result.metadata["anomaly_off_hours"] is True


# ---------------------------------------------------------------------------
# Tests — user identity extraction
# ---------------------------------------------------------------------------

class TestUserIdentity:
    @pytest.mark.asyncio
    async def test_dict_user_email(self):
        plugin = ToolCallAnomalyDetectionPlugin(_make_config(learning_window_seconds=9999))
        gc = GlobalContext(request_id="r", user={"email": "bob@co.com", "sub": "sub1"})
        ctx = PluginContext(global_context=gc)

        await plugin.tool_pre_invoke(_pre_payload(), ctx)
        assert "bob@co.com" in plugin._baselines

    @pytest.mark.asyncio
    async def test_anonymous_fallback(self):
        plugin = ToolCallAnomalyDetectionPlugin(_make_config(learning_window_seconds=9999))
        gc = GlobalContext(request_id="r", user=None)
        ctx = PluginContext(global_context=gc)

        await plugin.tool_pre_invoke(_pre_payload(), ctx)
        assert "anonymous" in plugin._baselines


# ---------------------------------------------------------------------------
# Tests — history pruning
# ---------------------------------------------------------------------------

class TestPruning:
    @pytest.mark.asyncio
    async def test_history_pruned(self):
        plugin = ToolCallAnomalyDetectionPlugin(
            _make_config(learning_window_seconds=9999, max_history_per_user=10)
        )
        ctx = _make_context()

        for i in range(20):
            await plugin.tool_pre_invoke(_pre_payload(f"tool_{i}"), _make_context())

        baseline = plugin._baselines["alice@example.com"]
        assert len(baseline.call_history) <= 10
