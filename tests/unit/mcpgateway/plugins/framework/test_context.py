# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_context.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for context passing plugins.
"""

import pytest
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginManager,
    ToolHookType,
    ToolPreInvokePayload,
    ToolPostInvokePayload,
)


@pytest.mark.asyncio
async def test_shared_context_across_pre_post_hooks():
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/context_plugin.yaml")
    await manager.initialize()
    assert manager.initialized

    # Test tool pre-invoke with transformation - use correct tool name from config
    tool_payload = ToolPreInvokePayload(name="test_tool", args={"input": "This is bad data", "quality": "wrong"})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, contexts = await manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, tool_payload, global_context=global_context)

    assert len(contexts) == 1
    context = next(iter(contexts.values()))
    assert context.state
    assert "key2" in context.state
    assert context.state["key2"] == "value2"
    assert context.global_context.state["globkey1"] == "globvalue1"
    assert len(context.global_context.state)
    assert not context.global_context.metadata

    # Should continue processing with transformations applied
    assert result.continue_processing
    assert result.modified_payload is None

    # Test tool post-invoke with transformation
    tool_result_payload = ToolPostInvokePayload(name="test_tool", result={"output": "Result was bad", "status": "wrong format"})
    result, contexts = await manager.invoke_hook(ToolHookType.TOOL_POST_INVOKE, tool_result_payload, global_context=global_context, local_contexts=contexts)

    assert len(contexts) == 1
    context = next(iter(contexts.values()))
    assert context.state
    assert len(context.state) == 2
    assert "key2" in context.state
    assert context.state["key2"] == "value2"
    assert context.state["key3"] == "value3"
    assert context.global_context.state
    assert context.global_context.state["globkey1"] == "globvalue1"
    assert context.global_context.state["globkey2"] == "globvalue2"
    assert len(context.global_context.state) == 2

    # Should continue processing with transformations applied
    assert result.continue_processing
    assert result.modified_payload is None
    await manager.shutdown()


@pytest.mark.asyncio
async def test_shared_context_across_pre_post_hooks_multi_plugins():
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/context_multiplugins.yaml")
    await manager.initialize()
    assert manager.initialized

    # Test tool pre-invoke with transformation - use correct tool name from config
    tool_payload = ToolPreInvokePayload(name="test_tool", args={"input": "This is bad data", "quality": "wrong"})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, contexts = await manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, tool_payload, global_context=global_context)

    assert len(contexts) == 2
    ctxs = [contexts[key] for key in contexts.keys()]
    assert len(ctxs) == 2
    context1 = ctxs[0]
    context2 = ctxs[1]
    assert context1.state
    assert "key2" in context1.state
    assert "cp2key1" not in context1.state
    assert context1.state["key2"] == "value2"
    assert len(context1.state) == 1
    assert context1.global_context.state["globkey1"] == "globvalue1"
    assert "gcp2globkey1" not in context1.global_context.state
    assert len(context1.global_context.state)
    assert not context1.global_context.metadata

    assert context2.state
    assert len(context2.state) == 1
    assert "cp2key1" in context2.state
    assert "key2" not in context2.state
    assert context2.global_context.state["globkey1"] == "globvalue1"
    assert context2.global_context.state["gcp2globkey1"] == "gcp2globvalue1"

    # Should continue processing with transformations applied
    assert result.continue_processing
    assert result.modified_payload is None
    # Test tool post-invoke with transformation
    tool_result_payload = ToolPostInvokePayload(name="test_tool", result={"output": "Result was bad", "status": "wrong format"})
    result, contexts = await manager.invoke_hook(ToolHookType.TOOL_POST_INVOKE, tool_result_payload, global_context=global_context, local_contexts=contexts)

    ctxs = [contexts[key] for key in contexts.keys()]
    assert len(ctxs) == 2
    context1 = ctxs[0]
    context2 = ctxs[1]
    assert context1.state
    assert len(context1.state) == 2
    assert context1.state["key3"] == "value3"
    assert context1.state["key2"] == "value2"
    assert "cp2key1" not in context1.state
    assert "cp2key2" not in context1.state
    assert context1.global_context.state["globkey1"] == "globvalue1"
    assert context1.global_context.state["gcp2globkey1"] == "gcp2globvalue1"
    assert "gcp2globkey2" not in context1.global_context.state
    assert context1.global_context.state["globkey2"] == "globvalue2"

    assert context2.global_context.state["globkey1"] == "globvalue1"
    assert context2.global_context.state["gcp2globkey1"] == "gcp2globvalue1"
    assert context2.global_context.state["gcp2globkey2"] == "gcp2globvalue2"
    assert context2.global_context.state["globkey2"] == "globvalue2"

    assert "key3" not in context2.state
    assert "key2" not in context2.state
    assert "cp2key1" in context2.state
    """
    assert "key2" in context.state
    assert context.state["key2"] == "value2"
    assert context.state["key3"] == "value3"
    assert context.global_context.state
    assert context.global_context.state["globkey1"] == "globvalue1"
    assert context.global_context.state["globkey2"] == "globvalue2"
    assert len(context.global_context.state) == 2

    # Should continue processing with transformations applied
    assert result.continue_processing
    assert result.modified_payload is None
    """
    await manager.shutdown()
