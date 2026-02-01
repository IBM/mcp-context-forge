# -*- coding: utf-8 -*-
"""Tests for cancellation_service."""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services.cancellation_service import CancellationService


@pytest.mark.asyncio
async def test_initialize_with_redis(monkeypatch):
    service = CancellationService()
    monkeypatch.setattr(service, "_listen_for_cancellations", AsyncMock())
    monkeypatch.setattr("mcpgateway.services.cancellation_service.get_redis_client", AsyncMock(return_value=MagicMock()))

    created_tasks = []

    def _fake_create_task(coro):
        created_tasks.append(coro)
        task = MagicMock()
        task.done.return_value = False
        return task

    monkeypatch.setattr("mcpgateway.services.cancellation_service.asyncio.create_task", _fake_create_task)

    await service.initialize()
    assert service._initialized is True
    assert service._pubsub_task is not None
    assert created_tasks


@pytest.mark.asyncio
async def test_shutdown_cancels_task():
    service = CancellationService()
    class DummyTask:
        def __init__(self):
            self.cancel_called = False

        def done(self):
            return False

        def cancel(self):
            self.cancel_called = True

        def __await__(self):
            async def _noop():
                return None

            return _noop().__await__()

    task = DummyTask()
    service._pubsub_task = task

    await service.shutdown()
    assert task.cancel_called is True


@pytest.mark.asyncio
async def test_cancel_run_unknown_publishes(monkeypatch):
    service = CancellationService()
    service._publish_cancellation = AsyncMock()

    result = await service.cancel_run("missing", reason="test")
    assert result is False
    service._publish_cancellation.assert_awaited_once_with("missing", "test")


@pytest.mark.asyncio
async def test_cancel_run_known_executes_callback(monkeypatch):
    service = CancellationService()
    callback = AsyncMock()
    await service.register_run("run-1", name="tool", cancel_callback=callback)
    service._publish_cancellation = AsyncMock()

    result = await service.cancel_run("run-1", reason="stop")
    assert result is True
    callback.assert_awaited_once_with("stop")
    service._publish_cancellation.assert_awaited_once_with("run-1", "stop")


@pytest.mark.asyncio
async def test_cancel_run_local_handles_callback_error():
    service = CancellationService()

    async def _boom(_reason):
        raise RuntimeError("bad")

    await service.register_run("run-1", cancel_callback=_boom)
    result = await service._cancel_run_local("run-1", reason="x")
    assert result is True


@pytest.mark.asyncio
async def test_publish_cancellation_no_redis():
    service = CancellationService()
    service._redis = None
    await service._publish_cancellation("run-1", reason="no-redis")


@pytest.mark.asyncio
async def test_publish_cancellation_redis_error():
    service = CancellationService()
    redis = AsyncMock()
    redis.publish.side_effect = RuntimeError("fail")
    service._redis = redis
    await service._publish_cancellation("run-1", reason="boom")


@pytest.mark.asyncio
async def test_get_status_and_is_registered():
    service = CancellationService()
    await service.register_run("run-1", name="tool")
    assert await service.is_registered("run-1") is True
    status = await service.get_status("run-1")
    assert status["name"] == "tool"
    await service.unregister_run("run-1")
    assert await service.is_registered("run-1") is False
