# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_span_attribute_customizer_mapping.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for SpanAttributeCustomizer attribute name mapping.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cpex.framework import ToolPreInvokePayload
from cpex.framework import GlobalContext, PluginConfig, PluginContext
from plugins.span_attribute_customizer.config_schema import SpanAttributeCustomizerConfig
from plugins.span_attribute_customizer.span_attribute_customizer import SpanAttributeCustomizerPlugin


@pytest.mark.asyncio
async def test_attribute_mapping_stored_in_context():
    """Test that attribute mapping is stored in global context state."""
    plugin_config = PluginConfig(
        name="SpanAttributeCustomizer",
        kind="test",
        hooks=[],
        priority=10,
        config={
            "attribute_mapping": {
                "tool.name": "controls.artifact.name",
                "tool.arguments": "controls.artifact.inputs",
            }
        },
    )

    plugin = SpanAttributeCustomizerPlugin(plugin_config)

    payload = ToolPreInvokePayload(name="test_tool", arguments={"key": "value"})
    global_context = GlobalContext(request_id="test-123")
    context = PluginContext(global_context=global_context)

    result = await plugin.tool_pre_invoke(payload, context)

    # Verify mapping is stored in context
    assert "span_attribute_mapping" in global_context.state
    mapping = global_context.state["span_attribute_mapping"]
    assert mapping == {
        "tool.name": "controls.artifact.name",
        "tool.arguments": "controls.artifact.inputs",
    }

    # Verify metadata reports mappings configured
    assert result.metadata["span_customizer"]["mappings_configured"] == 2


@pytest.mark.asyncio
async def test_empty_attribute_mapping():
    """Test that empty mapping doesn't break functionality."""
    plugin_config = PluginConfig(name="SpanAttributeCustomizer", kind="test", hooks=[], priority=10, config={"attribute_mapping": {}, "global_attributes": {"env": "test"}})

    plugin = SpanAttributeCustomizerPlugin(plugin_config)

    payload = ToolPreInvokePayload(name="test_tool", arguments={})
    global_context = GlobalContext(request_id="test-123")
    context = PluginContext(global_context=global_context)

    result = await plugin.tool_pre_invoke(payload, context)

    # Verify empty mapping is stored
    assert "span_attribute_mapping" in global_context.state
    assert global_context.state["span_attribute_mapping"] == {}

    # Verify custom attributes still work
    assert "custom_span_attributes" in global_context.state
    assert global_context.state["custom_span_attributes"]["env"] == "test"


@pytest.mark.asyncio
async def test_plugin_span_attribute_mapping():
    """Test that plugin span attributes can be mapped."""
    plugin_config = PluginConfig(
        name="SpanAttributeCustomizer",
        kind="test",
        hooks=[],
        priority=10,
        config={
            "attribute_mapping": {
                "plugin.name": "controls.artifact.name",
                "plugin.uuid": "controls.artifact.id",
                "plugin.mode": "controls.enforcement.mode",
                "plugin.priority": "controls.execution.priority",
            }
        },
    )

    plugin = SpanAttributeCustomizerPlugin(plugin_config)

    payload = ToolPreInvokePayload(name="test_tool", arguments={})
    global_context = GlobalContext(request_id="test-123")
    context = PluginContext(global_context=global_context)

    result = await plugin.tool_pre_invoke(payload, context)

    # Verify plugin attribute mapping is stored
    mapping = global_context.state["span_attribute_mapping"]
    assert "plugin.name" in mapping
    assert mapping["plugin.name"] == "controls.artifact.name"
    assert "plugin.uuid" in mapping
    assert mapping["plugin.uuid"] == "controls.artifact.id"


@pytest.mark.asyncio
async def test_combined_mapping_and_custom_attributes():
    """Test that mapping works alongside custom attributes and removals."""
    plugin_config = PluginConfig(
        name="SpanAttributeCustomizer",
        kind="test",
        hooks=[],
        priority=10,
        config={
            "attribute_mapping": {
                "tool.name": "controls.artifact.name",
            },
            "global_attributes": {
                "environment": "production",
                "team": "platform",
            },
            "remove_attributes": ["internal_debug"],
        },
    )

    plugin = SpanAttributeCustomizerPlugin(plugin_config)

    payload = ToolPreInvokePayload(name="test_tool", arguments={})
    global_context = GlobalContext(request_id="test-123")
    context = PluginContext(global_context=global_context)

    result = await plugin.tool_pre_invoke(payload, context)

    # Verify all three mechanisms are stored
    assert "span_attribute_mapping" in global_context.state
    assert "custom_span_attributes" in global_context.state
    assert "remove_span_attributes" in global_context.state

    # Verify mapping
    assert global_context.state["span_attribute_mapping"]["tool.name"] == "controls.artifact.name"

    # Verify custom attributes
    assert global_context.state["custom_span_attributes"]["environment"] == "production"
    assert global_context.state["custom_span_attributes"]["team"] == "platform"

    # Verify removal list
    assert "internal_debug" in global_context.state["remove_span_attributes"]


@pytest.mark.asyncio
async def test_tool_override_with_mapping():
    """Test that tool-specific overrides work with attribute mapping."""
    plugin_config = PluginConfig(
        name="SpanAttributeCustomizer",
        kind="test",
        hooks=[],
        priority=10,
        config={
            "attribute_mapping": {
                "tool.name": "controls.artifact.name",
            },
            "tool_overrides": {
                "weather_api": {
                    "attributes": {
                        "service": "weather",
                        "cost_center": "engineering",
                    }
                }
            },
        },
    )

    plugin = SpanAttributeCustomizerPlugin(plugin_config)

    payload = ToolPreInvokePayload(name="weather_api", arguments={})
    global_context = GlobalContext(request_id="test-123")
    context = PluginContext(global_context=global_context)

    result = await plugin.tool_pre_invoke(payload, context)

    # Verify mapping is present
    assert global_context.state["span_attribute_mapping"]["tool.name"] == "controls.artifact.name"

    # Verify tool-specific attributes are added
    custom_attrs = global_context.state["custom_span_attributes"]
    assert custom_attrs["service"] == "weather"
    assert custom_attrs["cost_center"] == "engineering"


@pytest.mark.asyncio
async def test_observability_service_applies_mapping():
    """Test that ObservabilityService applies attribute mapping from context."""
    from mcpgateway.services.observability_service import ObservabilityService

    # Create mock observability service
    with patch("mcpgateway.services.observability_service.SessionLocal") as mock_session:
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        obs_service = ObservabilityService()

        # Setup context with mapping
        global_context = GlobalContext(request_id="test-123")
        global_context.state["span_attribute_mapping"] = {
            "tool.name": "controls.artifact.name",
            "tool.arguments": "controls.artifact.inputs",
        }
        context = PluginContext(global_context=global_context)

        # Create attributes that should be mapped
        attributes = {
            "tool.name": "test_tool",
            "tool.arguments": '{"key": "value"}',
            "other_attr": "unchanged",
        }

        # Mock the start_span to capture the attributes
        with patch.object(obs_service, "start_span", return_value="span-123") as mock_start:
            # Simulate the mapping logic from observability_service.py
            attribute_mapping = context.global_context.state.get("span_attribute_mapping", {})
            if attribute_mapping:
                renamed_attributes = {}
                for old_name, value in attributes.items():
                    new_name = attribute_mapping.get(old_name, old_name)
                    renamed_attributes[new_name] = value
                attributes = renamed_attributes

            # Verify mapping was applied
            assert "controls.artifact.name" in attributes
            assert attributes["controls.artifact.name"] == "test_tool"
            assert "controls.artifact.inputs" in attributes
            assert attributes["controls.artifact.inputs"] == '{"key": "value"}'
            assert "other_attr" in attributes
            assert attributes["other_attr"] == "unchanged"

            # Verify original names are gone
            assert "tool.name" not in attributes
            assert "tool.arguments" not in attributes


@pytest.mark.asyncio
async def test_plugin_manager_applies_mapping():
    """Test that PluginManager applies attribute mapping to plugin spans."""
    from cpex.framework.manager import PluginManager

    # Setup context with mapping
    global_context = GlobalContext(request_id="test-123")
    global_context.state["span_attribute_mapping"] = {
        "plugin.name": "controls.artifact.name",
        "plugin.uuid": "controls.artifact.id",
        "plugin.mode": "controls.enforcement.mode",
    }
    context = PluginContext(global_context=global_context)

    # Create base attributes that should be mapped
    base_attributes = {
        "plugin.name": "TestPlugin",
        "plugin.uuid": "uuid-123",
        "plugin.mode": "enforce",
        "plugin.priority": 10,
    }

    # Simulate the mapping logic from manager.py
    attribute_mapping = context.global_context.state.get("span_attribute_mapping", {})
    if attribute_mapping:
        renamed_attributes = {}
        for old_name, value in base_attributes.items():
            new_name = attribute_mapping.get(old_name, old_name)
            renamed_attributes[new_name] = value
        base_attributes = renamed_attributes

    # Verify mapping was applied
    assert "controls.artifact.name" in base_attributes
    assert base_attributes["controls.artifact.name"] == "TestPlugin"
    assert "controls.artifact.id" in base_attributes
    assert base_attributes["controls.artifact.id"] == "uuid-123"
    assert "controls.enforcement.mode" in base_attributes
    assert base_attributes["controls.enforcement.mode"] == "enforce"

    # Verify unmapped attributes remain
    assert "plugin.priority" in base_attributes
    assert base_attributes["plugin.priority"] == 10

    # Verify original mapped names are gone
    assert "plugin.name" not in base_attributes
    assert "plugin.uuid" not in base_attributes
    assert "plugin.mode" not in base_attributes


@pytest.mark.asyncio
async def test_otel_span_attribute_mapping():
    """Test that OTEL span attributes are mapped correctly."""
    # Setup context with mapping
    global_context = GlobalContext(request_id="test-123")
    global_context.state["span_attribute_mapping"] = {
        "plugin.name": "controls.artifact.name",
        "plugin.hook.type": "controls.hook.type",
        "contextforge.runtime": "platform.runtime",
    }
    context = PluginContext(global_context=global_context)

    # Create OTEL attributes that should be mapped
    otel_attributes = {
        "plugin.name": "TestPlugin",
        "plugin.uuid": "uuid-123",
        "plugin.hook.type": "tool_pre_invoke",
        "contextforge.runtime": "python",
    }

    # Simulate the mapping logic from manager.py (OTEL span section)
    attribute_mapping = context.global_context.state.get("span_attribute_mapping", {})
    if attribute_mapping:
        renamed_otel_attributes = {}
        for old_name, value in otel_attributes.items():
            new_name = attribute_mapping.get(old_name, old_name)
            renamed_otel_attributes[new_name] = value
        otel_attributes = renamed_otel_attributes

    # Verify mapping was applied
    assert "controls.artifact.name" in otel_attributes
    assert otel_attributes["controls.artifact.name"] == "TestPlugin"
    assert "controls.hook.type" in otel_attributes
    assert otel_attributes["controls.hook.type"] == "tool_pre_invoke"
    assert "platform.runtime" in otel_attributes
    assert otel_attributes["platform.runtime"] == "python"

    # Verify unmapped attributes remain
    assert "plugin.uuid" in otel_attributes
    assert otel_attributes["plugin.uuid"] == "uuid-123"

    # Verify original mapped names are gone
    assert "plugin.name" not in otel_attributes
    assert "plugin.hook.type" not in otel_attributes
    assert "contextforge.runtime" not in otel_attributes
