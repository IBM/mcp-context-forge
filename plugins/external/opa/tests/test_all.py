# -*- coding: utf-8 -*-
"""Tests for registered plugins."""

# Standard
import asyncio

# Third-Party
import pytest

# First-Party
from mcpgateway.models import Message, ResourceContent, Role, TextContent
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginManager,
    PromptPosthookPayload,
    PromptPrehookPayload,
    PromptResult,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)


@pytest.fixture(scope="module", autouse=True)
def plugin_manager():
    """Initialize plugin manager."""
    plugin_manager = PluginManager("./resources/plugins/config.yaml")
    asyncio.run(plugin_manager.initialize())
    yield plugin_manager
    asyncio.run(plugin_manager.shutdown())


@pytest.mark.asyncio
async def test_prompt_pre_hook(plugin_manager: PluginManager):
    """Test prompt pre hook across all registered plugins."""
    # Customize payload for testing
    payload = PromptPrehookPayload(name="test_prompt", args={"arg0": "This is an argument"})
    global_context = GlobalContext(request_id="1")
    result, _ = await plugin_manager.prompt_pre_fetch(payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing


@pytest.mark.asyncio
async def test_prompt_post_hook(plugin_manager: PluginManager):
    """Test prompt post hook across all registered plugins."""
    # Customize payload for testing
    message = Message(content=TextContent(type="text", text="prompt"), role=Role.USER)
    prompt_result = PromptResult(messages=[message])
    payload = PromptPosthookPayload(name="test_prompt", result=prompt_result)
    global_context = GlobalContext(request_id="1")
    result, _ = await plugin_manager.prompt_post_fetch(payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing


@pytest.mark.asyncio
async def test_tool_pre_hook(plugin_manager: PluginManager):
    """Test tool pre hook across all registered plugins."""
    # Customize payload for testing
    payload = ToolPreInvokePayload(name="test_prompt", args={"arg0": "This is an argument"})
    global_context = GlobalContext(request_id="1")
    result, _ = await plugin_manager.tool_pre_invoke(payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing


@pytest.mark.asyncio
async def test_tool_post_hook(plugin_manager: PluginManager):
    """Test tool post hook across all registered plugins."""
    # Customize payload for testing
    payload = ToolPostInvokePayload(name="test_tool", result={"output0": "output value"})
    global_context = GlobalContext(request_id="1")
    result, _ = await plugin_manager.tool_post_invoke(payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing


@pytest.mark.asyncio
async def test_resource_pre_hook(plugin_manager: PluginManager):
    """Test tool post hook across all registered plugins."""
    # Customize payload for testing
    payload = ResourcePreFetchPayload(uri="https://test_resource.com", metadata={})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, _ = await plugin_manager.tool_post_invoke(payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing


@pytest.mark.asyncio
async def test_resource_post_hook(plugin_manager: PluginManager):
    """Test tool post hook across all registered plugins."""
    # Customize payload for testing
    content = ResourceContent(
        type="resource",
        uri="test://resource",
        text="test://test_resource.com",
    )
    payload = ResourcePostFetchPayload(uri="https://example.com", content=content)
    global_context = GlobalContext(request_id="1", server_id="2")
    result, _ = await plugin_manager.resource_post_fetch(payload, global_context)
    # Assert expected behaviors
    assert result.continue_processing
