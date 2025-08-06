# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for plugin manager.
"""
import pytest

from mcpgateway.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework.manager import PluginManager
from mcpgateway.plugins.framework.plugin_types import GlobalContext, PromptPosthookPayload, PromptPrehookPayload
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
    prompt = PromptPrehookPayload(name="test_prompt", args = {"user": "What a crapshow!"})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, contexts = await manager.prompt_pre_fetch(prompt, global_context=global_context)
    assert len(result.modified_payload.args) == 1
    assert result.modified_payload.args["user"] == "What a yikesshow!"

    message=Message(content=TextContent(type="text", text=result.modified_payload.args["user"]), role=Role.USER)

    prompt_result = PromptResult(messages=[message])

    payload_result = PromptPosthookPayload(name="test_prompt", result=prompt_result)

    result, _ = await manager.prompt_post_fetch(payload_result, global_context=global_context, local_contexts=contexts)
    assert len(result.modified_payload.result.messages) == 1
    assert result.modified_payload.result.messages[0].content.text == 'What a yikesshow!'
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

    prompt = PromptPrehookPayload(name="test_prompt", args = {"user": "It's always happy at the crapshow."})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, contexts = await manager.prompt_pre_fetch(prompt, global_context=global_context)
    assert len(result.modified_payload.args) == 1
    assert result.modified_payload.args["user"] == "It's always gleeful at the yikesshow."

    message=Message(content=TextContent(type="text", text="It's sad at the crud bakery."), role=Role.USER)

    prompt_result = PromptResult(messages=[message])

    payload_result = PromptPosthookPayload(name="test_prompt", result=prompt_result)

    result, _ = await manager.prompt_post_fetch(payload_result, global_context=global_context, local_contexts=contexts)
    assert len(result.modified_payload.result.messages) == 1
    assert result.modified_payload.result.messages[0].content.text == "It's sullen at the yikes bakery."
    await manager.shutdown()

@pytest.mark.asyncio
async def test_manager_no_plugins():
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_no_plugin.yaml")
    await manager.initialize()
    assert manager.initialized
    prompt = PromptPrehookPayload(name="test_prompt", args = {"user": "It's always happy at the crapshow."})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, _ = await manager.prompt_pre_fetch(prompt, global_context=global_context)
    assert result.continue_processing
    assert not result.modified_payload
    await manager.shutdown()

@pytest.mark.asyncio
async def test_manager_filter_plugins():
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_filter_plugin.yaml")
    await manager.initialize()
    assert manager.initialized
    prompt = PromptPrehookPayload(name="test_prompt", args = {"user": "innovative"})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, _ = await manager.prompt_pre_fetch(prompt, global_context=global_context)
    assert not result.continue_processing
    assert result.violation
    await manager.shutdown()

@pytest.mark.asyncio
async def test_manager_multi_filter_plugins():
    manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
    await manager.initialize()
    assert manager.initialized
    prompt = PromptPrehookPayload(name="test_prompt", args = {"user": "innovative crapshow."})
    global_context = GlobalContext(request_id="1", server_id="2")
    result, _ = await manager.prompt_pre_fetch(prompt, global_context=global_context)
    assert not result.continue_processing
    assert result.violation
    await manager.shutdown()
