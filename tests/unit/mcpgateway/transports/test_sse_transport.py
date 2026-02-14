# -*- coding: utf-8 -*-
"""Tests for mcpgateway.transports.sse_transport."""

# Standard
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from fastapi import Request

# First-Party
from mcpgateway.config import settings
from mcpgateway.transports import sse_transport
from mcpgateway.transports.sse_transport import SSETransport, _build_sse_frame, _get_sse_cleanup_timeout


class _DummyResponse:
    def __init__(self, body_iterator, **kwargs):
        self.body_iterator = body_iterator
        self.kwargs = kwargs


def test_build_sse_frame():
    frame = _build_sse_frame(b"message", b'{"ok": 1}', 15000)
    assert frame == b'event: message\r\ndata: {"ok": 1}\r\nretry: 15000\r\n\r\n'


@pytest.mark.asyncio
async def test_connect_disconnect_updates_state():
    transport = SSETransport("http://example.com")
    assert await transport.is_connected() is False

    await transport.connect()
    assert await transport.is_connected() is True

    await transport.disconnect()
    assert await transport.is_connected() is False
    assert transport._client_gone.is_set()


@pytest.mark.asyncio
async def test_send_message_requires_connection():
    transport = SSETransport()
    with pytest.raises(RuntimeError):
        await transport.send_message({"method": "ping"})

    await transport.connect()
    await transport.send_message({"method": "ping"})
    assert transport._message_queue.qsize() == 1


@pytest.mark.asyncio
async def test_send_message_queue_error():
    transport = SSETransport()
    await transport.connect()
    transport._message_queue = SimpleNamespace(put=AsyncMock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        await transport.send_message({"method": "ping"})


@pytest.mark.asyncio
async def test_receive_message_initializes_and_closes():
    transport = SSETransport()
    await transport.connect()
    generator = transport.receive_message()
    message = await anext(generator)
    assert message == {"jsonrpc": "2.0", "method": "initialize", "id": 1}
    transport._client_gone.set()
    await generator.aclose()


@pytest.mark.asyncio
async def test_receive_message_cancelled():
    transport = SSETransport()
    await transport.connect()
    generator = transport.receive_message()
    _ = await anext(generator)
    task = asyncio.create_task(anext(generator))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await generator.aclose()


@pytest.mark.asyncio
async def test_get_message_with_timeout_paths():
    transport = SSETransport()
    await transport._message_queue.put({"id": 1})
    result = await asyncio.wait_for(transport._get_message_with_timeout(0.1), timeout=0.5)
    assert result == {"id": 1}

    empty = await asyncio.wait_for(transport._get_message_with_timeout(0.01), timeout=0.5)
    assert empty is None


@pytest.mark.asyncio
async def test_get_message_with_timeout_none():
    transport = SSETransport()
    await transport._message_queue.put({"id": 2})
    result = await asyncio.wait_for(transport._get_message_with_timeout(None), timeout=0.5)
    assert result == {"id": 2}


@pytest.mark.asyncio
async def test_get_message_with_timeout_cancelled():
    transport = SSETransport()
    task = asyncio.create_task(transport._get_message_with_timeout(1.0))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_client_disconnected_flag():
    transport = SSETransport()
    assert await transport._client_disconnected(MagicMock(spec=Request)) is False
    transport._client_gone.set()
    assert await transport._client_disconnected(MagicMock(spec=Request)) is True


@pytest.mark.asyncio
async def test_create_sse_response_message_flow(monkeypatch):
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 123)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(side_effect=[False, True])
    on_disconnect = AsyncMock()

    await transport._message_queue.put({"jsonrpc": "2.0", "method": "ping", "id": 1})
    response = await transport.create_sse_response(request, on_disconnect_callback=on_disconnect)
    generator = response.body_iterator

    first = await anext(generator)
    second = await anext(generator)

    assert first.startswith(b"event: endpoint")
    assert b"/message?session_id=" in first
    assert second.startswith(b"event: message")

    transport._client_gone.set()
    await generator.aclose()
    on_disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_create_sse_response_keepalive_flow(monkeypatch):
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", True)
    monkeypatch.setattr(settings, "sse_retry_timeout", 321)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)
    monkeypatch.setattr(settings, "sse_keepalive_interval", 0.01)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(side_effect=[False, True])
    on_disconnect = AsyncMock()

    monkeypatch.setattr(transport, "_get_message_with_timeout", AsyncMock(return_value=None))

    response = await transport.create_sse_response(request, on_disconnect_callback=on_disconnect)
    generator = response.body_iterator

    first = await anext(generator)
    second = await anext(generator)
    third = await anext(generator)

    assert first.startswith(b"event: endpoint")
    assert second.startswith(b"event: keepalive")
    assert third.startswith(b"event: keepalive")

    transport._client_gone.set()
    await generator.aclose()
    on_disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_create_sse_response_disconnect_detected(monkeypatch):
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 100)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=True)
    on_disconnect = AsyncMock()

    response = await transport.create_sse_response(request, on_disconnect_callback=on_disconnect)
    generator = response.body_iterator

    first = await anext(generator)
    assert first.startswith(b"event: endpoint")

    with pytest.raises(StopAsyncIteration):
        await anext(generator)

    on_disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_create_sse_response_disconnect_callback_error(monkeypatch):
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 100)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=True)

    async def _disconnect_error():
        raise RuntimeError("boom")

    response = await transport.create_sse_response(request, on_disconnect_callback=_disconnect_error)
    generator = response.body_iterator

    first = await anext(generator)
    assert first.startswith(b"event: endpoint")

    with pytest.raises(StopAsyncIteration):
        await anext(generator)


@pytest.mark.asyncio
async def test_create_sse_response_rapid_yield_consecutive(monkeypatch):
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 100)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)
    monkeypatch.setattr(settings, "sse_rapid_yield_max", 0)

    counter = {"v": 0.0}

    def _fake_monotonic():
        counter["v"] += 0.01
        return counter["v"]

    monkeypatch.setattr(sse_transport.time, "monotonic", _fake_monotonic)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=False)
    on_disconnect = AsyncMock()

    for idx in range(10):
        await transport._message_queue.put({"jsonrpc": "2.0", "id": idx})

    response = await transport.create_sse_response(request, on_disconnect_callback=on_disconnect)
    generator = response.body_iterator

    frames = []
    for _ in range(20):
        try:
            frames.append(await anext(generator))
        except StopAsyncIteration:
            break

    assert transport._client_gone.is_set()
    assert len(frames) >= 2


@pytest.mark.asyncio
async def test_create_sse_response_rapid_yield_deque(monkeypatch):
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 100)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)
    monkeypatch.setattr(settings, "sse_rapid_yield_max", 1)
    monkeypatch.setattr(settings, "sse_rapid_yield_window_ms", 1000)

    counter = {"v": 0.0}

    def _fake_monotonic():
        counter["v"] += 0.001
        return counter["v"]

    monkeypatch.setattr(sse_transport.time, "monotonic", _fake_monotonic)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=False)
    on_disconnect = AsyncMock()

    for idx in range(2):
        await transport._message_queue.put({"jsonrpc": "2.0", "id": idx})

    response = await transport.create_sse_response(request, on_disconnect_callback=on_disconnect)
    generator = response.body_iterator

    frames = []
    for _ in range(10):
        try:
            frames.append(await anext(generator))
        except StopAsyncIteration:
            break

    assert transport._client_gone.is_set()
    assert len(frames) >= 2


def test_anyio_cancel_delivery_patch_toggle(monkeypatch):
    monkeypatch.setattr(settings, "anyio_cancel_delivery_patch_enabled", False)
    sse_transport._patch_applied = False
    assert sse_transport.apply_anyio_cancel_delivery_patch() is False
    assert sse_transport._patch_applied is False

    monkeypatch.setattr(settings, "anyio_cancel_delivery_patch_enabled", True)
    monkeypatch.setattr(settings, "anyio_cancel_delivery_max_iterations", 1)
    sse_transport._patch_applied = False

    original = sse_transport.CancelScope._deliver_cancellation
    assert sse_transport.apply_anyio_cancel_delivery_patch() is True
    assert sse_transport._patch_applied is True

    assert sse_transport.remove_anyio_cancel_delivery_patch() is True
    assert sse_transport.CancelScope._deliver_cancellation is original


def test_anyio_cancel_delivery_patch_failure(monkeypatch):
    monkeypatch.setattr(settings, "anyio_cancel_delivery_patch_enabled", True)
    sse_transport._patch_applied = False

    def _fail(_max):  # noqa: D401 - test stub
        raise RuntimeError("boom")

    monkeypatch.setattr(sse_transport, "_create_patched_deliver_cancellation", _fail)
    assert sse_transport.apply_anyio_cancel_delivery_patch() is False


def test_remove_anyio_cancel_delivery_patch_not_applied():
    sse_transport._patch_applied = False
    assert sse_transport.remove_anyio_cancel_delivery_patch() is False


def test_get_sse_cleanup_timeout_fallback(monkeypatch):
    class _BadSettings:
        @property
        def sse_task_group_cleanup_timeout(self):  # noqa: D401 - property for test
            raise RuntimeError("boom")

    monkeypatch.setattr(sse_transport, "settings", _BadSettings())
    assert _get_sse_cleanup_timeout() == 5.0


def test_patched_deliver_cancellation_limits_iterations(monkeypatch):
    calls = []

    def _orig(self, origin):  # noqa: D401 - test stub
        calls.append((self, origin))
        return True

    monkeypatch.setattr(sse_transport, "_original_deliver_cancellation", _orig)
    patched = sse_transport._create_patched_deliver_cancellation(1)

    origin = SimpleNamespace()
    scope = SimpleNamespace(_cancel_handle="handle")

    assert patched(scope, origin) is True
    assert patched(scope, origin) is False
    assert scope._cancel_handle is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_create_sse_response_errors_trigger_disconnect(monkeypatch):
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 123)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=False)
    on_disconnect = AsyncMock()

    transport._message_queue.get = AsyncMock(side_effect=RuntimeError("boom"))

    response = await transport.create_sse_response(request, on_disconnect_callback=on_disconnect)
    generator = response.body_iterator

    first = await anext(generator)
    assert first.startswith(b"event: endpoint")

    with pytest.raises(StopAsyncIteration):
        await anext(generator)

    on_disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_event_source_response_call_runs_tasks():
    response = sse_transport.EventSourceResponse(lambda: None)

    async def _noop(*_args, **_kwargs):
        return None

    response._stream_response = _noop
    response._ping = _noop
    response._listen_for_exit_signal = _noop
    response._listen_for_disconnect = _noop
    response.data_sender_callable = _noop
    response.background = AsyncMock()

    scope = {"type": "http"}

    async def _receive():
        return {"type": "http.disconnect"}

    async def _send(_message):
        return None

    await response(scope, _receive, _send)
    response.background.assert_awaited()


def test_anyio_cancel_delivery_patch_idempotent(monkeypatch):
    """Calling apply_anyio_cancel_delivery_patch twice should short-circuit when already applied."""
    monkeypatch.setattr(sse_transport, "_patch_applied", True)
    assert sse_transport.apply_anyio_cancel_delivery_patch() is True


def test_remove_anyio_cancel_delivery_patch_handles_exception(monkeypatch):
    """remove_anyio_cancel_delivery_patch should swallow assignment failures and return False."""

    class _BoomCancelScope:
        def __setattr__(self, _name, _value):  # noqa: D401 - test stub
            raise RuntimeError("boom")

    monkeypatch.setattr(sse_transport, "_patch_applied", True)
    monkeypatch.setattr(sse_transport, "CancelScope", _BoomCancelScope())
    assert sse_transport.remove_anyio_cancel_delivery_patch() is False


def test_patched_deliver_cancellation_max_iterations_no_cancel_handle(monkeypatch):
    """Max-iteration protection should still return False even if cancel handle is missing."""
    monkeypatch.setattr(sse_transport, "_original_deliver_cancellation", lambda *_args, **_kwargs: True)
    patched = sse_transport._create_patched_deliver_cancellation(0)

    origin = SimpleNamespace()
    scope = SimpleNamespace()

    assert patched(scope, origin) is False


@pytest.mark.asyncio
async def test_receive_message_exits_when_client_gone_set():
    transport = SSETransport()
    await transport.connect()

    generator = transport.receive_message()
    _ = await anext(generator)
    transport._client_gone.set()

    with pytest.raises(StopAsyncIteration):
        await anext(generator)


@pytest.mark.asyncio
async def test_event_source_response_call_skips_optional_sender_and_background():
    """Covers optional branches where sender/background are None."""
    response = sse_transport.EventSourceResponse(lambda: None)

    async def _noop(*_args, **_kwargs):
        return None

    response._stream_response = _noop
    response._ping = _noop
    response._listen_for_exit_signal = _noop
    response._listen_for_disconnect = _noop
    response.data_sender_callable = None
    response.background = None

    scope = {"type": "http"}

    async def _receive():
        return {"type": "http.disconnect"}

    async def _send(_message):
        return None

    await response(scope, _receive, _send)


@pytest.mark.asyncio
async def test_create_sse_response_resets_rapid_yield_counter_and_logs_debug(monkeypatch):
    """Cover normal-speed yield reset branch and debug logging path."""
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 123)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)
    monkeypatch.setattr(settings, "sse_rapid_yield_max", 0)

    counter = {"v": -0.2}

    def _fake_monotonic():
        counter["v"] += 0.2
        return counter["v"]

    monkeypatch.setattr(sse_transport.time, "monotonic", _fake_monotonic)

    monkeypatch.setattr(sse_transport.logger, "isEnabledFor", lambda level: level == logging.DEBUG)
    debug_mock = MagicMock()
    monkeypatch.setattr(sse_transport.logger, "debug", debug_mock)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(side_effect=[False, True])

    await transport._message_queue.put({"jsonrpc": "2.0", "method": "ping", "id": 1})

    response = await transport.create_sse_response(request)
    generator = response.body_iterator
    _ = await anext(generator)
    _ = await anext(generator)

    with pytest.raises(StopAsyncIteration):
        await anext(generator)

    assert debug_mock.called


@pytest.mark.asyncio
async def test_create_sse_response_deque_detection_returns_false_when_interval_not_ultra_fast(monkeypatch):
    """Cover deque-based detection branch where time_since_last >= 10ms."""
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 123)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)
    monkeypatch.setattr(settings, "sse_rapid_yield_max", 1)

    counter = {"v": -0.02}

    def _fake_monotonic():
        counter["v"] += 0.02
        return counter["v"]

    monkeypatch.setattr(sse_transport.time, "monotonic", _fake_monotonic)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(side_effect=[False, True])

    await transport._message_queue.put({"jsonrpc": "2.0", "method": "ping", "id": 1})

    response = await transport.create_sse_response(request)
    generator = response.body_iterator
    _ = await anext(generator)
    _ = await anext(generator)

    with pytest.raises(StopAsyncIteration):
        await anext(generator)


@pytest.mark.asyncio
async def test_create_sse_response_deque_detection_elapsed_window_false_branch(monkeypatch):
    """Cover deque-based detection where elapsed is not within the configured window (false branch)."""
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 123)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)
    monkeypatch.setattr(settings, "sse_rapid_yield_max", 1)
    monkeypatch.setattr(settings, "sse_rapid_yield_window_ms", 0)

    counter = {"v": -0.001}

    def _fake_monotonic():
        counter["v"] += 0.001
        return counter["v"]

    monkeypatch.setattr(sse_transport.time, "monotonic", _fake_monotonic)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(side_effect=[False, False, True])

    await transport._message_queue.put({"jsonrpc": "2.0", "method": "ping", "id": 1})
    await transport._message_queue.put({"jsonrpc": "2.0", "method": "ping", "id": 2})

    response = await transport.create_sse_response(request)
    generator = response.body_iterator
    _ = await anext(generator)
    _ = await anext(generator)
    _ = await anext(generator)

    with pytest.raises(StopAsyncIteration):
        await anext(generator)


@pytest.mark.asyncio
async def test_create_sse_response_keepalive_rapid_yield_disconnects(monkeypatch):
    """Resuming after keepalive yields should run post-yield logic and disconnect on rapid-yield spin."""
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", True)
    monkeypatch.setattr(settings, "sse_retry_timeout", 123)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)
    monkeypatch.setattr(settings, "sse_keepalive_interval", 0.0)
    monkeypatch.setattr(settings, "sse_rapid_yield_max", 0)

    counter = {"v": 0.0}

    def _fake_monotonic():
        counter["v"] += 0.001
        return counter["v"]

    monkeypatch.setattr(sse_transport.time, "monotonic", _fake_monotonic)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=False)
    on_disconnect = AsyncMock()

    monkeypatch.setattr(transport, "_get_message_with_timeout", AsyncMock(return_value=None))

    response = await transport.create_sse_response(request, on_disconnect_callback=on_disconnect)
    generator = response.body_iterator

    # Endpoint + immediate keepalive
    _ = await anext(generator)
    _ = await anext(generator)

    # Consume until rapid-yield protection stops the generator.
    for _ in range(30):
        try:
            await anext(generator)
        except StopAsyncIteration:
            break

    assert transport._client_gone.is_set()
    on_disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_create_sse_response_event_generator_cancelled_sets_client_gone(monkeypatch):
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 100)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(side_effect=asyncio.CancelledError())

    response = await transport.create_sse_response(request)
    generator = response.body_iterator
    _ = await anext(generator)
    with pytest.raises(asyncio.CancelledError):
        await anext(generator)
    assert transport._client_gone.is_set()


@pytest.mark.asyncio
async def test_create_sse_response_event_generator_error_sets_client_gone(monkeypatch):
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 100)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(side_effect=RuntimeError("boom"))

    response = await transport.create_sse_response(request)
    generator = response.body_iterator
    _ = await anext(generator)
    with pytest.raises(StopAsyncIteration):
        await anext(generator)
    assert transport._client_gone.is_set()


@pytest.mark.asyncio
async def test_create_sse_response_event_generator_generator_exit_sets_client_gone(monkeypatch):
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 100)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(side_effect=GeneratorExit())

    response = await transport.create_sse_response(request)
    generator = response.body_iterator
    _ = await anext(generator)
    with pytest.raises(StopAsyncIteration):
        await anext(generator)
    assert transport._client_gone.is_set()


@pytest.mark.asyncio
async def test_create_sse_response_client_close_handler_callback_error_swallowed(monkeypatch):
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 100)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=True)

    async def _disconnect_error():
        raise RuntimeError("boom")

    response = await transport.create_sse_response(request, on_disconnect_callback=_disconnect_error)
    await response.kwargs["client_close_handler_callable"]({"type": "http"})
    assert transport._client_gone.is_set()
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_create_sse_response_client_close_handler_without_callback(monkeypatch):
    """Cover on_client_close path when no disconnect callback is provided."""
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 100)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=True)

    response = await transport.create_sse_response(request, on_disconnect_callback=None)
    await response.kwargs["client_close_handler_callable"]({"type": "http"})
    assert transport._client_gone.is_set()
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_create_sse_response_keepalive_disabled_mid_loop(monkeypatch):
    """Cover branch where keepalive is disabled after timeout returns None, so no keepalive frame is yielded."""
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", True)
    monkeypatch.setattr(settings, "sse_retry_timeout", 100)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)

    async def _flip_and_return_none(_timeout):  # noqa: D401 - test stub
        settings.sse_keepalive_enabled = False
        return None

    monkeypatch.setattr(transport, "_get_message_with_timeout", _flip_and_return_none)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(side_effect=[False, True])

    response = await transport.create_sse_response(request)
    generator = response.body_iterator
    _ = await anext(generator)
    _ = await anext(generator)
    with pytest.raises(StopAsyncIteration):
        await anext(generator)


@pytest.mark.asyncio
async def test_create_sse_response_exits_when_client_gone_and_no_disconnect_callback(monkeypatch):
    """Cover while condition false at entry and skip disconnect callback in finally."""
    transport = SSETransport("http://base")
    monkeypatch.setattr(sse_transport, "EventSourceResponse", _DummyResponse)
    monkeypatch.setattr(settings, "sse_keepalive_enabled", False)
    monkeypatch.setattr(settings, "sse_retry_timeout", 100)
    monkeypatch.setattr(settings, "sse_send_timeout", 0)

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=False)

    response = await transport.create_sse_response(request, on_disconnect_callback=None)
    generator = response.body_iterator
    _ = await anext(generator)

    transport._client_gone.set()
    with pytest.raises(StopAsyncIteration):
        await anext(generator)
