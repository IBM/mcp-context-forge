# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/altk_json_processor/test_json_processor.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jason Tsay

Tests for ALTKJsonProcessor.
"""

# Standard
import json

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolHookType,
    ToolPostInvokePayload,
)

# ALTK is an optional dependency and may not be present, skip if not
have_altk = True
try:
    # Third-Party
    import altk  # noqa: F401 # type: ignore

    # First-Party
    from plugins.altk_json_processor.json_processor import ALTKJsonProcessor
except ModuleNotFoundError:
    have_altk = False


@pytest.mark.asyncio
@pytest.mark.skipif(not have_altk, reason="altk not available")
async def test_threshold():
    plugin = ALTKJsonProcessor(  # type: ignore
        PluginConfig(
            name="jsonprocessor", kind="plugins.altk_json_processor.json_processor.ALTKJsonProcessor", hooks=[ToolHookType.TOOL_POST_INVOKE], config={"llm_provider": "pytestmock", "length_threshold": 50}
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    # below threshold, so the plugin should not activate
    too_short = {"a": "1", "b": "2"}
    too_short_payload = {"content": [{"type": "text", "text": json.dumps(too_short)}]}
    res = await plugin.tool_post_invoke(ToolPostInvokePayload(name="x1", result=too_short_payload), ctx)
    assert res.modified_payload is None
    long_enough = {
        "a": "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
        "b": "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.",
        "c": "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur.",
        "d": "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.",
    }
    # above threshold, so the plugin should activate
    long_enough_payload = {"content": [{"type": "text", "text": json.dumps(long_enough)}]}
    res = await plugin.tool_post_invoke(ToolPostInvokePayload(name="x2", result=long_enough_payload), ctx)
    assert res.modified_payload is not None
    assert res.modified_payload.result["content"][0]["text"] == "(filtered response)"
