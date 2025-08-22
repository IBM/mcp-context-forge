# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/websocket_transport.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

WebSocket Transport Implementation.
This module implements WebSocket transport for MCP, providing
full-duplex communication between client and server.
"""

# Standard
import asyncio
from typing import Any, AsyncGenerator, Dict, Optional

# Third-Party
from fastapi import WebSocket, WebSocketDisconnect

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.transports.base import Transport

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class WebSocketTransport(Transport):
    """Transport implementation using WebSocket.

    This transport implementation uses WebSocket for full-duplex communication
    between the MCP gateway and clients. It provides real-time bidirectional
    messaging with automatic ping/pong keepalive support.

    Examples:
        >>> # Note: WebSocket transport requires a FastAPI WebSocket object
        >>> # and cannot be easily tested in doctest environment
        >>> from unittest.mock import Mock
        >>> mock_websocket = Mock(spec=WebSocket)
        >>> transport = WebSocketTransport(mock_websocket)
        >>> transport
        <mcpgateway.transports.websocket_transport.WebSocketTransport object at ...>

        >>> # Check initial connection state
        >>> transport._connected
        False
        >>> transport._ping_task is None
        True

        >>> # Verify it's a proper Transport subclass
        >>> from mcpgateway.transports.base import Transport
        >>> isinstance(transport, Transport)
        True
        >>> issubclass(WebSocketTransport, Transport)
        True

        >>> # Verify required methods exist
        >>> hasattr(transport, 'connect')
        True
        >>> hasattr(transport, 'disconnect')
        True
        >>> hasattr(transport, 'send_message')
        True
        >>> hasattr(transport, 'receive_message')
        True
        >>> hasattr(transport, 'is_connected')
        True
    """

    def __init__(self, websocket: WebSocket):
        """Initialize WebSocket transport.

        Args:
            websocket: FastAPI WebSocket connection

        Examples:
            >>> # Test initialization with mock WebSocket
            >>> from unittest.mock import Mock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> transport = WebSocketTransport(mock_ws)
            >>> transport._websocket is mock_ws
            True
            >>> transport._connected
            False
            >>> transport._ping_task is None
            True
        """
        self._websocket = websocket
        self._connected = False
        self._ping_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Set up WebSocket connection.

        Examples:
            >>> # Test connection setup with mock WebSocket
            >>> from unittest.mock import Mock, AsyncMock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> mock_ws.accept = AsyncMock()
            >>> transport = WebSocketTransport(mock_ws)
            >>> import asyncio
            >>> asyncio.run(transport.connect())
            >>> # Note: connect() may call disconnect() in finally block during testing
            >>> # So we check that accept was called instead of connection state
            >>> mock_ws.accept.called
            True
        """
        await self._websocket.accept()
        self._connected = True

        # Start ping task
        if settings.websocket_ping_interval > 0:
            self._ping_task = asyncio.create_task(self._ping_loop())

        logger.info("WebSocket transport connected")

    async def disconnect(self) -> None:
        """Clean up WebSocket connection.

        Examples:
            >>> # Test disconnection with mock WebSocket
            >>> from unittest.mock import Mock, AsyncMock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> mock_ws.close = AsyncMock()
            >>> transport = WebSocketTransport(mock_ws)
            >>> transport._connected = True
            >>> import asyncio
            >>> asyncio.run(transport.disconnect())
            >>> transport._connected
            False
            >>> mock_ws.close.called
            True

            >>> # Test disconnection when already disconnected
            >>> transport = WebSocketTransport(mock_ws)
            >>> asyncio.run(transport.disconnect())
            >>> transport._connected
            False
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (interpreter shutdown, for example)
            return

        if loop.is_closed():
            # The loop is already closed - further asyncio calls are illegal
            return

        ping_task = getattr(self, "_ping_task", None)

        should_cancel = ping_task and not ping_task.done() and ping_task is not asyncio.current_task()  # task exists  # still running  # not *this* coroutine

        if should_cancel:
            ping_task.cancel()
            try:
                await ping_task  # allow it to exit gracefully
            except asyncio.CancelledError:
                pass

        # ────────────────────────────────────────────────────────────────
        # 3.  Close the WebSocket connection (if still open)
        # ────────────────────────────────────────────────────────────────
        if getattr(self, "_connected", False):
            try:
                await self._websocket.close()
            finally:
                self._connected = False
                logger.info("WebSocket transport disconnected")

    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send a message over WebSocket.

        Args:
            message: Message to send

        Raises:
            RuntimeError: If transport is not connected
            Exception: If unable to send json to websocket

        Examples:
            >>> # Test sending message when connected
            >>> from unittest.mock import Mock, AsyncMock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> mock_ws.send_json = AsyncMock()
            >>> transport = WebSocketTransport(mock_ws)
            >>> transport._connected = True
            >>> message = {"jsonrpc": "2.0", "method": "test", "id": 1}
            >>> import asyncio
            >>> asyncio.run(transport.send_message(message))
            >>> mock_ws.send_json.called
            True
            >>> mock_ws.send_json.call_args[0][0]
            {'jsonrpc': '2.0', 'method': 'test', 'id': 1}

            >>> # Test sending message when not connected
            >>> transport = WebSocketTransport(mock_ws)
            >>> try:
            ...     asyncio.run(transport.send_message({"test": "message"}))
            ... except RuntimeError as e:
            ...     print("Expected error:", str(e))
            Expected error: Transport not connected

            >>> # Test message format validation
            >>> transport = WebSocketTransport(mock_ws)
            >>> transport._connected = True
            >>> valid_message = {"jsonrpc": "2.0", "method": "initialize", "params": {}}
            >>> isinstance(valid_message, dict)
            True
            >>> "jsonrpc" in valid_message
            True
        """
        if not self._connected:
            raise RuntimeError("Transport not connected")

        try:
            await self._websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            raise

    async def receive_message(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receive messages from WebSocket.

        Yields:
            Received messages

        Raises:
            RuntimeError: If transport is not connected

        Examples:
            >>> # Test receive message when connected
            >>> from unittest.mock import Mock, AsyncMock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> mock_ws.receive_json = AsyncMock(return_value={"test": "message"})
            >>> transport = WebSocketTransport(mock_ws)
            >>> transport._connected = True
            >>> import asyncio
            >>> async def test_receive():
            ...     async for msg in transport.receive_message():
            ...         return msg
            ...     return None
            >>> result = asyncio.run(test_receive())
            >>> result
            {'test': 'message'}

            >>> # Test receive message when not connected
            >>> transport = WebSocketTransport(mock_ws)
            >>> try:
            ...     async def test_receive():
            ...         async for msg in transport.receive_message():
            ...             pass
            ...     asyncio.run(test_receive())
            ... except RuntimeError as e:
            ...     print("Expected error:", str(e))
            Expected error: Transport not connected

            >>> # Verify generator behavior
            >>> transport = WebSocketTransport(mock_ws)
            >>> import inspect
            >>> inspect.isasyncgenfunction(transport.receive_message)
            True
        """
        if not self._connected:
            raise RuntimeError("Transport not connected")

        try:
            while True:
                message = await self._websocket.receive_json()
                yield message

        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
            self._connected = False
        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            self._connected = False
        finally:
            await self.disconnect()

    async def is_connected(self) -> bool:
        """Check if transport is connected.

        Returns:
            True if connected

        Examples:
            >>> # Test initial state
            >>> from unittest.mock import Mock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> transport = WebSocketTransport(mock_ws)
            >>> import asyncio
            >>> asyncio.run(transport.is_connected())
            False

            >>> # Test after connection
            >>> transport = WebSocketTransport(mock_ws)
            >>> transport._connected = True
            >>> asyncio.run(transport.is_connected())
            True

            >>> # Test after disconnection
            >>> transport = WebSocketTransport(mock_ws)
            >>> transport._connected = True
            >>> transport._connected = False
            >>> asyncio.run(transport.is_connected())
            False
        """
        return self._connected

    async def _ping_loop(self) -> None:
        """Send periodic ping messages to keep connection alive.

        Examples:
            >>> # Test ping loop method exists
            >>> from unittest.mock import Mock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> transport = WebSocketTransport(mock_ws)
            >>> hasattr(transport, '_ping_loop')
            True
            >>> callable(transport._ping_loop)
            True
        """
        try:
            while self._connected:
                await asyncio.sleep(settings.websocket_ping_interval)
                await self._websocket.send_bytes(b"ping")
                try:
                    resp = await asyncio.wait_for(
                        self._websocket.receive_bytes(),
                        timeout=settings.websocket_ping_interval / 2,
                    )
                    if resp != b"pong":
                        logger.warning("Invalid ping response")
                except asyncio.TimeoutError:
                    logger.warning("Ping timeout")
                    break
        except Exception as e:
            logger.error(f"Ping loop error: {e}")
        finally:
            await self.disconnect()

    async def send_ping(self) -> None:
        """Send a manual ping message.

        Examples:
            >>> # Test manual ping when connected
            >>> from unittest.mock import Mock, AsyncMock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> mock_ws.send_bytes = AsyncMock()
            >>> transport = WebSocketTransport(mock_ws)
            >>> transport._connected = True
            >>> import asyncio
            >>> asyncio.run(transport.send_ping())
            >>> mock_ws.send_bytes.called
            True
            >>> mock_ws.send_bytes.call_args[0][0]
            b'ping'

            >>> # Test manual ping when not connected
            >>> transport = WebSocketTransport(mock_ws)
            >>> transport._connected = False
            >>> asyncio.run(transport.send_ping())
            >>> # Should not call send_bytes when not connected
            >>> mock_ws.send_bytes.call_count
            1
        """
        if self._connected:
            await self._websocket.send_bytes(b"ping")
