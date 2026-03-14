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
from plugins.json_repair import json_repair as json_repair_module


@pytest.fixture
def plugin_config() -> PluginConfig:
    return PluginConfig(
        name="jsonr",
        kind="plugins.json_repair.json_repair.JSONRepairPlugin",
        hooks=[ToolHookType.TOOL_POST_INVOKE],
    )


@pytest.fixture
def plugin_ctx() -> PluginContext:
    return PluginContext(global_context=GlobalContext(request_id="r1"))


@pytest.fixture(params=["normal", "python_fallback"])
def mode(request):
    """Fixture to run tests in both normal mode and Python fallback mode."""
    return request.param


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw, expect_repaired",
    [
        ("{'a': 1, 'b': 2,}", True),  # Single quotes and trailing comma
        ('{"a": 1, "b": 2,}', True),  # Double quotes but trailing comma
        ('"a": 1, "b": 2', True),  # Missing outer braces
        ('{"a": 1, "b": 2}', False),  # Valid JSON
        ("not-json-at-all", False),  # Not JSON at all, unrepairable
    ],
)
async def test_json_repair_parity(raw, expect_repaired, mode, plugin_config, plugin_ctx, monkeypatch):
    """Test that JSON repair works correctly in both normal and Python fallback modes."""
    if mode == "python_fallback":
        monkeypatch.setattr(json_repair_module, "_RUST_AVAILABLE", False)
        monkeypatch.setattr(json_repair_module, "JSONRepairPluginRust", None)

    plugin = json_repair_module.JSONRepairPlugin(plugin_config)
    res = await plugin.tool_post_invoke(ToolPostInvokePayload(name="x", result=raw), plugin_ctx)

    # Check if repair was expected and validate results accordingly
    if expect_repaired:
        assert res.modified_payload is not None
        assert res.metadata == {"repaired": True}
        json.loads(res.modified_payload.result)  # Should not raise
    else:
        assert res.modified_payload is None  # No modification expected


class _BoomRust:
    def repair(self, _text):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_rust_exception_falls_back_to_python(monkeypatch, plugin_config, plugin_ctx):
    """Test that if the Rust implementation raises an exception, the plugin falls back to the Python repair method."""

    monkeypatch.setattr(json_repair_module, "_RUST_AVAILABLE", True)
    monkeypatch.setattr(json_repair_module, "JSONRepairPluginRust", lambda: _BoomRust())

    plugin = json_repair_module.JSONRepairPlugin(plugin_config)
    raw = "{'a': 1, 'b': 2,}"
    res = await plugin.tool_post_invoke(ToolPostInvokePayload(name="x", result=raw), plugin_ctx)

    assert res.modified_payload is not None
    assert res.metadata == {"repaired": True}
    json.loads(res.modified_payload.result)  # Should not raise
