"""
Tests for external client on stdio.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""
import os
import pytest

from mcpgateway.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.models import PluginContext, PromptPrehookPayload, PromptPosthookPayload


@pytest.mark.asyncio
async def test_client_load_stdio():
    os.environ["CFMCP_PLUGIN_CONFIG"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml"
    os.environ["PYTHONPATH"] = "."
    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin.yaml")
    print(config)

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    print(plugin)
    prompt = PromptPrehookPayload(name="test_prompt", args = {"text": "That was innovative!"})
    result = await plugin.prompt_pre_fetch(prompt, PluginContext(request_id="1", server_id="2"))
    assert result.violation
    assert result.violation.reason == "Prompt not allowed"
    assert result.violation.description == "A deny word was found in the prompt"
    assert result.violation.code == "deny"
    config = plugin.config
    assert config.name == "DenyListPlugin"
    assert config.description == "A plugin that implements a deny list filter."
    assert config.priority == 100
    assert config.kind == "external"
    await plugin.shutdown()
    del os.environ["CFMCP_PLUGIN_CONFIG"]
    del os.environ["PYTHONPATH"]

async def test_client_load_stdio_overrides():
    os.environ["CFMCP_PLUGIN_CONFIG"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml"
    os.environ["PYTHONPATH"] = "."
    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin_overrides.yaml")
    print(config)

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    print(plugin)
    prompt = PromptPrehookPayload(name="test_prompt", args = {"text": "That was innovative!"})
    result = await plugin.prompt_pre_fetch(prompt, PluginContext(request_id="1", server_id="2"))
    assert result.violation
    assert result.violation.reason == "Prompt not allowed"
    assert result.violation.description == "A deny word was found in the prompt"
    assert result.violation.code == "deny"
    config = plugin.config
    assert config.name == "DenyListPlugin"
    assert config.description == "a different configuration."
    assert config.priority == 150
    assert config.hooks[0] == "prompt_pre_fetch"
    assert config.hooks[1] == "prompt_post_fetch"
    assert config.kind == "external"
    await plugin.shutdown()
    del os.environ["CFMCP_PLUGIN_CONFIG"]
    del os.environ["PYTHONPATH"]

@pytest.mark.asyncio
async def test_client_load_stdio_post_prompt():
    os.environ["CFMCP_PLUGIN_CONFIG"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
    os.environ["PYTHONPATH"] = "."
    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_stdio_external_plugin_regex.yaml")
    print(config)

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    print(plugin)
    prompt = PromptPrehookPayload(name="test_prompt", args = {"user": "What a crapshow!"})
    context = PluginContext(request_id="1", server_id="2") 
    result = await plugin.prompt_pre_fetch(prompt, context)
    assert result.modified_payload.args["user"] == "What a yikesshow!"
    config = plugin.config
    assert config.name == "ReplaceBadWordsPlugin"
    assert config.description == "A plugin for finding and replacing words."
    assert config.priority == 150
    assert config.kind == "external"

    message = Message(content=TextContent(type="text", text="What the crud?"), role=Role.USER)
    prompt_result = PromptResult(messages=[message])

    payload_result = PromptPosthookPayload(name="test_prompt", result=prompt_result)

    result = await plugin.prompt_post_fetch(payload_result, context=context)
    assert len(result.modified_payload.result.messages) == 1
    assert result.modified_payload.result.messages[0].content.text == "What the yikes?"
    await plugin.shutdown()
    await loader.shutdown()
    del os.environ["CFMCP_PLUGIN_CONFIG"]
    del os.environ["PYTHONPATH"]