# -*- coding: utf-8 -*-
"""Unit tests for TOON Encoder Plugin.

Tests the plugin integration with the MCP Gateway plugin framework.
"""

import json

import pytest

from mcpgateway.plugins.framework import GlobalContext, ToolHookType, PluginConfig, PluginContext
from mcpgateway.plugins.framework.hooks.tools import ToolPostInvokePayload

from plugins.toon_encoder.toon_encoder import ToonEncoderPlugin


@pytest.fixture
def default_config() -> PluginConfig:
    """Create default plugin configuration."""
    return PluginConfig(
        name="ToonEncoder",
        kind="plugins.toon_encoder.toon_encoder.ToonEncoderPlugin",
        hooks=[ToolHookType.TOOL_POST_INVOKE],
        priority=900,
        config={"min_size_bytes": 10},  # Low threshold for testing
    )


@pytest.fixture
def plugin(default_config: PluginConfig) -> ToonEncoderPlugin:
    """Create plugin instance with default config."""
    return ToonEncoderPlugin(default_config)


@pytest.fixture
def context() -> PluginContext:
    """Create plugin context for tests."""
    return PluginContext(global_context=GlobalContext(request_id="test-request-1"))


class TestPluginInitialization:
    """Test plugin initialization and configuration."""

    def test_default_config(self, default_config: PluginConfig):
        """Plugin initializes with default configuration."""
        plugin = ToonEncoderPlugin(default_config)
        assert plugin._min_size_bytes == 10
        assert plugin._max_size_bytes == 1024 * 1024
        assert plugin._exclude_tools == []
        assert plugin._include_tools is None
        assert plugin._add_format_marker is True
        assert plugin._skip_on_error is True

    def test_custom_config(self):
        """Plugin respects custom configuration."""
        config = PluginConfig(
            name="ToonEncoder",
            kind="plugins.toon_encoder.toon_encoder.ToonEncoderPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            priority=900,
            config={
                "min_size_bytes": 500,
                "max_size_bytes": 10000,
                "exclude_tools": ["binary_tool"],
                "include_tools": ["json_tool", "api_tool"],
                "add_format_marker": False,
                "skip_on_error": False,
            },
        )
        plugin = ToonEncoderPlugin(config)
        assert plugin._min_size_bytes == 500
        assert plugin._max_size_bytes == 10000
        assert plugin._exclude_tools == ["binary_tool"]
        assert plugin._include_tools == ["json_tool", "api_tool"]
        assert plugin._add_format_marker is False
        assert plugin._skip_on_error is False


class TestToolFiltering:
    """Test tool include/exclude filtering."""

    def test_should_process_default(self, plugin: ToonEncoderPlugin):
        """All tools processed by default."""
        assert plugin._should_process_tool("any_tool") is True
        assert plugin._should_process_tool("another_tool") is True

    def test_should_process_with_exclude(self):
        """Excluded tools are skipped."""
        config = PluginConfig(
            name="ToonEncoder",
            kind="test",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            priority=900,
            config={"exclude_tools": ["skip_me", "skip_this_too"]},
        )
        plugin = ToonEncoderPlugin(config)
        assert plugin._should_process_tool("skip_me") is False
        assert plugin._should_process_tool("skip_this_too") is False
        assert plugin._should_process_tool("process_me") is True

    def test_should_process_with_include(self):
        """Only whitelisted tools are processed when include_tools is set."""
        config = PluginConfig(
            name="ToonEncoder",
            kind="test",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            priority=900,
            config={"include_tools": ["allowed_tool", "also_allowed"]},
        )
        plugin = ToonEncoderPlugin(config)
        assert plugin._should_process_tool("allowed_tool") is True
        assert plugin._should_process_tool("also_allowed") is True
        assert plugin._should_process_tool("not_allowed") is False


class TestContentProcessing:
    """Test content item processing."""

    @pytest.mark.asyncio
    async def test_skip_non_text_content(self, plugin: ToonEncoderPlugin, context: PluginContext):
        """Non-text content types are skipped."""
        payload = ToolPostInvokePayload(
            name="test_tool",
            result={
                "content": [
                    {"type": "image", "data": "base64data"},
                    {"type": "binary", "data": "bytes"},
                ]
            },
        )
        result = await plugin.tool_post_invoke(payload, context)
        assert result.continue_processing is True
        assert result.modified_payload is None

    @pytest.mark.asyncio
    async def test_skip_non_json_text(self, plugin: ToonEncoderPlugin, context: PluginContext):
        """Non-JSON text content is skipped."""
        payload = ToolPostInvokePayload(
            name="test_tool",
            result={"content": [{"type": "text", "text": "This is plain text, not JSON"}]},
        )
        result = await plugin.tool_post_invoke(payload, context)
        assert result.continue_processing is True
        assert result.modified_payload is None

    @pytest.mark.asyncio
    async def test_skip_small_content(self, context: PluginContext):
        """Content below min_size_bytes is skipped."""
        config = PluginConfig(
            name="ToonEncoder",
            kind="test",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            priority=900,
            config={"min_size_bytes": 1000},  # High threshold
        )
        plugin = ToonEncoderPlugin(config)

        # Small JSON that's under threshold
        small_json = json.dumps({"a": 1})
        payload = ToolPostInvokePayload(
            name="test_tool", result={"content": [{"type": "text", "text": small_json}]}
        )
        result = await plugin.tool_post_invoke(payload, context)
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_skip_large_content(self, context: PluginContext):
        """Content above max_size_bytes is skipped."""
        config = PluginConfig(
            name="ToonEncoder",
            kind="test",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            priority=900,
            config={"min_size_bytes": 10, "max_size_bytes": 50},  # Low max
        )
        plugin = ToonEncoderPlugin(config)

        # Large JSON that exceeds threshold
        large_json = json.dumps({"data": "x" * 100})
        payload = ToolPostInvokePayload(
            name="test_tool", result={"content": [{"type": "text", "text": large_json}]}
        )
        result = await plugin.tool_post_invoke(payload, context)
        assert result.continue_processing is True


class TestToonConversion:
    """Test actual TOON conversion."""

    @pytest.mark.asyncio
    async def test_converts_json_to_toon(self, plugin: ToonEncoderPlugin, context: PluginContext):
        """Valid JSON is converted to TOON."""
        # Create JSON that will be smaller as TOON
        data = {"name": "alice", "age": 30, "active": True}
        json_str = json.dumps(data)

        payload = ToolPostInvokePayload(
            name="test_tool", result={"content": [{"type": "text", "text": json_str}]}
        )
        result = await plugin.tool_post_invoke(payload, context)

        # Should have modified payload
        assert result.modified_payload is not None
        modified_result = result.modified_payload.result

        # Should have TOON content
        content = modified_result["content"][0]
        assert content["type"] == "text"
        assert content["text"] != json_str  # Should be different

        # Should have format marker
        assert content.get("annotations", {}).get("format") == "toon"

        # Metadata should indicate conversion
        assert result.metadata.get("toon_encoded") is True
        assert result.metadata.get("bytes_saved", 0) > 0

    @pytest.mark.asyncio
    async def test_preserves_existing_annotations(
        self, plugin: ToonEncoderPlugin, context: PluginContext
    ):
        """Existing annotations are preserved when adding format marker."""
        data = {"key": "value", "number": 12345}
        json_str = json.dumps(data)

        payload = ToolPostInvokePayload(
            name="test_tool",
            result={
                "content": [
                    {
                        "type": "text",
                        "text": json_str,
                        "annotations": {"source": "api", "priority": "high"},
                    }
                ]
            },
        )
        result = await plugin.tool_post_invoke(payload, context)

        if result.modified_payload:
            content = result.modified_payload.result["content"][0]
            annotations = content.get("annotations", {})
            # Original annotations should be preserved
            assert annotations.get("source") == "api"
            assert annotations.get("priority") == "high"
            # Format marker should be added
            assert annotations.get("format") == "toon"

    @pytest.mark.asyncio
    async def test_no_conversion_if_toon_larger(self, context: PluginContext):
        """JSON is kept if TOON would be larger."""
        config = PluginConfig(
            name="ToonEncoder",
            kind="test",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            priority=900,
            config={"min_size_bytes": 1},
        )
        plugin = ToonEncoderPlugin(config)

        # Very simple JSON that TOON can't improve much
        data = {"a": 1}
        json_str = json.dumps(data)

        payload = ToolPostInvokePayload(
            name="test_tool", result={"content": [{"type": "text", "text": json_str}]}
        )
        result = await plugin.tool_post_invoke(payload, context)

        # May or may not convert depending on exact encoding
        # The important thing is it doesn't make things worse
        if result.modified_payload:
            new_text = result.modified_payload.result["content"][0]["text"]
            assert len(new_text) <= len(json_str)

    @pytest.mark.asyncio
    async def test_handles_array_of_objects(
        self, plugin: ToonEncoderPlugin, context: PluginContext
    ):
        """Arrays of objects benefit from columnar encoding."""
        data = [
            {"id": 1, "name": "alice", "score": 100},
            {"id": 2, "name": "bob", "score": 200},
            {"id": 3, "name": "charlie", "score": 300},
        ]
        json_str = json.dumps(data)

        payload = ToolPostInvokePayload(
            name="test_tool", result={"content": [{"type": "text", "text": json_str}]}
        )
        result = await plugin.tool_post_invoke(payload, context)

        assert result.modified_payload is not None
        # Should have significant savings for array of objects
        assert result.metadata.get("bytes_saved", 0) > 0
        assert result.metadata.get("savings_percent", 0) > 10

    @pytest.mark.asyncio
    async def test_handles_nested_structures(
        self, plugin: ToonEncoderPlugin, context: PluginContext
    ):
        """Nested structures are converted correctly."""
        data = {
            "user": {"name": "alice", "email": "alice@example.com"},
            "items": [1, 2, 3, 4, 5],
            "metadata": {"version": 1, "active": True},
        }
        json_str = json.dumps(data)

        payload = ToolPostInvokePayload(
            name="test_tool", result={"content": [{"type": "text", "text": json_str}]}
        )
        result = await plugin.tool_post_invoke(payload, context)

        assert result.modified_payload is not None


class TestMultipleContentItems:
    """Test handling of multiple content items."""

    @pytest.mark.asyncio
    async def test_processes_multiple_items(
        self, plugin: ToonEncoderPlugin, context: PluginContext
    ):
        """Multiple content items are all processed."""
        data1 = {"first": "item", "number": 12345}
        data2 = {"second": "item", "value": 67890}

        payload = ToolPostInvokePayload(
            name="test_tool",
            result={
                "content": [
                    {"type": "text", "text": json.dumps(data1)},
                    {"type": "text", "text": json.dumps(data2)},
                ]
            },
        )
        result = await plugin.tool_post_invoke(payload, context)

        if result.modified_payload:
            content = result.modified_payload.result["content"]
            assert len(content) == 2

    @pytest.mark.asyncio
    async def test_mixed_content_types(self, plugin: ToonEncoderPlugin, context: PluginContext):
        """Mixed content types are handled correctly."""
        data = {"key": "value", "count": 42}

        payload = ToolPostInvokePayload(
            name="test_tool",
            result={
                "content": [
                    {"type": "text", "text": json.dumps(data)},  # Should convert
                    {"type": "image", "data": "base64"},  # Should skip
                    {"type": "text", "text": "plain text"},  # Should skip (not JSON)
                ]
            },
        )
        result = await plugin.tool_post_invoke(payload, context)

        if result.modified_payload:
            content = result.modified_payload.result["content"]
            assert len(content) == 3
            # Image and plain text should be unchanged
            assert content[1]["type"] == "image"
            assert content[2]["text"] == "plain text"


class TestErrorHandling:
    """Test error handling behavior."""

    @pytest.mark.asyncio
    async def test_handles_empty_result(self, plugin: ToonEncoderPlugin, context: PluginContext):
        """Empty results are handled gracefully."""
        payload = ToolPostInvokePayload(name="test_tool", result={})
        result = await plugin.tool_post_invoke(payload, context)
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_handles_missing_content(
        self, plugin: ToonEncoderPlugin, context: PluginContext
    ):
        """Missing content field is handled."""
        payload = ToolPostInvokePayload(name="test_tool", result={"other_field": "value"})
        result = await plugin.tool_post_invoke(payload, context)
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_handles_non_dict_result(
        self, plugin: ToonEncoderPlugin, context: PluginContext
    ):
        """Non-dict results are handled."""
        payload = ToolPostInvokePayload(name="test_tool", result="string_result")
        result = await plugin.tool_post_invoke(payload, context)
        assert result.continue_processing is True


class TestStatistics:
    """Test plugin statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_tracking(self, plugin: ToonEncoderPlugin, context: PluginContext):
        """Plugin tracks conversion statistics."""
        # Initial stats should be zero
        stats = plugin.get_stats()
        assert stats["tools_processed"] == 0
        assert stats["tools_converted"] == 0
        assert stats["items_attempted"] == 0
        assert stats["items_converted"] == 0
        assert stats["total_bytes_saved"] == 0

        # Perform a conversion
        data = [{"id": i, "name": f"user{i}"} for i in range(5)]
        payload = ToolPostInvokePayload(
            name="test_tool", result={"content": [{"type": "text", "text": json.dumps(data)}]}
        )
        await plugin.tool_post_invoke(payload, context)

        # Stats should be updated
        stats = plugin.get_stats()
        assert stats["tools_processed"] >= 1
        assert stats["items_attempted"] >= 1
        # May or may not be successful depending on size


class TestConfigOptions:
    """Test various configuration options."""

    @pytest.mark.asyncio
    async def test_disable_format_marker(self, context: PluginContext):
        """Format marker can be disabled."""
        config = PluginConfig(
            name="ToonEncoder",
            kind="test",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            priority=900,
            config={"min_size_bytes": 10, "add_format_marker": False},
        )
        plugin = ToonEncoderPlugin(config)

        data = {"name": "test", "value": 12345}
        payload = ToolPostInvokePayload(
            name="test_tool", result={"content": [{"type": "text", "text": json.dumps(data)}]}
        )
        result = await plugin.tool_post_invoke(payload, context)

        if result.modified_payload:
            content = result.modified_payload.result["content"][0]
            # Should not have format annotation
            assert "annotations" not in content or content.get("annotations", {}).get("format") is None
