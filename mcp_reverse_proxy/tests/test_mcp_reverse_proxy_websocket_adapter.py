# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/tests/test_mcp_reverse_proxy_websocket_adapter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the WebSocket reverse proxy transport adapter.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import ssl
from unittest.mock import AsyncMock, Mock

# Third-Party
import pytest

# First-Party
from mcp_reverse_proxy.transports.websocket_adapter import WebSocketAdapter
import mcp_reverse_proxy.transports.websocket_adapter as websocket_adapter_mod


class FakeWebSocketConnection:
    """Async iterable WebSocket connection fake."""

    def __init__(self, messages: list[str | bytes] | None = None) -> None:
        self._messages = list(messages or [])
        self.send = AsyncMock()
        self.close = AsyncMock()

    def __aiter__(self):
        """Return self as async iterator."""
        return self

    async def __anext__(self) -> str | bytes:
        """Yield queued messages until exhausted."""
        if self._messages:
            return self._messages.pop(0)
        raise StopAsyncIteration


@pytest.mark.asyncio
async def test_connect_builds_ws_url_headers_and_receive_task(monkeypatch) -> None:
    """Connect should normalize URL, pass headers, and start the receive task."""
    connection = FakeWebSocketConnection()
    connect_mock = AsyncMock(return_value=connection)
    created_tasks: list[asyncio.Task[None]] = []
    original_create_task = asyncio.create_task

    def capture_task(coro):
        task = original_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(websocket_adapter_mod, "websockets", Mock(connect=connect_mock))
    monkeypatch.setattr(websocket_adapter_mod.asyncio, "create_task", capture_task)

    adapter = WebSocketAdapter("http://gateway.example/api", "session-1", token="token-123")

    await adapter.connect()

    connect_mock.assert_awaited_once()
    assert connect_mock.await_args.args[0] == "ws://gateway.example/reverse-proxy/ws"
    assert connect_mock.await_args.kwargs["additional_headers"] == {
        "Authorization": "Bearer token-123",
        "X-Session-ID": "session-1",
    }
    assert connect_mock.await_args.kwargs["ssl"] is None
    assert adapter._connected is True
    assert adapter._connection is connection
    assert adapter._receive_task is created_tasks[0]

    adapter._receive_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await adapter._receive_task


@pytest.mark.asyncio
async def test_connect_uses_secure_defaults_and_custom_cert(monkeypatch) -> None:
    """Secure WebSocket URLs should use an SSL context configured from the CA data."""
    connection = FakeWebSocketConnection()
    connect_mock = AsyncMock(return_value=connection)
    receive_task = asyncio.create_task(asyncio.sleep(10))
    fake_ssl_context = Mock(spec=ssl.SSLContext)
    fake_ssl_context.check_hostname = True
    fake_ssl_context.verify_mode = ssl.CERT_REQUIRED
    fake_ssl_context.load_verify_locations = Mock()  # Mock the load_verify_locations method

    # Mock load_cert_data to return test certificate data
    test_cert_data = "MOCK_CERT_DATA"
    monkeypatch.setattr(websocket_adapter_mod, "load_cert_data", lambda cert: test_cert_data)

    monkeypatch.setattr(websocket_adapter_mod, "websockets", Mock(connect=connect_mock))
    # Mock SSLContext constructor to return our fake context
    monkeypatch.setattr(websocket_adapter_mod.ssl, "SSLContext", lambda protocol: fake_ssl_context)
    monkeypatch.setattr(websocket_adapter_mod.asyncio, "create_task", Mock(return_value=receive_task))

    adapter = WebSocketAdapter("gateway.example/base", "session-1", cert="test_cert_input")

    await adapter.connect()

    # Verify load_verify_locations was called with the cert data
    fake_ssl_context.load_verify_locations.assert_called_once_with(cadata=test_cert_data)
    assert connect_mock.await_args.args[0] == "wss://gateway.example/reverse-proxy/ws"
    assert connect_mock.await_args.kwargs["ssl"] is fake_ssl_context
    assert fake_ssl_context.check_hostname is True
    assert fake_ssl_context.verify_mode == ssl.CERT_REQUIRED

    receive_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await receive_task


@pytest.mark.asyncio
async def test_connect_requires_websockets_dependency(monkeypatch) -> None:
    """Missing websockets dependency should raise ImportError."""
    monkeypatch.setattr(websocket_adapter_mod, "websockets", None)

    adapter = WebSocketAdapter("http://gateway.example", "session-1")

    with pytest.raises(ImportError, match="websockets package required"):
        await adapter.connect()


@pytest.mark.asyncio
async def test_disconnect_cancels_receive_task_and_closes_connection() -> None:
    """Disconnect should cancel receive task, close the connection, and clear state."""
    adapter = WebSocketAdapter("http://gateway.example", "session-1")
    adapter._connected = True
    adapter._connection = FakeWebSocketConnection()
    adapter._receive_task = asyncio.create_task(asyncio.sleep(10))

    await adapter.disconnect()

    assert adapter._connected is False
    assert adapter._connection is None


@pytest.mark.asyncio
async def test_send_converts_bytes_and_forwards_to_connection() -> None:
    """Send should normalize bytes to text and forward the message."""
    adapter = WebSocketAdapter("http://gateway.example", "session-1")
    connection = FakeWebSocketConnection()
    adapter._connected = True
    adapter._connection = connection

    await adapter.send(b'{"type":"heartbeat"}')

    connection.send.assert_awaited_once_with('{"type":"heartbeat"}')


@pytest.mark.asyncio
async def test_send_raises_when_not_connected() -> None:
    """Send should fail if the adapter has no active connection."""
    adapter = WebSocketAdapter("http://gateway.example", "session-1")

    with pytest.raises(RuntimeError, match="Not connected to gateway"):
        await adapter.send("message")


@pytest.mark.asyncio
async def test_is_connected_returns_flag_state() -> None:
    """Connection status should reflect the internal connected flag."""
    adapter = WebSocketAdapter("http://gateway.example", "session-1")
    adapter._connected = True
    assert await adapter.is_connected() is True

    adapter._connected = False
    assert await adapter.is_connected() is False


@pytest.mark.asyncio
async def test_receive_messages_decodes_bytes_and_notifies_handlers() -> None:
    """Receive loop should decode byte frames and forward all messages to handlers."""
    adapter = WebSocketAdapter("http://gateway.example", "session-1")
    handler = AsyncMock()
    adapter.add_message_handler(handler)
    adapter._connected = True
    adapter._connection = FakeWebSocketConnection([b'{"type":"one"}', '{"type":"two"}'])

    await adapter._receive_messages()

    handler.assert_any_await('{"type":"one"}')
    handler.assert_any_await('{"type":"two"}')
    assert handler.await_count == 2
    assert adapter._connected is False
    assert adapter._connection is None


@pytest.mark.asyncio
async def test_receive_messages_continues_when_handler_raises() -> None:
    """One failing handler should not prevent later handlers from receiving a message."""
    adapter = WebSocketAdapter("http://gateway.example", "session-1")
    failing_handler = AsyncMock(side_effect=RuntimeError("boom"))
    successful_handler = AsyncMock()
    adapter.add_message_handler(failing_handler)
    adapter.add_message_handler(successful_handler)
    adapter._connected = True
    adapter._connection = FakeWebSocketConnection(['{"type":"test"}'])

    await adapter._receive_messages()

    failing_handler.assert_awaited_once_with('{"type":"test"}')
    successful_handler.assert_awaited_once_with('{"type":"test"}')


@pytest.mark.asyncio
async def test_receive_messages_treats_connection_closed_as_clean_shutdown(monkeypatch) -> None:
    """ConnectionClosed exceptions should end the loop and clear adapter state."""

    class FakeConnectionClosed(Exception):
        """Fake connection-closed exception type."""

    class RaisingConnection:
        """Async iterator that raises the configured close exception."""

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise FakeConnectionClosed("closed")

    fake_websockets = Mock()
    fake_websockets.exceptions = Mock(ConnectionClosed=FakeConnectionClosed)
    monkeypatch.setattr(websocket_adapter_mod, "websockets", fake_websockets)

    adapter = WebSocketAdapter("http://gateway.example", "session-1")
    adapter._connected = True
    adapter._connection = RaisingConnection()

    await adapter._receive_messages()

    assert adapter._connected is False
    assert adapter._connection is None


@pytest.mark.asyncio
async def test_receive_messages_re_raises_cancelled_error() -> None:
    """Cancelled receive loops should propagate cancellation after cleanup."""

    class CancelledConnection:
        """Async iterator that raises CancelledError."""

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise asyncio.CancelledError()

    adapter = WebSocketAdapter("http://gateway.example", "session-1")
    adapter._connected = True
    adapter._connection = CancelledConnection()

    with pytest.raises(asyncio.CancelledError):
        await adapter._receive_messages()

    assert adapter._connected is False
    assert adapter._connection is None


@pytest.mark.asyncio
async def test_receive_messages_returns_immediately_without_connection() -> None:
    """Receive loop should no-op when no connection is present."""
    adapter = WebSocketAdapter("http://gateway.example", "session-1")

    await adapter._receive_messages()
