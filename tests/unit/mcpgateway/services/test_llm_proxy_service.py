# -*- coding: utf-8 -*-
"""Tests for LLM proxy service."""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.db import LLMProviderType
from mcpgateway.llm_schemas import ChatCompletionRequest, ChatMessage
from mcpgateway.services.llm_proxy_service import (
    LLMModelNotFoundError,
    LLMProxyRequestError,
    LLMProxyService,
    LLMProviderNotFoundError,
)


class DummyScalar:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.fixture
def service():
    return LLMProxyService()


def _make_model(**overrides):
    data = {
        "id": "m1",
        "model_id": "gpt-4",
        "model_alias": "alias",
        "enabled": True,
        "provider_id": "p1",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _make_provider(**overrides):
    data = {
        "id": "p1",
        "name": "Provider",
        "provider_type": LLMProviderType.OPENAI,
        "enabled": True,
        "api_key": None,
        "api_base": "http://api",
        "default_temperature": 0.5,
        "default_max_tokens": 10,
        "config": {},
        "api_version": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_resolve_model_by_id(service):
    db = MagicMock()
    model = _make_model()
    provider = _make_provider()

    db.execute.side_effect = [DummyScalar(model), DummyScalar(provider)]

    resolved_provider, resolved_model = service._resolve_model(db, "m1")

    assert resolved_model.model_id == "gpt-4"
    assert resolved_provider.id == "p1"


def test_resolve_model_not_found(service):
    db = MagicMock()
    db.execute.side_effect = [DummyScalar(None), DummyScalar(None), DummyScalar(None)]

    with pytest.raises(LLMModelNotFoundError):
        service._resolve_model(db, "missing")


def test_resolve_model_provider_disabled(service):
    db = MagicMock()
    model = _make_model()
    provider = _make_provider(enabled=False)
    db.execute.side_effect = [DummyScalar(model), DummyScalar(provider)]

    with pytest.raises(LLMProviderNotFoundError):
        service._resolve_model(db, "m1")


def test_get_api_key_decode_error(service, monkeypatch: pytest.MonkeyPatch):
    provider = _make_provider(api_key="encoded")
    monkeypatch.setattr("mcpgateway.services.llm_proxy_service.decode_auth", lambda _: (_ for _ in ()).throw(RuntimeError("bad")))

    assert service._get_api_key(provider) is None


def test_build_openai_request(service):
    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    provider = _make_provider()
    model = _make_model()

    url, headers, body = service._build_openai_request(request, provider, model)

    assert url.endswith("/chat/completions")
    assert headers["Content-Type"] == "application/json"
    assert body["model"] == "gpt-4"


def test_build_azure_request(service):
    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    provider = _make_provider(provider_type=LLMProviderType.AZURE_OPENAI, api_base=None, config={"resource_name": "res", "deployment_name": "dep"})
    model = _make_model(model_id="gpt-4")

    url, headers, body = service._build_azure_request(request, provider, model)

    assert "openai/deployments/dep" in url
    assert headers["api-key"] == ""
    assert body["messages"]


@pytest.mark.asyncio
async def test_chat_completion_openai_success(service):
    provider = _make_provider(provider_type=LLMProviderType.OPENAI)
    model = _make_model()
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "id": "resp1",
        "created": 1,
        "model": "gpt-4",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    service._client = AsyncMock()
    service._client.post = AsyncMock(return_value=response)

    result = await service.chat_completion(MagicMock(), request)

    assert result.id == "resp1"
    assert result.choices[0].message.content == "ok"


@pytest.mark.asyncio
async def test_chat_completion_http_error(service):
    provider = _make_provider(provider_type=LLMProviderType.OPENAI)
    model = _make_model()
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])

    httpx_response = httpx.Response(status_code=400, text="bad", request=httpx.Request("POST", "http://api"))
    error = httpx.HTTPStatusError("bad", request=httpx_response.request, response=httpx_response)

    service._client = AsyncMock()
    service._client.post = AsyncMock(side_effect=error)

    with pytest.raises(LLMProxyRequestError):
        await service.chat_completion(MagicMock(), request)


def test_build_anthropic_request_with_system_message(service):
    request = ChatCompletionRequest(
        model="claude-3",
        messages=[
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="hi"),
        ],
        stream=True,
    )
    provider = _make_provider(provider_type=LLMProviderType.ANTHROPIC, api_base="http://anthropic", config={"anthropic_version": "2024-01-01"}, default_max_tokens=123, default_temperature=0.2)
    model = _make_model(model_id="claude-3")

    url, headers, body = service._build_anthropic_request(request, provider, model)

    assert url.endswith("/v1/messages")
    assert headers["anthropic-version"] == "2024-01-01"
    assert body["system"] == "sys"
    assert body["max_tokens"] == 123
    assert body["stream"] is True
    assert body["messages"][0]["role"] == "user"


def test_build_ollama_request_openai_compat(service):
    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")], stream=True)
    provider = _make_provider(provider_type=LLMProviderType.OLLAMA, api_base="http://ollama.local/v1", default_temperature=0.3, default_max_tokens=77)
    model = _make_model(model_id="llama3")

    url, headers, body = service._build_ollama_request(request, provider, model)

    assert url.endswith("/chat/completions")
    assert headers["Content-Type"] == "application/json"
    assert body["temperature"] == 0.3
    assert body["max_tokens"] == 77
    assert body["stream"] is True


def test_build_ollama_request_native_options(service):
    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")], temperature=0.5, stream=False)
    provider = _make_provider(provider_type=LLMProviderType.OLLAMA, api_base="http://ollama.local")
    model = _make_model(model_id="llama3")

    url, headers, body = service._build_ollama_request(request, provider, model)

    assert url.endswith("/api/chat")
    assert headers["Content-Type"] == "application/json"
    assert body["options"]["temperature"] == 0.5


def test_transform_anthropic_response(service):
    data = {
        "id": "resp",
        "content": [{"type": "text", "text": "hi"}, {"type": "text", "text": " there"}],
        "usage": {"input_tokens": 1, "output_tokens": 2},
        "stop_reason": "stop",
    }

    result = service._transform_anthropic_response(data, "claude")

    assert result.choices[0].message.content == "hi there"
    assert result.usage.total_tokens == 3
    assert result.model == "claude"


def test_transform_ollama_response_done(service):
    data = {"message": {"role": "assistant", "content": "ok"}, "done": True, "prompt_eval_count": 1, "eval_count": 2}

    result = service._transform_ollama_response(data, "llama3")

    assert result.choices[0].finish_reason == "stop"
    assert result.usage.total_tokens == 3


def test_transform_anthropic_stream_chunk(service):
    text_delta = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}
    stop_event = {"type": "message_stop"}

    chunk = service._transform_anthropic_stream_chunk(text_delta, "id", 1, "model")
    stop_chunk = service._transform_anthropic_stream_chunk(stop_event, "id", 1, "model")

    assert "\"content\":\"hi\"" in chunk
    assert "\"finish_reason\":\"stop\"" in stop_chunk
    assert service._transform_anthropic_stream_chunk({"type": "other"}, "id", 1, "model") is None


def test_transform_ollama_stream_chunk(service):
    chunk = service._transform_ollama_stream_chunk({"message": {"content": "hi"}, "done": False}, "id", 1, "model")
    stop_chunk = service._transform_ollama_stream_chunk({"message": {"content": ""}, "done": True}, "id", 1, "model")

    assert "\"content\":\"hi\"" in chunk
    assert "\"finish_reason\":\"stop\"" in stop_chunk


@pytest.mark.asyncio
async def test_chat_completion_anthropic_success(service):
    provider = _make_provider(provider_type=LLMProviderType.ANTHROPIC, api_base="http://anthropic", config={})
    model = _make_model(model_id="claude")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="claude", messages=[ChatMessage(role="user", content="hi")])

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "id": "resp1",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    service._client = AsyncMock()
    service._client.post = AsyncMock(return_value=response)

    result = await service.chat_completion(MagicMock(), request)

    assert result.model == "claude"
    assert result.choices[0].message.content == "ok"


@pytest.mark.asyncio
async def test_chat_completion_ollama_openai_compat(service):
    provider = _make_provider(provider_type=LLMProviderType.OLLAMA, api_base="http://ollama.local/v1")
    model = _make_model(model_id="llama3")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")])

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "id": "resp1",
        "created": 1,
        "model": "llama3",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    service._client = AsyncMock()
    service._client.post = AsyncMock(return_value=response)

    result = await service.chat_completion(MagicMock(), request)

    assert result.choices[0].message.content == "ok"


@pytest.mark.asyncio
async def test_chat_completion_stream_openai(service):
    provider = _make_provider(provider_type=LLMProviderType.OPENAI)
    model = _make_model(model_id="gpt-4")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")], stream=True)

    class DummyStreamResponse:
        def __init__(self, lines):
            self._lines = lines

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            for line in self._lines:
                yield line

    stream_response = DummyStreamResponse(["data: {\"choices\": []}", "data: [DONE]"])
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=stream_response)

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert "data: {\"choices\": []}\n\n" in chunks
    assert "data: [DONE]\n\n" in chunks


# ============================================================================
# Coverage improvement tests
# ============================================================================


@pytest.mark.asyncio
async def test_initialize_and_shutdown(service):
    """initialize() creates client, shutdown() closes it (lines 72-91)."""
    await service.initialize()
    assert service._initialized
    assert service._client is not None
    # Second call is no-op
    await service.initialize()
    assert service._initialized
    await service.shutdown()
    assert not service._initialized
    assert service._client is None
    # Shutdown when not initialized is no-op
    await service.shutdown()


def test_resolve_model_disabled(service):
    """Disabled model raises error (line 126)."""
    db = MagicMock()
    model = _make_model(enabled=False)
    db.execute.side_effect = [DummyScalar(model)]
    with pytest.raises(LLMModelNotFoundError, match="disabled"):
        service._resolve_model(db, "m1")


def test_resolve_model_provider_missing(service):
    """No provider record raises error (line 132)."""
    db = MagicMock()
    model = _make_model()
    db.execute.side_effect = [DummyScalar(model), DummyScalar(None)]
    with pytest.raises(LLMProviderNotFoundError, match="not found"):
        service._resolve_model(db, "m1")


def test_resolve_model_by_model_id(service):
    """Resolve by model_id when id lookup fails (line 116)."""
    db = MagicMock()
    model = _make_model()
    provider = _make_provider()
    db.execute.side_effect = [DummyScalar(None), DummyScalar(model), DummyScalar(provider)]
    p, m = service._resolve_model(db, "gpt-4")
    assert m.model_id == "gpt-4"


def test_resolve_model_by_alias(service):
    """Resolve by model_alias when id and model_id fail (line 120)."""
    db = MagicMock()
    model = _make_model()
    provider = _make_provider()
    db.execute.side_effect = [DummyScalar(None), DummyScalar(None), DummyScalar(model), DummyScalar(provider)]
    p, m = service._resolve_model(db, "alias")
    assert m.model_alias == "alias"


def test_get_api_key_success(service, monkeypatch: pytest.MonkeyPatch):
    """Successful API key decode (line 153)."""
    provider = _make_provider(api_key="encoded")
    monkeypatch.setattr("mcpgateway.services.llm_proxy_service.decode_auth", lambda _: {"api_key": "secret"})
    assert service._get_api_key(provider) == "secret"


def test_get_api_key_none(service):
    """No API key returns None (line 149)."""
    provider = _make_provider(api_key=None)
    assert service._get_api_key(provider) is None


def test_build_openai_request_all_optional_params(service, monkeypatch: pytest.MonkeyPatch):
    """OpenAI request with all optional params set (lines 183, 193-216)."""
    monkeypatch.setattr("mcpgateway.services.llm_proxy_service.decode_auth", lambda _: {"api_key": "key123"})
    request = ChatCompletionRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hi")],
        temperature=0.8,
        max_tokens=100,
        stream=True,
        tool_choice="auto",
        top_p=0.9,
        frequency_penalty=0.1,
        presence_penalty=0.2,
        stop=["END"],
    )
    provider = _make_provider(api_key="enc", api_base=None)
    model = _make_model()

    url, headers, body = service._build_openai_request(request, provider, model)

    assert "api.openai.com" in url
    assert headers["Authorization"] == "Bearer key123"
    assert body["temperature"] == 0.8
    assert body["max_tokens"] == 100
    assert body["stream"] is True
    assert body["tool_choice"] == "auto"
    assert body["top_p"] == 0.9
    assert body["frequency_penalty"] == 0.1
    assert body["presence_penalty"] == 0.2
    assert body["stop"] == ["END"]


def test_build_openai_request_provider_defaults(service):
    """OpenAI request uses provider defaults when request params are None (lines 194-200)."""
    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    provider = _make_provider(default_temperature=0.5, default_max_tokens=10)
    model = _make_model()

    url, headers, body = service._build_openai_request(request, provider, model)

    assert body["temperature"] == 0.5
    assert body["max_tokens"] == 10


def test_build_openai_request_with_tools(service):
    """OpenAI request with tools (lines 205-208)."""
    from mcpgateway.llm_schemas import FunctionDefinition, ToolDefinition

    tool = ToolDefinition(function=FunctionDefinition(name="test_fn", description="A test"))
    request = ChatCompletionRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[tool],
        tool_choice="auto",
    )
    provider = _make_provider()
    model = _make_model()

    url, headers, body = service._build_openai_request(request, provider, model)

    assert body["tools"][0]["function"]["name"] == "test_fn"
    assert body["tool_choice"] == "auto"


def test_build_azure_request_with_api_base_fallback(service):
    """Azure request uses empty base_url when both api_base and resource_name are empty (line 247)."""
    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    provider = _make_provider(
        provider_type=LLMProviderType.AZURE_OPENAI,
        api_base="https://myresource.openai.azure.com",
        config={},
    )
    model = _make_model()

    url, headers, body = service._build_azure_request(request, provider, model)

    assert "openai/deployments" in url


def test_build_azure_request_defaults(service):
    """Azure request uses provider temp/max_tokens defaults and stream (lines 262-272)."""
    request = ChatCompletionRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    provider = _make_provider(
        provider_type=LLMProviderType.AZURE_OPENAI,
        api_base="https://res.openai.azure.com",
        config={"deployment_name": "dep"},
        default_temperature=0.3,
        default_max_tokens=50,
    )
    model = _make_model()

    url, headers, body = service._build_azure_request(request, provider, model)

    assert body["temperature"] == 0.3
    assert body["max_tokens"] == 50
    assert body["stream"] is True


def test_build_anthropic_request_temperature_default(service):
    """Anthropic request uses provider default temperature (lines 330-332)."""
    request = ChatCompletionRequest(
        model="claude",
        messages=[ChatMessage(role="user", content="hi")],
    )
    provider = _make_provider(
        provider_type=LLMProviderType.ANTHROPIC,
        api_base="http://anthropic",
        config={},
        default_temperature=0.4,
        default_max_tokens=None,
    )
    model = _make_model(model_id="claude")

    url, headers, body = service._build_anthropic_request(request, provider, model)

    assert body["temperature"] == 0.4


def test_build_ollama_request_native_default_temp(service):
    """Ollama native API uses provider default temperature (lines 388-391)."""
    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")])
    provider = _make_provider(
        provider_type=LLMProviderType.OLLAMA,
        api_base="http://ollama.local",
        default_temperature=0.6,
        default_max_tokens=None,
    )
    model = _make_model(model_id="llama3")

    url, headers, body = service._build_ollama_request(request, provider, model)

    assert url.endswith("/api/chat")
    assert body["options"]["temperature"] == 0.6


def test_build_ollama_request_native_no_options(service):
    """Ollama native API without any temperature (no options key)."""
    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")])
    provider = _make_provider(
        provider_type=LLMProviderType.OLLAMA,
        api_base="http://ollama.local",
        default_temperature=None,
        default_max_tokens=None,
    )
    model = _make_model(model_id="llama3")

    url, headers, body = service._build_ollama_request(request, provider, model)

    assert "options" not in body


def test_build_ollama_openai_compat_request_max_tokens(service):
    """Ollama OpenAI-compat endpoint with request max_tokens (lines 372-375)."""
    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")], max_tokens=200)
    provider = _make_provider(
        provider_type=LLMProviderType.OLLAMA,
        api_base="http://ollama.local/v1",
        default_temperature=None,
        default_max_tokens=None,
    )
    model = _make_model(model_id="llama3")

    url, headers, body = service._build_ollama_request(request, provider, model)

    assert body["max_tokens"] == 200


@pytest.mark.asyncio
async def test_chat_completion_auto_initialize(service):
    """chat_completion auto-initializes when client is None (line 413)."""
    provider = _make_provider(provider_type=LLMProviderType.OPENAI)
    model = _make_model()
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "id": "resp1",
        "created": 1,
        "model": "gpt-4",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    # Don't set _client - let auto-initialize work, then mock the client
    original_init = service.initialize

    async def init_then_mock():
        await original_init()
        service._client = AsyncMock()
        service._client.post = AsyncMock(return_value=response)

    service.initialize = init_then_mock

    result = await service.chat_completion(MagicMock(), request)
    assert result.choices[0].message.content == "ok"


@pytest.mark.asyncio
async def test_chat_completion_azure(service):
    """chat_completion with Azure provider (line 419)."""
    provider = _make_provider(
        provider_type=LLMProviderType.AZURE_OPENAI,
        api_base="https://res.openai.azure.com",
        config={"deployment_name": "dep"},
    )
    model = _make_model()
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "id": "resp1",
        "created": 1,
        "model": "gpt-4",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "azure-ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    service._client = AsyncMock()
    service._client.post = AsyncMock(return_value=response)

    result = await service.chat_completion(MagicMock(), request)
    assert result.choices[0].message.content == "azure-ok"


@pytest.mark.asyncio
async def test_chat_completion_ollama_native(service):
    """chat_completion with Ollama native provider (line 444)."""
    provider = _make_provider(provider_type=LLMProviderType.OLLAMA, api_base="http://ollama.local")
    model = _make_model(model_id="llama3")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")])

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"message": {"role": "assistant", "content": "ollama-ok"}, "done": True, "prompt_eval_count": 1, "eval_count": 2}

    service._client = AsyncMock()
    service._client.post = AsyncMock(return_value=response)

    result = await service.chat_completion(MagicMock(), request)
    assert result.choices[0].message.content == "ollama-ok"


@pytest.mark.asyncio
async def test_chat_completion_request_error(service):
    """chat_completion raises on connection error (lines 450-452)."""
    provider = _make_provider(provider_type=LLMProviderType.OPENAI)
    model = _make_model()
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])

    service._client = AsyncMock()
    service._client.post = AsyncMock(side_effect=httpx.RequestError("timeout"))

    with pytest.raises(LLMProxyRequestError, match="Connection error"):
        await service.chat_completion(MagicMock(), request)


class DummyStreamResponse:
    """Reusable mock for streaming responses."""

    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


@pytest.mark.asyncio
async def test_chat_completion_stream_anthropic(service):
    """Streaming with Anthropic provider (lines 508-509)."""
    provider = _make_provider(provider_type=LLMProviderType.ANTHROPIC, api_base="http://anthropic", config={})
    model = _make_model(model_id="claude")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="claude", messages=[ChatMessage(role="user", content="hi")], stream=True)

    lines = [
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello"}}',
        'data: {"type": "message_stop"}',
        "data: [DONE]",
    ]
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert any("hello" in c for c in chunks)
    assert "data: [DONE]\n\n" in chunks


@pytest.mark.asyncio
async def test_chat_completion_stream_ollama_native(service):
    """Streaming with Ollama native API (lines 527-536)."""
    provider = _make_provider(provider_type=LLMProviderType.OLLAMA, api_base="http://ollama.local")
    model = _make_model(model_id="llama3")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")], stream=True)

    # Ollama native uses newline-delimited JSON (not SSE "data: " prefix)
    lines = [
        '{"message": {"content": "hi"}, "done": false}',
        '{"message": {"content": ""}, "done": true}',
    ]
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert any("hi" in c for c in chunks)


@pytest.mark.asyncio
async def test_chat_completion_stream_ollama_openai_compat(service):
    """Streaming with Ollama OpenAI-compat endpoint (lines 512-514)."""
    provider = _make_provider(provider_type=LLMProviderType.OLLAMA, api_base="http://ollama.local/v1")
    model = _make_model(model_id="llama3")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")], stream=True)

    lines = [
        'data: {"choices": [{"delta": {"content": "compat"}}]}',
        "data: [DONE]",
    ]
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert any("compat" in c for c in chunks)


@pytest.mark.asyncio
async def test_chat_completion_stream_azure(service):
    """Streaming with Azure provider (line 475)."""
    provider = _make_provider(
        provider_type=LLMProviderType.AZURE_OPENAI,
        api_base="https://res.openai.azure.com",
        config={"deployment_name": "dep"},
    )
    model = _make_model(model_id="gpt-4")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")], stream=True)

    lines = ['data: {"choices": [{"delta": {"content": "azure"}}]}', "data: [DONE]"]
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert any("azure" in c for c in chunks)


@pytest.mark.asyncio
async def test_chat_completion_stream_empty_lines_and_bad_json(service):
    """Streaming skips empty lines and invalid JSON (lines 494-495, 523-524)."""
    provider = _make_provider(provider_type=LLMProviderType.OPENAI)
    model = _make_model(model_id="gpt-4")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")], stream=True)

    lines = ["", "data: not-json", 'data: {"choices": []}', "data: [DONE]"]
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert "data: [DONE]\n\n" in chunks


@pytest.mark.asyncio
async def test_chat_completion_stream_http_error(service):
    """Streaming HTTP error yields error chunk (lines 538-545)."""
    provider = _make_provider(provider_type=LLMProviderType.OPENAI)
    model = _make_model(model_id="gpt-4")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")], stream=True)

    httpx_response = httpx.Response(status_code=500, text="error", request=httpx.Request("POST", "http://api"))

    class ErrorStreamResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def raise_for_status(self):
            raise httpx.HTTPStatusError("fail", request=httpx_response.request, response=httpx_response)

    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=ErrorStreamResponse())

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert any("proxy_error" in c for c in chunks)


@pytest.mark.asyncio
async def test_chat_completion_stream_request_error(service):
    """Streaming connection error yields error chunk (lines 546-553)."""
    provider = _make_provider(provider_type=LLMProviderType.OPENAI)
    model = _make_model(model_id="gpt-4")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")], stream=True)

    class ConnErrorStreamResponse:
        async def __aenter__(self):
            raise httpx.RequestError("connection refused")

        async def __aexit__(self, *args):
            return False

    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=ConnErrorStreamResponse())

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert any("proxy_error" in c for c in chunks)


@pytest.mark.asyncio
async def test_chat_completion_stream_auto_initialize(service):
    """chat_completion_stream auto-initializes (line 469)."""
    provider = _make_provider(provider_type=LLMProviderType.OPENAI)
    model = _make_model(model_id="gpt-4")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")], stream=True)

    lines = ["data: [DONE]"]
    original_init = service.initialize

    async def init_then_mock():
        await original_init()
        service._client = MagicMock()
        service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    service.initialize = init_then_mock

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert "data: [DONE]\n\n" in chunks


# ============================================================================
# Additional branch coverage tests
# ============================================================================


def test_build_openai_request_no_defaults(service):
    """OpenAI request with no temp/max_tokens and no provider defaults (branches 194->197, 199->202 false)."""
    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    provider = _make_provider(default_temperature=None, default_max_tokens=None)
    model = _make_model()

    url, headers, body = service._build_openai_request(request, provider, model)

    assert "temperature" not in body
    assert "max_tokens" not in body


def test_build_azure_request_explicit_params(service):
    """Azure request with explicit temperature and max_tokens (lines 262, 267)."""
    request = ChatCompletionRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hi")],
        temperature=0.9,
        max_tokens=200,
    )
    provider = _make_provider(
        provider_type=LLMProviderType.AZURE_OPENAI,
        api_base="https://res.openai.azure.com",
        config={"deployment_name": "dep"},
        default_temperature=0.3,
        default_max_tokens=50,
    )
    model = _make_model()

    url, headers, body = service._build_azure_request(request, provider, model)

    assert body["temperature"] == 0.9
    assert body["max_tokens"] == 200


def test_build_azure_request_no_defaults(service):
    """Azure request with no temp/max_tokens and no provider defaults (branches 263->266, 268->271 false)."""
    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    provider = _make_provider(
        provider_type=LLMProviderType.AZURE_OPENAI,
        api_base="https://res.openai.azure.com",
        config={"deployment_name": "dep"},
        default_temperature=None,
        default_max_tokens=None,
    )
    model = _make_model()

    url, headers, body = service._build_azure_request(request, provider, model)

    assert "temperature" not in body
    assert "max_tokens" not in body


def test_build_anthropic_request_explicit_temperature(service):
    """Anthropic request with explicit temperature (line 330)."""
    request = ChatCompletionRequest(
        model="claude",
        messages=[ChatMessage(role="user", content="hi")],
        temperature=0.7,
    )
    provider = _make_provider(
        provider_type=LLMProviderType.ANTHROPIC,
        api_base="http://anthropic",
        config={},
        default_temperature=0.4,
    )
    model = _make_model(model_id="claude")

    url, headers, body = service._build_anthropic_request(request, provider, model)

    assert body["temperature"] == 0.7


def test_build_anthropic_request_no_temperature_defaults(service):
    """Anthropic request with no temp and no provider default (branch 331->334 false)."""
    request = ChatCompletionRequest(
        model="claude",
        messages=[ChatMessage(role="user", content="hi")],
    )
    provider = _make_provider(
        provider_type=LLMProviderType.ANTHROPIC,
        api_base="http://anthropic",
        config={},
        default_temperature=None,
    )
    model = _make_model(model_id="claude")

    url, headers, body = service._build_anthropic_request(request, provider, model)

    assert "temperature" not in body


def test_build_ollama_openai_compat_explicit_temperature(service):
    """Ollama OpenAI-compat with explicit temperature (line 369)."""
    request = ChatCompletionRequest(
        model="llama3",
        messages=[ChatMessage(role="user", content="hi")],
        temperature=0.8,
    )
    provider = _make_provider(
        provider_type=LLMProviderType.OLLAMA,
        api_base="http://ollama.local/v1",
        default_temperature=0.3,
    )
    model = _make_model(model_id="llama3")

    url, headers, body = service._build_ollama_request(request, provider, model)

    assert body["temperature"] == 0.8


def test_build_ollama_openai_compat_no_defaults(service):
    """Ollama OpenAI-compat with no max_tokens and no provider default (branch 374->393 false)."""
    request = ChatCompletionRequest(
        model="llama3",
        messages=[ChatMessage(role="user", content="hi")],
    )
    provider = _make_provider(
        provider_type=LLMProviderType.OLLAMA,
        api_base="http://ollama.local/v1",
        default_temperature=None,
        default_max_tokens=None,
    )
    model = _make_model(model_id="llama3")

    url, headers, body = service._build_ollama_request(request, provider, model)

    assert "temperature" not in body
    assert "max_tokens" not in body


def test_transform_anthropic_response_non_text_block(service):
    """Anthropic response with non-text content block (branch 610->609 false)."""
    data = {
        "id": "resp",
        "content": [{"type": "tool_use", "id": "t1", "name": "fn"}, {"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    result = service._transform_anthropic_response(data, "claude")

    assert result.choices[0].message.content == "ok"


def test_transform_anthropic_stream_chunk_non_text_delta(service):
    """Anthropic stream chunk with non-text-delta type (branch 692->718 false)."""
    data = {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{}"}}

    result = service._transform_anthropic_stream_chunk(data, "id", 1, "model")

    assert result is None


@pytest.mark.asyncio
async def test_chat_completion_stream_ollama_native_data_prefix(service):
    """Ollama native streaming with 'data:' prefixed lines (line 516, branch 520->493)."""
    provider = _make_provider(provider_type=LLMProviderType.OLLAMA, api_base="http://ollama.local")
    model = _make_model(model_id="llama3")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")], stream=True)

    # Ollama native with data: prefix - the transform returns a chunk
    lines = [
        'data: {"message": {"content": "hi"}, "done": false}',
        "data: [DONE]",
    ]
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert any("hi" in c for c in chunks)


@pytest.mark.asyncio
async def test_chat_completion_stream_chunk_is_none(service):
    """Streaming where chunk returns None (branch 520->493 false)."""
    provider = _make_provider(provider_type=LLMProviderType.ANTHROPIC, api_base="http://anthropic", config={})
    model = _make_model(model_id="claude")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="claude", messages=[ChatMessage(role="user", content="hi")], stream=True)

    # "ping" event returns None from _transform_anthropic_stream_chunk
    lines = [
        'data: {"type": "ping"}',
        "data: [DONE]",
    ]
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    # Only the [DONE] chunk should come through, the ping produces None which is skipped
    assert "data: [DONE]\n\n" in chunks
    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_chat_completion_stream_non_sse_line_non_ollama(service):
    """Non-SSE line for non-Ollama provider is silently ignored (branch 527->493 false)."""
    provider = _make_provider(provider_type=LLMProviderType.OPENAI)
    model = _make_model(model_id="gpt-4")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")], stream=True)

    # A line without "data: " prefix, for a non-Ollama provider - should be skipped
    lines = ["some-random-line", 'data: {"choices": []}', "data: [DONE]"]
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert "data: [DONE]\n\n" in chunks


@pytest.mark.asyncio
async def test_chat_completion_stream_ollama_openai_compat_non_sse_line(service):
    """Ollama OpenAI-compat non-SSE line is skipped (branch 529->493 false)."""
    provider = _make_provider(provider_type=LLMProviderType.OLLAMA, api_base="http://ollama.local/v1")
    model = _make_model(model_id="llama3")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")], stream=True)

    # Non-SSE line for Ollama with /v1 (OpenAI-compat) - the elif at 527 is True,
    # but base_url.endswith("/v1") check at 529 is True, so `not endswith("/v1")` is False
    lines = ["random-non-sse", "data: [DONE]"]
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert "data: [DONE]\n\n" in chunks


@pytest.mark.asyncio
async def test_chat_completion_stream_ollama_native_non_sse_bad_json(service):
    """Ollama native non-SSE line with bad JSON (lines 535-536)."""
    provider = _make_provider(provider_type=LLMProviderType.OLLAMA, api_base="http://ollama.local")
    model = _make_model(model_id="llama3")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")], stream=True)

    # Non-SSE line that isn't valid JSON - hits the except orjson.JSONDecodeError at 535-536
    lines = ["not-valid-json", '{"message": {"content": "ok"}, "done": false}']
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert any("ok" in c for c in chunks)


@pytest.mark.asyncio
async def test_chat_completion_stream_ollama_native_non_sse_null_chunk(service):
    """Ollama native non-SSE line where transform returns None (branch 533->493 false)."""
    provider = _make_provider(provider_type=LLMProviderType.OLLAMA, api_base="http://ollama.local")
    model = _make_model(model_id="llama3")
    service._resolve_model = MagicMock(return_value=(provider, model))

    request = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="hi")], stream=True)

    # Valid JSON but _transform_ollama_stream_chunk returns a truthy chunk normally,
    # so we mock it to return None for one call
    lines = ['{"message": {"content": ""}, "done": false}', '{"message": {"content": "ok"}, "done": false}']
    service._client = MagicMock()
    service._client.stream = MagicMock(return_value=DummyStreamResponse(lines))

    # Patch transform to return None on first call, then normal on second
    original = service._transform_ollama_stream_chunk
    call_count = 0

    def mock_transform(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None
        return original(*args, **kwargs)

    service._transform_ollama_stream_chunk = mock_transform

    chunks = []
    async for chunk in service.chat_completion_stream(MagicMock(), request):
        chunks.append(chunk)

    assert any("ok" in c for c in chunks)
