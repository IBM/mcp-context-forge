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
