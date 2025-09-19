# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/code_safety_linter/test_code_safety_linter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for CodeSafetyLinterPlugin.
"""

import pytest

from mcpgateway.plugins.framework.models import (
    GlobalContext,
    HookType,
    PluginConfig,
    PluginContext,
    ToolPostInvokePayload,
)
from plugins.code_safety_linter.code_safety_linter import CodeSafetyLinterPlugin


@pytest.mark.asyncio
async def test_detects_eval_pattern():
    plugin = CodeSafetyLinterPlugin(
        PluginConfig(
            name="csl",
            kind="plugins.code_safety_linter.code_safety_linter.CodeSafetyLinterPlugin",
            hooks=[HookType.TOOL_POST_INVOKE],
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    res = await plugin.tool_post_invoke(ToolPostInvokePayload(name="x", result="eval('2+2')"), ctx)
    assert res.violation is not None
