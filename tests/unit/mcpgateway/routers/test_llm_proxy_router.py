# -*- coding: utf-8 -*-
"""Tests for LLM proxy router."""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

# First-Party
from mcpgateway.llm_schemas import ChatCompletionRequest, ChatMessage, GatewayModelInfo
from mcpgateway.routers import llm_proxy_router
from mcpgateway.services.llm_proxy_service import LLMModelNotFoundError


@pytest.mark.asyncio
async def test_chat_completions_streaming_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_proxy_router.settings, "llm_streaming_enabled", False)

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")], stream=True)

    with pytest.raises(HTTPException) as excinfo:
        await llm_proxy_router.chat_completions(request, db=MagicMock(), current_user={})

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_chat_completions_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_proxy_router.settings, "llm_streaming_enabled", True)

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    response = SimpleNamespace(id="resp")

    monkeypatch.setattr(llm_proxy_router.llm_proxy_service, "chat_completion", AsyncMock(return_value=response))

    result = await llm_proxy_router.chat_completions(request, db=MagicMock(), current_user={})

    assert result.id == "resp"


@pytest.mark.asyncio
async def test_chat_completions_model_not_found(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_proxy_router.settings, "llm_streaming_enabled", True)

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    monkeypatch.setattr(llm_proxy_router.llm_proxy_service, "chat_completion", AsyncMock(side_effect=LLMModelNotFoundError("missing")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_proxy_router.chat_completions(request, db=MagicMock(), current_user={})

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_chat_completions_streaming_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_proxy_router.settings, "llm_streaming_enabled", True)

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")], stream=True)

    async def fake_stream(db, req):
        yield "data: test\n\n"

    monkeypatch.setattr(llm_proxy_router.llm_proxy_service, "chat_completion_stream", fake_stream)

    result = await llm_proxy_router.chat_completions(request, db=MagicMock(), current_user={})

    assert isinstance(result, StreamingResponse)
    assert result.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_chat_completions_provider_not_found(monkeypatch: pytest.MonkeyPatch):
    from mcpgateway.services.llm_provider_service import LLMProviderNotFoundError

    monkeypatch.setattr(llm_proxy_router.settings, "llm_streaming_enabled", True)

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    monkeypatch.setattr(llm_proxy_router.llm_proxy_service, "chat_completion", AsyncMock(side_effect=LLMProviderNotFoundError("no provider")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_proxy_router.chat_completions(request, db=MagicMock(), current_user={})

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_chat_completions_auth_error(monkeypatch: pytest.MonkeyPatch):
    from mcpgateway.services.llm_proxy_service import LLMProxyAuthError

    monkeypatch.setattr(llm_proxy_router.settings, "llm_streaming_enabled", True)

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    monkeypatch.setattr(llm_proxy_router.llm_proxy_service, "chat_completion", AsyncMock(side_effect=LLMProxyAuthError("bad auth")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_proxy_router.chat_completions(request, db=MagicMock(), current_user={})

    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_chat_completions_request_error(monkeypatch: pytest.MonkeyPatch):
    from mcpgateway.services.llm_proxy_service import LLMProxyRequestError

    monkeypatch.setattr(llm_proxy_router.settings, "llm_streaming_enabled", True)

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    monkeypatch.setattr(llm_proxy_router.llm_proxy_service, "chat_completion", AsyncMock(side_effect=LLMProxyRequestError("upstream error")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_proxy_router.chat_completions(request, db=MagicMock(), current_user={})

    assert excinfo.value.status_code == 502


@pytest.mark.asyncio
async def test_chat_completions_unexpected_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_proxy_router.settings, "llm_streaming_enabled", True)

    request = ChatCompletionRequest(model="gpt-4", messages=[ChatMessage(role="user", content="hi")])
    monkeypatch.setattr(llm_proxy_router.llm_proxy_service, "chat_completion", AsyncMock(side_effect=RuntimeError("boom")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_proxy_router.chat_completions(request, db=MagicMock(), current_user={})

    assert excinfo.value.status_code == 500
    assert "Internal error" in excinfo.value.detail


@pytest.mark.asyncio
async def test_list_models(monkeypatch: pytest.MonkeyPatch):
    models = [GatewayModelInfo(id="m1", model_id="gpt-4", model_name="GPT", provider_id="p1", provider_name="Provider", provider_type="openai", supports_streaming=True, supports_function_calling=False, supports_vision=False)]

    class DummyService:
        def get_gateway_models(self, db):
            return models

    monkeypatch.setattr("mcpgateway.services.llm_provider_service.LLMProviderService", lambda: DummyService())

    response = await llm_proxy_router.list_models(db=MagicMock(), current_user={})

    assert response["object"] == "list"
    assert response["data"][0]["id"] == "gpt-4"


@pytest.mark.asyncio
async def test_list_models_empty(monkeypatch: pytest.MonkeyPatch):
    class DummyService:
        def get_gateway_models(self, db):
            return []

    monkeypatch.setattr("mcpgateway.services.llm_provider_service.LLMProviderService", lambda: DummyService())

    response = await llm_proxy_router.list_models(db=MagicMock(), current_user={})

    assert response["object"] == "list"
    assert response["data"] == []
