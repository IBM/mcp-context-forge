# -*- coding: utf-8 -*-
"""Unit tests for SpanAttributeCustomizer attribute name mapping.

Location: ./tests/unit/mcpgateway/plugins/test_span_attribute_customizer_mapping.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import pytest

from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginContext
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
        }
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
    plugin_config = PluginConfig(
        name="SpanAttributeCustomizer",
        kind="test",
        hooks=[],
        priority=10,
        config={
            "attribute_mapping": {},
            "global_attributes": {"env": "test"}
        }
    )
    
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
        }
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
        }
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
            }
        }
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
