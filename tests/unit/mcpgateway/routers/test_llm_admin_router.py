# -*- coding: utf-8 -*-
"""Tests for LLM admin router."""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
import orjson

# First-Party
from datetime import datetime, timezone

from mcpgateway.llm_schemas import ChatChoice, ChatCompletionResponse, ChatMessage, UsageStats
from mcpgateway.llm_schemas import HealthStatus, ProviderHealthCheck
from mcpgateway.routers import llm_admin_router
from mcpgateway.services.llm_provider_service import LLMProviderNotFoundError


@pytest.fixture
def mock_request():
    req = MagicMock()
    req.scope = {"root_path": ""}
    req.app = MagicMock()
    req.app.state = MagicMock()
    req.app.state.templates = MagicMock()
    req.app.state.templates.TemplateResponse.return_value = HTMLResponse("ok")
    return req


def _provider():
    return SimpleNamespace(
        id="p1",
        name="Provider",
        slug="provider",
        description=None,
        provider_type="openai",
        api_base=None,
        enabled=True,
        health_status=None,
        last_health_check=None,
        models=[],
        created_at=None,
        updated_at=None,
    )


def _model():
    return SimpleNamespace(
        id="m1",
        model_id="gpt",
        model_name="GPT",
        model_alias=None,
        description=None,
        provider_id="p1",
        supports_chat=True,
        supports_streaming=False,
        supports_function_calling=False,
        supports_vision=False,
        context_window=None,
        max_output_tokens=None,
        enabled=True,
        deprecated=False,
        created_at=None,
        updated_at=None,
    )


@pytest.mark.asyncio
async def test_get_providers_partial(mock_request, monkeypatch: pytest.MonkeyPatch):
    provider = _provider()
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "list_providers", lambda **kwargs: ([provider], 1))

    response = await llm_admin_router.get_providers_partial(mock_request, page=1, per_page=50, current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert isinstance(response, HTMLResponse)
    mock_request.app.state.templates.TemplateResponse.assert_called_once()


@pytest.mark.asyncio
async def test_get_models_partial_missing_provider(mock_request, monkeypatch: pytest.MonkeyPatch):
    model = _model()
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "list_models", lambda **kwargs: ([model], 1))
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "get_provider", MagicMock(side_effect=LLMProviderNotFoundError("missing")))
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "list_providers", lambda *args, **kwargs: ([], 0))

    response = await llm_admin_router.get_models_partial(mock_request, provider_id=None, page=1, per_page=50, current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert isinstance(response, HTMLResponse)


@pytest.mark.asyncio
async def test_set_provider_state_html(mock_request, monkeypatch: pytest.MonkeyPatch):
    provider = _provider()
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "set_provider_state", lambda *args, **kwargs: provider)

    response = await llm_admin_router.set_provider_state_html(mock_request, "p1", current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert isinstance(response, HTMLResponse)


@pytest.mark.asyncio
async def test_delete_provider_html_not_found(mock_request, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "delete_provider", MagicMock(side_effect=LLMProviderNotFoundError("missing")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_admin_router.delete_provider_html(mock_request, "missing", current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_check_provider_health(mock_request, monkeypatch: pytest.MonkeyPatch):
    health = ProviderHealthCheck(provider_id="p1", provider_name="Provider", provider_type="openai", status=HealthStatus.HEALTHY, response_time_ms=1.0, error=None, checked_at=datetime.now(timezone.utc))
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "check_provider_health", AsyncMock(return_value=health))

    result = await llm_admin_router.check_provider_health(mock_request, "p1", current_user_ctx={"db": MagicMock(), "email": "user@example.com"})
    assert result["status"] == "healthy"


@pytest.mark.asyncio
async def test_set_model_state_html(mock_request, monkeypatch: pytest.MonkeyPatch):
    model = _model()
    provider = _provider()
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "set_model_state", lambda *args, **kwargs: model)
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "get_provider", lambda *args, **kwargs: provider)

    response = await llm_admin_router.set_model_state_html(mock_request, "m1", current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert isinstance(response, HTMLResponse)


@pytest.mark.asyncio
async def test_delete_model_html_success(mock_request, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "delete_model", lambda *args, **kwargs: None)

    response = await llm_admin_router.delete_model_html(mock_request, "m1", current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_api_info_partial(mock_request, monkeypatch: pytest.MonkeyPatch):
    provider = _provider()
    model = _model()
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "list_providers", lambda *args, **kwargs: ([provider], 1))
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "list_models", lambda *args, **kwargs: ([model], 1))
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "get_provider", lambda *args, **kwargs: provider)

    response = await llm_admin_router.get_api_info_partial(mock_request, current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert isinstance(response, HTMLResponse)
    mock_request.app.state.templates.TemplateResponse.assert_called()


@pytest.mark.asyncio
async def test_admin_test_api_models(monkeypatch: pytest.MonkeyPatch):
    class DummyModel:
        def __init__(self, model_id, provider_name):
            self.model_id = model_id
            self.provider_name = provider_name

    monkeypatch.setattr(llm_admin_router.llm_provider_service, "get_gateway_models", lambda *_args, **_kwargs: [DummyModel("m1", "provider")])

    request = MagicMock()
    request.body = AsyncMock(return_value=orjson.dumps({"test_type": "models"}))

    response = await llm_admin_router.admin_test_api(request, db=MagicMock(), current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    payload = orjson.loads(response.body)
    assert payload["success"] is True
    assert payload["metrics"]["modelCount"] == 1


@pytest.mark.asyncio
async def test_admin_test_api_chat_success(monkeypatch: pytest.MonkeyPatch):
    response_obj = ChatCompletionResponse(
        id="resp1",
        created=1,
        model="m1",
        choices=[ChatChoice(index=0, message=ChatMessage(role="assistant", content="ok"), finish_reason="stop")],
        usage=UsageStats(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    class DummyProxy:
        async def chat_completion(self, *_args, **_kwargs):
            return response_obj

    import mcpgateway.services.llm_proxy_service as proxy_module

    monkeypatch.setattr(proxy_module, "LLMProxyService", lambda: DummyProxy())

    request = MagicMock()
    request.body = AsyncMock(return_value=orjson.dumps({"test_type": "chat", "model_id": "m1", "message": "hi"}))

    response = await llm_admin_router.admin_test_api(request, db=MagicMock(), current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    payload = orjson.loads(response.body)
    assert payload["success"] is True
    assert payload["assistant_message"] == "ok"


@pytest.mark.asyncio
async def test_admin_test_api_missing_model_id():
    request = MagicMock()
    request.body = AsyncMock(return_value=orjson.dumps({"test_type": "chat"}))

    with pytest.raises(HTTPException) as excinfo:
        await llm_admin_router.admin_test_api(request, db=MagicMock(), current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_admin_test_api_unknown_type():
    request = MagicMock()
    request.body = AsyncMock(return_value=orjson.dumps({"test_type": "unknown"}))

    with pytest.raises(HTTPException) as excinfo:
        await llm_admin_router.admin_test_api(request, db=MagicMock(), current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_get_provider_defaults(monkeypatch: pytest.MonkeyPatch):
    import mcpgateway.middleware.rbac as rbac_module

    monkeypatch.setattr(rbac_module.PermissionService, "check_permission", AsyncMock(return_value=True))

    result = await llm_admin_router.get_provider_defaults(MagicMock(), current_user_ctx={"email": "user@example.com", "db": MagicMock()})
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_get_provider_configs(monkeypatch: pytest.MonkeyPatch):
    import mcpgateway.middleware.rbac as rbac_module

    monkeypatch.setattr(rbac_module.PermissionService, "check_permission", AsyncMock(return_value=True))

    class DummyConfig:
        def model_dump(self):
            return {"fields": []}

    import mcpgateway.llm_provider_configs as config_module

    monkeypatch.setattr(config_module, "get_all_provider_configs", lambda: {"openai": DummyConfig()})

    result = await llm_admin_router.get_provider_configs(MagicMock(), current_user_ctx={"email": "user@example.com", "db": MagicMock()})
    assert result["openai"]["fields"] == []


@pytest.mark.asyncio
async def test_fetch_provider_models_no_support(monkeypatch: pytest.MonkeyPatch):
    provider = _provider()
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "get_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(llm_admin_router.LLMProviderType, "get_provider_defaults", lambda: {provider.provider_type: {"supports_model_list": False}})

    result = await llm_admin_router.fetch_provider_models(MagicMock(), "p1", db=MagicMock(), current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert result["success"] is False


@pytest.mark.asyncio
async def test_fetch_provider_models_no_base_url(monkeypatch: pytest.MonkeyPatch):
    provider = _provider()
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "get_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(llm_admin_router.LLMProviderType, "get_provider_defaults", lambda: {provider.provider_type: {"supports_model_list": True, "api_base": ""}})

    result = await llm_admin_router.fetch_provider_models(MagicMock(), "p1", db=MagicMock(), current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert result["success"] is False


@pytest.mark.asyncio
async def test_fetch_provider_models_success(monkeypatch: pytest.MonkeyPatch):
    provider = _provider()
    provider.api_base = "http://api"
    provider.api_key = None
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "get_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(llm_admin_router.LLMProviderType, "get_provider_defaults", lambda: {provider.provider_type: {"supports_model_list": True, "api_base": "http://api", "models_endpoint": "/models"}})

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "m1", "name": "Model", "owned_by": "openai"}]}

    class DummyClient:
        async def get(self, *_args, **_kwargs):
            return DummyResponse()

    import mcpgateway.services.http_client_service as http_service

    monkeypatch.setattr(http_service, "get_http_client", AsyncMock(return_value=DummyClient()))
    monkeypatch.setattr(http_service, "get_admin_timeout", lambda: 1)

    result = await llm_admin_router.fetch_provider_models(MagicMock(), "p1", db=MagicMock(), current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert result["success"] is True
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_sync_provider_models(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_admin_router, "fetch_provider_models", AsyncMock(return_value={"success": True, "models": [{"id": "m1"}, {"id": "m2"}]}))
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "list_models", lambda *_args, **_kwargs: ([SimpleNamespace(model_id="m1")], 1))
    create_model = MagicMock()
    monkeypatch.setattr(llm_admin_router.llm_provider_service, "create_model", create_model)

    result = await llm_admin_router.sync_provider_models(MagicMock(), "p1", db=MagicMock(), current_user_ctx={"db": MagicMock(), "email": "user@example.com"})

    assert result["added"] == 1
    assert result["skipped"] == 1
