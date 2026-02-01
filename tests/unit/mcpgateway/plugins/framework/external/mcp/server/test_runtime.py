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
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.asyncio
async def test_get_plugin_configs_requires_server(monkeypatch):
    monkeypatch.setattr(runtime, "SERVER", None)
    with pytest.raises(RuntimeError):
        await runtime.get_plugin_configs()


@pytest.mark.asyncio
async def test_get_plugin_config_returns_empty_dict(monkeypatch):
    server = MagicMock()
    server.get_plugin_config = AsyncMock(return_value=None)
    monkeypatch.setattr(runtime, "SERVER", server)
    result = await runtime.get_plugin_config(name="missing")
    assert result == {}


@pytest.mark.asyncio
async def test_invoke_hook_requires_server(monkeypatch):
    monkeypatch.setattr(runtime, "SERVER", None)
    with pytest.raises(RuntimeError):
        await runtime.invoke_hook("hook", "plugin", {}, {})


def test_ssl_config_with_tls(tmp_path):
    from mcpgateway.plugins.framework.models import MCPServerConfig, MCPServerTLSConfig

    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    ca_path = tmp_path / "ca.pem"
    cert_path.write_text("cert")
    key_path.write_text("key")
    ca_path.write_text("ca")

    config = MCPServerConfig(
        host="127.0.0.1",
        port=8000,
        tls=MCPServerTLSConfig(
            certfile=str(cert_path),
            keyfile=str(key_path),
            ca_bundle=str(ca_path),
            keyfile_password="secret",
            ssl_cert_reqs=2,
        ),
    )

    server = object.__new__(runtime.SSLCapableFastMCP)
    server.server_config = config
    ssl_config = runtime.SSLCapableFastMCP._get_ssl_config(server)

    assert ssl_config["ssl_keyfile"] == str(key_path)
    assert ssl_config["ssl_certfile"] == str(cert_path)
    assert ssl_config["ssl_ca_certs"] == str(ca_path)
    assert ssl_config["ssl_keyfile_password"] == "secret"


@pytest.mark.asyncio
async def test_start_health_check_server(monkeypatch):
    server = object.__new__(runtime.SSLCapableFastMCP)
    server.settings = SimpleNamespace(host="127.0.0.1", port=8000, log_level="INFO")

    served = MagicMock()

    class DummyServer:
        def __init__(self, config):
            self.config = config

        async def serve(self):
            served()

    monkeypatch.setattr(runtime.uvicorn, "Config", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(runtime.uvicorn, "Server", lambda config: DummyServer(config))

    await runtime.SSLCapableFastMCP._start_health_check_server(server, 9000)
    served.assert_called_once()


@pytest.mark.asyncio
async def test_run_streamable_http_async_with_ssl(monkeypatch):
    from mcpgateway.plugins.framework.models import MCPServerConfig

    server = object.__new__(runtime.SSLCapableFastMCP)
    server.server_config = MCPServerConfig(host="127.0.0.1", port=8000)
    server.settings = SimpleNamespace(host="127.0.0.1", port=8000, log_level="INFO")
    server.streamable_http_app = lambda: SimpleNamespace(routes=[])

    monkeypatch.setattr(runtime.SSLCapableFastMCP, "_get_ssl_config", lambda self: {"ssl_keyfile": "/tmp/key.pem"})
    monkeypatch.setattr(server, "_start_health_check_server", AsyncMock())

    served = MagicMock()

    class DummyServer:
        def __init__(self, config):
            self.config = config

        async def serve(self):
            served()

    monkeypatch.setattr(runtime.uvicorn, "Config", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(runtime.uvicorn, "Server", lambda config: DummyServer(config))

    await runtime.SSLCapableFastMCP.run_streamable_http_async(server)
    assert server._start_health_check_server.await_count == 1
    served.assert_called_once()


@pytest.mark.asyncio
async def test_run_stdio_transport(monkeypatch):
    created = {}

    class DummyServer:
        async def initialize(self):
            return True

        async def shutdown(self):
            created["shutdown"] = True

        def get_server_config(self):
            return None

    class DummyFastMCP:
        def __init__(self, *args, **kwargs):
            created["mcp"] = self

        def tool(self, name):
            def decorator(fn):
                created.setdefault("tools", []).append(name)
                return fn

            return decorator

        async def run_stdio_async(self):
            created["ran_stdio"] = True

    monkeypatch.setattr(runtime, "ExternalPluginServer", lambda: DummyServer())
    monkeypatch.setattr(runtime, "FastMCP", DummyFastMCP)
    monkeypatch.setenv("PLUGINS_TRANSPORT", "stdio")

    await runtime.run()

    assert created["ran_stdio"]
    assert created["shutdown"]
    runtime.SERVER = None


@pytest.mark.asyncio
async def test_run_http_transport(monkeypatch):
    created = {}

    class DummyServer:
        async def initialize(self):
            return True

        async def shutdown(self):
            created["shutdown"] = True

        def get_server_config(self):
            return None

    class DummyMCP:
        def __init__(self, *args, **kwargs):
            created["mcp"] = self

        def tool(self, name):
            def decorator(fn):
                created.setdefault("tools", []).append(name)
                return fn

            return decorator

        async def run_streamable_http_async(self):
            created["ran_http"] = True

    monkeypatch.setattr(runtime, "ExternalPluginServer", lambda: DummyServer())
    monkeypatch.setattr(runtime, "SSLCapableFastMCP", DummyMCP)
    monkeypatch.setenv("PLUGINS_TRANSPORT", "http")

    await runtime.run()

    assert created["ran_http"]
    assert created["shutdown"]
    runtime.SERVER = None
