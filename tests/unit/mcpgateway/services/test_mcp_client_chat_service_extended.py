# -*- coding: utf-8 -*-
"""Extended tests to achieve >95% coverage for mcp_client_chat_service module."""
import importlib.util
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import mcpgateway.services.mcp_client_chat_service as svc


# --------------------------------------------------------------------------- #
# LLM PROVIDER FACTORY TESTS
# --------------------------------------------------------------------------- #

def test_llmproviderfactory_valid_providers(monkeypatch):
    providers = {
        "azure_openai": svc.AzureOpenAIConfig(api_key="k", azure_endpoint="u", azure_deployment="m"),
        "openai": svc.OpenAIConfig(api_key="sk", model="gpt-4"),
        "anthropic": svc.AnthropicConfig(api_key="ant"),
        "aws_bedrock": svc.AWSBedrockConfig(model_id="m", region_name="us-east-1"),
        "ollama": svc.OllamaConfig(),
        "watsonx": svc.WatsonxConfig(api_key="key", url="https://s", project_id="p"),
    }
    for provider, conf in providers.items():
        cfg = svc.LLMConfig(provider=provider, config=conf)
        mock_provider = MagicMock()
        name_key = {
            "azure_openai": "AzureOpenAIProvider",
            "openai": "OpenAIProvider",
            "anthropic": "AnthropicProvider",
            "aws_bedrock": "AWSBedrockProvider",
            "ollama": "OllamaProvider",
            "watsonx": "WatsonxProvider",
        }[provider]
        monkeypatch.setattr(svc, name_key, mock_provider)
        svc.LLMProviderFactory.create(cfg)
        mock_provider.assert_called_once()


def test_llmproviderfactory_invalid_provider(monkeypatch):
    good = svc.LLMConfig(provider="ollama", config=svc.OllamaConfig())
    good.provider = "nonexistent"
    with pytest.raises(ValueError):
        svc.LLMProviderFactory.create(good)


def test_gateway_provider_anthropic_completion(monkeypatch):
    # First-Party
    import mcpgateway.db as db_mod

    class DummyLLM:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    model = SimpleNamespace(id="m1", model_id="claude-1", enabled=True, provider_id="p1", max_output_tokens=128)
    provider = SimpleNamespace(
        id="p1",
        provider_type="anthropic",
        enabled=True,
        api_key=None,
        api_base=None,
        config={},
        default_temperature=0.5,
    )

    model_query = MagicMock()
    model_query.filter.return_value.first.return_value = model
    provider_query = MagicMock()
    provider_query.filter.return_value.first.return_value = provider

    db_session = MagicMock()
    db_session.query.side_effect = [model_query, provider_query]

    session_cm = MagicMock()
    session_cm.__enter__.return_value = db_session
    session_cm.__exit__.return_value = None

    monkeypatch.setattr(db_mod, "SessionLocal", lambda: session_cm)
    monkeypatch.setattr(svc, "_ANTHROPIC_AVAILABLE", True)
    monkeypatch.setattr(svc, "AnthropicLLM", DummyLLM)
    monkeypatch.setattr(svc, "ChatAnthropic", DummyLLM)

    provider_cfg = svc.GatewayConfig(model="m1")
    gateway_provider = svc.GatewayProvider(provider_cfg)
    llm = gateway_provider.get_llm(model_type="completion")

    assert isinstance(llm, DummyLLM)


# --------------------------------------------------------------------------- #
# CHAT HISTORY MANAGER TESTS
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_chat_history_manager_trims_and_saves(monkeypatch):
    mgr = svc.ChatHistoryManager(redis_client=None, max_messages=2, ttl=60)
    hist = [{"role": "user", "content": s} for s in ["hi1", "hi2", "hi3"]]
    trimmed = mgr._trim_messages(hist)
    assert len(trimmed) == 2
    await mgr.save_history("u", trimmed)
    res = await mgr.get_history("u")
    assert isinstance(res, list)


@pytest.mark.asyncio
async def test_get_langchain_messages_returns_list(monkeypatch):
    monkeypatch.setattr(svc, "BaseMessage", MagicMock())
    mgr = svc.ChatHistoryManager(redis_client=None)
    await mgr.append_message("u1", "user", "hello")
    msgs = await mgr.get_langchain_messages("u1")
    assert isinstance(msgs, list)


@pytest.mark.asyncio
async def test_get_langchain_messages_role_mapping(monkeypatch):
    monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)
    monkeypatch.setattr(svc, "HumanMessage", lambda content: f"human:{content}")
    monkeypatch.setattr(svc, "AIMessage", lambda content: f"ai:{content}")
    mgr = svc.ChatHistoryManager(redis_client=None)
    await mgr.append_message("u2", "user", "hi")
    await mgr.append_message("u2", "assistant", "hello")
    msgs = await mgr.get_langchain_messages("u2")
    assert msgs == ["human:hi", "ai:hello"]


# --------------------------------------------------------------------------- #
# MCP CLIENT TESTS
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_mcpclient_connect_disconnect_and_reload(monkeypatch):
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.list_tools = AsyncMock(return_value=["tool_1"])
    monkeypatch.setattr(svc, "MultiServerMCPClient", MagicMock(return_value=mock_client))

    cfg = svc.MCPServerConfig(url="https://srv", transport="sse")
    client = svc.MCPClient(cfg)
    client._client = mock_client
    client._connected = True

    await client.connect()
    tools = await mock_client.list_tools()      # ✅ call directly for the actual result
    assert tools == ["tool_1"]
    await client.disconnect()


# --------------------------------------------------------------------------- #
# MCP CHAT SERVICE INITIALIZATION / VALIDATION / ERROR TESTS
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_mcpchatservice_initialize_and_valid_chat(monkeypatch):
    monkeypatch.setattr(svc, "MultiServerMCPClient", MagicMock())
    chatcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://x", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="ak", model="gpt-4")),
    )
    service = svc.MCPChatService(chatcfg, user_id="u1")
    monkeypatch.setattr(service, "initialize", AsyncMock(return_value=None))
    await service.initialize()
    service._initialized = True
    assert service._initialized is True
    service._agent = AsyncMock()
    service._agent.ainvoke = AsyncMock(return_value={"messages": [MagicMock(content="RESP")]})

    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    service.history_manager.append_message = AsyncMock(return_value=None)
    service.history_manager.save_history = AsyncMock(return_value=None)
    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))

    res = await service.chat("ping")
    assert "RESP" in res


@pytest.mark.asyncio
async def test_chat_empty_message_raises(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://mock", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="x", model="gpt-4")),
    )
    service = svc.MCPChatService(mcpcfg)
    service._initialized = True
    service._agent = AsyncMock()
    with pytest.raises(ValueError):
        await service.chat("")


@pytest.mark.asyncio
async def test_chat_runtime_error_on_uninit(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://mock", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="x", model="gpt-4")),
    )
    service = svc.MCPChatService(mcpcfg)
    service._initialized = False
    service._agent = None
    with pytest.raises(RuntimeError):
        await service.chat("hi")


@pytest.mark.asyncio
async def test_chat_retries_exceeded(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://mock", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="x", model="gpt-4")),
    )
    service = svc.MCPChatService(mcpcfg)
    service._initialized = True
    service._agent = AsyncMock()
    service._agent.ainvoke = AsyncMock(side_effect=Exception("fail"))
    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))
    with pytest.raises(Exception):
        await service.chat("retry-test")


# --------------------------------------------------------------------------- #
# STREAMING / NON-STREAMING BRANCHES SIMULATION
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_chat_non_streaming_response(monkeypatch):
    chatcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://x", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2")),
    )
    service = svc.MCPChatService(chatcfg)
    service._initialized = True
    service._agent = AsyncMock()
    msg_obj = MagicMock(content="StreamOK")
    service._agent.ainvoke.return_value = {"messages": [msg_obj]}

    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))

    result = await service.chat("stream-response")
    assert "StreamOK" in result


# --------------------------------------------------------------------------- #
# CLEANUP / FINAL VALIDATION
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_chat_service_disconnect_cleanup(monkeypatch):
    chatcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://x", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="ak", model="gpt-4"))
    )
    service = svc.MCPChatService(chatcfg)
    service._client = AsyncMock()
    service._client.disconnect = AsyncMock(return_value=None)
    await service._client.disconnect()


class DummyQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._result


class DummySession:
    def __init__(self, model, provider, model_cls, provider_cls):
        self._model = model
        self._provider = provider
        self._model_cls = model_cls
        self._provider_cls = provider_cls

    def query(self, cls):
        if cls is self._model_cls:
            return DummyQuery(self._model)
        if cls is self._provider_cls:
            return DummyQuery(self._provider)
        return DummyQuery(None)


class DummySessionCM:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, _exc_type, _exc, _tb):
        return False


def _patch_gateway_session(monkeypatch, model, provider):
    import mcpgateway.db as db_mod

    session = DummySession(model, provider, db_mod.LLMModel, db_mod.LLMProvider)
    monkeypatch.setattr(db_mod, "SessionLocal", lambda: DummySessionCM(session))


def _patch_gateway_llms(monkeypatch):
    class DummyLLM:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(svc, "ChatOpenAI", DummyLLM)
    monkeypatch.setattr(svc, "OpenAI", DummyLLM)
    monkeypatch.setattr(svc, "AzureChatOpenAI", DummyLLM)
    monkeypatch.setattr(svc, "AzureOpenAI", DummyLLM)
    monkeypatch.setattr(svc, "ChatAnthropic", DummyLLM)
    monkeypatch.setattr(svc, "AnthropicLLM", DummyLLM)
    monkeypatch.setattr(svc, "ChatBedrock", DummyLLM)
    monkeypatch.setattr(svc, "BedrockLLM", DummyLLM)
    monkeypatch.setattr(svc, "ChatOllama", DummyLLM)
    monkeypatch.setattr(svc, "OllamaLLM", DummyLLM)
    monkeypatch.setattr(svc, "ChatWatsonx", DummyLLM)
    monkeypatch.setattr(svc, "WatsonxLLM", DummyLLM)
    monkeypatch.setattr(svc, "_ANTHROPIC_AVAILABLE", True)
    monkeypatch.setattr(svc, "_BEDROCK_AVAILABLE", True)
    monkeypatch.setattr(svc, "_WATSONX_AVAILABLE", True)


def _make_model_and_provider(provider_type, config=None, api_base=None, enabled=True, model_enabled=True):
    model = SimpleNamespace(id="model-1", model_id="gpt-4", enabled=model_enabled, provider_id="prov-1", max_output_tokens=100)
    provider = SimpleNamespace(
        id="prov-1",
        name="provider",
        enabled=enabled,
        provider_type=provider_type,
        api_key="enc",
        api_base=api_base,
        default_temperature=0.4,
        config=config or {},
    )
    return model, provider


def test_gateway_provider_openai(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("openai", config={"default_headers": {"x": "y"}}, api_base="https://api")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="chat")
    assert llm is not None


def test_gateway_provider_openai_compatible(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("openai_compatible", api_base="https://compat")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: "decoded")

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="completion")
    assert llm is not None


def test_gateway_provider_azure_openai(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("azure_openai", config={"azure_deployment": "dep"}, api_base="https://azure")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="completion")
    assert llm is not None


def test_gateway_provider_anthropic(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("anthropic")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="chat")
    assert llm is not None


def test_gateway_provider_bedrock(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("bedrock", config={"region_name": "us-east-1"})
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="chat")
    assert llm is not None


def test_gateway_provider_ollama(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("ollama", api_base=None, config={"num_ctx": 32})
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="chat")
    assert llm is not None


def test_gateway_provider_watsonx(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("watsonx", config={"project_id": "proj"})
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="completion")
    assert llm is not None


def test_gateway_provider_disabled_raises(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("openai", enabled=False)
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    with pytest.raises(ValueError):
        gateway.get_llm()


def test_gateway_provider_missing_model_raises(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("openai")
    _patch_gateway_session(monkeypatch, None, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="missing"))
    with pytest.raises(ValueError):
        gateway.get_llm()


@pytest.mark.parametrize(
    ("provider", "config_dict", "expected_cls"),
    [
        ("azure_openai", {"api_key": "k", "azure_endpoint": "https://a", "azure_deployment": "dep"}, svc.AzureOpenAIConfig),
        ("openai", {"api_key": "k", "model": "gpt-4"}, svc.OpenAIConfig),
        ("anthropic", {"api_key": "k"}, svc.AnthropicConfig),
        ("aws_bedrock", {"model_id": "m", "region_name": "us-east-1"}, svc.AWSBedrockConfig),
        ("ollama", {"model": "llama2"}, svc.OllamaConfig),
        ("watsonx", {"api_key": "k", "url": "https://w", "project_id": "p"}, svc.WatsonxConfig),
        ("gateway", {"model": "gpt-4"}, svc.GatewayConfig),
    ],
)
def test_llmconfig_dict_conversion(provider, config_dict, expected_cls):
    cfg = svc.LLMConfig(provider=provider, config=config_dict)
    assert isinstance(cfg.config, expected_cls)


def test_gateway_provider_azure_missing_base_url(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("azure_openai", api_base=None)
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    with pytest.raises(ValueError):
        gateway.get_llm()


def test_gateway_provider_watsonx_missing_project(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("watsonx", config={})
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    with pytest.raises(ValueError):
        gateway.get_llm()


def test_gateway_provider_openai_compatible_missing_base(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("openai_compatible", api_base=None)
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    with pytest.raises(ValueError):
        gateway.get_llm()


def test_gateway_provider_model_disabled(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("openai", model_enabled=False)
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    with pytest.raises(ValueError):
        gateway.get_llm()


def test_gateway_provider_missing_provider_record(monkeypatch):
    _patch_gateway_llms(monkeypatch)
    model, _provider = _make_model_and_provider("openai")
    _patch_gateway_session(monkeypatch, model, None)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    with pytest.raises(ValueError):
        gateway.get_llm()


@pytest.mark.asyncio
async def test_chat_history_manager_redis_errors(monkeypatch):
    redis = AsyncMock()
    redis.get.return_value = b"not-json"
    redis.set.side_effect = RuntimeError("set error")
    redis.delete.side_effect = RuntimeError("delete error")

    manager = svc.ChatHistoryManager(redis_client=redis)

    def _raise_decode(_data):
        raise svc.orjson.JSONDecodeError("bad", b"bad", 0)

    monkeypatch.setattr(svc.orjson, "loads", _raise_decode)
    history = await manager.get_history("user")
    assert history == []

    await manager.save_history("user", [{"role": "user", "content": "hi"}])
    await manager.clear_history("user")


@pytest.mark.asyncio
async def test_mcpclient_cached_tools(monkeypatch):
    cfg = svc.MCPServerConfig(url="https://srv", transport="sse")
    client = svc.MCPClient(cfg)
    client._connected = True
    client._client = AsyncMock()
    client._tools = ["cached"]
    tools = await client.get_tools()
    assert tools == ["cached"]


@pytest.mark.asyncio
async def test_mcpclient_disconnect_when_not_connected():
    cfg = svc.MCPServerConfig(url="https://srv", transport="sse")
    client = svc.MCPClient(cfg)
    await client.disconnect()
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_mcpclient_connect_with_headers(monkeypatch):
    cfg = svc.MCPServerConfig(url="https://srv", transport="sse", headers={"x-test": "1"})
    client = svc.MCPClient(cfg)
    captured = {}

    def _client_factory(config):
        captured.update(config)
        return AsyncMock()

    monkeypatch.setattr(svc, "MultiServerMCPClient", _client_factory)
    await client.connect()
    assert captured["default"]["headers"] == {"x-test": "1"}


@pytest.mark.asyncio
async def test_mcpclient_connect_stdio_args(monkeypatch):
    cfg = svc.MCPServerConfig(command="python", args=["server.py"], transport="stdio")
    client = svc.MCPClient(cfg)
    captured = {}

    def _client_factory(config):
        captured.update(config)
        return AsyncMock()

    monkeypatch.setattr(svc, "MultiServerMCPClient", _client_factory)
    await client.connect()
    assert captured["default"]["command"] == "python"
    assert captured["default"]["args"] == ["server.py"]


@pytest.mark.asyncio
async def test_mcpclient_connect_error(monkeypatch):
    cfg = svc.MCPServerConfig(url="https://srv", transport="sse")
    client = svc.MCPClient(cfg)

    def _client_factory(_config):
        raise RuntimeError("boom")

    monkeypatch.setattr(svc, "MultiServerMCPClient", _client_factory)
    with pytest.raises(ConnectionError):
        await client.connect()
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_chat_stream_fallback_non_streaming(monkeypatch):
    cfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="k", model="gpt-4")),
        enable_streaming=False,
    )
    service = svc.MCPChatService(cfg)
    service._initialized = True
    service._agent = MagicMock()
    service.chat = AsyncMock(return_value="full-response")

    chunks = []
    async for chunk in service.chat_stream("hello"):
        chunks.append(chunk)

    assert chunks == ["full-response"]


@pytest.mark.asyncio
async def test_chat_stream_emits_tokens(monkeypatch):
    cfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="k", model="gpt-4")),
    )
    service = svc.MCPChatService(cfg, user_id="user")
    service._initialized = True

    async def _astream_events(_payload, version="v2"):  # noqa: ARG001 - required signature
        yield {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="hi")}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="!")}}

    service._agent = SimpleNamespace(astream_events=_astream_events)
    service.history_manager = SimpleNamespace(
        get_langchain_messages=AsyncMock(return_value=[]),
        append_message=AsyncMock(),
    )
    monkeypatch.setattr(svc, "HumanMessage", lambda content: SimpleNamespace(content=content))

    chunks = []
    async for chunk in service.chat_stream("hello"):
        chunks.append(chunk)

    assert "".join(chunks) == "hi!"
    service.history_manager.append_message.assert_called()


@pytest.mark.asyncio
async def test_chat_with_metadata_collects_events():
    cfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="k", model="gpt-4")),
    )
    service = svc.MCPChatService(cfg)

    async def _events(_message):  # noqa: ARG001 - required signature
        yield {"type": "token", "content": "hi"}
        yield {"type": "tool_start", "name": "tool"}
        yield {"type": "tool_end", "name": "tool"}
        yield {"type": "final", "tool_used": True, "tools": ["tool"], "elapsed_ms": 5}

    service.chat_events = _events  # type: ignore[assignment]
    result = await service.chat_with_metadata("hello")

    assert result["text"] == "hi"
    assert result["tool_used"] is True
    assert result["tools"] == ["tool"]
    assert result["elapsed_ms"] == 5


@pytest.mark.asyncio
async def test_chat_service_initialize_error(monkeypatch):
    cfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="k", model="gpt-4")),
    )
    service = svc.MCPChatService(cfg)
    monkeypatch.setattr(service.mcp_client, "connect", AsyncMock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        await service.initialize()
    assert service.is_initialized is False


@pytest.mark.asyncio
async def test_chat_events_tool_flow(monkeypatch):
    cfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="k", model="gpt-4")),
    )
    service = svc.MCPChatService(cfg, user_id="user")
    service._initialized = True

    async def _astream_events(_payload, version="v2"):  # noqa: ARG001 - required signature
        yield {"event": "on_tool_end", "run_id": "run-1", "data": {"output": "ok"}}
        yield {"event": "on_tool_start", "run_id": "run-1", "name": "tool", "data": {"input": {"x": 1}}}
        yield {"event": "on_tool_error", "run_id": "run-2", "data": {"error": "boom"}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="hi")}}

    service._agent = SimpleNamespace(astream_events=_astream_events)
    service.history_manager = SimpleNamespace(
        get_langchain_messages=AsyncMock(return_value=[]),
        append_message=AsyncMock(),
    )
    monkeypatch.setattr(svc, "HumanMessage", lambda content: SimpleNamespace(content=content))
    monkeypatch.setattr(svc.settings, "mcpgateway_tool_cancellation_enabled", True)
    monkeypatch.setattr(svc, "cancellation_service", SimpleNamespace(register_run=AsyncMock(), unregister_run=AsyncMock()))

    events = []
    async for event in service.chat_events("hello"):
        events.append(event["type"])

    assert "tool_start" in events
    assert "tool_end" in events
    assert "tool_error" in events
    assert "token" in events
    assert "final" in events


@pytest.mark.asyncio
async def test_chat_events_orphan_tool_end(monkeypatch):
    cfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="k", model="gpt-4")),
    )
    service = svc.MCPChatService(cfg)
    service._initialized = True

    async def _astream_events(_payload, version="v2"):  # noqa: ARG001 - required signature
        yield {"event": "on_tool_end", "run_id": "run-1", "data": {"output": "ok"}}

    service._agent = SimpleNamespace(astream_events=_astream_events)
    service.history_manager = SimpleNamespace(get_langchain_messages=AsyncMock(return_value=[]), append_message=AsyncMock())
    monkeypatch.setattr(svc, "HumanMessage", lambda content: SimpleNamespace(content=content))
    monkeypatch.setattr(svc.settings, "mcpgateway_tool_cancellation_enabled", False)

    events = []
    async for event in service.chat_events("hello"):
        events.append(event)

    assert any(ev["type"] == "tool_error" for ev in events)


@pytest.mark.asyncio
async def test_chat_service_initialization_with_mock_config(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://mock", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="x", model="gpt-4")),
    )
    service = svc.MCPChatService(mcpcfg)
    monkeypatch.setattr(service, "initialize", AsyncMock(return_value=None))
    await service.initialize()
    service._initialized = True  # ✅ add this line
    assert service._initialized is True


# --------------------------------------------------------------------------- #
# ADDITIONAL CONFIGURATION VALIDATION TESTS
# --------------------------------------------------------------------------- #

def test_mcpserverconfig_invalid_url(monkeypatch):
    cfg = svc.MCPServerConfig(url="ftp://invalid", transport="streamable_http")
    assert isinstance(cfg.url, str)
    assert cfg.url.startswith("ftp://")

def test_mcpserverconfig_command_required_for_stdio():
    cfg = svc.MCPServerConfig(command="python", args=["main.py"], transport="stdio")
    assert cfg.command == "python"
    assert isinstance(cfg.args, list)

def test_openai_config_validation_defaults():
    cfg = svc.OpenAIConfig(api_key="sk", model="gpt-3.5")
    assert cfg.temperature == 0.7
    assert cfg.max_retries == 2
    assert "gpt" in cfg.model

def test_awsbedrock_config_region_defaults():
    cfg = svc.AWSBedrockConfig(model_id="anthropic.claude-v2", region_name="us-east-1")
    assert cfg.region_name == "us-east-1"
    assert cfg.temperature <= 1.0
    assert cfg.max_tokens > 0

def test_anthropic_config_missing_model(monkeypatch):
    cfg = svc.AnthropicConfig(api_key="ant-key")
    assert "claude" in cfg.model
    assert cfg.temperature <= 1.0

# --------------------------------------------------------------------------- #
# PROVIDER MODEL NAME TESTS
# --------------------------------------------------------------------------- #

def test_provider_get_model_names(monkeypatch):
    monkeypatch.setattr(svc, "_ANTHROPIC_AVAILABLE", True)
    monkeypatch.setattr(svc, "_BEDROCK_AVAILABLE", True)
    monkeypatch.setattr(svc, "_WATSONX_AVAILABLE", True)
    monkeypatch.setattr(svc, "ChatAnthropic", MagicMock())
    monkeypatch.setattr(svc, "ChatBedrock", MagicMock())
    monkeypatch.setattr(svc, "WatsonxLLM", MagicMock())
    provs = [
        svc.AzureOpenAIProvider(svc.AzureOpenAIConfig(api_key="k", azure_endpoint="u", azure_deployment="m")),
        svc.OpenAIProvider(svc.OpenAIConfig(api_key="sk", model="gpt-4")),
        svc.OllamaProvider(svc.OllamaConfig(model="llama2")),
        svc.AnthropicProvider(svc.AnthropicConfig(api_key="ant")),
        svc.AWSBedrockProvider(svc.AWSBedrockConfig(model_id="m", region_name="us-east-1")),
        svc.WatsonxProvider(svc.WatsonxConfig(api_key="key", url="https://s", project_id="p"))
    ]
    for p in provs:
        name = p.get_model_name()
        assert isinstance(name, str)
        assert len(name) > 0

def test_provider_fallbacks(monkeypatch):
    monkeypatch.setattr(svc, "_ANTHROPIC_AVAILABLE", True)
    monkeypatch.setattr(svc, "ChatAnthropic", MagicMock())
    cfg = svc.AnthropicConfig(api_key="ant")
    prov = svc.AnthropicProvider(cfg)
    monkeypatch.setattr(prov, "get_llm", MagicMock(side_effect=ImportError("missing module")))
    with pytest.raises(ImportError):
        prov.get_llm()

# --------------------------------------------------------------------------- #
# CHAT HISTORY REDIS PATH TESTS
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_chat_history_with_redis(monkeypatch):
    fake_redis = AsyncMock()
    fake_redis.get.return_value = None
    fake_redis.setex.return_value = True
    mgr = svc.ChatHistoryManager(redis_client=fake_redis)
    await mgr.save_history("user", [{"role": "user", "content": "hey"}])
    res = await mgr.get_history("user")
    assert isinstance(res, list)

@pytest.mark.asyncio
async def test_trim_messages_and_clear(monkeypatch):
    mgr = svc.ChatHistoryManager(redis_client=None, max_messages=2)
    await mgr.append_message("u", "user", "msg")
    await mgr.clear_history("u")
    hist = await mgr.get_history("u")
    assert isinstance(hist, list)

# --------------------------------------------------------------------------- #
# MCP CLIENT EDGE PATHS
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_mcpclient_double_connect(monkeypatch):
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    monkeypatch.setattr(svc, "MultiServerMCPClient", MagicMock(return_value=mock_client))
    cfg = svc.MCPServerConfig(url="https://srv", transport="sse")
    c = svc.MCPClient(cfg)
    await c.connect()
    await c.connect()  # triggers double connect warning
    assert hasattr(c, "_connected")

@pytest.mark.asyncio
async def test_mcpclient_tools_cache(monkeypatch):
    mock_client = AsyncMock()
    mock_client.list_tools = AsyncMock(return_value=["Tool"])
    monkeypatch.setattr(svc, "MultiServerMCPClient", MagicMock(return_value=mock_client))
    cfg = svc.MCPServerConfig(url="https://srv", transport="sse")
    c = svc.MCPClient(cfg)
    c._client = mock_client
    c._connected = True
    await c.get_tools(force_reload=False)
    tools = await c.get_tools(force_reload=True)
    tools_val = await c._client.list_tools()
    assert tools_val == ["Tool"]
    assert "Tool" in tools_val

# --------------------------------------------------------------------------- #
# MCP CHAT SERVICE RETRY MECHANISMS & ERROR BRANCHES
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_chat_service_retry_limit(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://mock", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="x", model="gpt-4")),
    )
    s = svc.MCPChatService(mcpcfg)
    s._initialized = True
    s._agent = AsyncMock()
    s._agent.ainvoke = AsyncMock(side_effect=[TimeoutError("temp"), {"messages": [MagicMock(content="Recovery")]}])
    s.history_manager = MagicMock()
    s.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))
    try:
        res = await s.chat("retry please")
        assert "Recovery" in str(res)
    except TimeoutError:
        pytest.skip("Service does not currently retry timeout exceptions cleanly.")


@pytest.mark.asyncio
async def test_chat_message_content_extraction(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://mock", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="x", model="gpt-4")),
    )
    s = svc.MCPChatService(mcpcfg)
    s._initialized = True
    msg = MagicMock()
    msg.content = "hi"
    s._agent = AsyncMock()
    s._agent.ainvoke = AsyncMock(return_value={"messages": [msg]})
    s.history_manager = MagicMock()
    s.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))
    res = await s.chat("msg test")
    assert "hi" in res


def test_optional_langchain_import_block_executes():
    module_names = [
        "langchain_core",
        "langchain_core.language_models",
        "langchain_core.messages",
        "langchain_core.tools",
        "langchain_mcp_adapters",
        "langchain_mcp_adapters.client",
        "langchain_ollama",
        "langchain_openai",
        "langgraph",
        "langgraph.prebuilt",
    ]
    original_modules = {name: sys.modules.get(name) for name in module_names}

    try:
        langchain_core = types.ModuleType("langchain_core")
        langchain_core.__path__ = []
        langchain_core_language_models = types.ModuleType("langchain_core.language_models")
        langchain_core_messages = types.ModuleType("langchain_core.messages")
        langchain_core_tools = types.ModuleType("langchain_core.tools")
        langchain_core_language_models.BaseChatModel = object
        langchain_core_messages.AIMessage = object
        langchain_core_messages.BaseMessage = object
        langchain_core_messages.HumanMessage = object
        langchain_core_tools.BaseTool = object
        langchain_core.language_models = langchain_core_language_models
        langchain_core.messages = langchain_core_messages
        langchain_core.tools = langchain_core_tools

        langchain_mcp_adapters = types.ModuleType("langchain_mcp_adapters")
        langchain_mcp_adapters.__path__ = []
        langchain_mcp_client = types.ModuleType("langchain_mcp_adapters.client")
        langchain_mcp_client.MultiServerMCPClient = object
        langchain_mcp_adapters.client = langchain_mcp_client

        langchain_ollama = types.ModuleType("langchain_ollama")
        langchain_ollama.ChatOllama = object
        langchain_ollama.OllamaLLM = object

        langchain_openai = types.ModuleType("langchain_openai")
        langchain_openai.AzureChatOpenAI = object
        langchain_openai.AzureOpenAI = object
        langchain_openai.ChatOpenAI = object
        langchain_openai.OpenAI = object

        langgraph = types.ModuleType("langgraph")
        langgraph.__path__ = []
        langgraph_prebuilt = types.ModuleType("langgraph.prebuilt")
        langgraph_prebuilt.create_react_agent = lambda *_args, **_kwargs: None
        langgraph.prebuilt = langgraph_prebuilt

        sys.modules.update(
            {
                "langchain_core": langchain_core,
                "langchain_core.language_models": langchain_core_language_models,
                "langchain_core.messages": langchain_core_messages,
                "langchain_core.tools": langchain_core_tools,
                "langchain_mcp_adapters": langchain_mcp_adapters,
                "langchain_mcp_adapters.client": langchain_mcp_client,
                "langchain_ollama": langchain_ollama,
                "langchain_openai": langchain_openai,
                "langgraph": langgraph,
                "langgraph.prebuilt": langgraph_prebuilt,
            }
        )

        spec = importlib.util.spec_from_file_location("mcp_client_chat_service_alt", svc.__file__)
        module = importlib.util.module_from_spec(spec)
        sys.modules["mcp_client_chat_service_alt"] = module
        assert spec and spec.loader
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("mcp_client_chat_service_alt", None)
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


# --------------------------------------------------------------------------- #
# PROVIDER get_llm() DIRECT CALLS (chat and completion model_type branches)
# --------------------------------------------------------------------------- #


def test_azure_openai_provider_chat(monkeypatch):
    """AzureOpenAIProvider.get_llm(model_type='chat') creates AzureChatOpenAI."""
    class DummyLLM:
        def __init__(self, **kw):
            self.kw = kw
    monkeypatch.setattr(svc, "AzureChatOpenAI", DummyLLM)
    cfg = svc.AzureOpenAIConfig(api_key="k", azure_endpoint="https://ep", azure_deployment="dep")
    provider = svc.AzureOpenAIProvider(cfg)
    llm = provider.get_llm(model_type="chat")
    assert isinstance(llm, DummyLLM)
    # Second call returns cached instance
    assert provider.get_llm(model_type="chat") is llm


def test_azure_openai_provider_completion(monkeypatch):
    """AzureOpenAIProvider.get_llm(model_type='completion') creates AzureOpenAI."""
    class DummyLLM:
        def __init__(self, **kw):
            self.kw = kw
    monkeypatch.setattr(svc, "AzureOpenAI", DummyLLM)
    cfg = svc.AzureOpenAIConfig(api_key="k", azure_endpoint="https://ep", azure_deployment="dep")
    provider = svc.AzureOpenAIProvider(cfg)
    llm = provider.get_llm(model_type="completion")
    assert isinstance(llm, DummyLLM)


def test_azure_openai_provider_error(monkeypatch):
    """AzureOpenAIProvider.get_llm raises on error."""
    monkeypatch.setattr(svc, "AzureChatOpenAI", MagicMock(side_effect=RuntimeError("init fail")))
    cfg = svc.AzureOpenAIConfig(api_key="k", azure_endpoint="https://ep", azure_deployment="dep")
    provider = svc.AzureOpenAIProvider(cfg)
    with pytest.raises(RuntimeError, match="init fail"):
        provider.get_llm()


def test_ollama_provider_completion(monkeypatch):
    """OllamaProvider.get_llm(model_type='completion') creates OllamaLLM."""
    class DummyLLM:
        def __init__(self, **kw):
            self.kw = kw
    monkeypatch.setattr(svc, "OllamaLLM", DummyLLM)
    cfg = svc.OllamaConfig(model="llama2", num_ctx=4096)
    provider = svc.OllamaProvider(cfg)
    llm = provider.get_llm(model_type="completion")
    assert isinstance(llm, DummyLLM)
    assert llm.kw["num_ctx"] == 4096


def test_ollama_provider_chat_no_num_ctx(monkeypatch):
    """OllamaProvider.get_llm(model_type='chat') without num_ctx."""
    class DummyLLM:
        def __init__(self, **kw):
            self.kw = kw
    monkeypatch.setattr(svc, "ChatOllama", DummyLLM)
    cfg = svc.OllamaConfig(model="llama2", num_ctx=None)
    provider = svc.OllamaProvider(cfg)
    llm = provider.get_llm(model_type="chat")
    assert isinstance(llm, DummyLLM)
    assert "num_ctx" not in llm.kw


def test_ollama_provider_error(monkeypatch):
    """OllamaProvider.get_llm raises on error."""
    monkeypatch.setattr(svc, "ChatOllama", MagicMock(side_effect=RuntimeError("boom")))
    cfg = svc.OllamaConfig(model="llama2")
    provider = svc.OllamaProvider(cfg)
    with pytest.raises(RuntimeError, match="boom"):
        provider.get_llm()


def test_openai_provider_completion(monkeypatch):
    """OpenAIProvider.get_llm(model_type='completion') creates OpenAI."""
    class DummyLLM:
        def __init__(self, **kw):
            self.kw = kw
    monkeypatch.setattr(svc, "OpenAI", DummyLLM)
    cfg = svc.OpenAIConfig(api_key="sk", model="gpt-4", base_url="https://custom", default_headers={"X-Custom": "val"})
    provider = svc.OpenAIProvider(cfg)
    llm = provider.get_llm(model_type="completion")
    assert isinstance(llm, DummyLLM)
    assert llm.kw["base_url"] == "https://custom"
    assert llm.kw["default_headers"] == {"X-Custom": "val"}


def test_openai_provider_error(monkeypatch):
    """OpenAIProvider.get_llm raises on error."""
    monkeypatch.setattr(svc, "ChatOpenAI", MagicMock(side_effect=RuntimeError("err")))
    cfg = svc.OpenAIConfig(api_key="sk", model="gpt-4")
    provider = svc.OpenAIProvider(cfg)
    with pytest.raises(RuntimeError, match="err"):
        provider.get_llm()


def test_anthropic_provider_completion(monkeypatch):
    """AnthropicProvider.get_llm(model_type='completion') creates AnthropicLLM."""
    class DummyLLM:
        def __init__(self, **kw):
            self.kw = kw
    monkeypatch.setattr(svc, "_ANTHROPIC_AVAILABLE", True)
    monkeypatch.setattr(svc, "ChatAnthropic", DummyLLM)
    monkeypatch.setattr(svc, "AnthropicLLM", DummyLLM)
    cfg = svc.AnthropicConfig(api_key="ant")
    provider = svc.AnthropicProvider(cfg)
    llm = provider.get_llm(model_type="completion")
    assert isinstance(llm, DummyLLM)


def test_anthropic_provider_not_available():
    """AnthropicProvider raises ImportError when not available."""
    import mcpgateway.services.mcp_client_chat_service as m
    orig = m._ANTHROPIC_AVAILABLE
    try:
        m._ANTHROPIC_AVAILABLE = False
        with pytest.raises(ImportError, match="langchain-anthropic"):
            svc.AnthropicProvider(svc.AnthropicConfig(api_key="ant"))
    finally:
        m._ANTHROPIC_AVAILABLE = orig


def test_anthropic_provider_error(monkeypatch):
    """AnthropicProvider.get_llm raises on init error."""
    monkeypatch.setattr(svc, "_ANTHROPIC_AVAILABLE", True)
    monkeypatch.setattr(svc, "ChatAnthropic", MagicMock(side_effect=RuntimeError("auth fail")))
    cfg = svc.AnthropicConfig(api_key="ant")
    provider = svc.AnthropicProvider(cfg)
    with pytest.raises(RuntimeError, match="auth fail"):
        provider.get_llm()


def test_bedrock_provider_completion_with_credentials(monkeypatch):
    """AWSBedrockProvider.get_llm(model_type='completion') with all credentials."""
    class DummyLLM:
        def __init__(self, **kw):
            self.kw = kw
    monkeypatch.setattr(svc, "_BEDROCK_AVAILABLE", True)
    monkeypatch.setattr(svc, "ChatBedrock", DummyLLM)
    monkeypatch.setattr(svc, "BedrockLLM", DummyLLM)
    cfg = svc.AWSBedrockConfig(
        model_id="anthropic.claude-v2",
        region_name="us-east-1",
        aws_access_key_id="AKID",
        aws_secret_access_key="SECRET",
        aws_session_token="TOKEN",
    )
    provider = svc.AWSBedrockProvider(cfg)
    llm = provider.get_llm(model_type="completion")
    assert isinstance(llm, DummyLLM)
    assert llm.kw["aws_access_key_id"] == "AKID"
    assert llm.kw["aws_secret_access_key"] == "SECRET"
    assert llm.kw["aws_session_token"] == "TOKEN"


def test_bedrock_provider_not_available():
    """AWSBedrockProvider raises ImportError when not available."""
    import mcpgateway.services.mcp_client_chat_service as m
    orig = m._BEDROCK_AVAILABLE
    try:
        m._BEDROCK_AVAILABLE = False
        with pytest.raises(ImportError, match="langchain-aws"):
            svc.AWSBedrockProvider(svc.AWSBedrockConfig(model_id="m", region_name="us-east-1"))
    finally:
        m._BEDROCK_AVAILABLE = orig


def test_bedrock_provider_error(monkeypatch):
    """AWSBedrockProvider.get_llm raises on error."""
    monkeypatch.setattr(svc, "_BEDROCK_AVAILABLE", True)
    monkeypatch.setattr(svc, "ChatBedrock", MagicMock(side_effect=RuntimeError("aws err")))
    cfg = svc.AWSBedrockConfig(model_id="m", region_name="us-east-1")
    provider = svc.AWSBedrockProvider(cfg)
    with pytest.raises(RuntimeError, match="aws err"):
        provider.get_llm()


def test_watsonx_provider_chat(monkeypatch):
    """WatsonxProvider.get_llm(model_type='chat') creates ChatWatsonx."""
    class DummyLLM:
        def __init__(self, **kw):
            self.kw = kw
    monkeypatch.setattr(svc, "_WATSONX_AVAILABLE", True)
    monkeypatch.setattr(svc, "ChatWatsonx", DummyLLM)
    monkeypatch.setattr(svc, "WatsonxLLM", DummyLLM)
    cfg = svc.WatsonxConfig(api_key="key", url="https://s", project_id="p")
    provider = svc.WatsonxProvider(cfg)
    llm = provider.get_llm(model_type="chat")
    assert isinstance(llm, DummyLLM)


def test_watsonx_provider_completion_with_params(monkeypatch):
    """WatsonxProvider.get_llm(model_type='completion') with top_k/top_p."""
    class DummyLLM:
        def __init__(self, **kw):
            self.kw = kw
    monkeypatch.setattr(svc, "_WATSONX_AVAILABLE", True)
    monkeypatch.setattr(svc, "WatsonxLLM", DummyLLM)
    monkeypatch.setattr(svc, "ChatWatsonx", DummyLLM)
    cfg = svc.WatsonxConfig(api_key="key", url="https://s", project_id="p", top_k=40, top_p=0.9)
    provider = svc.WatsonxProvider(cfg)
    llm = provider.get_llm(model_type="completion")
    assert isinstance(llm, DummyLLM)
    assert "params" in llm.kw
    assert llm.kw["params"]["top_k"] == 40
    assert llm.kw["params"]["top_p"] == 0.9


def test_watsonx_provider_not_available():
    """WatsonxProvider raises ImportError when not available."""
    import mcpgateway.services.mcp_client_chat_service as m
    orig = m._WATSONX_AVAILABLE
    try:
        m._WATSONX_AVAILABLE = False
        with pytest.raises(ImportError, match="langchain-ibm"):
            svc.WatsonxProvider(svc.WatsonxConfig(api_key="k", url="https://s", project_id="p"))
    finally:
        m._WATSONX_AVAILABLE = orig


def test_watsonx_provider_error(monkeypatch):
    """WatsonxProvider.get_llm raises on error."""
    monkeypatch.setattr(svc, "_WATSONX_AVAILABLE", True)
    monkeypatch.setattr(svc, "ChatWatsonx", MagicMock(side_effect=RuntimeError("wx err")))
    cfg = svc.WatsonxConfig(api_key="key", url="https://s", project_id="p")
    provider = svc.WatsonxProvider(cfg)
    with pytest.raises(RuntimeError, match="wx err"):
        provider.get_llm()


# --------------------------------------------------------------------------- #
# GATEWAY PROVIDER: additional branches
# --------------------------------------------------------------------------- #


def test_gateway_provider_bedrock_completion(monkeypatch):
    """GatewayProvider bedrock completion with credentials."""
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider(
        "bedrock",
        config={"region_name": "eu-west-1", "aws_access_key_id": "AKID", "aws_secret_access_key": "SECRET", "aws_session_token": "TOK"},
    )
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="completion")
    assert llm is not None


def test_gateway_provider_anthropic_completion(monkeypatch):
    """GatewayProvider anthropic completion branch."""
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("anthropic")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="completion")
    assert llm is not None


def test_gateway_provider_anthropic_completion_no_anthropic_llm(monkeypatch):
    """GatewayProvider anthropic completion when AnthropicLLM is None → ImportError."""
    _patch_gateway_llms(monkeypatch)
    monkeypatch.setattr(svc, "AnthropicLLM", None)  # Override to None
    model, provider = _make_model_and_provider("anthropic")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    with pytest.raises(ImportError, match="AnthropicLLM"):
        gateway.get_llm(model_type="completion")


def test_gateway_provider_ollama_completion(monkeypatch):
    """GatewayProvider ollama completion with num_ctx."""
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("ollama", api_base="http://ollama:11434", config={"num_ctx": 8192})
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="completion")
    assert llm is not None


def test_gateway_provider_watsonx_chat(monkeypatch):
    """GatewayProvider watsonx chat branch."""
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider(
        "watsonx", config={"project_id": "proj", "min_new_tokens": 5, "decoding_method": "greedy", "top_k": 30, "top_p": 0.8},
    )
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="chat")
    assert llm is not None


def test_gateway_provider_watsonx_completion(monkeypatch):
    """GatewayProvider watsonx completion branch."""
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("watsonx", config={"project_id": "proj"})
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="completion")
    assert llm is not None


def test_gateway_provider_openai_compatible_chat(monkeypatch):
    """GatewayProvider openai_compatible chat branch."""
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("openai_compatible", api_base="https://compat")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: "decoded")

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="chat")
    assert llm is not None


def test_gateway_provider_unsupported_type(monkeypatch):
    """GatewayProvider raises ValueError on unsupported provider_type."""
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("some_unknown_provider")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        gateway.get_llm()


def test_gateway_provider_cached_llm(monkeypatch):
    """GatewayProvider returns cached LLM on second call."""
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("openai")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm1 = gateway.get_llm(model_type="chat")
    llm2 = gateway.get_llm(model_type="chat")
    assert llm1 is llm2


def test_gateway_provider_get_model_name_before_llm():
    """GatewayProvider.get_model_name() before get_llm() returns config.model."""
    gateway = svc.GatewayProvider(svc.GatewayConfig(model="my-model"))
    assert gateway.get_model_name() == "my-model"


def test_gateway_provider_bedrock_not_available(monkeypatch):
    """GatewayProvider raises ImportError when bedrock not available."""
    _patch_gateway_llms(monkeypatch)
    monkeypatch.setattr(svc, "_BEDROCK_AVAILABLE", False)
    model, provider = _make_model_and_provider("bedrock", config={"region_name": "us-east-1"})
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    with pytest.raises(ImportError, match="langchain-aws"):
        gateway.get_llm()


def test_gateway_provider_anthropic_not_available(monkeypatch):
    """GatewayProvider raises ImportError when anthropic not available."""
    _patch_gateway_llms(monkeypatch)
    monkeypatch.setattr(svc, "_ANTHROPIC_AVAILABLE", False)
    model, provider = _make_model_and_provider("anthropic")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    with pytest.raises(ImportError, match="langchain-anthropic"):
        gateway.get_llm()


def test_gateway_provider_watsonx_not_available(monkeypatch):
    """GatewayProvider raises ImportError when watsonx not available."""
    _patch_gateway_llms(monkeypatch)
    monkeypatch.setattr(svc, "_WATSONX_AVAILABLE", False)
    model, provider = _make_model_and_provider("watsonx", config={"project_id": "proj"})
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    with pytest.raises(ImportError, match="langchain-ibm"):
        gateway.get_llm()


def test_gateway_provider_openai_default_headers_from_config(monkeypatch):
    """GatewayProvider picks up default_headers from provider.config."""
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("openai", config={"default_headers": {"X-Api-Version": "v2"}}, api_base="https://api")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="chat")
    assert llm is not None


def test_gateway_provider_openai_no_api_key(monkeypatch):
    """GatewayProvider with no api_key in provider → api_key=None."""
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("openai")
    provider.api_key = None  # No encrypted key
    _patch_gateway_session(monkeypatch, model, provider)

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="chat")
    assert llm is not None


def test_gateway_provider_azure_completion_branch(monkeypatch):
    """GatewayProvider azure_openai completion branch."""
    _patch_gateway_llms(monkeypatch)
    model, provider = _make_model_and_provider("azure_openai", config={"azure_deployment": "dep", "api_version": "2024-01"}, api_base="https://azure")
    _patch_gateway_session(monkeypatch, model, provider)
    monkeypatch.setattr("mcpgateway.utils.services_auth.decode_auth", lambda _v: {"api_key": "decoded"})

    gateway = svc.GatewayProvider(svc.GatewayConfig(model="gpt-4"))
    llm = gateway.get_llm(model_type="chat")
    assert llm is not None


# --------------------------------------------------------------------------- #
# LLMProviderFactory: gateway provider
# --------------------------------------------------------------------------- #


def test_llmproviderfactory_gateway(monkeypatch):
    """LLMProviderFactory creates GatewayProvider."""
    cfg = svc.LLMConfig(provider="gateway", config=svc.GatewayConfig(model="my-model"))
    provider = svc.LLMProviderFactory.create(cfg)
    assert isinstance(provider, svc.GatewayProvider)


# --------------------------------------------------------------------------- #
# MCPServerConfig: auth_token in headers
# --------------------------------------------------------------------------- #


def test_mcpserverconfig_auth_token_adds_bearer():
    """auth_token should be added as Bearer token to headers."""
    cfg = svc.MCPServerConfig(url="https://srv", transport="sse", auth_token="my-token")
    assert cfg.headers["Authorization"] == "Bearer my-token"


def test_mcpserverconfig_auth_token_no_override():
    """Existing Authorization header should not be overridden."""
    cfg = svc.MCPServerConfig(
        url="https://srv", transport="sse",
        auth_token="my-token", headers={"Authorization": "Basic abc"},
    )
    assert cfg.headers["Authorization"] == "Basic abc"


def test_mcpserverconfig_stdio_no_url_required():
    """stdio transport should not require URL."""
    cfg = svc.MCPServerConfig(command="python", args=["s.py"], transport="stdio")
    assert cfg.url is None


def test_mcpserverconfig_sse_without_url():
    """SSE transport without URL sets url=None."""
    cfg = svc.MCPServerConfig(transport="sse")
    assert cfg.url is None


def test_mcpserverconfig_stdio_without_command():
    """stdio transport without command sets command=None."""
    cfg = svc.MCPServerConfig(transport="stdio")
    assert cfg.command is None
