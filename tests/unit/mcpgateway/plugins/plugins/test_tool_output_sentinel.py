# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/test_tool_output_sentinel.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the test-only tool output sentinel plugin.
"""

from __future__ import annotations

import pytest

from cpex.framework import PluginConfig, PluginContext, ToolHookType, ToolPostInvokePayload
from cpex.framework.models import GlobalContext
from plugins.test_tool_output_sentinel import ToolOutputSentinelPlugin


def _plugin() -> ToolOutputSentinelPlugin:
    """Build a configured sentinel plugin for unit tests.

    Returns:
        Configured plugin instance.
    """
    return ToolOutputSentinelPlugin(
        PluginConfig(
            name="ToolOutputSentinelPlugin",
            kind="plugins.test_tool_output_sentinel.ToolOutputSentinelPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            priority=10,
            config={"sentinel_text": "[UNIT-SENTINEL]", "separator": "\n"},
        )
    )


def _context() -> PluginContext:
    """Build a minimal plugin context.

    Returns:
        Minimal plugin context for unit tests.
    """
    return PluginContext(global_context=GlobalContext(request_id="test-tool-output-sentinel"))


@pytest.mark.asyncio
async def test_tool_post_invoke_appends_to_string_result() -> None:
    """String tool results should receive the sentinel suffix."""
    plugin = _plugin()
    result = await plugin.tool_post_invoke(ToolPostInvokePayload(name="demo-tool", result="hello"), _context())
    assert result.modified_payload is not None
    assert result.modified_payload.result == "hello\n[UNIT-SENTINEL]"


@pytest.mark.asyncio
async def test_tool_post_invoke_appends_to_mcp_content_result() -> None:
    """MCP content arrays should receive the sentinel on the first text item."""
    plugin = _plugin()
    payload = ToolPostInvokePayload(
        name="demo-tool",
        result={"content": [{"type": "text", "text": "2026-03-15T10:00:00Z"}], "isError": False},
    )

    result = await plugin.tool_post_invoke(payload, _context())

    assert result.modified_payload is not None
    modified = result.modified_payload.result
    assert modified["content"][0]["text"] == "2026-03-15T10:00:00Z\n[UNIT-SENTINEL]"


@pytest.mark.asyncio
async def test_tool_post_invoke_is_idempotent_for_existing_sentinel() -> None:
    """Existing sentinels should not be duplicated."""
    plugin = _plugin()
    payload = ToolPostInvokePayload(
        name="demo-tool",
        result={"content": [{"type": "text", "text": "hello\n[UNIT-SENTINEL]"}], "isError": False},
    )

    result = await plugin.tool_post_invoke(payload, _context())

    assert result.modified_payload is None
    assert result.continue_processing is True
