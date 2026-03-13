# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/json_prune/test_json_prune.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Alexander Wiegand

Tests for JSONPrunePlugin.
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
from plugins.json_prune.json_prune import JSONPrunePlugin, _get_pruned


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plugin(webhooks=None, debug=False):
    """Create a JSONPrunePlugin with given webhooks config."""
    config = {}
    if webhooks is not None:
        config["webhooks"] = webhooks
    config["debug"] = debug
    return JSONPrunePlugin(
        PluginConfig(
            name="json_prune",
            kind="plugins.json_prune.json_prune.JSONPrunePlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            config=config,
        )
    )


def _ctx():
    """Create a minimal PluginContext."""
    return PluginContext(global_context=GlobalContext(request_id="test"))


# ===========================================================================
# TestGetPruned - 7 tests
# ===========================================================================


class TestGetPruned:
    """Tests for the _get_pruned recursive helper."""

    def test_flat_single_field(self):
        """Keep a single top-level field."""
        data = {"name": "Alice", "age": 30, "email": "a@b.com"}
        assert _get_pruned(data, ["name"]) == {"name": "Alice"}

    def test_flat_multi_fields(self):
        """Keep multiple top-level fields."""
        data = {"name": "Alice", "age": 30, "email": "a@b.com"}
        result = _get_pruned(data, ["name", "age"])
        assert result == {"name": "Alice", "age": 30}

    def test_nested_dict(self):
        """Keep a nested path."""
        data = {"user": {"name": "Alice", "age": 30}, "meta": "x"}
        assert _get_pruned(data, ["user.name"]) == {"user": {"name": "Alice"}}

    def test_list_of_dicts(self):
        """Prune each element of a top-level list."""
        data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        assert _get_pruned(data, ["name"]) == [{"name": "Alice"}, {"name": "Bob"}]

    def test_empty_whitelist(self):
        """Empty whitelist returns empty dict."""
        data = {"name": "Alice", "age": 30}
        assert _get_pruned(data, []) == {}

    def test_scalar_passthrough(self):
        """Scalars pass through unchanged."""
        assert _get_pruned(42, ["anything"]) == 42
        assert _get_pruned("hello", []) == "hello"

    def test_deeply_nested(self):
        """Three levels of nesting."""
        data = {"a": {"b": {"c": "deep", "d": "drop"}, "e": "drop"}}
        assert _get_pruned(data, ["a.b.c"]) == {"a": {"b": {"c": "deep"}}}


# ===========================================================================
# TestJSONPrunePluginStringResult - 5 tests
# ===========================================================================


class TestJSONPrunePluginStringResult:
    """Tests for string-type tool results."""

    @pytest.mark.asyncio
    async def test_basic_prune(self):
        """Prune a plain JSON string result."""
        plugin = _make_plugin(webhooks=[{"name": "api", "fields": ["name"]}])
        payload = ToolPostInvokePayload(name="api", result='{"name": "Alice", "age": 30}')
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is not None
        parsed = json.loads(res.modified_payload.result)
        assert parsed == {"name": "Alice"}
        assert res.metadata.get("pruned") is True

    @pytest.mark.asyncio
    async def test_nested_prune(self):
        """Prune nested fields from a string result."""
        plugin = _make_plugin(webhooks=[{"name": "api", "fields": ["user.name"]}])
        payload = ToolPostInvokePayload(
            name="api",
            result='{"user": {"name": "Alice", "age": 30}, "meta": "x"}',
        )
        res = await plugin.tool_post_invoke(payload, _ctx())
        parsed = json.loads(res.modified_payload.result)
        assert parsed == {"user": {"name": "Alice"}}

    @pytest.mark.asyncio
    async def test_no_match_tool_passthrough(self):
        """Tool not in webhooks is passed through."""
        plugin = _make_plugin(webhooks=[{"name": "other", "fields": ["x"]}])
        payload = ToolPostInvokePayload(name="api", result='{"a": 1}')
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is None
        assert res.continue_processing is True

    @pytest.mark.asyncio
    async def test_non_json_passthrough(self):
        """Non-JSON string result is passed through."""
        plugin = _make_plugin(webhooks=[{"name": "api", "fields": ["x"]}])
        payload = ToolPostInvokePayload(name="api", result="not json at all")
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is None
        assert res.continue_processing is True

    @pytest.mark.asyncio
    async def test_empty_fields_prune(self):
        """Empty fields list prunes everything."""
        plugin = _make_plugin(webhooks=[{"name": "api", "fields": []}])
        payload = ToolPostInvokePayload(name="api", result='{"a": 1, "b": 2}')
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is not None
        parsed = json.loads(res.modified_payload.result)
        assert parsed == {}


# ===========================================================================
# TestJSONPrunePluginDictResult - 4 tests
# ===========================================================================


class TestJSONPrunePluginDictResult:
    """Tests for MCP content dict results."""

    @pytest.mark.asyncio
    async def test_content_dict_prune(self):
        """Prune JSON inside an MCP content dict."""
        plugin = _make_plugin(webhooks=[{"name": "api", "fields": ["title"]}])
        payload = ToolPostInvokePayload(
            name="api",
            result={
                "content": [{"type": "text", "text": '{"title": "Hello", "noise": "drop"}'}],
            },
        )
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is not None
        content_text = res.modified_payload.result["content"][0]["text"]
        parsed = json.loads(content_text)
        assert parsed == {"title": "Hello"}

    @pytest.mark.asyncio
    async def test_content_dict_non_json_text(self):
        """Non-JSON text inside content dict is passed through."""
        plugin = _make_plugin(webhooks=[{"name": "api", "fields": ["x"]}])
        payload = ToolPostInvokePayload(
            name="api",
            result={"content": [{"type": "text", "text": "not json"}]},
        )
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is None
        assert res.continue_processing is True

    @pytest.mark.asyncio
    async def test_empty_content(self):
        """Empty content list is passed through."""
        plugin = _make_plugin(webhooks=[{"name": "api", "fields": ["x"]}])
        payload = ToolPostInvokePayload(name="api", result={"content": []})
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is None
        assert res.continue_processing is True

    @pytest.mark.asyncio
    async def test_non_text_type(self):
        """Content item with non-text type is passed through."""
        plugin = _make_plugin(webhooks=[{"name": "api", "fields": ["x"]}])
        payload = ToolPostInvokePayload(
            name="api",
            result={"content": [{"type": "image", "data": "base64..."}]},
        )
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is None
        assert res.continue_processing is True


# ===========================================================================
# TestJSONPrunePluginDebugMode - 2 tests
# ===========================================================================


class TestJSONPrunePluginDebugMode:
    """Tests for debug mode logging."""

    @pytest.mark.asyncio
    async def test_debug_prune(self):
        """Debug mode still prunes correctly."""
        plugin = _make_plugin(webhooks=[{"name": "api", "fields": ["name"]}], debug=True)
        payload = ToolPostInvokePayload(name="api", result='{"name": "Alice", "age": 30}')
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is not None
        parsed = json.loads(res.modified_payload.result)
        assert parsed == {"name": "Alice"}

    @pytest.mark.asyncio
    async def test_debug_non_json_passthrough(self):
        """Debug mode passes through non-JSON with logging."""
        plugin = _make_plugin(webhooks=[{"name": "api", "fields": ["x"]}], debug=True)
        payload = ToolPostInvokePayload(name="api", result="not json")
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is None
        assert res.continue_processing is True


# ===========================================================================
# TestJSONPrunePluginEdgeCases - 3 tests
# ===========================================================================


class TestJSONPrunePluginEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_non_dict_non_string_result(self):
        """Non-dict, non-string result types are passed through."""
        plugin = _make_plugin(webhooks=[{"name": "api", "fields": ["x"]}])
        payload = ToolPostInvokePayload(name="api", result=12345)
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is None
        assert res.continue_processing is True

    @pytest.mark.asyncio
    async def test_no_webhooks(self):
        """Plugin with empty webhooks passes everything through."""
        plugin = _make_plugin(webhooks=[])
        payload = ToolPostInvokePayload(name="api", result='{"a": 1}')
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is None
        assert res.continue_processing is True

    @pytest.mark.asyncio
    async def test_no_config(self):
        """Plugin with no config at all works."""
        plugin = JSONPrunePlugin(
            PluginConfig(
                name="json_prune",
                kind="plugins.json_prune.json_prune.JSONPrunePlugin",
                hooks=[ToolHookType.TOOL_POST_INVOKE],
            )
        )
        payload = ToolPostInvokePayload(name="api", result='{"a": 1}')
        res = await plugin.tool_post_invoke(payload, _ctx())
        assert res.modified_payload is None
        assert res.continue_processing is True
