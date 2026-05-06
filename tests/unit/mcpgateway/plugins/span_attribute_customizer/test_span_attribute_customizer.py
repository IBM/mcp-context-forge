# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/span_attribute_customizer/test_span_attribute_customizer.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for SpanAttributeCustomizer plugin.
"""

import pytest

from cpex.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ResourceHookType,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)
from plugins.span_attribute_customizer.config_schema import (
    AttributeTransformation,
    ConditionalAttribute,
    SpanAttributeCustomizerConfig,
    ToolOverride,
)
from plugins.span_attribute_customizer.span_attribute_customizer import SpanAttributeCustomizerPlugin


@pytest.fixture
def basic_plugin_config():
    """Create a basic plugin configuration."""
    return PluginConfig(
        name="SpanAttributeCustomizer",
        kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
        hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
        priority=10,
        config={
            "global_attributes": {"environment": "test", "region": "us-east-1"},
            "tool_overrides": {},
            "transformations": [],
            "conditions": [],
            "remove_attributes": [],
        },
    )


@pytest.fixture
def plugin_context():
    """Create a plugin context with global context."""
    global_ctx = GlobalContext(request_id="test-request-123")
    return PluginContext(global_context=global_ctx)


class TestSpanAttributeCustomizerPlugin:
    """Test suite for SpanAttributeCustomizer plugin."""

    def test_plugin_initialization(self, basic_plugin_config):
        """Test plugin initializes correctly with basic config."""
        plugin = SpanAttributeCustomizerPlugin(basic_plugin_config)
        assert plugin is not None
        assert plugin.cfg.global_attributes == {"environment": "test", "region": "us-east-1"}

    def test_plugin_initialization_with_empty_config(self):
        """Test plugin initializes with empty configuration."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={},
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        assert plugin.cfg.global_attributes == {}
        assert plugin.cfg.tool_overrides == {}

    @pytest.mark.asyncio
    async def test_global_attributes_added(self, basic_plugin_config, plugin_context):
        """Test global attributes are added to context state."""
        plugin = SpanAttributeCustomizerPlugin(basic_plugin_config)
        payload = ToolPreInvokePayload(name="test_tool", arguments={"arg1": "value1"})

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        assert "custom_span_attributes" in plugin_context.global_context.state
        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        assert custom_attrs["environment"] == "test"
        assert custom_attrs["region"] == "us-east-1"
        assert result.metadata["span_customizer"]["attributes_added"] == 2

    @pytest.mark.asyncio
    async def test_tool_specific_overrides(self, plugin_context):
        """Test per-tool attribute overrides."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"environment": "test"},
                "tool_overrides": {"weather_api": {"attributes": {"service": "weather", "cost_center": "engineering"}}},
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="weather_api", arguments={})

        result = await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        assert custom_attrs["environment"] == "test"
        assert custom_attrs["service"] == "weather"
        assert custom_attrs["cost_center"] == "engineering"

    @pytest.mark.asyncio
    async def test_attribute_removal(self, plugin_context):
        """Test attribute removal functionality."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"environment": "test", "debug_info": "sensitive"},
                "remove_attributes": ["debug_info"],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        removal_list = plugin_context.global_context.state["remove_span_attributes"]
        assert "debug_info" in removal_list

    @pytest.mark.asyncio
    async def test_tool_specific_removal(self, plugin_context):
        """Test per-tool attribute removal."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"environment": "test"},
                "tool_overrides": {"sensitive_tool": {"remove_attributes": ["tool.arguments"]}},
                "remove_attributes": ["global_debug"],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="sensitive_tool", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        removal_list = plugin_context.global_context.state["remove_span_attributes"]
        assert "global_debug" in removal_list
        assert "tool.arguments" in removal_list

    @pytest.mark.asyncio
    async def test_hash_transformation(self, plugin_context):
        """Test hash transformation operation."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"user_email": "test@example.com"},
                "transformations": [{"field": "user_email", "operation": "hash"}],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        # Hash should be 32 characters (HMAC-SHA-256 truncated)
        assert len(custom_attrs["user_email"]) == 32
        assert custom_attrs["user_email"] != "test@example.com"

    @pytest.mark.asyncio
    async def test_uppercase_transformation(self, plugin_context):
        """Test uppercase transformation operation."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"team_id": "team-alpha"},
                "transformations": [{"field": "team_id", "operation": "uppercase"}],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        assert custom_attrs["team_id"] == "TEAM-ALPHA"

    @pytest.mark.asyncio
    async def test_lowercase_transformation(self, plugin_context):
        """Test lowercase transformation operation."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"service_name": "WEATHER-API"},
                "transformations": [{"field": "service_name", "operation": "lowercase"}],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        assert custom_attrs["service_name"] == "weather-api"

    @pytest.mark.asyncio
    async def test_truncate_transformation(self, plugin_context):
        """Test truncate transformation operation."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"description": "This is a very long description that should be truncated"},
                "transformations": [{"field": "description", "operation": "truncate", "params": {"max_length": 20}}],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        assert len(custom_attrs["description"]) == 20
        assert custom_attrs["description"] == "This is a very long "

    @pytest.mark.asyncio
    async def test_truncate_default_length(self, plugin_context):
        """Test truncate transformation with default max_length."""
        long_text = "x" * 100
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"text": long_text},
                "transformations": [{"field": "text", "operation": "truncate"}],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        assert len(custom_attrs["text"]) == 50  # Default max_length

    @pytest.mark.asyncio
    async def test_conditional_attributes_match(self, plugin_context):
        """Test conditional attributes when condition matches."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"environment": "test"},
                "conditions": [{"when": 'tool.name == "sensitive_operation"', "add": {"audit_required": True, "compliance_level": "high"}}],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="sensitive_operation", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        assert custom_attrs["audit_required"] is True
        assert custom_attrs["compliance_level"] == "high"

    @pytest.mark.asyncio
    async def test_conditional_attributes_no_match(self, plugin_context):
        """Test conditional attributes when condition doesn't match."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"environment": "test"},
                "conditions": [{"when": 'tool.name == "sensitive_operation"', "add": {"audit_required": True}}],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="normal_operation", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        assert "audit_required" not in custom_attrs

    @pytest.mark.asyncio
    async def test_multiple_transformations(self, plugin_context):
        """Test multiple transformations applied in sequence."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"email": "test@example.com", "team": "alpha"},
                "transformations": [{"field": "email", "operation": "hash"}, {"field": "team", "operation": "uppercase"}],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        assert len(custom_attrs["email"]) == 32  # Hashed (HMAC-SHA256 truncated to 32 chars)
        assert custom_attrs["team"] == "ALPHA"  # Uppercased

    @pytest.mark.asyncio
    async def test_unknown_transformation_operation(self, plugin_context):
        """Test that unknown transformation operations are handled gracefully."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"field": "value"},
                "transformations": [{"field": "field", "operation": "unknown_op"}],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        # Should keep original value when transformation fails
        assert custom_attrs["field"] == "value"

    @pytest.mark.asyncio
    async def test_transformation_on_nonexistent_field(self, plugin_context):
        """Test transformation on field that doesn't exist."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"field1": "value1"},
                "transformations": [{"field": "nonexistent_field", "operation": "uppercase"}],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        # Should not crash, just skip the transformation
        assert "nonexistent_field" not in custom_attrs

    @pytest.mark.asyncio
    async def test_resource_pre_fetch_hook(self, basic_plugin_config, plugin_context):
        """Test resource_pre_fetch hook adds attributes."""
        plugin = SpanAttributeCustomizerPlugin(basic_plugin_config)
        payload = ResourcePreFetchPayload(uri="http://example.com/resource")

        result = await plugin.resource_pre_fetch(payload, plugin_context)

        assert "custom_span_attributes" in plugin_context.global_context.state
        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        assert custom_attrs["environment"] == "test"

    @pytest.mark.asyncio
    async def test_resource_post_fetch_hook(self, basic_plugin_config, plugin_context):
        """Test resource_post_fetch hook returns successfully."""
        plugin = SpanAttributeCustomizerPlugin(basic_plugin_config)
        payload = ResourcePostFetchPayload(uri="http://example.com/resource", content={"data": "test"})

        result = await plugin.resource_post_fetch(payload, plugin_context)

        assert result is not None

    @pytest.mark.asyncio
    async def test_complex_configuration(self, plugin_context):
        """Test complex configuration with all features combined."""
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"environment": "production", "region": "us-east-1", "user_email": "admin@example.com"},
                "tool_overrides": {"weather_api": {"attributes": {"service": "weather"}, "remove_attributes": ["internal_id"]}},
                "transformations": [{"field": "user_email", "operation": "hash"}, {"field": "region", "operation": "uppercase"}],
                "conditions": [{"when": 'tool.name == "weather_api"', "add": {"cost_tracking": True}}],
                "remove_attributes": ["debug_info"],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)
        payload = ToolPreInvokePayload(name="weather_api", arguments={})

        await plugin.tool_pre_invoke(payload, plugin_context)

        custom_attrs = plugin_context.global_context.state["custom_span_attributes"]
        removal_list = plugin_context.global_context.state["remove_span_attributes"]

        # Check global attributes
        assert custom_attrs["environment"] == "production"

        # Check transformations
        assert len(custom_attrs["user_email"]) == 32  # Hashed with HMAC-SHA-256
        assert custom_attrs["region"] == "US-EAST-1"  # Uppercased

        # Check tool override
        assert custom_attrs["service"] == "weather"

        # Check conditional
        assert custom_attrs["cost_tracking"] is True

        # Check removals
        assert "debug_info" in removal_list
        assert "internal_id" in removal_list

    @pytest.mark.asyncio
    async def test_shutdown(self, basic_plugin_config):
        """Test plugin shutdown."""
        plugin = SpanAttributeCustomizerPlugin(basic_plugin_config)
        await plugin.shutdown()
        # Should complete without error


class TestConfigSchema:
    """Test configuration schema validation."""

    def test_attribute_transformation_schema(self):
        """Test AttributeTransformation schema."""
        transform = AttributeTransformation(field="test_field", operation="hash")
        assert transform.field == "test_field"
        assert transform.operation == "hash"
        assert transform.params is None

    def test_attribute_transformation_with_params(self):
        """Test AttributeTransformation with parameters."""
        transform = AttributeTransformation(field="text", operation="truncate", params={"max_length": 100})
        assert transform.params["max_length"] == 100

    def test_conditional_attribute_schema(self):
        """Test ConditionalAttribute schema."""
        condition = ConditionalAttribute(when='tool.name == "test"', add={"attr": "value"})
        assert condition.when == 'tool.name == "test"'
        assert condition.add == {"attr": "value"}

    def test_tool_override_schema(self):
        """Test ToolOverride schema."""
        override = ToolOverride(attributes={"service": "test"}, remove_attributes=["debug"])
        assert override.attributes == {"service": "test"}
        assert override.remove_attributes == ["debug"]

    def test_tool_override_optional_fields(self):
        """Test ToolOverride with optional fields."""
        override = ToolOverride()
        assert override.attributes is None
        assert override.remove_attributes is None

    def test_span_attribute_customizer_config_defaults(self):
        """Test SpanAttributeCustomizerConfig with defaults."""
        config = SpanAttributeCustomizerConfig()
        assert config.global_attributes == {}
        assert config.tool_overrides == {}
        assert config.transformations == []
        assert config.conditions == []
        assert config.remove_attributes == []

    def test_span_attribute_customizer_config_full(self):
        """Test SpanAttributeCustomizerConfig with all fields."""
        config = SpanAttributeCustomizerConfig(
            global_attributes={"env": "test"},
            tool_overrides={"tool1": ToolOverride(attributes={"service": "s1"})},
            transformations=[AttributeTransformation(field="f1", operation="hash")],
            conditions=[ConditionalAttribute(when="true", add={"a": "b"})],
            remove_attributes=["debug"],
        )
        assert config.global_attributes == {"env": "test"}
        assert "tool1" in config.tool_overrides
        assert len(config.transformations) == 1
        assert len(config.conditions) == 1
        assert config.remove_attributes == ["debug"]
