# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the MCP Gateway SSE transport implementation.

"""

# Standard
import asyncio
import json
import types
from unittest.mock import Mock, AsyncMock, patch

# First-Party
from mcpgateway.transports.sse_transport import SSETransport

# Third-Party
from fastapi import Request
import pytest
from sse_starlette.sse import EventSourceResponse


@pytest.fixture
def sse_transport():
    """Create an SSE transport instance."""
    return SSETransport(base_url="http://test.example")


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request."""
    mock = Mock(spec=Request)
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
        with patch.object(sse_transport._message_queue, "put", side_effect=Exception("fail")), \
            patch("mcpgateway.transports.sse_transport.logger") as mock_logger:
            with pytest.raises(Exception, match="fail"):
                await sse_transport.send_message({"foo": "bar"})
            assert mock_logger.error.called

    @pytest.mark.asyncio
    async def test_receive_message_cancelled(self, sse_transport):
        """Test receive_message handles CancelledError and logs."""
        await sse_transport.connect()
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError), \
            patch("mcpgateway.transports.sse_transport.logger") as mock_logger:
            gen = sse_transport.receive_message()
            await gen.__anext__()  # initialize message
            with pytest.raises(asyncio.CancelledError):
                await gen.__anext__()
            # Check that logger.info was called with the cancel message
            assert any(
                "SSE receive loop cancelled" in str(call)
                for call in [args[0] for args, _ in mock_logger.info.call_args_list]
            )
    @pytest.mark.asyncio
    async def test_receive_message_finally_logs(self, sse_transport):
        """Test receive_message logs in finally block."""
        await sse_transport.connect()
        with patch("asyncio.sleep", side_effect=Exception("fail")), \
            patch("mcpgateway.transports.sse_transport.logger") as mock_logger:
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
        """Test event_generator handles generic Exception and CancelledError."""
        await sse_transport.connect()
        # Patch _message_queue.get to raise Exception, then CancelledError
        with patch.object(sse_transport._message_queue, "get", side_effect=[Exception("fail"), asyncio.CancelledError()]), \
             patch("mcpgateway.transports.sse_transport.logger") as mock_logger:
            response = await sse_transport.create_sse_response(mock_request)
            gen = response.body_iterator
            await gen.__anext__()  # endpoint
            await gen.__anext__()  # keepalive
            # Should yield error event
            event = await gen.__anext__()
            assert event["event"] == "error"
            assert "fail" in event["data"]
            # Should handle CancelledError gracefully and stop
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
            assert mock_logger.error.called or mock_logger.info.called
            
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
        event = await generator.__anext__()
        assert "event" in event
        assert event["event"] == "endpoint"
        assert sse_transport._session_id in event["data"]

        # Second event should be keepalive
        event = await generator.__anext__()
        assert event["event"] == "keepalive"

        # Queue a test message
        test_message = {"jsonrpc": "2.0", "result": "test", "id": 1}
        await sse_transport._message_queue.put(test_message)

        # Next event should be the message
        event = await generator.__anext__()
        assert event["event"] == "message"
        assert json.loads(event["data"]) == test_message

        # Cancel the generator to clean up
        sse_transport._client_gone.set()
