# -*- coding: utf-8 -*-
"""Tests for LLM admin router."""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

# First-Party
from datetime import datetime, timezone

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
