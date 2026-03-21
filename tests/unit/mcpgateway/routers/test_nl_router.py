# -*- coding: utf-8 -*-
"""Unit tests for NL router endpoints."""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators


_originals = patch_rbac_decorators()
# First-Party
from mcpgateway.routers import nl_router  # noqa: E402

restore_rbac_decorators(_originals)


@pytest.mark.asyncio
async def test_execute_nl_requires_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(nl_router.settings, "nl_execution_enabled", True)
    monkeypatch.setattr(nl_router.settings, "nl_execution_model", "")

    with pytest.raises(HTTPException) as excinfo:
        nl_router._ensure_enabled()

    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_execute_nl_calls_service(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(nl_router.settings, "nl_execution_enabled", True)
    monkeypatch.setattr(nl_router.settings, "nl_execution_model", "gpt-4")

    service_execute = AsyncMock(return_value={"session_id": "s1", "type": "success", "response": "ok"})
    monkeypatch.setattr(nl_router, "service", MagicMock(execute=service_execute))

    payload = nl_router.NLExecuteRequest(query="hello")
    result = await nl_router.execute_nl(payload, request=MagicMock(headers={}), db=MagicMock(), current_user_ctx={})

    assert result.type == "success"
    service_execute.assert_awaited_once()
