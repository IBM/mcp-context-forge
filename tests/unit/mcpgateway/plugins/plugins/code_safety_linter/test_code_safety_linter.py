# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/code_safety_linter/test_code_safety_linter.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for CodeSafetyLinterPlugin.
"""

import pytest

from cpex.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolHookType,
    ToolPostInvokePayload,
)
from plugins.code_safety_linter.code_safety_linter import CodeSafetyLinterPlugin


@pytest.mark.asyncio
async def test_detects_eval_pattern():
    plugin = CodeSafetyLinterPlugin(
        PluginConfig(
            name="csl",
            kind="plugins.code_safety_linter.code_safety_linter.CodeSafetyLinterPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    res = await plugin.tool_post_invoke(ToolPostInvokePayload(name="x", result="eval('2+2')"), ctx)
    assert res.violation is not None


@pytest.mark.asyncio
async def test_detects_eval_pattern_in_real_mcp_content_shape():
    """Regression test: real MCP tool results are dicts shaped like
    {"content": [{"type": "text", "text": "..."}], "structuredContent": {"result": "..."}},
    not a bare string and not {"text": "..."}. Prior to this fix, payload.result.get("text")
    always returned None for this shape, so the scan never ran and dangerous output was
    silently allowed through regardless of content. See issue/PR for a live-gateway
    reproduction: identical eval()/os.system()/rm -rf payloads passed through unblocked."""
    plugin = CodeSafetyLinterPlugin(
        PluginConfig(
            name="csl",
            kind="plugins.code_safety_linter.code_safety_linter.CodeSafetyLinterPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    real_shape_result = {
        "content": [{"type": "text", "text": "output containing eval('2+2') here"}],
        "isError": False,
        "structuredContent": {"result": "output containing eval('2+2') here"},
    }
    res = await plugin.tool_post_invoke(ToolPostInvokePayload(name="x", result=real_shape_result), ctx)
    assert res.violation is not None


@pytest.mark.asyncio
async def test_allows_real_mcp_content_shape_without_dangerous_pattern():
    """Sanity check: the real-shape extraction should not false-positive on benign output."""
    plugin = CodeSafetyLinterPlugin(
        PluginConfig(
            name="csl",
            kind="plugins.code_safety_linter.code_safety_linter.CodeSafetyLinterPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    benign_result = {
        "content": [{"type": "text", "text": "Hello, world!"}],
        "isError": False,
        "structuredContent": {"result": "Hello, world!"},
    }
    res = await plugin.tool_post_invoke(ToolPostInvokePayload(name="x", result=benign_result), ctx)
    assert res.violation is None
