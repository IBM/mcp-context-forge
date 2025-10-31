# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/schema_guard/test_schema_guard.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for SchemaGuardPlugin.
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
from plugins.schema_guard.schema_guard import SchemaGuardPlugin


@pytest.mark.asyncio
async def test_schema_guard_valid_and_invalid():
    cfg = {
        "arg_schemas": {
            "calc": {
                "type": "object",
                "required": ["a", "b"],
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            }
        },
        "result_schemas": {"calc": {"type": "object", "required": ["result"], "properties": {"result": {"type": "number"}}}},
        "block_on_violation": True,
    }
    plugin = SchemaGuardPlugin(
        PluginConfig(
            name="sg",
            kind="plugins.schema_guard.schema_guard.SchemaGuardPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
            config=cfg,
        )
    )

    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    ok = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="calc", args={"a": 1, "b": 2}), ctx)
    assert ok.violation is None
    bad = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="calc", args={"a": 1}), ctx)
    assert bad.violation is not None

    res_ok = await plugin.tool_post_invoke(ToolPostInvokePayload(name="calc", result={"result": 3}), ctx)
    assert res_ok.violation is None
    res_bad = await plugin.tool_post_invoke(ToolPostInvokePayload(name="calc", result={}), ctx)
    assert res_bad.violation is not None
