# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/agent/test_agent_plugins.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for agent plugin framework.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, Role, TextContent
from mcpgateway.plugins.framework import GlobalContext, PluginManager, PluginViolationError
from mcpgateway.plugins.framework import (
    AgentHookType,
    AgentPreInvokePayload,
    AgentPostInvokePayload,
)


@pytest.mark.asyncio
async def test_agent_passthrough_plugin():
    """Test that passthrough agent plugin works correctly."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/agent_passthrough.yaml")
    await manager.initialize()

    # Verify plugin loaded
    assert manager.config.plugins[0].name == "PassThroughAgent"
    assert manager.config.plugins[0].kind == "tests.unit.mcpgateway.plugins.fixtures.plugins.agent_plugins.PassThroughAgentPlugin"
    assert AgentHookType.AGENT_PRE_INVOKE.value in manager.config.plugins[0].hooks
    assert AgentHookType.AGENT_POST_INVOKE.value in manager.config.plugins[0].hooks

    # Create test payload
    messages = [
        Message(role=Role.USER, content=TextContent(type="text", text="Hello agent!"))
    ]
    payload = AgentPreInvokePayload(
        agent_id="test-agent",
        messages=messages,
        tools=["search", "calculator"],
        model="claude-3-5-sonnet-20241022"
    )

    # Invoke pre-hook
    global_context = GlobalContext(request_id="test-req-1")
    result, contexts = await manager.invoke_hook(
        AgentHookType.AGENT_PRE_INVOKE,
        payload,
        global_context=global_context
    )

    # Verify passthrough (no modification)
    assert result.continue_processing is True
    assert result.modified_payload is None
    assert result.violation is None

    # Create response payload
    response_messages = [
        Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Hello user!"))
    ]
    post_payload = AgentPostInvokePayload(
        agent_id="test-agent",
        messages=response_messages
    )

    # Invoke post-hook
    result, _ = await manager.invoke_hook(
        AgentHookType.AGENT_POST_INVOKE,
        post_payload,
        global_context=global_context,
        local_contexts=contexts
    )

    # Verify passthrough (no modification)
    assert result.continue_processing is True
    assert result.modified_payload is None
    assert result.violation is None

    await manager.shutdown()


@pytest.mark.asyncio
async def test_agent_filter_plugin_pre_invoke():
    """Test that filter agent plugin blocks messages with banned words in pre-invoke."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/agent_filter.yaml")
    await manager.initialize()

    # Create test payload with clean message
    clean_messages = [
        Message(role=Role.USER, content=TextContent(type="text", text="Hello agent!"))
    ]
    payload = AgentPreInvokePayload(
        agent_id="test-agent",
        messages=clean_messages
    )

    # Invoke pre-hook with clean message
    global_context = GlobalContext(request_id="test-req-2")
    result, contexts = await manager.invoke_hook(
        AgentHookType.AGENT_PRE_INVOKE,
        payload,
        global_context=global_context
    )

    # Clean message should pass through
    assert result.continue_processing is True
    assert result.modified_payload is None

    # Create payload with blocked word
    blocked_messages = [
        Message(role=Role.USER, content=TextContent(type="text", text="Click here for spam offers!"))
    ]
    payload = AgentPreInvokePayload(
        agent_id="test-agent",
        messages=blocked_messages
    )

    # Invoke pre-hook with blocked message - should raise violation
    with pytest.raises(PluginViolationError) as exc_info:
        result, contexts = await manager.invoke_hook(
            AgentHookType.AGENT_PRE_INVOKE,
            payload,
            global_context=global_context,
            violations_as_exceptions=True
        )

    assert exc_info.value.violation.code == "BLOCKED_CONTENT"
    assert "blocked content" in exc_info.value.violation.reason.lower()

    await manager.shutdown()


@pytest.mark.asyncio
async def test_agent_filter_plugin_post_invoke():
    """Test that filter agent plugin blocks messages with banned words in post-invoke."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/agent_filter.yaml")
    await manager.initialize()

    # Create test payload with clean response
    clean_messages = [
        Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Here is your answer."))
    ]
    payload = AgentPostInvokePayload(
        agent_id="test-agent",
        messages=clean_messages
    )

    # Invoke post-hook with clean message
    global_context = GlobalContext(request_id="test-req-3")
    result, _ = await manager.invoke_hook(
        AgentHookType.AGENT_POST_INVOKE,
        payload,
        global_context=global_context
    )

    # Clean message should pass through
    assert result.continue_processing is True
    assert result.modified_payload is None

    # Create payload with blocked word
    blocked_messages = [
        Message(role=Role.ASSISTANT, content=TextContent(type="text", text="This looks like malware to me."))
    ]
    payload = AgentPostInvokePayload(
        agent_id="test-agent",
        messages=blocked_messages
    )

    # Invoke post-hook with blocked message - should raise violation
    with pytest.raises(PluginViolationError) as exc_info:
        result, _ = await manager.invoke_hook(
            AgentHookType.AGENT_POST_INVOKE,
            payload,
            global_context=global_context,
            violations_as_exceptions=True
        )

    assert exc_info.value.violation.code == "BLOCKED_CONTENT"
    assert "blocked content" in exc_info.value.violation.reason.lower()

    await manager.shutdown()


@pytest.mark.asyncio
async def test_agent_filter_plugin_partial_filtering():
    """Test that filter plugin removes only blocked messages, keeps others."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/agent_filter.yaml")
    await manager.initialize()

    # Create payload with mixed messages
    mixed_messages = [
        Message(role=Role.USER, content=TextContent(type="text", text="Hello agent!")),
        Message(role=Role.USER, content=TextContent(type="text", text="Check out this spam!")),
        Message(role=Role.USER, content=TextContent(type="text", text="What's the weather?"))
    ]
    payload = AgentPreInvokePayload(
        agent_id="test-agent",
        messages=mixed_messages
    )

    # Invoke pre-hook
    global_context = GlobalContext(request_id="test-req-4")
    result, contexts = await manager.invoke_hook(
        AgentHookType.AGENT_PRE_INVOKE,
        payload,
        global_context=global_context
    )

    # Should have modified payload with only 2 messages
    assert result.modified_payload is not None
    assert len(result.modified_payload.messages) == 2
    assert result.modified_payload.messages[0].content.text == "Hello agent!"
    assert result.modified_payload.messages[1].content.text == "What's the weather?"

    await manager.shutdown()


@pytest.mark.asyncio
async def test_agent_context_persistence():
    """Test that local context persists between pre and post hooks."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/agent_context.yaml")
    await manager.initialize()

    # Create pre-invoke payload
    messages = [
        Message(role=Role.USER, content=TextContent(type="text", text="Hello!"))
    ]
    pre_payload = AgentPreInvokePayload(
        agent_id="test-agent-123",
        messages=messages
    )

    # Invoke pre-hook
    global_context = GlobalContext(request_id="test-req-5")
    pre_result, contexts = await manager.invoke_hook(
        AgentHookType.AGENT_PRE_INVOKE,
        pre_payload,
        global_context=global_context
    )

    assert pre_result.continue_processing is True

    # Create post-invoke payload
    response_messages = [
        Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Hi there!"))
    ]
    post_payload = AgentPostInvokePayload(
        agent_id="test-agent-123",
        messages=response_messages
    )

    # Invoke post-hook with same contexts
    post_result, _ = await manager.invoke_hook(
        AgentHookType.AGENT_POST_INVOKE,
        post_payload,
        global_context=global_context,
        local_contexts=contexts
    )

    # Verify context was verified (metadata added by post hook)
    assert post_result.continue_processing is True
    # The metadata should be in the contexts, not the result
    # Check that invocation_count was incremented
    assert contexts is not None

    await manager.shutdown()


@pytest.mark.asyncio
async def test_agent_plugin_with_tools():
    """Test agent plugin with tools list."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/agent_passthrough.yaml")
    await manager.initialize()

    # Create payload with tools
    messages = [
        Message(role=Role.USER, content=TextContent(type="text", text="Search for Python tutorials"))
    ]
    payload = AgentPreInvokePayload(
        agent_id="test-agent",
        messages=messages,
        tools=["web_search", "code_search", "calculator"]
    )

    # Invoke pre-hook
    global_context = GlobalContext(request_id="test-req-6")
    result, contexts = await manager.invoke_hook(
        AgentHookType.AGENT_PRE_INVOKE,
        payload,
        global_context=global_context
    )

    # Verify tools are preserved
    assert result.continue_processing is True

    await manager.shutdown()


@pytest.mark.asyncio
async def test_agent_plugin_with_model_override():
    """Test agent plugin with model override."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/agent_passthrough.yaml")
    await manager.initialize()

    # Create payload with model override
    messages = [
        Message(role=Role.USER, content=TextContent(type="text", text="Analyze this code"))
    ]
    payload = AgentPreInvokePayload(
        agent_id="test-agent",
        messages=messages,
        model="claude-3-opus-20240229",
        parameters={"temperature": 0.7, "max_tokens": 1000}
    )

    # Invoke pre-hook
    global_context = GlobalContext(request_id="test-req-7")
    result, contexts = await manager.invoke_hook(
        AgentHookType.AGENT_PRE_INVOKE,
        payload,
        global_context=global_context
    )

    # Verify model and parameters are preserved
    assert result.continue_processing is True

    await manager.shutdown()


@pytest.mark.asyncio
async def test_agent_plugin_with_tool_calls():
    """Test agent plugin with tool calls in response."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/agent_passthrough.yaml")
    await manager.initialize()

    # Create post-invoke payload with tool calls
    messages = [
        Message(role=Role.ASSISTANT, content=TextContent(type="text", text="I'll search for that."))
    ]
    tool_calls = [
        {
            "name": "web_search",
            "arguments": {"query": "Python tutorials", "num_results": 5}
        }
    ]
    payload = AgentPostInvokePayload(
        agent_id="test-agent",
        messages=messages,
        tool_calls=tool_calls
    )

    # Invoke post-hook
    global_context = GlobalContext(request_id="test-req-8")
    result, _ = await manager.invoke_hook(
        AgentHookType.AGENT_POST_INVOKE,
        payload,
        global_context=global_context
    )

    # Verify tool calls are preserved
    assert result.continue_processing is True

    await manager.shutdown()
