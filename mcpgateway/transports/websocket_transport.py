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
from typing import Any, AsyncGenerator, Dict, Optional, TYPE_CHECKING
import uuid

# Third-Party
from fastapi import WebSocket, WebSocketDisconnect

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.transports.base import Transport

# TYPE_CHECKING import to avoid circular dependency
if TYPE_CHECKING:
    from mcpgateway.cache.session_pool_manager import SessionPoolManager

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

    def __init__(self, websocket: WebSocket, session_id: Optional[str] = None, pool_manager: Optional["SessionPoolManager"] = None, server_id: Optional[str] = None):
        """Initialize WebSocket transport.

        Args:
            websocket: FastAPI WebSocket connection
            session_id: Optional session ID for pooled sessions. If not provided, generates a new UUID.
            pool_manager: Optional SessionPoolManager for pool-aware operations
            server_id: Optional server ID for pool operations

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

            >>> # Test with provided session ID (for pooling)
            >>> pooled_id = "pooled-ws-123"
            >>> transport = WebSocketTransport(mock_ws, session_id=pooled_id)
            >>> transport.session_id
            'pooled-ws-123'
            >>> transport.is_pooled
            True
        """
        self._websocket = websocket
        self._connected = False
        self._ping_task: Optional[asyncio.Task] = None
        self._session_id = session_id or str(uuid.uuid4())
        self._is_pooled = session_id is not None
        self._pool_manager = pool_manager
        self._server_id = server_id
        self._acquired_from_pool = False

    async def connect(self, pool_manager: Optional["SessionPoolManager"] = None, server_id: Optional[str] = None) -> None:
        """Set up WebSocket connection, optionally using a pooled session.

        Args:
            pool_manager: Optional SessionPoolManager to acquire session from pool
            server_id: Optional server ID for pool operations

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
        # Update pool manager and server ID if provided
        if pool_manager:
            self._pool_manager = pool_manager
        if server_id:
            self._server_id = server_id

        # Try to acquire from pool if pool manager and server ID are available
        if self._pool_manager and self._server_id and not self._is_pooled:
            try:
                pooled_session_id = await self._pool_manager.acquire_session(self._server_id)
                if pooled_session_id:
                    self._session_id = pooled_session_id
                    self._is_pooled = True
                    self._acquired_from_pool = True
                    logger.info(f"WebSocket transport acquired pooled session: {self._session_id} for server {self._server_id}")
            except Exception as e:
                logger.warning(f"Failed to acquire pooled session, using new session: {e}")

        await self._websocket.accept()
        self._connected = True

        # Start ping task
        if settings.websocket_ping_interval > 0:
            self._ping_task = asyncio.create_task(self._ping_loop())

        logger.info(f"WebSocket transport connected: {self._session_id}")

    async def disconnect(self, pool_manager: Optional["SessionPoolManager"] = None, server_id: Optional[str] = None, healthy: bool = True, error: Optional[str] = None) -> None:
        """Clean up WebSocket connection and release session back to pool if applicable.

        Args:
            pool_manager: Optional SessionPoolManager to release session back to pool
            server_id: Optional server ID for pool operations
            healthy: Whether the session is still healthy (default: True)
            error: Optional error message if session is unhealthy

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

                # Release session back to pool if it was acquired from pool
                if self._acquired_from_pool and self._pool_manager and self._server_id:
                    try:
                        await self._pool_manager.release_session(
                            self._server_id,
                            self._session_id,
                            healthy=healthy,
                            error=error
                        )
                        logger.info(f"WebSocket transport released pooled session: {self._session_id} for server {self._server_id}")
                    except Exception as e:
                        logger.error(f"Failed to release pooled session: {e}")

                logger.info(f"WebSocket transport disconnected: {self._session_id}")

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

    @property
    def session_id(self) -> str:
        """Get the session ID for this transport.

        Returns:
            str: session_id

        Examples:
            >>> from unittest.mock import Mock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> transport = WebSocketTransport(mock_ws)
            >>> isinstance(transport.session_id, str)
            True
            >>> len(transport.session_id) > 0
            True
        """
        return self._session_id

    @property
    def is_pooled(self) -> bool:
        """Check if this transport is using a pooled session.

        Returns:
            bool: True if session is from a pool, False otherwise

        Examples:
            >>> from unittest.mock import Mock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> transport = WebSocketTransport(mock_ws)
            >>> transport.is_pooled
            False
            >>> transport_pooled = WebSocketTransport(mock_ws, session_id="pooled-123")
            >>> transport_pooled.is_pooled
            True
        """
        return self._is_pooled

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

    @classmethod
    async def create_pooled_session(
        cls,
        pool_manager: "SessionPoolManager",
        server_id: str,
        websocket: WebSocket,
        timeout: Optional[int] = None
    ) -> Optional["WebSocketTransport"]:
        """Create a new WebSocket transport using a pooled session.

        This is a factory method that creates a transport instance with a session
        acquired from the pool. If pool acquisition fails, returns None.

        Args:
            pool_manager: SessionPoolManager to acquire session from
            server_id: Server ID for pool operations
            websocket: FastAPI WebSocket connection
            timeout: Optional timeout for pool acquisition

        Returns:
            WebSocketTransport instance with pooled session, or None if acquisition fails

        Examples:
            >>> # This method requires a SessionPoolManager instance
            >>> # and cannot be easily tested in doctest environment
            >>> callable(WebSocketTransport.create_pooled_session)
            True
        """
        try:
            session_id = await pool_manager.acquire_session(server_id, timeout=timeout)
            if not session_id:
                logger.warning(f"Failed to acquire pooled session for server {server_id}")
                return None

            transport = cls(
                websocket=websocket,
                session_id=session_id,
                pool_manager=pool_manager,
                server_id=server_id
            )
            transport._acquired_from_pool = True
            logger.info(f"Created WebSocket transport with pooled session: {session_id} for server {server_id}")
            return transport
        except Exception as e:
            logger.error(f"Error creating pooled WebSocket transport: {e}")
            return None

    async def get_or_create_session(
        self,
        pool_manager: Optional["SessionPoolManager"] = None,
        server_id: Optional[str] = None
    ) -> str:
        """Get existing session ID or create a new one, with pool fallback.

        This method attempts to use a pooled session if pool_manager and server_id
        are provided. If pool acquisition fails, it falls back to the current session ID
        or generates a new one.

        Args:
            pool_manager: Optional SessionPoolManager to acquire session from pool
            server_id: Optional server ID for pool operations

        Returns:
            Session ID (either pooled or new)

        Examples:
            >>> # Test with no pool manager
            >>> from unittest.mock import Mock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> transport = WebSocketTransport(mock_ws)
            >>> import asyncio
            >>> session_id = asyncio.run(transport.get_or_create_session())
            >>> isinstance(session_id, str)
            True
            >>> len(session_id) > 0
            True
        """
        # If already have a pooled session, return it
        if self._session_id and self._is_pooled:
            return self._session_id

        # Try to acquire from pool
        if pool_manager and server_id:
            try:
                pooled_id = await pool_manager.acquire_session(server_id)
                if pooled_id:
                    self._session_id = pooled_id
                    self._is_pooled = True
                    self._acquired_from_pool = True
                    self._pool_manager = pool_manager
                    self._server_id = server_id
                    logger.info(f"Acquired pooled session: {pooled_id} for server {server_id}")
                    return pooled_id
            except Exception as e:
                logger.warning(f"Failed to acquire pooled session, using fallback: {e}")

        # Fallback to existing or new session
        if not self._session_id:
            self._session_id = str(uuid.uuid4())
            logger.info(f"Created new session: {self._session_id}")

        return self._session_id

    async def migrate_session(
        self,
        new_websocket: WebSocket,
        pool_manager: Optional["SessionPoolManager"] = None,
        server_id: Optional[str] = None
    ) -> bool:
        """Migrate this transport to a new WebSocket connection.

        This method is useful for handling reconnections while preserving the session.
        It closes the old WebSocket and migrates to the new one, optionally updating
        pool information.

        Args:
            new_websocket: New WebSocket connection to migrate to
            pool_manager: Optional updated SessionPoolManager
            server_id: Optional updated server ID

        Returns:
            True if migration successful, False otherwise

        Examples:
            >>> # Test migration with mock WebSockets
            >>> from unittest.mock import Mock, AsyncMock
            >>> old_ws = Mock(spec=WebSocket)
            >>> old_ws.close = AsyncMock()
            >>> new_ws = Mock(spec=WebSocket)
            >>> new_ws.accept = AsyncMock()
            >>> transport = WebSocketTransport(old_ws)
            >>> transport._connected = True
            >>> import asyncio
            >>> result = asyncio.run(transport.migrate_session(new_ws))
            >>> result
            True
        """
        try:
            # Close old WebSocket without releasing to pool
            old_connected = self._connected
            if old_connected:
                try:
                    await self._websocket.close()
                except Exception as e:
                    logger.warning(f"Error closing old WebSocket during migration: {e}")

            # Update to new WebSocket
            self._websocket = new_websocket

            # Update pool information if provided
            if pool_manager:
                self._pool_manager = pool_manager
            if server_id:
                self._server_id = server_id

            # Accept new connection
            await new_websocket.accept()
            self._connected = True

            # Restart ping task if needed
            if settings.websocket_ping_interval > 0:
                if self._ping_task and not self._ping_task.done():
                    self._ping_task.cancel()
                self._ping_task = asyncio.create_task(self._ping_loop())

            logger.info(f"Successfully migrated WebSocket session: {self._session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to migrate WebSocket session: {e}")
            self._connected = False
            return False

    async def check_pool_health(self) -> bool:
        """Check if the pooled session is still healthy.

        This method verifies that the transport is connected and, if using a pooled
        session, that the pool manager is still available.

        Returns:
            True if session is healthy, False otherwise

        Examples:
            >>> # Test health check for non-pooled session
            >>> from unittest.mock import Mock
            >>> mock_ws = Mock(spec=WebSocket)
            >>> transport = WebSocketTransport(mock_ws)
            >>> transport._connected = True
            >>> import asyncio
            >>> asyncio.run(transport.check_pool_health())
            True

            >>> # Test health check when disconnected
            >>> transport = WebSocketTransport(mock_ws)
            >>> asyncio.run(transport.check_pool_health())
            False
        """
        if not self._connected:
            return False

        # If using a pooled session, verify pool manager is available
        if self._is_pooled and self._acquired_from_pool:
            if not self._pool_manager or not self._server_id:
                logger.warning(f"Pooled session {self._session_id} missing pool manager or server ID")
                return False

        return True
