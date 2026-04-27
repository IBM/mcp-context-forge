# -*- coding: utf-8 -*-
"""Unit tests for PluginExecutor OTEL attribute mapping (lines 478-482).

Location: ./tests/unit/mcpgateway/plugins/framework/test_executor_otel_mapping.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcpgateway.plugins.framework.manager import PluginExecutor
from mcpgateway.plugins.framework.base import HookRef
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolHookType,
)
from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload, ToolPreInvokeResult


@pytest.mark.asyncio
async def test_executor_otel_attribute_mapping_applied():
    """Test that OTEL span attributes are mapped when attribute_mapping is present (lines 478-482)."""
    # Setup context with attribute mapping
    global_context = GlobalContext(request_id="test-123")
    global_context.state["span_attribute_mapping"] = {
        "plugin.name": "controls.artifact.name",
        "plugin.hook.type": "controls.hook.type",
        "contextforge.runtime": "platform.runtime",
    }
    context = PluginContext(global_context=global_context)

    # Create a mock plugin that returns success
    mock_plugin = MagicMock()
    mock_plugin.tool_pre_invoke = AsyncMock(return_value=ToolPreInvokeResult(
        continue_processing=True,
        modified_payload=None,
        violation=None,
        metadata={}
    ))

    # Create plugin config and hook ref
    plugin_config = PluginConfig(
        name="TestPlugin",
        kind="test",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
    )

    plugin_ref = MagicMock(
        uuid="test-uuid",
        mode=MagicMock(value="enforce"),
        priority=10,
        plugin=mock_plugin,
        config=plugin_config,
    )
    plugin_ref.name = "TestPlugin"

    hook_ref = HookRef(
        hook=ToolHookType.TOOL_PRE_INVOKE,
        plugin_ref=plugin_ref,
    )

    # Track OTEL span attributes
    captured_otel_attrs = {}

    def mock_create_span(name, attributes):
        captured_otel_attrs.update(attributes)
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        return mock_span

    # Create executor and execute
    with patch('mcpgateway.plugins.framework.manager.create_span', side_effect=mock_create_span):
        executor = PluginExecutor(timeout=30)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await executor._execute_with_timeout(hook_ref, payload, context)

        # Verify OTEL attributes were mapped (lines 478-482 executed)
        assert len(captured_otel_attrs) > 0

        # Check that mapping was applied
        assert "controls.artifact.name" in captured_otel_attrs
        assert captured_otel_attrs["controls.artifact.name"] == "TestPlugin"

        assert "controls.hook.type" in captured_otel_attrs
        assert captured_otel_attrs["controls.hook.type"] == ToolHookType.TOOL_PRE_INVOKE

        assert "platform.runtime" in captured_otel_attrs
        assert captured_otel_attrs["platform.runtime"] == "python"

        # Verify original names are gone
        assert "plugin.name" not in captured_otel_attrs
        assert "plugin.hook.type" not in captured_otel_attrs
        assert "contextforge.runtime" not in captured_otel_attrs


@pytest.mark.asyncio
async def test_executor_otel_no_mapping_when_empty():
    """Test that empty attribute_mapping doesn't break OTEL span creation."""
    # Setup context with empty mapping
    global_context = GlobalContext(request_id="test-123")
    global_context.state["span_attribute_mapping"] = {}
    context = PluginContext(global_context=global_context)

    # Create mock plugin
    mock_plugin = MagicMock()
    mock_plugin.tool_pre_invoke = AsyncMock(return_value=ToolPreInvokeResult(
        continue_processing=True,
        modified_payload=None,
        violation=None,
        metadata={}
    ))

    plugin_config = PluginConfig(
        name="TestPlugin",
        kind="test",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
    )

    plugin_ref = MagicMock(
        uuid="test-uuid",
        mode=MagicMock(value="enforce"),
        priority=10,
        plugin=mock_plugin,
        config=plugin_config,
    )
    plugin_ref.name = "TestPlugin"

    hook_ref = HookRef(
        hook=ToolHookType.TOOL_PRE_INVOKE,
        plugin_ref=plugin_ref,
    )

    captured_otel_attrs = {}

    def mock_create_span(name, attributes):
        captured_otel_attrs.update(attributes)
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        return mock_span

    with patch('mcpgateway.plugins.framework.manager.create_span', side_effect=mock_create_span):
        executor = PluginExecutor(timeout=30)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await executor._execute_with_timeout(hook_ref, payload, context)

        # Verify original attribute names remain
        assert "plugin.name" in captured_otel_attrs
        assert captured_otel_attrs["plugin.name"] == "TestPlugin"


@pytest.mark.asyncio
async def test_executor_otel_no_mapping_when_missing():
    """Test that missing attribute_mapping doesn't break OTEL span creation."""
    # Setup context WITHOUT mapping
    global_context = GlobalContext(request_id="test-123")
    context = PluginContext(global_context=global_context)

    mock_plugin = MagicMock()
    mock_plugin.tool_pre_invoke = AsyncMock(return_value=ToolPreInvokeResult(
        continue_processing=True,
        modified_payload=None,
        violation=None,
        metadata={}
    ))

    plugin_config = PluginConfig(
        name="TestPlugin",
        kind="test",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
    )

    plugin_ref = MagicMock(
        uuid="test-uuid",
        mode=MagicMock(value="enforce"),
        priority=10,
        plugin=mock_plugin,
        config=plugin_config,
    )
    plugin_ref.name = "TestPlugin"

    hook_ref = HookRef(
        hook=ToolHookType.TOOL_PRE_INVOKE,
        plugin_ref=plugin_ref,
    )

    captured_otel_attrs = {}

    def mock_create_span(name, attributes):
        captured_otel_attrs.update(attributes)
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        return mock_span

    with patch('mcpgateway.plugins.framework.manager.create_span', side_effect=mock_create_span):
        executor = PluginExecutor(timeout=30)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        await executor._execute_with_timeout(hook_ref, payload, context)

        # Verify original attribute names remain
        assert "plugin.name" in captured_otel_attrs
        assert "contextforge.runtime" in captured_otel_attrs
