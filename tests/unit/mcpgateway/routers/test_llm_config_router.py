# -*- coding: utf-8 -*-
"""Tests for LLM config router."""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from fastapi import HTTPException

# First-Party
from mcpgateway.llm_schemas import (
    HealthStatus,
    LLMModelCreate,
    LLMModelResponse,
    LLMModelUpdate,
    LLMProviderCreate,
    LLMProviderResponse,
    LLMProviderUpdate,
    ProviderHealthCheck,
)
from mcpgateway.routers import llm_config_router
from mcpgateway.services.llm_provider_service import (
    LLMModelConflictError,
    LLMModelNotFoundError,
    LLMProviderNameConflictError,
    LLMProviderNotFoundError,
)


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def ctx(mock_db):
    return {"db": mock_db, "email": "user@example.com"}


def _provider():
    return SimpleNamespace(id="p1", name="Provider", slug="provider", models=[], provider_type="openai", enabled=True)


def _model():
    return SimpleNamespace(id="m1", provider_id="p1", model_id="gpt", model_name="GPT", models=[])


def _provider_response():
    return LLMProviderResponse(
        id="p1",
        name="Provider",
        slug="provider",
        description=None,
        provider_type="openai",
        api_base=None,
        api_version=None,
        config={},
        default_model=None,
        default_temperature=0.7,
        default_max_tokens=None,
        enabled=True,
        health_status="unknown",
        last_health_check=None,
        plugin_ids=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        created_by=None,
        modified_by=None,
        model_count=0,
    )


def _model_response():
    return LLMModelResponse(
        id="m1",
        provider_id="p1",
        model_id="gpt",
        model_name="GPT",
        model_alias=None,
        description=None,
        supports_chat=True,
        supports_streaming=True,
        supports_function_calling=False,
        supports_vision=False,
        context_window=None,
        max_output_tokens=None,
        enabled=True,
        deprecated=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        provider_name=None,
        provider_type=None,
    )


@pytest.mark.asyncio
async def test_create_provider_success(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    provider = _provider()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "create_provider", lambda **kwargs: provider)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_provider_response", lambda p, model_count: SimpleNamespace(id=p.id))

    result = await llm_config_router.create_provider(LLMProviderCreate(name="Provider", provider_type="openai"), current_user_ctx=ctx, db=mock_db)
    assert result.id == "p1"


@pytest.mark.asyncio
async def test_create_provider_conflict(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "create_provider", MagicMock(side_effect=LLMProviderNameConflictError("Provider")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.create_provider(LLMProviderCreate(name="Provider", provider_type="openai"), current_user_ctx=ctx, db=mock_db)

    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_list_providers(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    provider = _provider()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "list_providers", lambda **kwargs: ([provider], 1))
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_provider_response", lambda p, model_count: _provider_response())

    response = await llm_config_router.list_providers(page=1, page_size=50, current_user_ctx=ctx, db=mock_db)

    assert response.total == 1
    assert response.providers[0].id == "p1"


@pytest.mark.asyncio
async def test_get_provider_not_found(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_provider", MagicMock(side_effect=LLMProviderNotFoundError("missing")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.get_provider("missing", current_user_ctx=ctx, db=mock_db)

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_update_provider_success(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    provider = _provider()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "update_provider", lambda **kwargs: provider)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_provider_response", lambda p, model_count: _provider_response())

    result = await llm_config_router.update_provider("p1", LLMProviderUpdate(name="Provider"), current_user_ctx=ctx, db=mock_db)
    assert result.id == "p1"


@pytest.mark.asyncio
async def test_update_provider_conflict(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "update_provider", MagicMock(side_effect=LLMProviderNameConflictError("Provider")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.update_provider("p1", LLMProviderUpdate(name="Provider"), current_user_ctx=ctx, db=mock_db)

    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_provider_not_found(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "delete_provider", MagicMock(side_effect=LLMProviderNotFoundError("missing")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.delete_provider("missing", current_user_ctx=ctx, db=mock_db)

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_set_provider_state(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    provider = _provider()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "set_provider_state", lambda *args, **kwargs: provider)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_provider_response", lambda p, model_count: _provider_response())

    result = await llm_config_router.set_provider_state("p1", activate=True, current_user_ctx=ctx, db=mock_db)
    assert result.id == "p1"


@pytest.mark.asyncio
async def test_check_provider_health(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    health = ProviderHealthCheck(provider_id="p1", provider_name="Provider", provider_type="openai", status=HealthStatus.HEALTHY, response_time_ms=1.0, error=None, checked_at=datetime.now(timezone.utc))
    monkeypatch.setattr(llm_config_router.llm_provider_service, "check_provider_health", AsyncMock(return_value=health))

    result = await llm_config_router.check_provider_health("p1", current_user_ctx=ctx, db=mock_db)
    assert result.provider_id == "p1"


@pytest.mark.asyncio
async def test_create_model_conflict(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "create_model", MagicMock(side_effect=LLMModelConflictError("conflict")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.create_model(LLMModelCreate(provider_id="p1", model_id="gpt", model_name="GPT"), current_user_ctx=ctx, db=mock_db)

    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_get_model_not_found(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_model", MagicMock(side_effect=LLMModelNotFoundError("missing")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.get_model("missing", current_user_ctx=ctx, db=mock_db)

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_update_model_success(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    model = _model()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "update_model", lambda *args, **kwargs: model)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_model_response", lambda m, provider=None: _model_response())

    result = await llm_config_router.update_model("m1", LLMModelUpdate(model_name="GPT"), current_user_ctx=ctx, db=mock_db)
    assert result.id == "m1"


@pytest.mark.asyncio
async def test_delete_model_not_found(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "delete_model", MagicMock(side_effect=LLMModelNotFoundError("missing")))

    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.delete_model("missing", current_user_ctx=ctx, db=mock_db)

    assert excinfo.value.status_code == 404


# ============================================================================
# Coverage improvement tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_provider_generic_error(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "create_provider", MagicMock(side_effect=RuntimeError("boom")))
    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.create_provider(LLMProviderCreate(name="P", provider_type="openai"), current_user_ctx=ctx, db=mock_db)
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_get_provider_success(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    provider = _provider()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_provider", lambda db, pid: provider)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_provider_response", lambda p, mc: _provider_response())
    result = await llm_config_router.get_provider("p1", current_user_ctx=ctx, db=mock_db)
    assert result.id == "p1"


@pytest.mark.asyncio
async def test_update_provider_not_found(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "update_provider", MagicMock(side_effect=LLMProviderNotFoundError("missing")))
    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.update_provider("missing", LLMProviderUpdate(name="P"), current_user_ctx=ctx, db=mock_db)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_provider_success(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "delete_provider", MagicMock())
    result = await llm_config_router.delete_provider("p1", current_user_ctx=ctx, db=mock_db)
    assert result is None


@pytest.mark.asyncio
async def test_set_provider_state_not_found(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "set_provider_state", MagicMock(side_effect=LLMProviderNotFoundError("missing")))
    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.set_provider_state("missing", activate=True, current_user_ctx=ctx, db=mock_db)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_check_provider_health_not_found(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "check_provider_health", AsyncMock(side_effect=LLMProviderNotFoundError("missing")))
    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.check_provider_health("missing", current_user_ctx=ctx, db=mock_db)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_create_model_success(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    model = _model()
    provider = _provider()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "create_model", lambda db, data: model)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_provider", lambda db, pid: provider)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_model_response", lambda m, p=None: _model_response())
    result = await llm_config_router.create_model(LLMModelCreate(provider_id="p1", model_id="gpt", model_name="GPT"), current_user_ctx=ctx, db=mock_db)
    assert result.id == "m1"


@pytest.mark.asyncio
async def test_create_model_provider_not_found(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "create_model", MagicMock(side_effect=LLMProviderNotFoundError("missing")))
    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.create_model(LLMModelCreate(provider_id="missing", model_id="gpt", model_name="GPT"), current_user_ctx=ctx, db=mock_db)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_list_models_success(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    model = _model()
    provider = _provider()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "list_models", lambda **kwargs: ([model], 1))
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_provider", lambda db, pid: provider)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_model_response", lambda m, p=None: _model_response())
    result = await llm_config_router.list_models(page=1, page_size=50, current_user_ctx=ctx, db=mock_db)
    assert result.total == 1


@pytest.mark.asyncio
async def test_list_models_provider_not_found_fallback(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    model = _model()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "list_models", lambda **kwargs: ([model], 1))
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_provider", MagicMock(side_effect=LLMProviderNotFoundError("missing")))
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_model_response", lambda m, p=None: _model_response())
    result = await llm_config_router.list_models(page=1, page_size=50, current_user_ctx=ctx, db=mock_db)
    assert result.total == 1


@pytest.mark.asyncio
async def test_get_model_success(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    model = _model()
    provider = _provider()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_model", lambda db, mid: model)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_provider", lambda db, pid: provider)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_model_response", lambda m, p=None: _model_response())
    result = await llm_config_router.get_model("m1", current_user_ctx=ctx, db=mock_db)
    assert result.id == "m1"


@pytest.mark.asyncio
async def test_get_model_provider_not_found_fallback(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    model = _model()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_model", lambda db, mid: model)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_provider", MagicMock(side_effect=LLMProviderNotFoundError("missing")))
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_model_response", lambda m, p=None: _model_response())
    result = await llm_config_router.get_model("m1", current_user_ctx=ctx, db=mock_db)
    assert result.id == "m1"


@pytest.mark.asyncio
async def test_update_model_not_found(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "update_model", MagicMock(side_effect=LLMModelNotFoundError("missing")))
    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.update_model("missing", LLMModelUpdate(model_name="GPT"), current_user_ctx=ctx, db=mock_db)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_update_model_provider_not_found_fallback(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    model = _model()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "update_model", lambda *args, **kwargs: model)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_provider", MagicMock(side_effect=LLMProviderNotFoundError("missing")))
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_model_response", lambda m, p=None: _model_response())
    result = await llm_config_router.update_model("m1", LLMModelUpdate(model_name="GPT"), current_user_ctx=ctx, db=mock_db)
    assert result.id == "m1"


@pytest.mark.asyncio
async def test_delete_model_success(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "delete_model", MagicMock())
    result = await llm_config_router.delete_model("m1", current_user_ctx=ctx, db=mock_db)
    assert result is None


@pytest.mark.asyncio
async def test_set_model_state_success(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    model = _model()
    provider = _provider()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "set_model_state", lambda *args, **kwargs: model)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_provider", lambda db, pid: provider)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_model_response", lambda m, p=None: _model_response())
    result = await llm_config_router.set_model_state("m1", activate=True, current_user_ctx=ctx, db=mock_db)
    assert result.id == "m1"


@pytest.mark.asyncio
async def test_set_model_state_not_found(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "set_model_state", MagicMock(side_effect=LLMModelNotFoundError("missing")))
    with pytest.raises(HTTPException) as excinfo:
        await llm_config_router.set_model_state("missing", current_user_ctx=ctx, db=mock_db)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_set_model_state_provider_not_found_fallback(monkeypatch: pytest.MonkeyPatch, ctx, mock_db):
    model = _model()
    monkeypatch.setattr(llm_config_router.llm_provider_service, "set_model_state", lambda *args, **kwargs: model)
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_provider", MagicMock(side_effect=LLMProviderNotFoundError("missing")))
    monkeypatch.setattr(llm_config_router.llm_provider_service, "to_model_response", lambda m, p=None: _model_response())
    result = await llm_config_router.set_model_state("m1", activate=True, current_user_ctx=ctx, db=mock_db)
    assert result.id == "m1"


@pytest.mark.asyncio
async def test_get_gateway_models(monkeypatch: pytest.MonkeyPatch, mock_db):
    monkeypatch.setattr(llm_config_router.llm_provider_service, "get_gateway_models", lambda db: [])
    result = await llm_config_router.get_gateway_models(db=mock_db, current_user={"email": "user@test.com"})
    assert result.count == 0
