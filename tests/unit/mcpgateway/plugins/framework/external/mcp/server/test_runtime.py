# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/mcp/server/test_runtime.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for external client on stdio.
"""

# Standard
import asyncio
import json

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginContext,
    PromptPosthookPayload,
    PromptPrehookPayload,
    PromptHookType,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    ResourceHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
    ToolHookType,
)
from mcpgateway.plugins.framework.external.mcp.server import ExternalPluginServer
import mcpgateway.plugins.framework.external.mcp.server.runtime as runtime


@pytest.fixture
def server():
    server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
    asyncio.run(server.initialize())
    yield server
    asyncio.run(server.shutdown())


@pytest.fixture
def tool_server():
    server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_tool_hooks.yaml")
    asyncio.run(server.initialize())
    yield server
    asyncio.run(server.shutdown())


@pytest.mark.asyncio
async def test_get_plugin_configs(monkeypatch, server):
    monkeypatch.setattr(runtime, "SERVER", server)
    configs = await runtime.get_plugin_configs()
    assert len(configs) > 0


@pytest.mark.asyncio
async def test_get_plugin_config(monkeypatch, server):
    monkeypatch.setattr(runtime, "SERVER", server)
    config = await runtime.get_plugin_config(name="DenyListPlugin")
    assert config["name"] == "DenyListPlugin"


@pytest.mark.asyncio
async def test_prompt_pre_fetch(monkeypatch, server):
    monkeypatch.setattr(runtime, "SERVER", server)
    payload = PromptPrehookPayload(prompt_id="123", args={"user": "This is so innovative"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await runtime.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, "DenyListPlugin", payload.model_dump(), context.model_dump())
    assert result
    assert result["result"]
    assert not result["result"]["continue_processing"]


@pytest.mark.asyncio
async def test_prompt_post_fetch(monkeypatch, server):
    monkeypatch.setattr(runtime, "SERVER", server)
    message = Message(content=TextContent(type="text", text="crap prompt"), role=Role.USER)
    prompt_result = PromptResult(messages=[message])
    payload = PromptPosthookPayload(prompt_id="123", result=prompt_result)
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await runtime.invoke_hook(PromptHookType.PROMPT_POST_FETCH, "ReplaceBadWordsPlugin", payload.model_dump(), context.model_dump())
    assert result
    assert result["result"]
    assert result["result"]["continue_processing"]
    assert "crap" not in result["result"]["modified_payload"]


@pytest.mark.asyncio
async def test_tool_pre_invoke(monkeypatch, tool_server):
    monkeypatch.setattr(runtime, "SERVER", tool_server)
    payload = ToolPreInvokePayload(name="test_tool", args={"arg0": "bad argument"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await runtime.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, "ToolTestPlugin", payload.model_dump(), context.model_dump())
    assert result
    assert result["result"]
    assert result["result"]["continue_processing"]
    assert "bad" not in result["result"]["modified_payload"]["args"]["arg0"]


@pytest.mark.asyncio
async def test_tool_post_invoke(monkeypatch, tool_server):
    monkeypatch.setattr(runtime, "SERVER", tool_server)
    payload = ToolPostInvokePayload(name="test_tool", result={"message": "wrong result"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await runtime.invoke_hook(ToolHookType.TOOL_POST_INVOKE, "ToolTestPlugin", payload.model_dump(), context.model_dump())
    assert result
    assert result["result"]
    assert result["result"]["continue_processing"]
    assert "wrong" not in result["result"]["modified_payload"]["result"]["message"]


@pytest.mark.asyncio
async def test_resource_pre_fetch(monkeypatch, server):
    monkeypatch.setattr(runtime, "SERVER", server)
    payload = ResourcePreFetchPayload(uri="resource", metadata={"arg0": "Good argument"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await runtime.invoke_hook(ResourceHookType.RESOURCE_PRE_FETCH, "ResourceFilterExample", payload.model_dump(), context.model_dump())
    assert result
    assert result["result"]
    assert not result["result"]["continue_processing"]


@pytest.mark.asyncio
async def test_resource_post_fetch(monkeypatch, server):
    monkeypatch.setattr(runtime, "SERVER", server)
    payload = ResourcePostFetchPayload(uri="resource", content="content")
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await runtime.invoke_hook(ResourceHookType.RESOURCE_POST_FETCH, "ResourceFilterExample", payload.model_dump(), context.model_dump())
    assert result
    assert result["result"]
    assert result["result"]["continue_processing"]
