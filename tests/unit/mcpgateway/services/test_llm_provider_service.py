# -*- coding: utf-8 -*-
"""Tests for LLM provider service."""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import LLMProviderType
from mcpgateway.llm_schemas import (
    GatewayModelInfo,
    LLMModelCreate,
    LLMModelUpdate,
    LLMProviderCreate,
    LLMProviderUpdate,
)
from mcpgateway.services.llm_provider_service import (
    LLMModelConflictError,
    LLMModelNotFoundError,
    LLMProviderNameConflictError,
    LLMProviderNotFoundError,
    LLMProviderService,
)


@pytest.fixture
def service():
    return LLMProviderService()


@pytest.fixture
def db():
    return MagicMock(spec=Session)


def _mock_execute_scalar(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar.return_value = value
    return result


def test_create_provider_success(service, db, monkeypatch: pytest.MonkeyPatch):
    db.execute.return_value = _mock_execute_scalar(None)
    monkeypatch.setattr("mcpgateway.services.llm_provider_service.encode_auth", lambda data: "encoded")

    provider_data = LLMProviderCreate(
        name="Provider",
        provider_type=LLMProviderType.OPENAI,
        api_key="secret",
        api_base="http://api",
        enabled=True,
    )

    provider = service.create_provider(db, provider_data, created_by="user")

    assert provider.name == "Provider"
    assert provider.api_key == "encoded"
    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.refresh.assert_called_once()


def test_create_provider_conflict(service, db):
    db.execute.return_value = _mock_execute_scalar(SimpleNamespace(id="p1"))

    provider_data = LLMProviderCreate(
        name="Provider",
        provider_type=LLMProviderType.OPENAI,
        enabled=True,
    )

    with pytest.raises(LLMProviderNameConflictError):
        service.create_provider(db, provider_data)


def test_get_provider_not_found(service, db):
    db.execute.return_value = _mock_execute_scalar(None)

    with pytest.raises(LLMProviderNotFoundError):
        service.get_provider(db, "missing")


def test_list_providers_pagination(service, db):
    providers = [SimpleNamespace(name="p1"), SimpleNamespace(name="p2")]
    count_result = MagicMock()
    count_result.scalar.return_value = 2
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = providers
    db.execute.side_effect = [count_result, list_result]

    result, total = service.list_providers(db, enabled_only=False, page=1, page_size=10)

    assert total == 2
    assert result == providers


def test_update_provider_conflict(service, db):
    provider = SimpleNamespace(id="p1", name="Old", slug="old", enabled=True)
    service.get_provider = MagicMock(return_value=provider)

    db.execute.return_value = _mock_execute_scalar(SimpleNamespace(id="other"))

    with pytest.raises(LLMProviderNameConflictError):
        service.update_provider(db, "p1", LLMProviderUpdate(name="New"))


def test_update_provider_fields(service, db, monkeypatch: pytest.MonkeyPatch):
    provider = SimpleNamespace(
        id="p1",
        name="Old",
        slug="old",
        description=None,
        provider_type=LLMProviderType.OPENAI,
        api_key=None,
        api_base=None,
        api_version=None,
        config={},
        default_model=None,
        default_temperature=None,
        default_max_tokens=None,
        enabled=True,
        plugin_ids=None,
    )
    service.get_provider = MagicMock(return_value=provider)
    db.execute.return_value = _mock_execute_scalar(None)
    monkeypatch.setattr("mcpgateway.services.llm_provider_service.encode_auth", lambda data: "encoded")

    update = LLMProviderUpdate(
        name="New",
        description="desc",
        api_key="secret",
        api_base="http://api",
        enabled=False,
    )

    updated = service.update_provider(db, "p1", update, modified_by="editor")

    assert updated.name == "New"
    assert updated.description == "desc"
    assert updated.api_key == "encoded"
    assert updated.enabled is False
    db.commit.assert_called_once()
    db.refresh.assert_called_once()


def test_delete_provider(service, db):
    provider = SimpleNamespace(id="p1", name="Provider")
    service.get_provider = MagicMock(return_value=provider)

    assert service.delete_provider(db, "p1") is True
    db.delete.assert_called_once_with(provider)
    db.commit.assert_called_once()


def test_set_provider_state_toggle(service, db):
    provider = SimpleNamespace(id="p1", name="Provider", enabled=True)
    service.get_provider = MagicMock(return_value=provider)

    updated = service.set_provider_state(db, "p1")

    assert updated.enabled is False


def test_create_model_conflict(service, db):
    service.get_provider = MagicMock()
    db.execute.return_value = _mock_execute_scalar(SimpleNamespace(id="m1"))

    model_data = LLMModelCreate(provider_id="p1", model_id="gpt", model_name="GPT")

    with pytest.raises(LLMModelConflictError):
        service.create_model(db, model_data)


def test_create_model_success(service, db):
    service.get_provider = MagicMock()
    db.execute.return_value = _mock_execute_scalar(None)
    model_data = LLMModelCreate(provider_id="p1", model_id="gpt", model_name="GPT")

    model = service.create_model(db, model_data)

    assert model.model_id == "gpt"
    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.refresh.assert_called_once()


def test_get_model_not_found(service, db):
    db.execute.return_value = _mock_execute_scalar(None)

    with pytest.raises(LLMModelNotFoundError):
        service.get_model(db, "missing")


def test_list_models(service, db):
    models = [SimpleNamespace(model_id="m1")]
    count_result = MagicMock()
    count_result.scalar.return_value = 1
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = models
    db.execute.side_effect = [count_result, list_result]

    result, total = service.list_models(db, provider_id=None, enabled_only=False, page=1, page_size=10)

    assert total == 1
    assert result == models


def test_set_model_state(service, db):
    model = SimpleNamespace(model_id="m1", enabled=True)
    service.get_model = MagicMock(return_value=model)

    updated = service.set_model_state(db, "m1", activate=False)

    assert updated.enabled is False
    db.commit.assert_called_once()
    db.refresh.assert_called_once()


def test_get_gateway_models(service, db):
    model = SimpleNamespace(
        id="m1",
        model_id="gpt",
        model_name="GPT",
        supports_streaming=True,
        supports_function_calling=False,
        supports_vision=False,
    )
    provider = SimpleNamespace(id="p1", name="Provider", provider_type="openai")
    result = MagicMock()
    result.all.return_value = [(model, provider)]
    db.execute.return_value = result

    models = service.get_gateway_models(db)

    assert models[0].model_id == "gpt"
    assert isinstance(models[0], GatewayModelInfo)


@pytest.mark.asyncio
async def test_check_provider_health_openai(service, db, monkeypatch: pytest.MonkeyPatch):
    provider = SimpleNamespace(
        id="p1",
        name="Provider",
        provider_type=LLMProviderType.OPENAI,
        api_key=None,
        api_base="http://api",
        health_status=None,
        last_health_check=None,
    )
    service.get_provider = MagicMock(return_value=provider)

    class DummyClient:
        async def get(self, url, headers=None, timeout=10.0):
            return SimpleNamespace(status_code=200)

    async def fake_get_http_client():
        return DummyClient()

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", fake_get_http_client)

    result = await service.check_provider_health(db, "p1")

    assert result.provider_id == "p1"
    assert provider.health_status == result.status.value
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_check_provider_health_ollama_failure(service, db, monkeypatch: pytest.MonkeyPatch):
    provider = SimpleNamespace(
        id="p1",
        name="Provider",
        provider_type=LLMProviderType.OLLAMA,
        api_key=None,
        api_base="http://ollama",
        health_status=None,
        last_health_check=None,
    )
    service.get_provider = MagicMock(return_value=provider)

    class DummyClient:
        async def get(self, url, timeout=10.0):
            return SimpleNamespace(status_code=500)

    async def fake_get_http_client():
        return DummyClient()

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", fake_get_http_client)

    result = await service.check_provider_health(db, "p1")

    assert result.status.value in ("unhealthy", "unknown")


def test_to_provider_and_model_response(service):
    provider = SimpleNamespace(
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
        models=[],
    )

    response = service.to_provider_response(provider, model_count=0)
    assert response.name == "Provider"

    model = SimpleNamespace(
        id="m1",
        provider_id="p1",
        model_id="gpt",
        model_name="GPT",
        model_alias=None,
        description=None,
        supports_chat=True,
        supports_streaming=False,
        supports_function_calling=False,
        supports_vision=False,
        context_window=None,
        max_output_tokens=None,
        enabled=True,
        deprecated=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    model_response = service.to_model_response(model, provider)
    assert model_response.model_id == "gpt"
