# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the MCP Gateway WebSocket transport implementation.
"""

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from mcpgateway.transports.websocket_transport import WebSocketTransport


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    mock = AsyncMock(spec=WebSocket)
    mock.accept = AsyncMock()
    mock.send_json = AsyncMock()
    mock.send_bytes = AsyncMock()
    mock.receive_json = AsyncMock()
    mock.receive_bytes = AsyncMock()
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def websocket_transport(mock_websocket):
    """Create a WebSocket transport with a mock WebSocket."""
    return WebSocketTransport(websocket=mock_websocket)


class TestWebSocketTransport:
    """Tests for the WebSocketTransport class."""

    @pytest.mark.asyncio
    async def test_connect(self, websocket_transport, mock_websocket):
        """Test connecting to WebSocket transport."""
        # Initially should not be connected
        assert await websocket_transport.is_connected() is False

        # Connect
        await websocket_transport.connect()

        # Should have accepted the connection
        mock_websocket.accept.assert_called_once()
        assert await websocket_transport.is_connected() is True

    @pytest.mark.asyncio
    async def test_disconnect(self, websocket_transport, mock_websocket):
        """Test disconnecting from WebSocket transport."""
        # Connect first
        await websocket_transport.connect()
        assert await websocket_transport.is_connected() is True

        # Disconnect
        await websocket_transport.disconnect()

        # Should have closed the connection
        mock_websocket.close.assert_called_once()
        assert await websocket_transport.is_connected() is False

    @pytest.mark.asyncio
    async def test_send_message(self, websocket_transport, mock_websocket):
        """Test sending a message over WebSocket."""
        # Connect first
        await websocket_transport.connect()

        # Send message
        test_message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        await websocket_transport.send_message(test_message)

        # Should have sent the message
        mock_websocket.send_json.assert_called_once_with(test_message)

    @pytest.mark.asyncio
    async def test_send_message_not_connected(self, websocket_transport):
        """Test sending message when not connected raises error."""
        # Don't connect
        test_message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        # Should raise error
        with pytest.raises(RuntimeError, match="Transport not connected"):
            await websocket_transport.send_message(test_message)

    @pytest.mark.asyncio
    async def test_receive_message(self, websocket_transport, mock_websocket):
        """Test receiving messages from WebSocket."""
        # Connect first
        await websocket_transport.connect()

        # Set up return values
        test_messages = [
            {"jsonrpc": "2.0", "method": "test1", "id": 1},
            {"jsonrpc": "2.0", "method": "test2", "id": 2},
            WebSocketDisconnect(),  # Raise this after the second message
        ]

        mock_websocket.receive_json.side_effect = [
            test_messages[0],
            test_messages[1],
            WebSocketDisconnect(),
        ]

        # Get message generator
        receive_gen = websocket_transport.receive_message()

        # First message
        message1 = await receive_gen.__anext__()
        assert message1 == test_messages[0]

        # Second message
        message2 = await receive_gen.__anext__()
        assert message2 == test_messages[1]

        # Third should raise StopAsyncIteration due to WebSocketDisconnect
        with pytest.raises(StopAsyncIteration):
            await receive_gen.__anext__()

        # Connection should be closed
        assert await websocket_transport.is_connected() is False

    @pytest.mark.asyncio
    async def test_send_ping(self, websocket_transport, mock_websocket):
        """Test sending a ping message."""
        # Connect first
        await websocket_transport.connect()

        # Send ping
        await websocket_transport.send_ping()

        # Should have sent ping bytes
        mock_websocket.send_bytes.assert_called_once_with(b"ping")

    @pytest.mark.asyncio
    async def test_ping_loop(self, websocket_transport, mock_websocket):
        """Test the ping loop with valid response."""
        # Mock dependencies
        with patch("mcpgateway.config.settings") as mock_settings, patch("asyncio.sleep", new_callable=AsyncMock):

            # Configure settings
            mock_settings.websocket_ping_interval = 0.1  # Short interval for testing

            # Connect
            await websocket_transport.connect()

            # Mock responses to check loop behavior
            mock_websocket.receive_bytes.return_value = b"pong"

            # Start ping task
            ping_task = asyncio.create_task(websocket_transport._ping_loop())

            # Let it run a little
            await asyncio.sleep(0.2)

            # Should have sent at least one ping
            assert mock_websocket.send_bytes.call_count >= 1
            mock_websocket.send_bytes.assert_called_with(b"ping")

            # Should have received pong
            assert mock_websocket.receive_bytes.call_count >= 1

            # Cancel task to clean up
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
