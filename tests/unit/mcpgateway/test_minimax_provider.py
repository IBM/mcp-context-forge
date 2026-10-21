#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test MiniMax defaults, discovery, and serialized chat requests.
Location: ./tests/unit/mcpgateway/test_minimax_provider.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlsplit

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.db import LLMProviderType
from mcpgateway.llm_provider_configs import get_provider_config
from mcpgateway.llm_schemas import ChatCompletionRequest, ChatMessage, LLMProviderCreate, LLMProviderTypeEnum
from mcpgateway.routers import llm_admin_router
from mcpgateway.services import llm_proxy_service
from mcpgateway.services.llm_provider_service import LLMProviderService
from mcpgateway.utils.ssrf_pinning import PinnedTarget


def test_minimax_registration():
    """Expose the same defaults through the provider registries."""
    defaults = LLMProviderType.get_provider_defaults()[LLMProviderType.MINIMAX]
    config = get_provider_config("minimax")
    assert LLMProviderTypeEnum.MINIMAX.value in LLMProviderType.get_all_types()
    assert config.api_base_default == defaults["api_base"] == "https://api.minimax.io/v1"
    assert defaults["default_model"] == "MiniMax-M3.1-Flash"
    assert defaults["models"] == ["MiniMax-M3.1-Flash", "MiniMax-M3"]


@pytest.mark.parametrize("model_id", [None, "MiniMax-M3", "MiniMax-M2.7", "saved-custom-model"])
def test_minimax_create_defaults(monkeypatch, model_id):
    """Apply new-provider defaults without replacing an explicit model."""
    service = LLMProviderService()
    monkeypatch.setattr(service, "_validate_provider_api_base", lambda _url: None)
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    data = LLMProviderCreate(name="MiniMax", provider_type="minimax", default_model=model_id)
    provider = service.create_provider(db, data)
    assert provider.api_base == "https://api.minimax.io/v1"
    assert provider.default_model == (model_id or "MiniMax-M3.1-Flash")
    assert data.api_base is None


def test_non_minimax_defaults_unchanged(monkeypatch):
    """Keep generic compatible and OpenAI providers outside MiniMax defaults."""
    service = LLMProviderService()
    monkeypatch.setattr(service, "_validate_provider_api_base", lambda _url: None)
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    provider = service.create_provider(db, LLMProviderCreate(name="OpenAI", provider_type="openai"))
    assert provider.api_base is None
    assert provider.default_model is None
    proxy = llm_proxy_service.LLMProxyService()
    monkeypatch.setattr(proxy, "_get_api_key", lambda _provider: None)
    request = ChatCompletionRequest(model="gpt-4o", messages=[ChatMessage(role="user", content="Hello")])
    url, _headers, payload = proxy._build_openai_request(provider, request, "gpt-4o")
    assert url == "https://api.openai.com/v1/chat/completions"
    assert payload["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_minimax_discovery_is_current_and_offline(monkeypatch):
    """Discover current models without requesting an unverified listing endpoint."""
    provider = SimpleNamespace(provider_type="minimax")
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "get_provider", lambda *_args: provider)
    result = await llm_admin_router.fetch_provider_models(request=MagicMock(), provider_id="minimax", db=MagicMock(), current_user_ctx={"db": MagicMock(), "email": "user@example.com"})
    assert result["success"] is True
    assert [model["id"] for model in result["models"]] == ["MiniMax-M3.1-Flash", "MiniMax-M3"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("model_id", ["MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M2.7", "saved-custom-model"])
@pytest.mark.parametrize("api_base", [None, "https://api.minimaxi.com/v1", "https://gateway.example/v1"])
async def test_minimax_http_boundary(monkeypatch, api_base, model_id, stream):
    """Preserve selected models and tool history at the HTTP transport boundary."""
    provider = SimpleNamespace(
        id="provider",
        name="MiniMax",
        provider_type="minimax",
        enabled=True,
        api_key=None,
        api_base=api_base,
        default_temperature=0.7,
        default_max_tokens=4096,
    )
    model = SimpleNamespace(id="model", model_id=model_id, enabled=True, provider_id=provider.id)
    db = MagicMock()
    db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=model)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=provider)),
    ]
    base_url = api_base or "https://api.minimax.io/v1"
    hostname = urlsplit(base_url).hostname
    target = PinnedTarget(f"{base_url}/chat/completions", hostname, hostname, ("203.0.113.10",))
    resolver = AsyncMock(return_value=target)
    monkeypatch.setattr(llm_proxy_service, "resolve_pinned_target", resolver)
    captured = []

    def handle(request):
        """Capture the serialized request and return an offline response."""
        captured.append(request)
        if stream:
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n', headers={"content-type": "text/event-stream"})
        return httpx.Response(
            200,
            json={
                "id": "completion",
                "created": 1,
                "model": model_id,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            },
        )

    @asynccontextmanager
    async def isolated_client(**_kwargs):
        """Keep the real HTTP serializer and replace only the network transport."""
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False) as client:
            yield client

    monkeypatch.setattr(llm_proxy_service, "get_isolated_http_client", isolated_client)
    service = llm_proxy_service.LLMProxyService()
    service._client = MagicMock()
    monkeypatch.setattr(service, "_get_api_key", lambda _provider: "test-minimax-token")
    messages = [
        ChatMessage(role="user", content="Check the weather"),
        ChatMessage(role="assistant", tool_calls=[{"id": "call-1", "type": "function", "function": {"name": "weather", "arguments": "{}"}}]),
        ChatMessage(role="tool", tool_call_id="call-1", content="Sunny"),
    ]
    request = ChatCompletionRequest(model=model.id, messages=messages, stream=stream)
    if stream:
        chunks = [chunk async for chunk in service.chat_completion_stream(db, request)]
        assert chunks[-1] == "data: [DONE]\n\n"
    else:
        result = await service.chat_completion(db, request)
        assert result.choices[0].message.content == "ok"
    resolver.assert_awaited_once_with(f"{base_url}/chat/completions", "LLM provider URL")
    assert len(captured) == 1
    outgoing = captured[0]
    assert str(outgoing.url) == "https://203.0.113.10/v1/chat/completions"
    assert outgoing.headers["host"] == hostname
    assert outgoing.headers["authorization"] == "Bearer test-minimax-token"
    assert outgoing.extensions["sni_hostname"] == hostname
    payload = json.loads(outgoing.content)
    assert payload == {
        "model": model_id,
        "messages": [message.model_dump(exclude_none=True) for message in messages],
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": stream,
    }
