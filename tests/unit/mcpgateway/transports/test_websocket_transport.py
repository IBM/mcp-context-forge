# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_websocket_transport.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for ContextForge WebSocket transport implementation.
"""

# Standard
import asyncio
import logging
from unittest.mock import Mock, AsyncMock, patch

# Third-Party
from fastapi import WebSocket, WebSocketDisconnect
import pytest

# First-Party
from mcpgateway.transports.websocket_transport import WebSocketTransport


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    mock = Mock(spec=WebSocket)
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
    async def test_connect_without_ping_task_when_interval_disabled(self, monkeypatch, websocket_transport):
        monkeypatch.setattr("mcpgateway.transports.websocket_transport.settings.websocket_ping_interval", 0)

        await websocket_transport.connect()

        assert websocket_transport._ping_task is None

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
    async def test_ping_loop_normal(self, monkeypatch):
        """Test _ping_loop with normal pong response."""
        # First-Party
        from mcpgateway.transports.websocket_transport import WebSocketTransport

        mock_ws = Mock(spec=WebSocket)
        mock_ws.receive_bytes.return_value = b"pong"
        mock_ws.send_bytes = AsyncMock()
        transport = WebSocketTransport(mock_ws)
        transport._connected = True

        # Patch settings and asyncio.sleep to run fast
        monkeypatch.setattr("mcpgateway.transports.websocket_transport.settings.websocket_ping_interval", 0.01)
        monkeypatch.setattr("asyncio.sleep", AsyncMock())

        # Run only one iteration
        async def fake_receive_bytes():
            transport._connected = False
            return b"pong"

        mock_ws.receive_bytes.side_effect = fake_receive_bytes

        await transport._ping_loop()
        mock_ws.send_bytes.assert_called_with(b"ping")

    @pytest.mark.asyncio
    async def test_ping_loop_invalid_pong(self, monkeypatch, caplog):
        """Test _ping_loop logs warning on invalid pong."""
        # First-Party
        from mcpgateway.transports.websocket_transport import WebSocketTransport

        mock_ws = Mock(spec=WebSocket)
        mock_ws.receive_bytes.return_value = b"notpong"
        mock_ws.send_bytes = AsyncMock()
        transport = WebSocketTransport(mock_ws)
        transport._connected = True

        monkeypatch.setattr("mcpgateway.transports.websocket_transport.settings.websocket_ping_interval", 0.01)
        monkeypatch.setattr("asyncio.sleep", AsyncMock())

        # Run only one iteration
        async def fake_receive_bytes():
            transport._connected = False
            return b"notpong"

        mock_ws.receive_bytes.side_effect = fake_receive_bytes

        with caplog.at_level("WARNING"):
            await transport._ping_loop()
            assert "Invalid ping response" in caplog.text

    @pytest.mark.asyncio
    async def test_ping_loop_timeout(self, monkeypatch, caplog):
        """Test _ping_loop logs warning on timeout."""
        # First-Party
        from mcpgateway.transports.websocket_transport import WebSocketTransport

        mock_ws = Mock(spec=WebSocket)
        mock_ws.send_bytes = AsyncMock()
        transport = WebSocketTransport(mock_ws)
        transport._connected = True

        monkeypatch.setattr("mcpgateway.transports.websocket_transport.settings.websocket_ping_interval", 0.01)
        monkeypatch.setattr("asyncio.sleep", AsyncMock())

        # Simulate timeout
        async def fake_wait_for(*a, **kw):
            raise asyncio.TimeoutError

        monkeypatch.setattr("asyncio.wait_for", fake_wait_for)

        with caplog.at_level("WARNING"), pytest.warns(RuntimeWarning):
            await transport._ping_loop()
            assert "Ping timeout" in caplog.text

    @pytest.mark.asyncio
    async def test_ping_loop_exception(self, monkeypatch, caplog):
        """Test _ping_loop logs error on unexpected exception."""
        # First-Party
        from mcpgateway.transports.websocket_transport import WebSocketTransport

        mock_ws = Mock(spec=WebSocket)
        mock_ws.send_bytes.side_effect = Exception("fail!")
        transport = WebSocketTransport(mock_ws)
        transport._connected = True

        monkeypatch.setattr("mcpgateway.transports.websocket_transport.settings.websocket_ping_interval", 0.01)
        monkeypatch.setattr("asyncio.sleep", AsyncMock())

        with caplog.at_level("ERROR"):
            await transport._ping_loop()
            assert "Ping loop error: fail!" in caplog.text

    @pytest.mark.asyncio
    @patch("asyncio.sleep")
    async def test_ping_loop_calls_disconnect(self, mock_sleep):
        """Test _ping_loop always calls disconnect in finally."""
        # First-Party
        from mcpgateway.transports.websocket_transport import WebSocketTransport

        mock_ws = Mock(spec=WebSocket)

        # Stop after one iteration

        async def fake_receive_bytes():
            transport._connected = False
            return b"pong"

        mock_ws.receive_bytes.side_effect = fake_receive_bytes

        transport = WebSocketTransport(mock_ws)
        transport._connected = True

        with patch.object(transport, "disconnect") as disconnect_mock:
            assert await transport.is_connected()
            await transport._ping_loop()
            assert disconnect_mock.call_count == 1

        assert mock_ws.send_bytes.call_count == 1
        assert mock_ws.receive_bytes.call_count == 1
        assert mock_sleep.call_count == 1

    @pytest.mark.asyncio
    async def test_send_message_raises_on_send_error(self, websocket_transport, mock_websocket, caplog):
        """Test send_message logs and raises on send_json error."""
        await websocket_transport.connect()
        mock_websocket.send_json.side_effect = Exception("send error")
        with caplog.at_level(logging.ERROR):
            with pytest.raises(Exception, match="send error"):
                await websocket_transport.send_message({"foo": "bar"})
        assert "Failed to send message" in caplog.text

    @pytest.mark.asyncio
    async def test_receive_message_runtime_error(self, websocket_transport):
        """Test receive_message raises if not connected."""
        with pytest.raises(RuntimeError, match="Transport not connected"):
            gen = websocket_transport.receive_message()
            await gen.__anext__()

    @pytest.mark.asyncio
    async def test_receive_message_logs_and_disconnects_on_error(self, websocket_transport, mock_websocket, caplog):
        """Test receive_message logs error and disconnects on generic error."""
        await websocket_transport.connect()
        mock_websocket.receive_json.side_effect = Exception("unexpected error")
        gen = websocket_transport.receive_message()
        with caplog.at_level(logging.ERROR):
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
        assert "Error receiving message" in caplog.text
        assert await websocket_transport.is_connected() is False

    @pytest.mark.asyncio
    async def test_send_ping_only_when_connected(self, websocket_transport, mock_websocket):
        """Test send_ping does nothing if not connected."""
        # Not connected yet
        await websocket_transport.send_ping()
        mock_websocket.send_bytes.assert_not_called()
        # Now connect
        await websocket_transport.connect()
        await websocket_transport.send_ping()
        mock_websocket.send_bytes.assert_called_with(b"ping")

    @pytest.mark.asyncio
    async def test_disconnect_returns_when_loop_closed(self, websocket_transport, monkeypatch, mock_websocket):
        class _ClosedLoop:
            def is_closed(self) -> bool:
                return True

        monkeypatch.setattr("asyncio.get_running_loop", lambda: _ClosedLoop())
        websocket_transport._connected = True

        await websocket_transport.disconnect()

        mock_websocket.close.assert_not_called()
        assert await websocket_transport.is_connected() is True

    @pytest.mark.asyncio
    async def test_disconnect_returns_when_no_running_loop(self, websocket_transport, monkeypatch, mock_websocket):
        def _raise_runtime_error():
            raise RuntimeError("no running loop")

        monkeypatch.setattr("asyncio.get_running_loop", _raise_runtime_error)
        websocket_transport._connected = True

        await websocket_transport.disconnect()

        mock_websocket.close.assert_not_called()
        assert await websocket_transport.is_connected() is True

    # @pytest.mark.asyncio
    # async def test_ping_loop(websocket_transport, mock_websocket):
    #     """Test the ping loop with valid response."""

    #     # Patch the interval before import is used
    #     with patch("mcpgateway.transports.websocket_transport.settings.websocket_ping_interval", 0.05), \
    #         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

    #         # Make the client respond with pong
    #         mock_websocket.receive_bytes.return_value = b"pong"

    #         # Call connect (this starts the ping loop internally)
    #         await websocket_transport.connect()

    #         # Wait briefly to let ping loop run (via mocked asyncio.sleep)
    #         await asyncio.sleep(0.15)

    #         # Now assert that at least one ping was sent
    #         assert mock_websocket.send_bytes.call_count >= 1
    #         mock_websocket.send_bytes.assert_called_with(b"ping")

    #         assert mock_websocket.receive_bytes.call_count >= 1

    #         # Cancel the ping task cleanly
    #         await websocket_transport.disconnect()
