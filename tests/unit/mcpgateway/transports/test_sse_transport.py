# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_sse_transport.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the MCP Gateway SSE transport implementation.
"""

# Standard
import asyncio
import json
from typing import Dict
from unittest.mock import Mock, patch

# Third-Party
from fastapi import Request
import pytest
from sse_starlette.sse import EventSourceResponse

# First-Party
from mcpgateway.transports.sse_transport import _build_sse_frame, SSETransport


def parse_sse_frame(frame: bytes) -> Dict[str, str | int]:
    """Parse an SSE frame from bytes to dict for testing.

    Args:
        frame: SSE frame as bytes

    Returns:
        Dict with 'event', 'data', and 'retry' keys
    """
    text = frame.decode("utf-8")
    result = {}
    for line in text.split("\r\n"):
        if line.startswith("event: "):
            result["event"] = line[7:]
        elif line.startswith("data: "):
            result["data"] = line[6:]
        elif line.startswith("retry: "):
            result["retry"] = int(line[7:])
    return result


class TestBuildSSEFrame:
    """Tests for the _build_sse_frame helper function."""

    def test_build_sse_frame_message(self):
        """Test SSE frame construction for message events."""
        frame = _build_sse_frame(b"message", b'{"test": 1}', 15000)
        assert frame == b'event: message\r\ndata: {"test": 1}\r\nretry: 15000\r\n\r\n'

    def test_build_sse_frame_keepalive(self):
        """Test keepalive frame construction."""
        frame = _build_sse_frame(b"keepalive", b"{}", 15000)
        assert frame == b"event: keepalive\r\ndata: {}\r\nretry: 15000\r\n\r\n"

    def test_build_sse_frame_error(self):
        """Test error frame construction."""
        frame = _build_sse_frame(b"error", b'{"error": "test"}', 5000)
        assert frame == b'event: error\r\ndata: {"error": "test"}\r\nretry: 5000\r\n\r\n'

    def test_build_sse_frame_endpoint(self):
        """Test endpoint frame construction."""
        frame = _build_sse_frame(b"endpoint", b"http://localhost:8000/message?session_id=abc123", 5000)
        parsed = parse_sse_frame(frame)
        assert parsed["event"] == "endpoint"
        assert parsed["data"] == "http://localhost:8000/message?session_id=abc123"
        assert parsed["retry"] == 5000


@pytest.fixture
def sse_transport():
    """Create an SSE transport instance."""
    return SSETransport(base_url="http://test.example")


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request with is_disconnected mocked."""
    from unittest.mock import AsyncMock

    mock = Mock(spec=Request)
    # Mock is_disconnected as an async method returning False (client connected)
    mock.is_disconnected = AsyncMock(return_value=False)
    return mock


class TestSSETransport:
    """Tests for the SSETransport class."""

    @pytest.mark.asyncio
    async def test_connect_disconnect(self, sse_transport):
        """Test connecting and disconnecting from SSE transport."""
        # Initially should not be connected
        assert await sse_transport.is_connected() is False

        # Connect
        await sse_transport.connect()
        assert await sse_transport.is_connected() is True
        assert sse_transport._connected is True

        # Disconnect
        await sse_transport.disconnect()
        assert await sse_transport.is_connected() is False
        assert sse_transport._connected is False
        assert sse_transport._client_gone.is_set()

    @pytest.mark.asyncio
    async def test_send_message(self, sse_transport):
        """Test sending a message over SSE."""
        # Connect first
        await sse_transport.connect()

        # Test message
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        # Send message
        await sse_transport.send_message(message)

        # Verify message was queued
        assert sse_transport._message_queue.qsize() == 1
        queued_message = await sse_transport._message_queue.get()
        assert queued_message == message

    @pytest.mark.asyncio
    async def test_send_message_not_connected(self, sse_transport):
        """Test sending message when not connected raises error."""
        # Don't connect
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        # Should raise error
        with pytest.raises(RuntimeError, match="Transport not connected"):
            await sse_transport.send_message(message)

    @pytest.mark.asyncio
    async def test_receive_message_not_connected(self, sse_transport):
        """receive_message should raise RuntimeError if not connected."""
        with pytest.raises(RuntimeError):
            async for _ in sse_transport.receive_message():
                pass

    @pytest.mark.asyncio
    async def test_send_message_queue_exception(self, sse_transport):
        """send_message should log and raise if queue.put fails."""
        await sse_transport.connect()
        with patch.object(sse_transport._message_queue, "put", side_effect=Exception("fail")), patch("mcpgateway.transports.sse_transport.logger") as mock_logger:
            with pytest.raises(Exception, match="fail"):
                await sse_transport.send_message({"foo": "bar"})
            assert mock_logger.error.called

    @pytest.mark.asyncio
    async def test_receive_message_cancelled(self, sse_transport):
        """Test receive_message handles CancelledError and logs."""
        await sse_transport.connect()
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError), patch("mcpgateway.transports.sse_transport.logger") as mock_logger:
            gen = sse_transport.receive_message()
            await gen.__anext__()  # initialize message
            with pytest.raises(asyncio.CancelledError):
                await gen.__anext__()
            # Check that logger.info was called with the cancel message
            assert any("SSE receive loop cancelled" in str(call) for call in [args[0] for args, _ in mock_logger.info.call_args_list])

    @pytest.mark.asyncio
    async def test_receive_message_finally_logs(self, sse_transport):
        """Test receive_message logs in finally block."""
        await sse_transport.connect()
        with patch("asyncio.sleep", side_effect=Exception("fail")), patch("mcpgateway.transports.sse_transport.logger") as mock_logger:
            gen = sse_transport.receive_message()
            await gen.__anext__()  # initialize message
            with pytest.raises(Exception):
                await gen.__anext__()
            assert any("SSE receive loop ended" in str(call) for call in mock_logger.info.call_args_list)

    @pytest.mark.asyncio
    async def test_create_sse_response(self, sse_transport, mock_request):
        """Test creating SSE response."""
        # Connect first
        await sse_transport.connect()

        # Create SSE response
        response = await sse_transport.create_sse_response(mock_request)

        # Should be an EventSourceResponse
        assert isinstance(response, EventSourceResponse)

        # Verify response headers
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers["Content-Type"] == "text/event-stream"
        assert response.headers["X-MCP-SSE"] == "true"

    @pytest.mark.asyncio
    async def test_create_sse_response_event_generator_error(self, sse_transport, mock_request):
        """Test event_generator handles consecutive errors by stopping gracefully."""
        await sse_transport.connect()
        # Patch _get_message_with_timeout to raise Exception multiple times (simulating consecutive errors)
        # After max_consecutive_errors (3), the generator should stop
        with patch.object(
            sse_transport, "_get_message_with_timeout", side_effect=[Exception("fail1"), Exception("fail2"), Exception("fail3")]
        ), patch("mcpgateway.transports.sse_transport.logger") as mock_logger:
            response = await sse_transport.create_sse_response(mock_request)
            gen = response.body_iterator
            await gen.__anext__()  # endpoint
            await gen.__anext__()  # keepalive
            # After 3 consecutive errors, the generator should stop (no error events yielded)
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
            # Verify warnings were logged for the errors
            assert mock_logger.warning.called or mock_logger.info.called

    def test_session_id_property(self, sse_transport):
        """Test session_id property returns the correct value."""
        assert sse_transport.session_id == sse_transport._session_id

    @pytest.mark.asyncio
    async def test_client_disconnected(self, sse_transport, mock_request):
        """Test _client_disconnected returns correct state."""
        assert await sse_transport._client_disconnected(mock_request) is False
        sse_transport._client_gone.set()
        assert await sse_transport._client_disconnected(mock_request) is True

    @pytest.mark.asyncio
    async def test_receive_message(self, sse_transport):
        """Test receiving messages from client."""
        # Connect first
        await sse_transport.connect()

        # Get receive generator
        receive_gen = sse_transport.receive_message()

        # Should yield initialize message first
        first_message = await receive_gen.__anext__()
        assert first_message["jsonrpc"] == "2.0"
        assert first_message["method"] == "initialize"

        # Trigger client disconnection to end the loop
        sse_transport._client_gone.set()

        # Wait for the generator to end
        with pytest.raises(StopAsyncIteration):
            # Use a timeout in case the generator doesn't end
            async def wait_with_timeout():
                await asyncio.wait_for(receive_gen.__anext__(), timeout=1.0)

            await wait_with_timeout()

    @pytest.mark.asyncio
    async def test_event_generator(self, sse_transport, mock_request):
        """Test the event generator for SSE."""
        # Connect first
        await sse_transport.connect()

        # Create SSE response
        response = await sse_transport.create_sse_response(mock_request)

        # Access the generator from the response
        generator = response.body_iterator

        # First event should be endpoint
        frame = await generator.__anext__()
        event = parse_sse_frame(frame)
        assert "event" in event
        assert event["event"] == "endpoint"
        assert sse_transport._session_id in event["data"]

        # Second event should be keepalive
        frame = await generator.__anext__()
        event = parse_sse_frame(frame)
        assert event["event"] == "keepalive"

        # Queue a test message
        test_message = {"jsonrpc": "2.0", "result": "test", "id": 1}
        await sse_transport._message_queue.put(test_message)

        # Next event should be the message
        frame = await generator.__anext__()
        event = parse_sse_frame(frame)
        assert event["event"] == "message"
        assert json.loads(event["data"]) == test_message

        # Cancel the generator to clean up
        sse_transport._client_gone.set()

    @pytest.mark.asyncio
    async def test_keepalive_disabled(self, sse_transport, mock_request):
        """Test SSE response when keepalive is disabled."""
        with patch("mcpgateway.transports.sse_transport.settings") as mock_settings:
            mock_settings.sse_keepalive_enabled = False
            mock_settings.sse_keepalive_interval = 30
            mock_settings.sse_retry_timeout = 5000
            mock_settings.sse_send_timeout = 30.0
            mock_settings.sse_rapid_yield_window_ms = 1000
            mock_settings.sse_rapid_yield_max = 50

            await sse_transport.connect()
            response = await sse_transport.create_sse_response(mock_request)
            generator = response.body_iterator

            # First event should be endpoint
            frame = await generator.__anext__()
            event = parse_sse_frame(frame)
            assert event["event"] == "endpoint"

            # No immediate keepalive should be sent
            # Queue a test message
            test_message = {"jsonrpc": "2.0", "result": "test", "id": 1}
            await sse_transport._message_queue.put(test_message)

            # Next event should be the message (no keepalive)
            frame = await generator.__anext__()
            event = parse_sse_frame(frame)
            assert event["event"] == "message"

            sse_transport._client_gone.set()

    @pytest.mark.asyncio
    async def test_keepalive_custom_interval(self, sse_transport, mock_request):
        """Test SSE response with custom keepalive interval."""
        with patch("mcpgateway.transports.sse_transport.settings") as mock_settings:
            mock_settings.sse_keepalive_enabled = True
            mock_settings.sse_keepalive_interval = 60  # Custom interval
            mock_settings.sse_retry_timeout = 5000
            mock_settings.sse_send_timeout = 30.0
            mock_settings.sse_rapid_yield_window_ms = 1000
            mock_settings.sse_rapid_yield_max = 50

            await sse_transport.connect()
            response = await sse_transport.create_sse_response(mock_request)
            generator = response.body_iterator

            # First event should be endpoint
            frame = await generator.__anext__()
            event = parse_sse_frame(frame)
            assert event["event"] == "endpoint"

            # Second event should be immediate keepalive
            frame = await generator.__anext__()
            event = parse_sse_frame(frame)
            assert event["event"] == "keepalive"
            assert event["data"] == "{}"

            sse_transport._client_gone.set()

    @pytest.mark.asyncio
    async def test_keepalive_timeout_behavior(self, sse_transport, mock_request):
        """Test timeout behavior respects keepalive settings."""
        with patch("mcpgateway.transports.sse_transport.settings") as mock_settings:
            mock_settings.sse_keepalive_enabled = True
            mock_settings.sse_keepalive_interval = 1  # 1 second for quick test
            mock_settings.sse_retry_timeout = 5000
            mock_settings.sse_send_timeout = 30.0
            mock_settings.sse_rapid_yield_window_ms = 1000
            mock_settings.sse_rapid_yield_max = 50

            await sse_transport.connect()
            response = await sse_transport.create_sse_response(mock_request)
            generator = response.body_iterator

            # Skip endpoint and initial keepalive
            await generator.__anext__()  # endpoint
            await generator.__anext__()  # initial keepalive

            # Wait for timeout keepalive (should happen after 1 second)
            frame = await asyncio.wait_for(generator.__anext__(), timeout=2.0)
            event = parse_sse_frame(frame)
            assert event["event"] == "keepalive"

            sse_transport._client_gone.set()

    @pytest.mark.asyncio
    async def test_get_message_with_timeout_returns_message(self, sse_transport):
        """Test _get_message_with_timeout returns message when available."""
        await sse_transport.connect()
        test_message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        await sse_transport._message_queue.put(test_message)

        result = await sse_transport._get_message_with_timeout(timeout=1.0)
        assert result == test_message

    @pytest.mark.asyncio
    async def test_get_message_with_timeout_returns_none_on_timeout(self, sse_transport):
        """Test _get_message_with_timeout returns None on timeout."""
        await sse_transport.connect()
        # Don't put any message in the queue

        result = await sse_transport._get_message_with_timeout(timeout=0.1)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_message_with_timeout_no_timeout(self, sse_transport):
        """Test _get_message_with_timeout with None timeout waits indefinitely."""
        await sse_transport.connect()
        test_message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        # Schedule message to be put after a small delay
        async def put_message():
            await asyncio.sleep(0.05)
            await sse_transport._message_queue.put(test_message)

        asyncio.create_task(put_message())

        result = await asyncio.wait_for(sse_transport._get_message_with_timeout(timeout=None), timeout=1.0)
        assert result == test_message


def test_anyio_cancel_delivery_patch_toggle(monkeypatch):
    from anyio._backends._asyncio import CancelScope

    import mcpgateway.transports.sse_transport as sse_transport

    # Ensure we start from the original implementation
    monkeypatch.setattr(CancelScope, "_deliver_cancellation", sse_transport._original_deliver_cancellation)
    sse_transport._patch_applied = False

    monkeypatch.setattr(sse_transport.settings, "anyio_cancel_delivery_patch_enabled", True)
    monkeypatch.setattr(sse_transport.settings, "anyio_cancel_delivery_max_iterations", 1)

    assert sse_transport.apply_anyio_cancel_delivery_patch() is True
    assert CancelScope._deliver_cancellation is not sse_transport._original_deliver_cancellation

    assert sse_transport.remove_anyio_cancel_delivery_patch() is True
    assert CancelScope._deliver_cancellation is sse_transport._original_deliver_cancellation


def test_get_sse_cleanup_timeout_fallback(monkeypatch):
    import mcpgateway.transports.sse_transport as sse_transport

    class DummySettings:
        pass

    monkeypatch.setattr(sse_transport, "settings", DummySettings())

    assert sse_transport._get_sse_cleanup_timeout() == 5.0
