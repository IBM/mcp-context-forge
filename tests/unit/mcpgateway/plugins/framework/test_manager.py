# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor, Fred Araujo

Unit tests for plugin manager.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework import GlobalContext, PluginManager, PluginViolationError
from mcpgateway.plugins.framework import PromptHookType, ToolHookType,  HttpHeaderPayload,  PromptPosthookPayload, PromptPrehookPayload, ToolPostInvokePayload, ToolPreInvokePayload
from plugins.regex_filter.search_replace import SearchReplaceConfig


@pytest.mark.asyncio
async def test_manager_single_transformer_prompt_plugin():
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
    await manager.initialize()
    assert manager.config.plugins[0].name == "ReplaceBadWordsPlugin"
    assert manager.config.plugins[0].kind == "plugins.regex_filter.search_replace.SearchReplacePlugin"
    assert manager.config.plugins[0].description == "A plugin for finding and replacing words."
    assert manager.config.plugins[0].version == "0.1"
    assert manager.config.plugins[0].author == "MCP Context Forge Team"
    assert manager.config.plugins[0].hooks[0] == "prompt_pre_fetch"
    assert manager.config.plugins[0].hooks[1] == "prompt_post_fetch"
    assert manager.config.plugins[0].config
    srconfig = SearchReplaceConfig.model_validate(manager.config.plugins[0].config)
    assert len(srconfig.words) == 2
    assert srconfig.words[0].search == "crap"
    assert srconfig.words[0].replace == "crud"
    prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "What a crapshow!"})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, contexts = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, global_context=global_context)
    assert len(result.modified_payload.args) == 1
    assert result.modified_payload.args["user"] == "What a yikesshow!"

    message = Message(content=TextContent(type="text", text=result.modified_payload.args["user"]), role=Role.USER)

    prompt_result = PromptResult(messages=[message])

    payload_result = PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)

    result, _ = await manager.invoke_hook(PromptHookType.PROMPT_POST_FETCH, payload_result, global_context=global_context, local_contexts=contexts)
    assert len(result.modified_payload.result.messages) == 1
    assert result.modified_payload.result.messages[0].content.text == "What a yikesshow!"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_multiple_transformer_preprompt_plugin():
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins.yaml")
    await manager.initialize()
    assert manager.initialized
    assert manager.config.plugins[0].name == "SynonymsPlugin"
    assert manager.config.plugins[0].kind == "plugins.regex_filter.search_replace.SearchReplacePlugin"
    assert manager.config.plugins[0].description == "A plugin for finding and replacing synonyms."
    assert manager.config.plugins[0].version == "0.1"
    assert manager.config.plugins[0].author == "MCP Context Forge Team"
    assert manager.config.plugins[0].hooks[0] == "prompt_pre_fetch"
    assert manager.config.plugins[0].hooks[1] == "prompt_post_fetch"
    assert manager.config.plugins[0].config
    srconfig = SearchReplaceConfig.model_validate(manager.config.plugins[0].config)
    assert len(srconfig.words) == 2
    assert srconfig.words[0].search == "happy"
    assert srconfig.words[0].replace == "gleeful"
    assert manager.config.plugins[1].name == "ReplaceBadWordsPlugin"
    assert manager.config.plugins[1].kind == "plugins.regex_filter.search_replace.SearchReplacePlugin"
    assert manager.config.plugins[1].description == "A plugin for finding and replacing words."
    assert manager.config.plugins[1].version == "0.1"
    assert manager.config.plugins[1].author == "MCP Context Forge Team"
    assert manager.config.plugins[1].hooks[0] == "prompt_pre_fetch"
    assert manager.config.plugins[1].hooks[1] == "prompt_post_fetch"
    assert manager.config.plugins[1].config
    srconfig = SearchReplaceConfig.model_validate(manager.config.plugins[1].config)
    assert srconfig.words[0].search == "crap"
    assert srconfig.words[0].replace == "crud"
    assert manager.plugin_count == 2

    prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "It's always happy at the crapshow."})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, contexts = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, global_context=global_context)
    assert len(result.modified_payload.args) == 1
    assert result.modified_payload.args["user"] == "It's always gleeful at the yikesshow."

    message = Message(content=TextContent(type="text", text="It's sad at the crud bakery."), role=Role.USER)

    prompt_result = PromptResult(messages=[message])

    payload_result = PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)

    result, _ = await manager.invoke_hook(PromptHookType.PROMPT_POST_FETCH, payload_result, global_context=global_context, local_contexts=contexts)
    assert len(result.modified_payload.result.messages) == 1
    assert result.modified_payload.result.messages[0].content.text == "It's sullen at the yikes bakery."
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_no_plugins():
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")
    await manager.initialize()
    assert manager.initialized
    prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "It's always happy at the crapshow."})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, _ = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, global_context=global_context)
    assert result.continue_processing
    assert not result.modified_payload
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_filter_plugins():
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_filter_plugin.yaml")
    await manager.initialize()
    assert manager.initialized
    prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "innovative"})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, _ = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, global_context=global_context)
    assert not result.continue_processing
    assert result.violation

    with pytest.raises(PluginViolationError) as ve:
        result, _ = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, global_context=global_context, violations_as_exceptions=True)
    assert ve.value.violation
    assert ve.value.violation.reason == "Prompt not allowed"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_multi_filter_plugins():
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
    await manager.initialize()
    assert manager.initialized
    prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "innovative crapshow."})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, _ = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, global_context=global_context)
    assert not result.continue_processing
    assert result.violation
    with pytest.raises(PluginViolationError) as ve:
        result, _ = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, global_context=global_context, violations_as_exceptions=True)
    assert ve.value.violation
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_tool_hooks_empty():
    """Test tool hooks with no plugins configured."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")
    await manager.initialize()
    assert manager.initialized

    # Test tool pre-invoke with no plugins
    tool_payload = ToolPreInvokePayload(name="calculator", args={"operation": "add", "a": 5, "b": 3})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, contexts = await manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, tool_payload, global_context=global_context)

    # Should continue processing with no modifications
    assert result.continue_processing
    assert result.modified_payload is None
    assert result.violation is None
    assert contexts is None

    # Test tool post-invoke with no plugins
    tool_result_payload = ToolPostInvokePayload(name="calculator", result={"result": 8, "status": "success"})
    result, contexts = await manager.invoke_hook(ToolHookType.TOOL_POST_INVOKE, tool_result_payload, global_context=global_context)

    # Should continue processing with no modifications
    assert result.continue_processing
    assert result.modified_payload is None
    assert result.violation is None
    assert contexts is None

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_tool_hooks_with_transformer_plugin():
    """Test tool hooks with a transformer plugin that doesn't have tool hooks configured."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
    await manager.initialize()
    assert manager.initialized

    # Test tool pre-invoke - no plugins configured for tool hooks
    tool_payload = ToolPreInvokePayload(name="test_tool", args={"input": "This is crap data"})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, contexts = await manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, tool_payload, global_context=global_context)

    # Should continue processing with no modifications (no plugins for tool hooks)
    assert result.continue_processing
    assert result.modified_payload is None  # No plugins = no modifications
    assert result.violation is None
    assert contexts is None

    # Test tool post-invoke - no plugins configured for tool hooks
    tool_result_payload = ToolPostInvokePayload(name="test_tool", result={"output": "Result with crap in it"})
    result, _ = await manager.invoke_hook(ToolHookType.TOOL_POST_INVOKE, tool_result_payload, global_context=global_context, local_contexts=contexts)

    # Should continue processing with no modifications (no plugins for tool hooks)
    assert result.continue_processing
    assert result.modified_payload is None  # No plugins = no modifications
    assert result.violation is None

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_tool_hooks_with_actual_plugin():
    """Test tool hooks with a real plugin configured for tool processing."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_tool_hooks.yaml")
    await manager.initialize()
    assert manager.initialized

    # Test tool pre-invoke with transformation - use correct tool name from config
    tool_payload = ToolPreInvokePayload(name="test_tool", args={"input": "This is bad data", "quality": "wrong"})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, contexts = await manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, tool_payload, global_context=global_context)

    # Should continue processing with transformations applied
    assert result.continue_processing
    assert result.modified_payload is not None
    assert result.modified_payload.name == "test_tool"
    assert result.modified_payload.args["input"] == "This is good data"  # bad -> good
    assert result.modified_payload.args["quality"] == "right"  # wrong -> right
    assert result.violation is None

    # Test tool post-invoke with transformation
    tool_result_payload = ToolPostInvokePayload(name="test_tool", result={"output": "Result was bad", "status": "wrong format"})
    result, _ = await manager.invoke_hook(ToolHookType.TOOL_POST_INVOKE, tool_result_payload, global_context=global_context, local_contexts=contexts)

    # Should continue processing with transformations applied
    assert result.continue_processing
    assert result.modified_payload is not None
    assert result.modified_payload.name == "test_tool"
    assert result.modified_payload.result["output"] == "Result was good"  # bad -> good
    assert result.modified_payload.result["status"] == "right format"  # wrong -> right
    assert result.violation is None

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_tool_hooks_with_header_mods():
    """Test tool hooks with a real plugin configured for tool processing."""
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/tool_headers_plugin.yaml")
    await manager.initialize()
    assert manager.initialized

    # Test tool pre-invoke with transformation - use correct tool name from config
    tool_payload = ToolPreInvokePayload(name="test_tool", args={"input": "This is bad data", "quality": "wrong"}, headers=None)
    global_context = GlobalContext(request_id="1", server_id="2")
    result, contexts = await manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, tool_payload, global_context=global_context)

    # Should continue processing with transformations applied
    assert result.continue_processing
    assert result.modified_payload is not None
    assert result.modified_payload.name == "test_tool"
    assert result.modified_payload.args["input"] == "This is bad data"  # bad -> good
    assert result.modified_payload.args["quality"] == "wrong"  # wrong -> right
    assert result.violation is None
    assert result.modified_payload.headers
    assert result.modified_payload.headers["User-Agent"] == "Mozilla/5.0"
    assert result.modified_payload.headers["Connection"] == "keep-alive"

    # Test tool pre-invoke with transformation - use correct tool name from config
    tool_payload = ToolPreInvokePayload(name="test_tool", args={"input": "This is bad data", "quality": "wrong"}, headers=HttpHeaderPayload({"Content-Type": "application/json"}))
    global_context = GlobalContext(request_id="1", server_id="2")
    result, contexts = await manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, tool_payload, global_context=global_context)

    # Should continue processing with transformations applied
    assert result.continue_processing
    assert result.modified_payload is not None
    assert result.modified_payload.name == "test_tool"
    assert result.modified_payload.args["input"] == "This is bad data"  # bad -> good
    assert result.modified_payload.args["quality"] == "wrong"  # wrong -> right
    assert result.violation is None
    assert result.modified_payload.headers
    assert result.modified_payload.headers["User-Agent"] == "Mozilla/5.0"
    assert result.modified_payload.headers["Connection"] == "keep-alive"
    assert result.modified_payload.headers["Content-Type"] == "application/json"

    await manager.shutdown()


@pytest.mark.asyncio
async def test_plugin_manager_singleton_behavior():
    """Test that PluginManager implements proper singleton pattern (Borg pattern).

    Verifies that:
    1. Multiple instances share the same internal state
    2. Initialization only happens once per process
    3. reset() properly clears the shared state
    4. After reset, a new instance can be initialized with different config
    """
    # Clean up any previous state
    PluginManager.reset()

    # Create first instance with a specific config
    config1_path = "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
    manager1 = PluginManager(config1_path)
    await manager1.initialize()

    # Verify first instance is initialized
    assert manager1.initialized
    assert manager1.config is not None
    assert manager1.config.plugins[0].name == "ReplaceBadWordsPlugin"
    plugin_count_1 = manager1.plugin_count
    assert plugin_count_1 > 0

    # Create second instance with same config - should share state
    manager2 = PluginManager(config1_path)

    # Verify both instances share the same state (Borg pattern)
    assert manager2.initialized is True, "Second instance should already be initialized"
    assert manager2.config is manager1.config, "Both instances should share the same config object"
    assert manager2.plugin_count == plugin_count_1, "Both instances should report same plugin count"
    assert id(manager1.__dict__) == id(manager2.__dict__), "Both instances should share the same __dict__"

    # Verify that calling initialize again on second instance doesn't re-initialize
    await manager2.initialize()
    assert manager2.plugin_count == plugin_count_1, "Plugin count should not change on re-initialization"

    # Create third instance with different config path
    config2_path = "./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins.yaml"
    manager3 = PluginManager(config2_path)

    # Verify third instance STILL shares state (config path is ignored after first init)
    assert manager3.initialized is True, "Third instance should already be initialized"
    assert manager3.config is manager1.config, "Third instance should share config from first instance"
    assert manager3.config.plugins[0].name == "ReplaceBadWordsPlugin", "Config should not change"

    # Shutdown the manager
    await manager1.shutdown()

    # Now test reset functionality
    PluginManager.reset()

    # Verify reset clears the state
    manager4 = PluginManager(config2_path)
    assert not manager4.initialized, "After reset, new instance should not be initialized"
    assert manager4.config is not None, "After reset, config should be loaded from new path"

    # Initialize with the new config
    await manager4.initialize()
    assert manager4.initialized
    assert manager4.config.plugins[0].name == "SynonymsPlugin", "Should have different config after reset"
    plugin_count_2 = manager4.plugin_count
    assert plugin_count_2 != plugin_count_1, "Plugin count should differ with different config"

    # Create fifth instance - should share new state
    manager5 = PluginManager(config1_path)
    assert manager5.initialized is True
    assert manager5.config is manager4.config, "New instances after reset should share new state"
    assert manager5.config.plugins[0].name == "SynonymsPlugin", "Should still have config from after reset"

    # Clean up
    await manager4.shutdown()
    PluginManager.reset()
