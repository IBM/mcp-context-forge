# -*- coding: utf-8 -*-
"""Tests for mcpgateway.transports.sse_transport."""

# Standard
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from fastapi import Request

# First-Party
from mcpgateway.config import settings
from mcpgateway.transports import sse_transport
from mcpgateway.transports.sse_transport import SSETransport, _build_sse_frame


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
async def test_receive_message_initializes_and_closes():
    transport = SSETransport()
    await transport.connect()
    generator = transport.receive_message()
    message = await anext(generator)
    assert message == {"jsonrpc": "2.0", "method": "initialize", "id": 1}
    transport._client_gone.set()
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
