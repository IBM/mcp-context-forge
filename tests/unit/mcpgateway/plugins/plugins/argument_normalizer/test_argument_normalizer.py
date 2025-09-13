# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/argument_normalizer/test_argument_normalizer.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for Argument Normalizer Plugin.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    HookType,
    PluginConfig,
    PluginContext,
    PromptPrehookPayload,
    ToolPreInvokePayload,
)

from plugins.argument_normalizer.argument_normalizer import (
    ArgumentNormalizerConfig,
    ArgumentNormalizerPlugin,
)


def _mk_plugin(config: dict | None = None) -> ArgumentNormalizerPlugin:
    cfg = PluginConfig(
        name="arg_norm",
        kind="plugins.argument_normalizer.argument_normalizer.ArgumentNormalizerPlugin",
        hooks=[HookType.PROMPT_PRE_FETCH, HookType.TOOL_PRE_INVOKE],
        priority=30,
        config=config or {},
    )
    return ArgumentNormalizerPlugin(cfg)


@pytest.mark.asyncio
async def test_whitespace_and_unicode_normalization_prompt_pre():
    plugin = _mk_plugin(
        {
            "enable_unicode": True,
            "unicode_form": "NFC",
            "enable_whitespace": True,
            "trim": True,
            "collapse_internal": True,
            "normalize_newlines": True,
        }
    )
    # "e" + combining acute accent
    raw = "  He\u006C\u006C\u006F   W\u006F\u0072\u006C\u0064  \r\n" + "Cafe\u0301"
    payload = PromptPrehookPayload(name="greet", args={"text": raw})
    ctx = PluginContext(global_context=GlobalContext(request_id="t1"))

    res = await plugin.prompt_pre_fetch(payload, ctx)
    assert res.modified_payload is not None
    out = res.modified_payload.args["text"]
    # Whitespace collapsed and trimmed, newlines normalized
    assert out.startswith("He") and out.endswith("Café")
    assert "  " not in out
    assert "\r" not in out


@pytest.mark.asyncio
async def test_casing_and_numbers():
    plugin = _mk_plugin(
        {
            "enable_casing": True,
            "case_strategy": "lower",
            "enable_numbers": True,
            "decimal_detection": "auto",
        }
    )
    payload = PromptPrehookPayload(name="case", args={"v": "  JOHN DOE owes 1.234,56 EUR  "})
    ctx = PluginContext(global_context=GlobalContext(request_id="t2"))

    res = await plugin.prompt_pre_fetch(payload, ctx)
    assert res.modified_payload is not None
    out = res.modified_payload.args["v"]
    assert out.startswith("john doe owes ")
    assert "1234.56" in out


@pytest.mark.asyncio
async def test_dates_day_first_and_mdy():
    # day_first = True to interpret 31/12/2023
    plugin = _mk_plugin({"enable_dates": True, "day_first": True})
    payload = PromptPrehookPayload(name="dates", args={"a": "Due 31/12/2023", "b": "Start 12/31/2023"})
    ctx = PluginContext(global_context=GlobalContext(request_id="t3"))
    res = await plugin.prompt_pre_fetch(payload, ctx)
    assert res.modified_payload is not None
    a = res.modified_payload.args["a"]
    b = res.modified_payload.args["b"]
    assert "2023-12-31" in a
    # For b, day_first still applies to ambiguous; 12/31 becomes month/day (invalid day 31 for month 12 is valid), expect 2023-12-31
    assert "2023-12-31" in b


@pytest.mark.asyncio
async def test_tool_pre_invoke_nested_structures():
    plugin = _mk_plugin({"enable_casing": True, "case_strategy": "lower"})
    args = {"user": {"name": "  ALICE  ", "tags": ["  DEV ", "OPS  "]}}
    payload = ToolPreInvokePayload(name="toolX", args=args)
    ctx = PluginContext(global_context=GlobalContext(request_id="t4"))
    res = await plugin.tool_pre_invoke(payload, ctx)
    assert res.modified_payload is not None
    norm = res.modified_payload.args
    assert norm["user"]["name"] == "alice"
    assert norm["user"]["tags"] == ["dev", "ops"]
