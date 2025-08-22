# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_streamable_http.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for external client on streamable http.
"""
import os
import subprocess
import sys
import time

import pytest

from mcpgateway.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework import ConfigLoader, PluginLoader, PluginContext, PromptPrehookPayload, PromptPosthookPayload

@pytest.fixture(autouse=True)
def server_proc():
    current_env = os.environ.copy()
    current_env["CHUK_MCP_CONFIG_PATH"] = "plugins/resources/server/config-http.yaml"
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
    current_env["PYTHONPATH"] = "."
    # Start the server as a subprocess
    try:
        with subprocess.Popen([sys.executable, "mcpgateway/plugins/framework/external/mcp/server/runtime.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=current_env) as server_proc:
            time.sleep(2)  # Give the server time to start
            yield server_proc
            server_proc.terminate()
            server_proc.wait(timeout=3) # Wait for the subprocess to complete
    except subprocess.TimeoutExpired:
        server_proc.kill() # Force kill if timeout occurs
        server_proc.wait(timeout=3)

@pytest.mark.skip(reason="Flaky, fails on Python 3.12, need to debug.")
@pytest.mark.asyncio
async def test_client_load_streamable_http(server_proc):
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_strhttp_external_plugin_regex.yaml")

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
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
    server_proc.terminate()
    server_proc.wait() # Wait for the process to fully terminate

@pytest.fixture(autouse=True)
def server_proc1():
    current_env = os.environ.copy()
    current_env["CHUK_MCP_CONFIG_PATH"] = "plugins/resources/server/config-http.yaml"
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml"
    current_env["PYTHONPATH"] = "."
    # Start the server as a subprocess
    try:
        with subprocess.Popen([sys.executable, "mcpgateway/plugins/framework/external/mcp/server/runtime.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=current_env) as server_proc:
            time.sleep(2)  # Give the server time to start
            yield server_proc
            server_proc.terminate()
            server_proc.wait(timeout=3) # Wait for the subprocess to complete
    except subprocess.TimeoutExpired:
        server_proc.kill() # Force kill if timeout occurs
        server_proc.wait(timeout=3)

@pytest.mark.skip(reason="Flaky, need to debug.")
@pytest.mark.asyncio
async def test_client_load_strhttp_overrides(server_proc1):
    assert not server_proc1.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_strhttp_external_plugin_overrides.yaml")

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
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
    await loader.shutdown()
    server_proc1.terminate()
    server_proc1.wait() # Wait for the process to fully terminate

@pytest.fixture(autouse=True)
def server_proc2():
    current_env = os.environ.copy()
    current_env["CHUK_MCP_CONFIG_PATH"] = "plugins/resources/server/config-http.yaml"
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml"
    current_env["PYTHONPATH"] = "."
    # Start the server as a subprocess
    try:
        with subprocess.Popen([sys.executable, "mcpgateway/plugins/framework/external/mcp/server/runtime.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=current_env) as server_proc:
            time.sleep(2)  # Give the server time to start
            yield server_proc
            server_proc.terminate()
            server_proc.wait(timeout=3) # Wait for the subprocess to complete
    except subprocess.TimeoutExpired:
        server_proc.kill() # Force kill if timeout occurs
        server_proc.wait(timeout=3)

@pytest.mark.skip(reason="Flaky, fails on Python 3.12, need to debug.")
@pytest.mark.asyncio
async def test_client_load_strhttp_post_prompt(server_proc2):
    assert not server_proc2.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_strhttp_external_plugin_regex.yaml")

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
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
    server_proc2.terminate()
    server_proc2.wait() # Wait for the process to fully terminate
