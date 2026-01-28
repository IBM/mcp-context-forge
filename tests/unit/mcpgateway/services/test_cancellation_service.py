# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_cancellation_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

import pytest
import asyncio
from unittest.mock import AsyncMock

from mcpgateway.services.cancellation_service import CancellationService, cancellation_service


@pytest.mark.asyncio
async def test_register_and_cancel_triggers_callback():
    svc = CancellationService()

    mock_cb = AsyncMock()

    await svc.register_run("r1", name="tool1", cancel_callback=mock_cb)

    res = await svc.cancel_run("r1", reason="stop")
    assert res is True
    mock_cb.assert_awaited_once_with("stop")


@pytest.mark.asyncio
async def test_cancel_nonexistent_returns_false():
    svc = CancellationService()
    res = await svc.cancel_run("noexist")
    assert res is False


@pytest.mark.asyncio
async def test_unregister_removes_run():
    svc = CancellationService()
    await svc.register_run("r2", name="tool2")
    assert await svc.get_status("r2") is not None
    await svc.unregister_run("r2")
    assert await svc.get_status("r2") is None


@pytest.mark.asyncio
async def test_is_registered_returns_true_for_registered_run():
    svc = CancellationService()
    await svc.register_run("r3", name="tool3")
    assert await svc.is_registered("r3") is True


@pytest.mark.asyncio
async def test_is_registered_returns_false_for_unregistered_run():
    svc = CancellationService()
    assert await svc.is_registered("nonexistent") is False


@pytest.mark.asyncio
async def test_is_registered_returns_false_after_unregister():
    svc = CancellationService()
    await svc.register_run("r4", name="tool4")
    assert await svc.is_registered("r4") is True
    await svc.unregister_run("r4")
    assert await svc.is_registered("r4") is False


@pytest.mark.asyncio
async def test_cancel_logs_reason_and_metadata():
    """Test that cancellation logs include reason and metadata."""
    svc = CancellationService()
    await svc.register_run("r5", name="test_tool")

    # Cancel with reason
    result = await svc.cancel_run("r5", reason="user requested")
    assert result is True

    # Verify status includes cancellation metadata
    status = await svc.get_status("r5")
    assert status is not None
    assert status["cancelled"] is True
    assert status["cancel_reason"] == "user requested"
    assert "cancelled_at" in status
