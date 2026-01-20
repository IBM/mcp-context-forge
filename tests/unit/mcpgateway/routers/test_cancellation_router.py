# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_cancellation_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for cancellation router endpoints.
"""

from unittest.mock import AsyncMock, patch

import pytest

from mcpgateway.services.cancellation_service import CancellationService, cancellation_service


@pytest.mark.asyncio
async def test_cancel_returns_cancelled_for_registered_run():
    """Test that cancelling a registered run returns 'cancelled' status."""
    svc = CancellationService()
    await svc.register_run("test-run", name="test_tool")

    result = await svc.cancel_run("test-run", reason="unit test")

    assert result is True
    status = await svc.get_status("test-run")
    assert status["cancelled"] is True
    assert status["cancel_reason"] == "unit test"


@pytest.mark.asyncio
async def test_cancel_returns_false_for_unknown_run():
    """Test that cancelling an unknown run returns False."""
    svc = CancellationService()

    result = await svc.cancel_run("unknown-run", reason="test")

    assert result is False


@pytest.mark.asyncio
async def test_cancel_invokes_callback():
    """Test that cancel invokes the registered callback."""
    svc = CancellationService()
    mock_cb = AsyncMock()

    await svc.register_run("callback-test", name="tool", cancel_callback=mock_cb)
    await svc.cancel_run("callback-test", reason="test reason")

    mock_cb.assert_awaited_once_with("test reason")


@pytest.mark.asyncio
async def test_status_returns_none_for_unknown_run():
    """Test that get_status returns None for unknown runs."""
    svc = CancellationService()

    status = await svc.get_status("nonexistent")

    assert status is None


@pytest.mark.asyncio
async def test_status_returns_run_info():
    """Test that get_status returns run info for registered runs."""
    svc = CancellationService()
    await svc.register_run("status-test", name="test_tool")

    status = await svc.get_status("status-test")

    assert status is not None
    assert status["name"] == "test_tool"
    assert status["cancelled"] is False
    assert "registered_at" in status


@pytest.mark.asyncio
async def test_is_registered_returns_correct_values():
    """Test that is_registered returns correct values."""
    svc = CancellationService()

    assert await svc.is_registered("not-registered") is False

    await svc.register_run("registered", name="tool")
    assert await svc.is_registered("registered") is True

    await svc.unregister_run("registered")
    assert await svc.is_registered("registered") is False


@pytest.mark.asyncio
async def test_unregister_removes_run():
    """Test that unregister removes the run."""
    svc = CancellationService()
    await svc.register_run("to-remove", name="tool")

    await svc.unregister_run("to-remove")

    assert await svc.get_status("to-remove") is None


@pytest.mark.asyncio
async def test_cancel_is_idempotent():
    """Test that calling cancel multiple times is idempotent."""
    svc = CancellationService()
    mock_cb = AsyncMock()
    await svc.register_run("idem-test", name="tool", cancel_callback=mock_cb)

    # First cancel
    result1 = await svc.cancel_run("idem-test", reason="first")
    assert result1 is True
    assert mock_cb.call_count == 1

    # Second cancel - should return True but not invoke callback again
    result2 = await svc.cancel_run("idem-test", reason="second")
    assert result2 is True
    assert mock_cb.call_count == 1  # Still 1, not invoked again


@pytest.mark.asyncio
async def test_cancel_callback_exception_is_handled():
    """Test that exceptions in cancel callbacks are handled gracefully."""
    svc = CancellationService()

    async def failing_cb(reason):
        raise RuntimeError("Callback failed")

    await svc.register_run("fail-cb-test", name="tool", cancel_callback=failing_cb)

    # Should not raise, exception is logged
    result = await svc.cancel_run("fail-cb-test", reason="test")
    assert result is True

    status = await svc.get_status("fail-cb-test")
    assert status["cancelled"] is True
