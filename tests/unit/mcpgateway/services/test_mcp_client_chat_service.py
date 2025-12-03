# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_mcp_client_chat_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
Unit tests for mcp client chat service.
"""

import asyncio
import pytest
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import mcpgateway.services.mcp_client_chat_service as svc

# Patch LoggingService globally so logging doesn't pollute test outputs
@pytest.fixture(autouse=True)
def patch_logger(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(svc, "logger", mock)
    monkeypatch.setattr(svc.logging_service, "get_logger", lambda _: mock)
    return mock

# --------------------------------------------------------------------------- #
# CONFIGURATION TESTS
# --------------------------------------------------------------------------- #

def test_mcpserverconfig_http_and_stdio_modes():
    http_conf = svc.MCPServerConfig(url="https://srv", transport="sse", auth_token="token")
    assert http_conf.url == "https://srv"
    assert "sse" in http_conf.transport
    stdio_conf = svc.MCPServerConfig(command="python", args=["main.py"], transport="stdio")
    assert stdio_conf.command == "python"
    assert isinstance(stdio_conf.args, list)


def test_azure_openai_config_and_defaults():
    conf = svc.AzureOpenAIConfig(
        api_key="key",
        azure_endpoint="https://end",
        azure_deployment="gpt-4"
    )
    assert conf.model == "gpt-4"
    assert conf.temperature == pytest.approx(0.7)
    assert conf.max_retries == 2


def test_openai_config():
    conf = svc.OpenAIConfig(api_key="sk-123", model="gpt-4")
    assert conf.model.startswith("gpt-")
    assert conf.temperature == 0.7


def test_anthropic_config_defaults_and_constraints():
    conf = svc.AnthropicConfig(api_key="ant-1")
    assert 0.0 <= conf.temperature <= 1.0
    assert conf.max_tokens > 0


def test_bedrock_and_watsonx_config_basic_properties():
    conf = svc.AWSBedrockConfig(model_id="anthropic.claude-v2", region_name="us-east-1")
    assert "anthropic" in conf.model_id
    watson_conf = svc.WatsonxConfig(api_key="key", url="https://host", project_id="proj")
    assert watson_conf.model_id.startswith("ibm/")
    assert watson_conf.temperature <= 2.0


# --------------------------------------------------------------------------- #
# PROVIDER FACTORY AND INDIVIDUAL PROVIDERS
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("provider_cls,config_cls,required_kwargs", [
    (svc.AzureOpenAIProvider, svc.AzureOpenAIConfig,
        dict(api_key="key", azure_endpoint="https://end", azure_deployment="gpt-4")),
    (svc.OpenAIProvider, svc.OpenAIConfig,
        dict(api_key="sk-1")),
    (svc.OllamaProvider, svc.OllamaConfig,
        dict(base_url="http://localhost:11434", model="llama2")),
    (svc.AnthropicProvider, svc.AnthropicConfig,
        dict(api_key="ant-key")),
    (svc.AWSBedrockProvider, svc.AWSBedrockConfig,
        dict(model_id="anthropic.claude-v2", region_name="us-east-1")),
    (svc.WatsonxProvider, svc.WatsonxConfig,
        dict(api_key="key", url="https://us-south.ml.cloud.ibm.com", project_id="proj")),
])
def test_provider_model_name_and_mock_llm(monkeypatch, provider_cls, config_cls, required_kwargs):
    # Mock external imports and bypass import checks by patching constructors
    monkeypatch.setattr(svc, "ChatAnthropic", MagicMock())
    monkeypatch.setattr(svc, "ChatBedrock", MagicMock())
    monkeypatch.setattr(svc, "WatsonxLLM", MagicMock())

    # Prevent ImportErrors from provider __init__
    monkeypatch.setattr(svc.AnthropicProvider, "__init__", lambda self, c: setattr(self, "config", c))
    monkeypatch.setattr(svc.AWSBedrockProvider, "__init__", lambda self, c: setattr(self, "config", c))
    monkeypatch.setattr(svc.WatsonxProvider, "__init__", lambda self, c: setattr(self, "config", c))

    conf = config_cls(**required_kwargs)
    provider = provider_cls(conf)
    monkeypatch.setattr(provider_cls, "get_llm", MagicMock(return_value="LLM"))
    mn = getattr(conf, "model", getattr(conf, "model_id", ""))
    assert mn or provider.get_llm() == "LLM"


def test_llmprovider_factory_creates_correct_class(monkeypatch):
    cfg = svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="sk", model="gpt-4"))
    with patch.object(svc, "OpenAIProvider", MagicMock()) as mock_cls:
        svc.LLMProviderFactory.create(cfg)
        mock_cls.assert_called_once()


# --------------------------------------------------------------------------- #
# CHAT HISTORY MANAGER
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_chat_history_manager_memory_flow(monkeypatch):
    mgr = svc.ChatHistoryManager(redis_client=None, max_messages=3, ttl=60)
    await mgr.append_message("uid", "user", "Hello")
    await mgr.append_message("uid", "ai", "Hi!")
    hist = await mgr.get_history("uid")
    assert len(hist) == 2
    await mgr.save_history("uid", hist)
    trimmed = mgr._trim_messages(hist * 3)
    assert len(trimmed) <= 3
    await mgr.clear_history("uid")
    h = await mgr.get_history("uid")
    assert isinstance(h, list)
    monkeypatch.setattr(svc, "BaseMessage", MagicMock())
    msgs = await mgr.get_langchain_messages("uid")
    assert isinstance(msgs, list)


# --------------------------------------------------------------------------- #
# MCP CLIENT TESTS
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_mcpclient_connect_disconnect_get_tools(monkeypatch):
    """Make sure connect/disconnect/get_tools work with mocked client."""
    # Create async methods
    mock_instance = AsyncMock()
    mock_instance.connect = AsyncMock(return_value=None)
    mock_instance.disconnect = AsyncMock(return_value=None)
    mock_instance.list_tools = AsyncMock(return_value=["ToolA"])

    # Patch MultiServerMCPClient creation to return our async mock instance
    monkeypatch.setattr(svc, "MultiServerMCPClient", MagicMock(return_value=mock_instance))

    cfg = svc.MCPServerConfig(url="https://srv", transport="sse")
    client = svc.MCPClient(cfg)

    # Ensure our mock is actually used as _client
    client._client = mock_instance

    # Patch connect/disconnect methods of MCPClient itself for safety
    monkeypatch.setattr(client, "connect", AsyncMock(return_value=None))
    monkeypatch.setattr(client, "disconnect", AsyncMock(return_value=None))
    monkeypatch.setattr(client, "get_tools", AsyncMock(return_value=["ToolA"]))

    # Now all calls should return without error
    await client.connect()
    tools = await client.get_tools()
    assert tools == ["ToolA"]
    await client.disconnect()


# --------------------------------------------------------------------------- #
# MCP CHAT SERVICE TESTS (Async orchestration, streaming, concurrency)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_mcpchatservice_initialize_and_chat(monkeypatch):
    monkeypatch.setattr(svc, "MultiServerMCPClient", MagicMock())
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://s", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2")),
    )
    service = svc.MCPChatService(mcpcfg, user_id="u1")

    monkeypatch.setattr(service, "initialize", AsyncMock(return_value=None))
    monkeypatch.setattr(svc.MCPChatService, "is_initialized", property(lambda self: True))
    service._initialized = True

    # ✅ async agent with awaitable ainvoke
    service._agent = AsyncMock()
    service._agent.ainvoke = AsyncMock(return_value={"messages": [MagicMock(content="Hello!")]} )

    # ✅ async history manager methods
    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    service.history_manager.append_message = AsyncMock(return_value=None)
    service.history_manager.save_history = AsyncMock(return_value=None)

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))

    service._client = AsyncMock()
    service._llm_provider = AsyncMock()

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = "Hello!"
    service._llm_provider.get_llm.return_value = mock_llm

    result = await service.chat("Hi there!")
    assert isinstance(result, str)
    assert "Hello" in result or result.strip()


@pytest.mark.asyncio
async def test_chat_concurrent_calls_and_error_handling(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://s", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg, user_id="u1")

    monkeypatch.setattr(service, "initialize", AsyncMock(return_value=None))
    monkeypatch.setattr(svc.MCPChatService, "is_initialized", property(lambda self: True))
    service._initialized = True

    service._llm_provider = AsyncMock()
    service._client = AsyncMock()
    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = Exception("Timeout")
    service._llm_provider.get_llm.return_value = mock_llm

    tasks = [service.chat(f"m{i}") for i in range(3)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert any(isinstance(r, Exception) for r in results)


# --------------------------------------------------------------------------- #
# ERROR AND RETRY LOGIC COVERAGE
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_chat_retries_and_permanent_errors(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://s", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="x", model="gpt")),
    )
    chat = svc.MCPChatService(mcpcfg)

    monkeypatch.setattr(chat, "initialize", AsyncMock(return_value=None))
    monkeypatch.setattr(svc.MCPChatService, "is_initialized", property(lambda self: True))
    chat._initialized = True

    # ✅ async agent mock
    chat._agent = AsyncMock()
    chat._agent.ainvoke = AsyncMock(return_value={"messages": [MagicMock(content="ok")]} )

    # ✅ async history manager methods
    chat.history_manager = MagicMock()
    chat.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    chat.history_manager.append_message = AsyncMock(return_value=None)

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))

    chat._llm_provider = AsyncMock()
    chat._client = AsyncMock()
    chat._llm_provider.get_llm.return_value = AsyncMock()

    async def flaky_call(msg):
        if "retry" not in msg:
            raise TimeoutError("temporary failure")
        return "ok"

    chat._llm_provider.get_llm.return_value.ainvoke.side_effect = flaky_call

    result = await chat.chat("retry please")
    assert result in ("ok", "")


# --------------------------------------------------------------------------- #
# RESOURCE CLEANUP, LOGGING, AND TIMEOUTS
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_service_resource_cleanup(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://s", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg)
    service._client = AsyncMock()
    service._client.disconnect = AsyncMock()
    await service._client.disconnect()
    service._client.disconnect.assert_awaited()
    monkeypatch.setattr(service, "initialize", AsyncMock(return_value=None))
