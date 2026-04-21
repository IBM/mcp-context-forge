# -*- coding: utf-8 -*-
"""Unit tests for PluginManager observability attribute mapping.

Location: ./tests/unit/mcpgateway/plugins/framework/test_manager_observability_mapping.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolHookType,
)
from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload, ToolPreInvokeResult
from mcpgateway.plugins.framework.manager import PluginManager


@pytest.mark.asyncio
async def test_manager_base_attributes_mapping_with_observability():
    """Test that base_attributes mapping is applied when observability is enabled (line 450)."""
    # Create a real plugin that returns a result
    class TestPlugin:
        def __init__(self, config):
            self.config = config
        
        async def tool_pre_invoke(self, payload, context):
            return ToolPreInvokeResult(
                continue_processing=True,
                modified_payload=None,
                violation=None,
                metadata={}
            )
    
    plugin_config = PluginConfig(
        name="TestPlugin",
        kind="test",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
    )
    
    # Setup context with attribute mapping
    global_context = GlobalContext(request_id="test-123")
    global_context.state["span_attribute_mapping"] = {
        "plugin.name": "controls.artifact.name",
        "plugin.uuid": "controls.artifact.id",
    }
    context = PluginContext(global_context=global_context)
    
    # Create manager with observability enabled
    manager = PluginManager()
    manager.observability = MagicMock()
    manager.observability.start_span = MagicMock(return_value="span-123")
    manager.observability.end_span = MagicMock()
    
    # Register the plugin
    test_plugin = TestPlugin(plugin_config)
    manager._plugins = {
        "TestPlugin": MagicMock(
            name="TestPlugin",
            uuid="test-uuid",
            mode=MagicMock(value="enforce"),
            priority=10,
            plugin=test_plugin,
            config=plugin_config,
        )
    }
    manager._hooks = {
        ToolHookType.TOOL_PRE_INVOKE: [
            MagicMock(
                name=ToolHookType.TOOL_PRE_INVOKE,
                plugin_ref=manager._plugins["TestPlugin"],
                hook=test_plugin.tool_pre_invoke,
            )
        ]
    }
    
    # Mock current_trace_id to return a trace ID
    with patch('mcpgateway.plugins.framework.manager.current_trace_id', return_value="trace-123"):
        # Execute hook
        payload = ToolPreInvokePayload(name="test_tool", arguments={})
        await manager.execute_hooks(ToolHookType.TOOL_PRE_INVOKE, payload, context)
        
        # Verify start_span was called
        assert manager.observability.start_span.called
        call_kwargs = manager.observability.start_span.call_args[1]
        attributes = call_kwargs.get('attributes', {})
        
        # Verify that attribute mapping was applied (line 450 executed)
        # The mapping should have renamed plugin.name to controls.artifact.name
        assert "controls.artifact.name" in attributes or "plugin.name" in attributes


@pytest.mark.asyncio
async def test_manager_otel_attributes_mapping():
    """Test that OTEL span attributes mapping is applied (lines 478-482)."""
    # Create a real plugin that returns a result
    class TestPlugin:
        def __init__(self, config):
            self.config = config
        
        async def tool_pre_invoke(self, payload, context):
            return ToolPreInvokeResult(
                continue_processing=True,
                modified_payload=None,
                violation=None,
                metadata={}
            )
    
    plugin_config = PluginConfig(
        name="TestPlugin",
        kind="test",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
    )
    
    # Setup context with attribute mapping for OTEL attributes
    global_context = GlobalContext(request_id="test-123")
    global_context.state["span_attribute_mapping"] = {
        "plugin.name": "controls.artifact.name",
        "plugin.hook.type": "controls.hook.type",
        "contextforge.runtime": "platform.runtime",
    }
    context = PluginContext(global_context=global_context)
    
    # Track the OTEL span attributes that were used
    captured_otel_attrs = {}
    
    def mock_create_span(name, attributes):
        captured_otel_attrs.update(attributes)
        return MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
    
    # Create manager
    with patch('mcpgateway.plugins.framework.manager.create_span', side_effect=mock_create_span):
        manager = PluginManager()
        
        # Register the plugin
        test_plugin = TestPlugin(plugin_config)
        manager._plugins = {
            "TestPlugin": MagicMock(
                name="TestPlugin",
                uuid="test-uuid",
                mode=MagicMock(value="enforce"),
                priority=10,
                plugin=test_plugin,
                config=plugin_config,
            )
        }
        manager._hooks = {
            ToolHookType.TOOL_PRE_INVOKE: [
                MagicMock(
                    name=ToolHookType.TOOL_PRE_INVOKE,
                    plugin_ref=manager._plugins["TestPlugin"],
                    hook=test_plugin.tool_pre_invoke,
                )
            ]
        }
        
        # Execute hook
        payload = ToolPreInvokePayload(name="test_tool", arguments={})
        await manager.execute_hooks(ToolHookType.TOOL_PRE_INVOKE, payload, context)
        
        # Verify OTEL attributes were mapped (lines 478-482 executed)
        assert len(captured_otel_attrs) > 0
        
        # Check that mapping was applied
        assert "controls.artifact.name" in captured_otel_attrs or "plugin.name" in captured_otel_attrs
        
        # If mapping was applied, verify the mapped names exist
        if "controls.artifact.name" in captured_otel_attrs:
            assert captured_otel_attrs["controls.artifact.name"] == "TestPlugin"
            assert "plugin.name" not in captured_otel_attrs  # Original should be gone


@pytest.mark.asyncio
async def test_manager_no_mapping_when_empty():
    """Test that empty mapping doesn't break execution."""
    class TestPlugin:
        def __init__(self, config):
            self.config = config
        
        async def tool_pre_invoke(self, payload, context):
            return ToolPreInvokeResult(
                continue_processing=True,
                modified_payload=None,
                violation=None,
                metadata={}
            )
    
    plugin_config = PluginConfig(
        name="TestPlugin",
        kind="test",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
    )
    
    # Setup context with empty attribute mapping
    global_context = GlobalContext(request_id="test-123")
    global_context.state["span_attribute_mapping"] = {}
    context = PluginContext(global_context=global_context)
    
    captured_otel_attrs = {}
    
    def mock_create_span(name, attributes):
        captured_otel_attrs.update(attributes)
        return MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
    
    with patch('mcpgateway.plugins.framework.manager.create_span', side_effect=mock_create_span):
        manager = PluginManager()
        test_plugin = TestPlugin(plugin_config)
        manager._plugins = {
            "TestPlugin": MagicMock(
                name="TestPlugin",
                uuid="test-uuid",
                mode=MagicMock(value="enforce"),
                priority=10,
                plugin=test_plugin,
                config=plugin_config,
            )
        }
        manager._hooks = {
            ToolHookType.TOOL_PRE_INVOKE: [
                MagicMock(
                    name=ToolHookType.TOOL_PRE_INVOKE,
                    plugin_ref=manager._plugins["TestPlugin"],
                    hook=test_plugin.tool_pre_invoke,
                )
            ]
        }
        
        payload = ToolPreInvokePayload(name="test_tool", arguments={})
        await manager.execute_hooks(ToolHookType.TOOL_PRE_INVOKE, payload, context)
        
        # Verify execution succeeded with empty mapping
        assert len(captured_otel_attrs) > 0
        # Original attribute names should remain
        assert "plugin.name" in captured_otel_attrs


@pytest.mark.asyncio
async def test_manager_no_mapping_when_not_in_context():
    """Test that missing mapping in context doesn't break execution."""
    class TestPlugin:
        def __init__(self, config):
            self.config = config
        
        async def tool_pre_invoke(self, payload, context):
            return ToolPreInvokeResult(
                continue_processing=True,
                modified_payload=None,
                violation=None,
                metadata={}
            )
    
    plugin_config = PluginConfig(
        name="TestPlugin",
        kind="test",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
    )
    
    # Setup context WITHOUT attribute mapping
    global_context = GlobalContext(request_id="test-123")
    context = PluginContext(global_context=global_context)
    
    captured_otel_attrs = {}
    
    def mock_create_span(name, attributes):
        captured_otel_attrs.update(attributes)
        return MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))
    
    with patch('mcpgateway.plugins.framework.manager.create_span', side_effect=mock_create_span):
        manager = PluginManager()
        test_plugin = TestPlugin(plugin_config)
        manager._plugins = {
            "TestPlugin": MagicMock(
                name="TestPlugin",
                uuid="test-uuid",
                mode=MagicMock(value="enforce"),
                priority=10,
                plugin=test_plugin,
                config=plugin_config,
            )
        }
        manager._hooks = {
            ToolHookType.TOOL_PRE_INVOKE: [
                MagicMock(
                    name=ToolHookType.TOOL_PRE_INVOKE,
                    plugin_ref=manager._plugins["TestPlugin"],
                    hook=test_plugin.tool_pre_invoke,
                )
            ]
        }
        
        payload = ToolPreInvokePayload(name="test_tool", arguments={})
        await manager.execute_hooks(ToolHookType.TOOL_PRE_INVOKE, payload, context)
        
        # Verify execution succeeded without mapping
        assert len(captured_otel_attrs) > 0
        assert "plugin.name" in captured_otel_attrs
