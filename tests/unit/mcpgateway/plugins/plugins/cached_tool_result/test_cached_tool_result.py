# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/cached_tool_result/test_cached_tool_result.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for CachedToolResultPlugin.
"""

import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolHookType,
    ToolPreInvokePayload,
    ToolPostInvokePayload,
)
from plugins.cached_tool_result.cached_tool_result import CachedToolResultPlugin


@pytest.mark.asyncio
async def test_cache_store_and_hit():
    plugin = CachedToolResultPlugin(
        PluginConfig(
            name="cache",
            kind="plugins.cached_tool_result.cached_tool_result.CachedToolResultPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
            config={"cacheable_tools": ["echo"], "ttl": 60},
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    pre = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="echo", args={"x": 1}), ctx)
    assert pre.metadata and pre.metadata.get("cache_hit") is False
    # store
    post = await plugin.tool_post_invoke(ToolPostInvokePayload(name="echo", result={"ok": True}), ctx)
    assert post.metadata and post.metadata.get("cache_stored") is True
    # check next pre sees a hit
    ctx2 = PluginContext(global_context=GlobalContext(request_id="r2"))
    pre2 = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="echo", args={"x": 1}), ctx2)
    assert pre2.metadata and pre2.metadata.get("cache_hit") is True
