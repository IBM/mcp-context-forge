# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/output_length_guard/test_output_length_guard.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for Output Length Guard Plugin.
"""

# First-Party
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolHookType,
    ToolPostInvokePayload,
)

from plugins.output_length_guard.output_length_guard import (
    OutputLengthGuardPlugin,
)

import pytest


def _mk_plugin(config: dict | None = None) -> OutputLengthGuardPlugin:
    cfg = PluginConfig(
        name="out_len_guard",
        kind="plugins.output_length_guard.output_length_guard.OutputLengthGuardPlugin",
        hooks=[ToolHookType.TOOL_POST_INVOKE],
        priority=90,
        config=config or {},
    )
    return OutputLengthGuardPlugin(cfg)


@pytest.mark.asyncio
async def test_truncate_long_string():
    plugin = _mk_plugin({"max_chars": 10, "strategy": "truncate", "ellipsis": "..."})
    payload = ToolPostInvokePayload(name="writer", result="abcdefghijklmnopqrstuvwxyz")
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    res = await plugin.tool_post_invoke(payload, ctx)
    assert res.modified_payload is not None
    assert res.modified_payload.result == "abcdefg..."  # 7 + 3 dots = 10
    assert res.metadata and res.metadata.get("truncated") is True


@pytest.mark.asyncio
async def test_allow_under_min_when_truncate():
    plugin = _mk_plugin({"min_chars": 5, "max_chars": 50, "strategy": "truncate"})
    payload = ToolPostInvokePayload(name="writer", result="hey")
    ctx = PluginContext(global_context=GlobalContext(request_id="r2"))
    res = await plugin.tool_post_invoke(payload, ctx)
    # No modification, only metadata
    assert res.modified_payload is None
    assert res.metadata and res.metadata.get("within_bounds") is False


@pytest.mark.asyncio
async def test_block_when_out_of_bounds():
    plugin = _mk_plugin({"min_chars": 5, "max_chars": 10, "strategy": "block"})
    payload = ToolPostInvokePayload(name="writer", result="too short")
    ctx = PluginContext(global_context=GlobalContext(request_id="r3"))
    res = await plugin.tool_post_invoke(payload, ctx)
    # length is 9 -> in range, so not blocked
    assert res.violation is None
    # Now too long
    payload2 = ToolPostInvokePayload(name="writer", result="this is definitely too long")
    res2 = await plugin.tool_post_invoke(payload2, ctx)
    assert res2.violation is not None
    assert res2.continue_processing is False


@pytest.mark.asyncio
async def test_dict_text_field_handling():
    plugin = _mk_plugin({"max_chars": 5, "strategy": "truncate", "ellipsis": ""})
    payload = ToolPostInvokePayload(name="writer", result={"text": "123456789", "other": 1})
    ctx = PluginContext(global_context=GlobalContext(request_id="r4"))
    res = await plugin.tool_post_invoke(payload, ctx)
    assert res.modified_payload is not None
    assert res.modified_payload.result["text"] == "12345"
    assert res.modified_payload.result["other"] == 1


@pytest.mark.asyncio
async def test_list_of_strings():
    plugin = _mk_plugin({"max_chars": 3, "strategy": "truncate", "ellipsis": ""})
    payload = ToolPostInvokePayload(name="writer", result=["abcd", "ef", "ghijk"])
    ctx = PluginContext(global_context=GlobalContext(request_id="r5"))
    res = await plugin.tool_post_invoke(payload, ctx)
    assert res.modified_payload is not None
    assert res.modified_payload.result == ["abc", "ef", "ghi"]
