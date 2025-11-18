# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/json_repair/test_json_repair.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for JSONRepairPlugin.
"""

import json
import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolHookType,
    ToolPostInvokePayload,
)
from plugins.json_repair.json_repair import JSONRepairPlugin


@pytest.mark.asyncio
async def test_repairs_trailing_commas_and_single_quotes():
    plugin = JSONRepairPlugin(
        PluginConfig(
            name="jsonr",
            kind="plugins.json_repair.json_repair.JSONRepairPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    broken = "{'a': 1, 'b': 2,}"
    res = await plugin.tool_post_invoke(ToolPostInvokePayload(name="x", result=broken), ctx)
    assert res.modified_payload is not None
    fixed = res.modified_payload.result
    json.loads(fixed)
