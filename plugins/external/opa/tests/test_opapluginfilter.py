# -*- coding: utf-8 -*-
"""Tests for plugin."""

# Third-Party
import pytest

# First-Party
from opapluginfilter.plugin import OPAPluginFilter
from mcpgateway.plugins.framework import (
    PluginConfig,
    PluginContext,
    ToolPreInvokePayload,
    GlobalContext
)


@pytest.mark.asyncio
async def test_opapluginfilter():
    """Test plugin prompt prefetch hook."""
    config = PluginConfig(
        name="test",
        kind="opapluginfilter.OPAPluginFilter",
        hooks=["tool_pre_invoke"],
        config={"setting_one": "test_value"},
    )

    plugin = OPAPluginFilter(config)

    # Test your plugin logic
    payload = ToolPreInvokePayload(name="test_tool", args={"repo_path": "This is an argument"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.tool_pre_invoke(payload, context)
    import pdb
    pdb.set_trace()
    assert result.continue_processing
