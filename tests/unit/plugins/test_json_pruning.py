# -*- coding: utf-8 -*-
"""Tests for JSON Pruning Plugin.
Location: ./tests/unit/plugins/test_json_pruning.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Matt Van Horn

Verifies all functionality:
1. Strip configured field names from dict results
2. Truncate arrays beyond max_array_items
3. Truncate strings beyond max_string_length
4. Limit nesting depth beyond max_depth
5. Handle JSON string results (parse, prune, re-serialize)
6. Handle non-JSON string results (string truncation only)
7. Handle list results
8. Pass through non-prunable types unchanged
9. No modification when nothing to prune
10. Custom configuration overrides
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
    ToolPostInvokePayload,
)
from plugins.json_pruning.json_pruning import (
    _prune,
    _try_parse_json,
    JSONPruningConfig,
    JSONPruningPlugin,
)


@pytest.fixture
def plugin():
    """Create a JSON pruning plugin with test configuration."""
    config = PluginConfig(
        name="test_pruning",
        kind="plugins.json_pruning.json_pruning.JSONPruningPlugin",
        version="0.1.0",
        author="test",
        hooks=["tool_post_invoke"],
        config={
            "strip_fields": ["_links", "debug", "_metadata"],
            "max_array_items": 3,
            "max_string_length": 20,
            "max_depth": 3,
        },
    )
    return JSONPruningPlugin(config)


@pytest.fixture
def default_plugin():
    """Create a JSON pruning plugin with default configuration."""
    config = PluginConfig(
        name="test_pruning_default",
        kind="plugins.json_pruning.json_pruning.JSONPruningPlugin",
        version="0.1.0",
        author="test",
        hooks=["tool_post_invoke"],
    )
    return JSONPruningPlugin(config)


@pytest.fixture
def context():
    """Create a plugin context for testing."""
    global_ctx = GlobalContext(request_id="test-request-123")
    return PluginContext(plugin_id="test_pruning", global_context=global_ctx)


class TestPruneFunction:
    """Tests for the _prune helper function."""

    def test_strip_fields_from_dict(self):
        """Strip configured field names from a dict."""
        cfg = JSONPruningConfig(strip_fields=["debug", "_links"])
        data = {"name": "test", "debug": {"verbose": True}, "_links": {"self": "/api/test"}, "value": 42}
        result, modified = _prune(data, cfg)
        assert modified is True
        assert "debug" not in result
        assert "_links" not in result
        assert result["name"] == "test"
        assert result["value"] == 42

    def test_strip_nested_fields(self):
        """Strip fields from nested dicts."""
        cfg = JSONPruningConfig(strip_fields=["debug"])
        data = {"outer": {"inner": {"debug": "remove me", "keep": "this"}}}
        result, modified = _prune(data, cfg)
        assert modified is True
        assert "debug" not in result["outer"]["inner"]
        assert result["outer"]["inner"]["keep"] == "this"

    def test_no_modification_when_nothing_to_strip(self):
        """Return unmodified when no fields match."""
        cfg = JSONPruningConfig(strip_fields=["nonexistent"])
        data = {"name": "test", "value": 42}
        result, modified = _prune(data, cfg)
        assert modified is False
        assert result == data

    def test_truncate_array(self):
        """Truncate arrays beyond max_array_items."""
        cfg = JSONPruningConfig(max_array_items=2, strip_fields=[])
        data = [1, 2, 3, 4, 5]
        result, modified = _prune(data, cfg)
        assert modified is True
        assert len(result) == 3  # 2 items + truncation notice
        assert result[0] == 1
        assert result[1] == 2
        assert "3 more items truncated" in result[2]

    def test_array_within_limit(self):
        """Do not truncate arrays within limit."""
        cfg = JSONPruningConfig(max_array_items=10, strip_fields=[])
        data = [1, 2, 3]
        result, modified = _prune(data, cfg)
        assert modified is False
        assert result == [1, 2, 3]

    def test_truncate_string(self):
        """Truncate strings beyond max_string_length."""
        cfg = JSONPruningConfig(max_string_length=10, strip_fields=[], string_truncation_suffix="...")
        long_string = "a" * 50
        result, modified = _prune(long_string, cfg)
        assert modified is True
        assert len(result) == 10  # 7 chars + "..."
        assert result.endswith("...")

    def test_string_within_limit(self):
        """Do not truncate strings within limit."""
        cfg = JSONPruningConfig(max_string_length=100, strip_fields=[])
        short_string = "hello"
        result, modified = _prune(short_string, cfg)
        assert modified is False
        assert result == "hello"

    def test_max_depth_limit(self):
        """Replace content beyond max depth with placeholder."""
        cfg = JSONPruningConfig(max_depth=2, strip_fields=[], depth_placeholder="{...}")
        data = {"level1": {"level2": {"level3": "deep"}}}
        result, modified = _prune(data, cfg)
        assert modified is True
        assert result["level1"]["level2"] == "{...}"

    def test_max_depth_empty_containers_pass_through(self):
        """Empty containers at max depth are not replaced."""
        cfg = JSONPruningConfig(max_depth=1, strip_fields=[])
        data = {"level1": {}}
        result, modified = _prune(data, cfg)
        assert modified is False
        assert result == {"level1": {}}

    def test_primitives_pass_through(self):
        """Primitive types pass through unchanged."""
        cfg = JSONPruningConfig(strip_fields=[])
        for value in [42, 3.14, True, None]:
            result, modified = _prune(value, cfg)
            assert modified is False
            assert result == value

    def test_combined_pruning(self):
        """Multiple pruning rules apply together."""
        cfg = JSONPruningConfig(
            strip_fields=["debug"],
            max_array_items=2,
            max_string_length=10,
            max_depth=3,
            string_truncation_suffix="...",
        )
        data = {
            "debug": "remove",
            "items": [1, 2, 3, 4, 5],
            "description": "a" * 50,
        }
        result, modified = _prune(data, cfg)
        assert modified is True
        assert "debug" not in result
        assert len(result["items"]) == 3  # 2 + notice
        assert len(result["description"]) == 10


class TestTryParseJson:
    """Tests for the _try_parse_json helper."""

    def test_valid_json_object(self):
        """Parse a valid JSON object."""
        assert _try_parse_json('{"a": 1}') == {"a": 1}

    def test_valid_json_array(self):
        """Parse a valid JSON array."""
        assert _try_parse_json("[1, 2, 3]") == [1, 2, 3]

    def test_invalid_json(self):
        """Return None for invalid JSON."""
        assert _try_parse_json("not json") is None

    def test_empty_string(self):
        """Return None for empty string."""
        assert _try_parse_json("") is None

    def test_none_input(self):
        """Return None for None input."""
        assert _try_parse_json(None) is None


class TestJSONPruningPluginDictResult:
    """Test plugin with dict results."""

    @pytest.mark.asyncio
    async def test_strips_fields_from_dict(self, plugin, context):
        """Plugin strips configured fields from dict result."""
        payload = ToolPostInvokePayload(
            name="test_tool",
            result={"data": "keep", "debug": {"verbose": True}, "_links": {"self": "/api"}},
        )
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is not None
        pruned = result.modified_payload.result
        assert "data" in pruned
        assert "debug" not in pruned
        assert "_links" not in pruned
        assert result.metadata["pruned"] is True

    @pytest.mark.asyncio
    async def test_no_modification_clean_dict(self, plugin, context):
        """Plugin passes through dict with no matching fields."""
        payload = ToolPostInvokePayload(
            name="test_tool",
            result={"data": "keep", "status": "ok"},
        )
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is None
        assert result.continue_processing is True


class TestJSONPruningPluginStringResult:
    """Test plugin with string results."""

    @pytest.mark.asyncio
    async def test_prunes_json_string(self, plugin, context):
        """Plugin parses JSON string, prunes, and re-serializes."""
        json_str = json.dumps({"data": "keep", "debug": "remove"})
        payload = ToolPostInvokePayload(name="test_tool", result=json_str)
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is not None
        parsed = json.loads(result.modified_payload.result)
        assert "data" in parsed
        assert "debug" not in parsed

    @pytest.mark.asyncio
    async def test_truncates_non_json_string(self, plugin, context):
        """Plugin truncates non-JSON strings beyond max_string_length."""
        long_text = "x" * 100
        payload = ToolPostInvokePayload(name="test_tool", result=long_text)
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is not None
        assert len(result.modified_payload.result) <= 20 + len("...")

    @pytest.mark.asyncio
    async def test_short_non_json_string_passes(self, plugin, context):
        """Plugin passes through short non-JSON strings."""
        payload = ToolPostInvokePayload(name="test_tool", result="ok")
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is None
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_clean_json_string_passes(self, plugin, context):
        """Plugin passes through JSON string with nothing to prune."""
        json_str = json.dumps({"status": "ok"})
        payload = ToolPostInvokePayload(name="test_tool", result=json_str)
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is None
        assert result.continue_processing is True


class TestJSONPruningPluginListResult:
    """Test plugin with list results."""

    @pytest.mark.asyncio
    async def test_truncates_list(self, plugin, context):
        """Plugin truncates list beyond max_array_items."""
        payload = ToolPostInvokePayload(name="test_tool", result=[1, 2, 3, 4, 5, 6, 7])
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is not None
        pruned = result.modified_payload.result
        assert len(pruned) == 4  # 3 items + notice
        assert "4 more items truncated" in pruned[-1]

    @pytest.mark.asyncio
    async def test_list_within_limit_passes(self, plugin, context):
        """Plugin passes through list within limit."""
        payload = ToolPostInvokePayload(name="test_tool", result=[1, 2])
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is None
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_prunes_dicts_in_list(self, plugin, context):
        """Plugin prunes dict elements within a list."""
        payload = ToolPostInvokePayload(
            name="test_tool",
            result=[{"data": "keep", "debug": "remove"}, {"data": "also keep"}],
        )
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is not None
        pruned = result.modified_payload.result
        assert "debug" not in pruned[0]
        assert pruned[0]["data"] == "keep"


class TestJSONPruningPluginPassthrough:
    """Test plugin passthrough for unsupported types."""

    @pytest.mark.asyncio
    async def test_int_result_passes(self, plugin, context):
        """Plugin passes through integer results."""
        payload = ToolPostInvokePayload(name="test_tool", result=42)
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is None
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_none_result_passes(self, plugin, context):
        """Plugin passes through None results."""
        payload = ToolPostInvokePayload(name="test_tool", result=None)
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is None
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_bool_result_passes(self, plugin, context):
        """Plugin passes through boolean results."""
        payload = ToolPostInvokePayload(name="test_tool", result=True)
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is None
        assert result.continue_processing is True


class TestJSONPruningPluginDepthLimit:
    """Test depth limiting behavior."""

    @pytest.mark.asyncio
    async def test_deep_dict_pruned(self, plugin, context):
        """Plugin replaces deeply nested content with placeholder."""
        deep = {"l1": {"l2": {"l3": {"l4": "too deep"}}}}
        payload = ToolPostInvokePayload(name="test_tool", result=deep)
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is not None
        pruned = result.modified_payload.result
        assert pruned["l1"]["l2"]["l3"] == "{...}"

    @pytest.mark.asyncio
    async def test_shallow_dict_not_pruned(self, plugin, context):
        """Plugin does not prune shallow dicts."""
        shallow = {"l1": {"l2": "ok"}}
        payload = ToolPostInvokePayload(name="test_tool", result=shallow)
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload is None
        assert result.continue_processing is True


class TestJSONPruningConfig:
    """Test configuration handling."""

    def test_default_config(self):
        """Default config has sensible values."""
        cfg = JSONPruningConfig()
        assert "_links" in cfg.strip_fields
        assert cfg.max_array_items == 50
        assert cfg.max_string_length == 5000
        assert cfg.max_depth == 10

    def test_custom_config(self):
        """Custom config overrides defaults."""
        cfg = JSONPruningConfig(strip_fields=["custom"], max_array_items=10, max_string_length=100, max_depth=5)
        assert cfg.strip_fields == ["custom"]
        assert cfg.max_array_items == 10
        assert cfg.max_string_length == 100
        assert cfg.max_depth == 5

    def test_plugin_reads_config(self):
        """Plugin reads config from PluginConfig.config dict."""
        config = PluginConfig(
            name="test",
            kind="test",
            version="0.1.0",
            author="test",
            hooks=["tool_post_invoke"],
            config={"strip_fields": ["custom_field"], "max_depth": 5},
        )
        plugin = JSONPruningPlugin(config)
        assert plugin._cfg.strip_fields == ["custom_field"]
        assert plugin._cfg.max_depth == 5
        # Defaults still apply for unset values
        assert plugin._cfg.max_array_items == 50

    def test_plugin_with_no_config(self):
        """Plugin uses defaults when no config provided."""
        config = PluginConfig(
            name="test",
            kind="test",
            version="0.1.0",
            author="test",
            hooks=["tool_post_invoke"],
        )
        plugin = JSONPruningPlugin(config)
        assert plugin._cfg.max_depth == 10


class TestJSONPruningPluginMetadata:
    """Test metadata in results."""

    @pytest.mark.asyncio
    async def test_metadata_on_dict_prune(self, plugin, context):
        """Metadata indicates pruning occurred on dict."""
        payload = ToolPostInvokePayload(name="test_tool", result={"debug": "x", "data": "y"})
        result = await plugin.tool_post_invoke(payload, context)
        assert result.metadata["pruned"] is True
        assert result.metadata["result_type"] == "dict"

    @pytest.mark.asyncio
    async def test_metadata_on_json_string_prune(self, plugin, context):
        """Metadata indicates pruning occurred on JSON string."""
        payload = ToolPostInvokePayload(name="test_tool", result=json.dumps({"debug": "x"}))
        result = await plugin.tool_post_invoke(payload, context)
        assert result.metadata["pruned"] is True
        assert result.metadata["result_type"] == "json_string"

    @pytest.mark.asyncio
    async def test_metadata_on_string_truncation(self, plugin, context):
        """Metadata includes length info on string truncation."""
        long_text = "x" * 100
        payload = ToolPostInvokePayload(name="test_tool", result=long_text)
        result = await plugin.tool_post_invoke(payload, context)
        assert result.metadata["pruned"] is True
        assert result.metadata["original_length"] == 100

    @pytest.mark.asyncio
    async def test_metadata_on_list_prune(self, plugin, context):
        """Metadata indicates pruning occurred on list."""
        payload = ToolPostInvokePayload(name="test_tool", result=[{"debug": "x"}, {"data": "y"}])
        result = await plugin.tool_post_invoke(payload, context)
        assert result.metadata["pruned"] is True
        assert result.metadata["result_type"] == "list"
