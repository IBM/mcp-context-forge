# -*- coding: utf-8 -*-
"""Tests for cancellation_service."""

# Standard
import asyncio
import json
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
async def test_initialize_is_idempotent(monkeypatch):
    service = CancellationService()
    mock_get = AsyncMock(return_value=None)
    monkeypatch.setattr("mcpgateway.services.cancellation_service.get_redis_client", mock_get)

    await service.initialize()
    await service.initialize()

    # Second call should return early without re-fetching.
    assert mock_get.await_count == 1


@pytest.mark.asyncio
async def test_initialize_logs_warning_on_exception(monkeypatch):
    service = CancellationService()
    monkeypatch.setattr("mcpgateway.services.cancellation_service.get_redis_client", AsyncMock(side_effect=RuntimeError("boom")))

    await service.initialize()
    assert service._initialized is True


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
async def test_shutdown_handles_cancelled_error_from_task():
    service = CancellationService()

    class DummyTask:
        def done(self):
            return False

        def cancel(self):
            return None

        def __await__(self):
            async def _raise():
                raise asyncio.CancelledError()

            return _raise().__await__()

    service._pubsub_task = DummyTask()
    await service.shutdown()


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
async def test_cancel_run_local_run_not_found():
    service = CancellationService()
    assert await service._cancel_run_local("missing") is False


@pytest.mark.asyncio
async def test_cancel_run_local_already_cancelled():
    service = CancellationService()
    await service.register_run("run-1")
    service._runs["run-1"]["cancelled"] = True
    assert await service._cancel_run_local("run-1") is True


@pytest.mark.asyncio
async def test_cancel_run_local_callback_success():
    service = CancellationService()
    callback = AsyncMock()
    await service.register_run("run-1", cancel_callback=callback)
    assert await service._cancel_run_local("run-1", reason="ok") is True
    callback.assert_awaited_once_with("ok")


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
async def test_publish_cancellation_success_logs_debug(monkeypatch):
    service = CancellationService()
    redis = AsyncMock()
    service._redis = redis

    await service._publish_cancellation("run-1", reason="ok")
    redis.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_status_and_is_registered():
    service = CancellationService()
    await service.register_run("run-1", name="tool")
    assert await service.is_registered("run-1") is True
    status = await service.get_status("run-1")
    assert status["name"] == "tool"
    await service.unregister_run("run-1")
    assert await service.is_registered("run-1") is False


@pytest.mark.asyncio
async def test_cancel_run_already_cancelled(monkeypatch):
    service = CancellationService()
    await service.register_run("run-1", name="tool")
    service._runs["run-1"]["cancelled"] = True
    service._publish_cancellation = AsyncMock()

    result = await service.cancel_run("run-1", reason="again")
    assert result is True
    service._publish_cancellation.assert_not_awaited()


@pytest.mark.asyncio
async def test_listen_for_cancellations_returns_when_not_initialized():
    service = CancellationService()
    assert await service._listen_for_cancellations() is None


@pytest.mark.asyncio
async def test_listen_for_cancellations_timeout_continues(monkeypatch):
    service = CancellationService()

    class DummyPubSub:
        async def subscribe(self, _channel):
            return None

        async def unsubscribe(self, _channel):
            return None

        async def aclose(self):
            return None

        async def get_message(self, **_kwargs):
            return None

    class DummyRedis:
        def pubsub(self):
            return DummyPubSub()

    service._redis = DummyRedis()

    calls = {"n": 0}

    async def _fake_wait_for(*_args, **_kwargs):
        # Ensure we don't leak an un-awaited coroutine created by pubsub.get_message(...).
        if _args:
            aw = _args[0]
            close = getattr(aw, "close", None)
            if callable(close):
                close()
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.TimeoutError()
        raise asyncio.CancelledError()

    monkeypatch.setattr("mcpgateway.services.cancellation_service.asyncio.wait_for", _fake_wait_for)

    with pytest.raises(asyncio.CancelledError):
        await service._listen_for_cancellations()


@pytest.mark.asyncio
async def test_listen_for_cancellations_skips_null_run_id(monkeypatch):
    service = CancellationService()

    messages = [
        {"type": "message", "data": json.dumps({"run_id": None, "reason": "stop"}).encode()},
    ]

    class DummyPubSub:
        def __init__(self, items):
            self._items = list(items)
            self.unsubscribe_called = False

        async def subscribe(self, _channel):
            return None

        async def get_message(self, **_kwargs):
            if self._items:
                return self._items.pop(0)
            raise asyncio.CancelledError()

        async def unsubscribe(self, _channel):
            self.unsubscribe_called = True

        async def aclose(self):
            return None

    class DummyRedis:
        def __init__(self, pubsub):
            self._pubsub = pubsub

        def pubsub(self):
            return self._pubsub

    pubsub = DummyPubSub(messages)
    service._redis = DummyRedis(pubsub)
    monkeypatch.setattr(service, "_cancel_run_local", AsyncMock())

    task = asyncio.create_task(service._listen_for_cancellations())
    with pytest.raises(asyncio.CancelledError):
        await task

    service._cancel_run_local.assert_not_awaited()
    assert pubsub.unsubscribe_called is True


@pytest.mark.asyncio
async def test_listen_for_cancellations_pubsub_error_is_caught():
    service = CancellationService()

    class DummyRedis:
        def pubsub(self):
            raise RuntimeError("boom")

    service._redis = DummyRedis()
    # Should not raise.
    assert await service._listen_for_cancellations() is None


@pytest.mark.asyncio
async def test_listen_for_cancellations_cleanup_uses_close_when_aclose_missing():
    service = CancellationService()

    class DummyPubSub:
        def __init__(self):
            self.closed = False

        async def subscribe(self, _channel):
            return None

        async def get_message(self, **_kwargs):
            raise asyncio.CancelledError()

        async def unsubscribe(self, _channel):
            return None

        async def close(self):
            self.closed = True

    class DummyRedis:
        def __init__(self, pubsub):
            self._pubsub = pubsub

        def pubsub(self):
            return self._pubsub

    pubsub = DummyPubSub()
    service._redis = DummyRedis(pubsub)

    task = asyncio.create_task(service._listen_for_cancellations())
    with pytest.raises(asyncio.CancelledError):
        await task

    assert pubsub.closed is True


@pytest.mark.asyncio
async def test_listen_for_cancellations_cleanup_exception_is_swallowed(monkeypatch):
    service = CancellationService()

    class DummyPubSub:
        async def subscribe(self, _channel):
            return None

        async def get_message(self, **_kwargs):
            raise asyncio.CancelledError()

        async def unsubscribe(self, _channel):
            raise RuntimeError("boom")

        async def aclose(self):
            return None

    class DummyRedis:
        def __init__(self, pubsub):
            self._pubsub = pubsub

        def pubsub(self):
            return self._pubsub

    service._redis = DummyRedis(DummyPubSub())
    debug = MagicMock()
    monkeypatch.setattr("mcpgateway.services.cancellation_service.logger.debug", debug)

    task = asyncio.create_task(service._listen_for_cancellations())
    with pytest.raises(asyncio.CancelledError):
        await task

    assert debug.called


@pytest.mark.asyncio
async def test_listen_for_cancellations_processes_messages(monkeypatch):
    service = CancellationService()

    messages = [
        None,
        {"type": "subscribe"},
        {"type": "message", "data": json.dumps({"run_id": "run-1", "reason": "stop"}).encode()},
        {"type": "message", "data": b"not-json"},
    ]

    class DummyPubSub:
        def __init__(self, items):
            self._items = list(items)
            self.unsubscribe_called = False
            self.closed = False

        async def subscribe(self, _channel):
            return None

        async def get_message(self, **_kwargs):
            if self._items:
                return self._items.pop(0)
            raise asyncio.CancelledError()

        async def unsubscribe(self, _channel):
            self.unsubscribe_called = True

        async def aclose(self):
            self.closed = True

    class DummyRedis:
        def __init__(self, pubsub):
            self._pubsub = pubsub

        def pubsub(self):
            return self._pubsub

    pubsub = DummyPubSub(messages)
    service._redis = DummyRedis(pubsub)
    monkeypatch.setattr(service, "_cancel_run_local", AsyncMock())

    task = asyncio.create_task(service._listen_for_cancellations())
    with pytest.raises(asyncio.CancelledError):
        await task

    service._cancel_run_local.assert_awaited_with("run-1", reason="stop")
    assert pubsub.unsubscribe_called is True
    assert pubsub.closed is True
