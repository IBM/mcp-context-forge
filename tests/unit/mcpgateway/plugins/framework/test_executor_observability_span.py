# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_executor_observability_span.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for PluginExecutor observability span creation with attribute mapping (lines 436, 446, 448-450).
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
from mcpgateway.plugins.framework.observability import current_trace_id


@pytest.mark.asyncio
async def test_executor_observability_span_with_mapping():
    """Test observability span creation with attribute mapping (lines 436, 446, 448-450)."""
    # Setup context with trace_id and attribute mapping
    global_context = GlobalContext(request_id="test-123")
    global_context.state["trace_id"] = "trace-456"
    global_context.state["span_attribute_mapping"] = {
        "plugin.name": "controls.artifact.name",
        "plugin.uuid": "controls.artifact.uuid",
    }
    context = PluginContext(global_context=global_context)

    # Create mock plugin
    mock_plugin = MagicMock()
    mock_plugin.tool_pre_invoke = AsyncMock(return_value=ToolPreInvokeResult(continue_processing=True, modified_payload=None, violation=None, metadata={}))

    plugin_config = PluginConfig(
        name="TestPlugin",
        kind="test",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
    )

    plugin_ref = MagicMock(
        uuid="test-uuid-789",
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

    # Create mock observability provider
    mock_observability = MagicMock()
    mock_observability.start_span = MagicMock(return_value="span-123")
    mock_observability.end_span = MagicMock()

    # Track what attributes were passed to start_span
    captured_attributes = {}

    def capture_start_span(trace_id, name, kind, resource_type=None, resource_name=None, attributes=None):
        if attributes:
            captured_attributes.update(attributes)
        return "span-123"

    mock_observability.start_span = MagicMock(side_effect=capture_start_span)

    # Create executor with observability
    executor = PluginExecutor(timeout=30, observability=mock_observability)
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # Set trace context
    current_trace_id.set("trace-456")
    try:
        await executor._execute_with_timeout(hook_ref, payload, context)
    finally:
        current_trace_id.set(None)

    # Verify observability.start_span was called (line 436 executed)
    assert mock_observability.start_span.called

    # Verify attribute mapping was applied (lines 446, 448-450 executed)
    assert "controls.artifact.name" in captured_attributes
    assert captured_attributes["controls.artifact.name"] == "TestPlugin"
    assert "controls.artifact.uuid" in captured_attributes
    assert captured_attributes["controls.artifact.uuid"] == "test-uuid-789"

    # Verify original names are gone
    assert "plugin.name" not in captured_attributes
    assert "plugin.uuid" not in captured_attributes

    # Verify end_span was called
    assert mock_observability.end_span.called


@pytest.mark.asyncio
async def test_executor_observability_span_without_mapping():
    """Test observability span creation without attribute mapping."""
    # Setup context with trace_id but NO mapping
    global_context = GlobalContext(request_id="test-123")
    global_context.state["trace_id"] = "trace-456"
    context = PluginContext(global_context=global_context)

    mock_plugin = MagicMock()
    mock_plugin.tool_pre_invoke = AsyncMock(return_value=ToolPreInvokeResult(continue_processing=True, modified_payload=None, violation=None, metadata={}))

    plugin_config = PluginConfig(
        name="TestPlugin",
        kind="test",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
    )

    plugin_ref = MagicMock(
        uuid="test-uuid-789",
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

    mock_observability = MagicMock()
    captured_attributes = {}

    def capture_start_span(trace_id, name, kind, resource_type=None, resource_name=None, attributes=None):
        if attributes:
            captured_attributes.update(attributes)
        return "span-123"

    mock_observability.start_span = MagicMock(side_effect=capture_start_span)
    mock_observability.end_span = MagicMock()

    executor = PluginExecutor(timeout=30, observability=mock_observability)
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    # Set trace context
    current_trace_id.set("trace-456")
    try:
        await executor._execute_with_timeout(hook_ref, payload, context)
    finally:
        current_trace_id.set(None)

    # Verify original attribute names remain
    assert "plugin.name" in captured_attributes
    assert captured_attributes["plugin.name"] == "TestPlugin"
    assert "plugin.uuid" in captured_attributes
    assert captured_attributes["plugin.uuid"] == "test-uuid-789"


@pytest.mark.asyncio
async def test_executor_no_observability_span_without_trace():
    """Test that no span is created when trace_id is missing."""
    # Setup context WITHOUT trace_id
    global_context = GlobalContext(request_id="test-123")
    context = PluginContext(global_context=global_context)

    mock_plugin = MagicMock()
    mock_plugin.tool_pre_invoke = AsyncMock(return_value=ToolPreInvokeResult(continue_processing=True, modified_payload=None, violation=None, metadata={}))

    plugin_config = PluginConfig(
        name="TestPlugin",
        kind="test",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
    )

    plugin_ref = MagicMock(
        uuid="test-uuid-789",
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

    mock_observability = MagicMock()
    mock_observability.start_span = MagicMock(return_value="span-123")

    executor = PluginExecutor(timeout=30, observability=mock_observability)
    payload = ToolPreInvokePayload(name="test_tool", arguments={})

    await executor._execute_with_timeout(hook_ref, payload, context)

    # Verify start_span was NOT called (no trace_id)
    assert not mock_observability.start_span.called
