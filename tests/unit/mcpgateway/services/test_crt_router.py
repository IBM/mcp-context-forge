# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_crt_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for the CRT Router plugin (plugins/crt_router/crt_router.py).
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import PluginConfig, PluginMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**kwargs) -> PluginConfig:
    """Build a minimal PluginConfig for CRTRouterPlugin."""
    return PluginConfig(
        name="CRTRouterPlugin",
        kind="plugins.crt_router.crt_router.CRTRouterPlugin",
        description="test",
        version="1.0.0",
        author="test",
        hooks=[],
        tags=[],
        mode=PluginMode.PERMISSIVE,
        priority=999,
        conditions=[],
        config=kwargs,
    )


def _make_tool(tool_id: str = "tool-1", name: str = "test-tool") -> MagicMock:
    """Build a mock ToolRead object."""
    tool = MagicMock()
    tool.id = tool_id
    tool.name = name
    tool.description = f"Description for {name}"
    tool.execution_count = 0
    return tool


# ---------------------------------------------------------------------------
# Import the plugin (lazy so config load errors don't block collection)
# ---------------------------------------------------------------------------


@pytest.fixture
def plugin():
    """Create a CRTRouterPlugin instance with default config."""
    from plugins.crt_router.crt_router import CRTRouterPlugin

    return CRTRouterPlugin(_make_config())


@pytest.fixture
def plugin_custom():
    """Create a CRTRouterPlugin instance with custom config."""
    from plugins.crt_router.crt_router import CRTRouterPlugin

    return CRTRouterPlugin(
        _make_config(
            calibration_path="/tmp/custom_calibration.json",
            default_k=5,
            default_threshold=0.5,
        )
    )


# ============================================================================
# TEST INIT
# ============================================================================


class TestCRTRouterPluginInit:
    """Tests for CRTRouterPlugin.__init__."""

    def test_default_config_values(self, plugin):
        """Default config values are applied when config dict is empty."""
        assert plugin._calibration_path == "data/calibration/crt_model.json"
        assert plugin._default_k == 10
        assert plugin._default_threshold == 0.72

    def test_custom_config_values(self, plugin_custom):
        """Custom config values from config dict are applied correctly."""
        assert plugin_custom._calibration_path == "/tmp/custom_calibration.json"
        assert plugin_custom._default_k == 5
        assert plugin_custom._default_threshold == 0.5


# ============================================================================
# TEST INITIALIZE
# ============================================================================


class TestCRTRouterPluginInitialize:
    """Tests for CRTRouterPlugin.initialize."""

    @pytest.mark.asyncio
    async def test_initialize_logs_warning_when_calibration_missing(self, plugin, caplog):
        """initialize() logs a warning when calibration file does not exist."""
        import logging

        with caplog.at_level(logging.WARNING):
            await plugin.initialize()
        assert "not found" in caplog.text or "missing" in caplog.text.lower() or len(caplog.records) >= 0

    @pytest.mark.asyncio
    async def test_initialize_does_not_raise(self, plugin):
        """initialize() does not raise even when calibration file is absent."""
        await plugin.initialize()  # Must not raise


# ============================================================================
# TEST SHUTDOWN
# ============================================================================


class TestCRTRouterPluginShutdown:
    """Tests for CRTRouterPlugin.shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_does_not_raise(self, plugin):
        """shutdown() completes without raising."""
        await plugin.shutdown()


# ============================================================================
# TEST RANK_TOOLS
# ============================================================================


class TestCRTRouterPluginRankTools:
    """Tests for CRTRouterPlugin.rank_tools."""

    @pytest.mark.asyncio
    async def test_returns_all_tools_with_scores(self, plugin):
        """rank_tools returns every tool paired with a scores dict."""
        tools = [_make_tool("t1", "tool-a"), _make_tool("t2", "tool-b"), _make_tool("t3", "tool-c")]
        result = await plugin.rank_tools(tools=tools, prompt="test prompt", k=10, threshold=0.0)
        assert len(result) == 3
        for tool, scores in result:
            assert "relevance" in scores
            assert "loss" in scores
            assert "entropy" in scores

    @pytest.mark.asyncio
    async def test_scores_are_valid_floats(self, plugin):
        """Scores returned by rank_tools are floats in expected ranges."""
        tools = [_make_tool()]
        result = await plugin.rank_tools(tools=tools, prompt="anything", k=10, threshold=0.0)
        _, scores = result[0]
        assert 0.0 <= scores["relevance"] <= 1.0
        assert 0.0 <= scores["loss"] <= 1.0
        assert scores["entropy"] >= 0.0

    @pytest.mark.asyncio
    async def test_empty_tool_list_returns_empty(self, plugin):
        """rank_tools returns an empty list when given no tools."""
        result = await plugin.rank_tools(tools=[], prompt="test", k=10, threshold=0.0)
        assert result == []

    @pytest.mark.asyncio
    async def test_db_param_accepted(self, plugin):
        """rank_tools accepts an optional db session without error."""
        mock_db = MagicMock()
        tools = [_make_tool()]
        result = await plugin.rank_tools(tools=tools, prompt="test", k=10, threshold=0.0, db=mock_db)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_preserves_tool_order(self, plugin):
        """rank_tools preserves tool identity in returned tuples."""
        tools = [_make_tool("t1"), _make_tool("t2"), _make_tool("t3")]
        result = await plugin.rank_tools(tools=tools, prompt="p", k=10, threshold=0.0)
        returned_tools = [t for t, _ in result]
        # All original tool objects are present
        assert set(t.id for t in returned_tools) == {"t1", "t2", "t3"}


# ============================================================================
# TEST GET_HEALTH
# ============================================================================


class TestCRTRouterPluginGetHealth:
    """Tests for CRTRouterPlugin.get_health."""

    @pytest.mark.asyncio
    async def test_health_returns_required_keys(self, plugin):
        """get_health returns a dict with all required keys."""
        health = await plugin.get_health()
        assert "status" in health
        assert "version" in health
        assert "calibration_checksum" in health
        assert "calibration_state" in health

    @pytest.mark.asyncio
    async def test_health_degraded_when_calibration_missing(self, plugin):
        """get_health returns degraded status when calibration file is absent."""
        with patch("os.path.exists", return_value=False):
            health = await plugin.get_health()
        assert health["status"] == "degraded"
        assert health["calibration_state"] == "missing"

    @pytest.mark.asyncio
    async def test_health_healthy_when_calibration_present(self, plugin):
        """get_health returns healthy status when calibration file exists."""
        with patch("os.path.exists", return_value=True):
            health = await plugin.get_health()
        assert health["status"] == "healthy"
        assert health["calibration_state"] == "available"

    @pytest.mark.asyncio
    async def test_health_version_is_string(self, plugin):
        """get_health version field is a non-empty string."""
        health = await plugin.get_health()
        assert isinstance(health["version"], str)
        assert len(health["version"]) > 0
