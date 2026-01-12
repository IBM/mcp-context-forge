# -*- coding: utf-8 -*-
import pytest
import asyncio
from unittest.mock import AsyncMock

from mcpgateway.services.orchestration_service import OrchestrationService, orchestration_service


@pytest.mark.asyncio
async def test_register_and_cancel_triggers_callback():
    svc = OrchestrationService()

    mock_cb = AsyncMock()

    await svc.register_run("r1", name="tool1", cancel_callback=mock_cb)

    res = await svc.cancel_run("r1", reason="stop")
    assert res is True
    mock_cb.assert_awaited_once_with("stop")


@pytest.mark.asyncio
async def test_cancel_nonexistent_returns_false():
    svc = OrchestrationService()
    res = await svc.cancel_run("noexist")
    assert res is False


@pytest.mark.asyncio
async def test_unregister_removes_run():
    svc = OrchestrationService()
    await svc.register_run("r2", name="tool2")
    assert await svc.get_status("r2") is not None
    await svc.unregister_run("r2")
    assert await svc.get_status("r2") is None
