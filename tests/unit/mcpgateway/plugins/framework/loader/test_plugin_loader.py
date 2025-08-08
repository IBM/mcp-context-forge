# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for config and plugin loaders.
"""

import pytest

from mcpgateway.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.models import PluginMode
from mcpgateway.plugins.framework.plugin_types import GlobalContext, PluginContext, PromptPosthookPayload, PromptPrehookPayload
from plugins.regex_filter.search_replace import SearchReplaceConfig, SearchReplacePlugin


def test_config_loader_load():
    """pytest for testing the config loader."""
    config = ConfigLoader.load_config(config="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
    assert config
    assert len(config.plugins) == 1
    assert config.plugins[0].name == "ReplaceBadWordsPlugin"
    assert config.plugins[0].kind == "plugins.regex_filter.search_replace.SearchReplacePlugin"
    assert config.plugins[0].description == "A plugin for finding and replacing words."
    assert config.plugins[0].version == "0.1"
    assert config.plugins[0].author == "MCP Context Forge Team"
    assert config.plugins[0].hooks[0] == "prompt_pre_fetch"
    assert config.plugins[0].hooks[1] == "prompt_post_fetch"
    assert config.plugins[0].config
    srconfig = SearchReplaceConfig.model_validate(config.plugins[0].config)
    assert len(srconfig.words) == 2
    assert srconfig.words[0].search == "crap"
    assert srconfig.words[0].replace == "crud"

@pytest.mark.asyncio
async def test_plugin_loader_load():
    """Load a plugin with the plugin loader."""
    config = ConfigLoader.load_config(config="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    assert isinstance(plugin, SearchReplacePlugin)
    assert plugin.name == "ReplaceBadWordsPlugin"
    assert plugin.mode == PluginMode.ENFORCE
    assert plugin.priority == 150
    assert "test_prompt" in plugin.conditions[0].prompts
    assert plugin.hooks[0] == "prompt_pre_fetch"
    assert plugin.hooks[1] == "prompt_post_fetch"

    context = PluginContext(GlobalContext(request_id="1", server_id="2"))
    prompt = PromptPrehookPayload(name="test_prompt", args = {"user": "What a crapshow!"})
    result = await plugin.prompt_pre_fetch(prompt, context=context)
    assert len(result.modified_payload.args) == 1
    assert result.modified_payload.args["user"] == "What a yikesshow!"

    message=Message(content=TextContent(type="text", text="What the crud?"), role=Role.USER)
    prompt_result = PromptResult(messages=[message])

    payload_result = PromptPosthookPayload(name="test_prompt", result=prompt_result)

    result = await plugin.prompt_post_fetch(payload_result, context)
    assert len(result.modified_payload.result.messages) == 1
    assert result.modified_payload.result.messages[0].content.text == 'What the yikes?'

    await loader.shutdown()

@pytest.mark.asyncio
async def test_plugin_loader_invalid_plugin_load():
    """Load an invalid plugin with the plugin loader."""
    config = ConfigLoader.load_config(config="./tests/unit/mcpgateway/plugins/fixtures/configs/invalid_single_plugin.yaml", use_jinja=False)
    loader = PluginLoader()
    with pytest.raises(ModuleNotFoundError):
        plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
