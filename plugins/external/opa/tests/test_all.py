# -*- coding: utf-8 -*-
"""Tests for registered plugins."""

# Standard
import asyncio

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, ResourceContent, Role, TextContent, PromptResult
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginManager,
    ToolHookType,
    PromptHookType,
    ResourceHookType,
    PromptPosthookPayload,
    PromptPrehookPayload,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)


@pytest.fixture(scope="module", autouse=True)
def plugin_manager():
    """Initialize plugin manager.

    Yields:
        PluginManager: An initialized plugin manager instance.
    """
    plugin_manager = PluginManager("./resources/plugins/config.yaml")
    asyncio.run(plugin_manager.initialize())
    yield plugin_manager
    asyncio.run(plugin_manager.shutdown())


@pytest.mark.asyncio
async def test_prompt_pre_hook(plugin_manager: PluginManager):
    """Test prompt pre hook across all registered plugins.

    Args:
        plugin_manager: The plugin manager instance.
    """
    # Customize payload for testing
    payload = PromptPrehookPayload(prompt_id="test_prompt", args={"arg0": "This is an argument"})
    global_context = GlobalContext(request_id="1")
    result, _ = await plugin_manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing


@pytest.mark.asyncio
async def test_prompt_post_hook(plugin_manager: PluginManager):
    """Test prompt post hook across all registered plugins.

    Args:
        plugin_manager: The plugin manager instance.
    """
    # Customize payload for testing
    message = Message(content=TextContent(type="text", text="prompt"), role=Role.USER)
    prompt_result = PromptResult(messages=[message])
    payload = PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)
    global_context = GlobalContext(request_id="1")
    result, _ = await plugin_manager.invoke_hook(PromptHookType.PROMPT_POST_FETCH, payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing


@pytest.mark.asyncio
async def test_tool_pre_hook(plugin_manager: PluginManager):
    """Test tool pre hook across all registered plugins.

    Args:
        plugin_manager: The plugin manager instance.
    """
    # Customize payload for testing
    payload = ToolPreInvokePayload(name="test_prompt", args={"arg0": "This is an argument"})
    global_context = GlobalContext(request_id="1")
    result, _ = await plugin_manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing


@pytest.mark.asyncio
async def test_tool_post_hook(plugin_manager: PluginManager):
    """Test tool post hook across all registered plugins.

    Args:
        plugin_manager: The plugin manager instance.
    """
    # Customize payload for testing
    payload = ToolPostInvokePayload(name="test_tool", result={"output0": "output value"})
    global_context = GlobalContext(request_id="1")
    result, _ = await plugin_manager.invoke_hook(ToolHookType.TOOL_POST_INVOKE, payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing


@pytest.mark.asyncio
async def test_resource_pre_hook(plugin_manager: PluginManager):
    """Test tool post hook across all registered plugins.

    Args:
        plugin_manager: The plugin manager instance.
    """
    # Customize payload for testing
    payload = ResourcePreFetchPayload(uri="https://test_resource.com", metadata={})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, _ = await plugin_manager.invoke_hook(ResourceHookType.RESOURCE_PRE_FETCH, payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing


@pytest.mark.asyncio
async def test_resource_post_hook(plugin_manager: PluginManager):
    """Test tool post hook across all registered plugins.

    Args:
        plugin_manager: The plugin manager instance.
    """
    # Customize payload for testing
    content = ResourceContent(
        type="resource",
        uri="test://resource",
        text="test://test_resource.com",
        id="1"
    )
    payload = ResourcePostFetchPayload(uri="https://example.com", content=content)
    global_context = GlobalContext(request_id="1", server_id="2")
    result, _ = await plugin_manager.invoke_hook(ResourceHookType.RESOURCE_POST_FETCH, payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing
