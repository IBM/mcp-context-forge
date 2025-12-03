# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/stdio_transport.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

stdio Transport Implementation.
This module implements standard input/output (stdio) transport for MCP Gateway, enabling
communication over stdin/stdout streams. This transport is particularly useful
for command-line tools, subprocess communication, and scenarios where processes
need to communicate via standard I/O channels.

The StdioTransport class provides asynchronous message handling with proper
JSON encoding/decoding and stream management. It follows the MCP transport
protocol for bidirectional communication between MCP clients and servers.

Key Features:
- Asynchronous stream handling with asyncio
- JSON message encoding/decoding
- Line-based message protocol
- Proper connection state management
- Error handling and logging
- Clean resource cleanup

Note:
    This transport requires access to sys.stdin and sys.stdout. In testing
    environments or when these streams are not available, the transport
    will raise RuntimeError during connection attempts.
"""

# Standard
import asyncio
import json
import sys
from typing import Any, AsyncGenerator, Dict, Optional, TYPE_CHECKING
import uuid

# First-Party
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.transports.base import Transport

# TYPE_CHECKING import to avoid circular dependency
if TYPE_CHECKING:
    from mcpgateway.cache.session_pool_manager import SessionPoolManager

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class StdioTransport(Transport):
    """Transport implementation using stdio streams.

    This transport implementation uses standard input/output streams for
    communication. It's commonly used for command-line tools and processes
    that communicate via stdin/stdout.

    Examples:
        >>> # Create a new stdio transport instance
        >>> transport = StdioTransport()
        >>> transport
        <mcpgateway.transports.stdio_transport.StdioTransport object at ...>

        >>> # Check initial connection state
        >>> import asyncio
        >>> asyncio.run(transport.is_connected())
        False

        >>> # Verify it's a proper Transport subclass
        >>> isinstance(transport, Transport)
        True
        >>> issubclass(StdioTransport, Transport)
        True

        >>> # Check that required methods exist
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

    def __init__(self, session_id: Optional[str] = None, pool_manager: Optional["SessionPoolManager"] = None, server_id: Optional[str] = None):
        """Initialize stdio transport.

        Args:
            session_id: Optional session ID for pooled sessions. If not provided, generates a new UUID.
            pool_manager: Optional SessionPoolManager for pool-aware operations
            server_id: Optional server ID for pool operations

        Examples:
            >>> # Create transport instance
            >>> transport = StdioTransport()
            >>> transport._stdin_reader is None
            True
            >>> transport._stdout_writer is None
            True
            >>> transport._connected
            False

            >>> # Test with provided session ID (for pooling)
            >>> pooled_id = "pooled-stdio-123"
            >>> transport = StdioTransport(session_id=pooled_id)
            >>> transport.session_id
            'pooled-stdio-123'
            >>> transport.is_pooled
            True
        """
        self._stdin_reader: Optional[asyncio.StreamReader] = None
        self._stdout_writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._session_id = session_id or str(uuid.uuid4())
        self._is_pooled = session_id is not None
        self._pool_manager = pool_manager
        self._server_id = server_id
        self._acquired_from_pool = False

    async def connect(self, pool_manager: Optional["SessionPoolManager"] = None, server_id: Optional[str] = None) -> None:
        """Set up stdio streams, optionally using a pooled session.

        Args:
            pool_manager: Optional SessionPoolManager to acquire session from pool
            server_id: Optional server ID for pool operations

        Examples:
            >>> # Note: This method requires actual stdio streams
            >>> # and cannot be easily tested in doctest environment
            >>> transport = StdioTransport()
            >>> # The connect method exists and is callable
            >>> callable(transport.connect)
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
                    logger.info(f"Stdio transport acquired pooled session: {self._session_id} for server {self._server_id}")
            except Exception as e:
                logger.warning(f"Failed to acquire pooled session, using new session: {e}")

        loop = asyncio.get_running_loop()

        # Set up stdin reader
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        self._stdin_reader = reader

        # Set up stdout writer
        transport, protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout)
        self._stdout_writer = asyncio.StreamWriter(transport, protocol, reader, loop)

        self._connected = True
        # Keep a stable log message expected by tests, include session id at debug level
        logger.info("stdio transport connected")
        logger.debug(f"Stdio transport session id: {self._session_id}")

    async def disconnect(self, pool_manager: Optional["SessionPoolManager"] = None, server_id: Optional[str] = None, healthy: bool = True, error: Optional[str] = None) -> None:
        """Clean up stdio streams and release session back to pool if applicable.

        Args:
            pool_manager: Optional SessionPoolManager to release session back to pool
            server_id: Optional server ID for pool operations
            healthy: Whether the session is still healthy (default: True)
            error: Optional error message if session is unhealthy

        Examples:
            >>> # Note: This method requires actual stdio streams
            >>> # and cannot be easily tested in doctest environment
            >>> transport = StdioTransport()
            >>> # The disconnect method exists and is callable
            >>> callable(transport.disconnect)
            True
        """
        if self._stdout_writer:
            self._stdout_writer.close()
            await self._stdout_writer.wait_closed()
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
                logger.info(f"Stdio transport released pooled session: {self._session_id} for server {self._server_id}")
            except Exception as e:
                logger.error(f"Failed to release pooled session: {e}")

        logger.info(f"Stdio transport disconnected: {self._session_id}")

    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send a message over stdout.

        Args:
            message: Message to send

        Raises:
            RuntimeError: If transport is not connected
            Exception: If unable to write to stdio writer

        Examples:
            >>> # Test with unconnected transport
            >>> transport = StdioTransport()
            >>> import asyncio
            >>> try:
            ...     asyncio.run(transport.send_message({"test": "message"}))
            ... except RuntimeError as e:
            ...     print("Expected error:", str(e))
            Expected error: Transport not connected

            >>> # Verify message format validation
            >>> transport = StdioTransport()
            >>> # Valid message format
            >>> valid_message = {"jsonrpc": "2.0", "method": "test", "id": 1}
            >>> isinstance(valid_message, dict)
            True
            >>> "jsonrpc" in valid_message
            True
        """
        if not self._stdout_writer:
            raise RuntimeError("Transport not connected")

        try:
            data = json.dumps(message)
            self._stdout_writer.write(f"{data}\n".encode())
            await self._stdout_writer.drain()
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            raise

    async def receive_message(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receive messages from stdin.

        Yields:
            Received messages

        Raises:
            RuntimeError: If transport is not connected

        Examples:
            >>> # Test with unconnected transport
            >>> transport = StdioTransport()
            >>> import asyncio
            >>> try:
            ...     async def test_receive():
            ...         async for msg in transport.receive_message():
            ...             pass
            ...     asyncio.run(test_receive())
            ... except RuntimeError as e:
            ...     print("Expected error:", str(e))
            Expected error: Transport not connected

            >>> # Verify generator behavior
            >>> transport = StdioTransport()
            >>> # The method returns an async generator
            >>> import inspect
            >>> inspect.isasyncgenfunction(transport.receive_message)
            True
        """
        if not self._stdin_reader:
            raise RuntimeError("Transport not connected")

        while True:
            try:
                # Read line from stdin
                line = await self._stdin_reader.readline()
                if not line:
                    break

                # Parse JSON message
                message = json.loads(line.decode().strip())
                yield message

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Failed to receive message: {e}")
                continue

    async def is_connected(self) -> bool:
        """Check if transport is connected.

        Returns:
            True if connected

        Examples:
            >>> # Test initial state
            >>> transport = StdioTransport()
            >>> import asyncio
            >>> asyncio.run(transport.is_connected())
            False

            >>> # Test after manual connection state change
            >>> transport = StdioTransport()
            >>> transport._connected = True
            >>> asyncio.run(transport.is_connected())
            True

            >>> # Test after manual disconnection
            >>> transport = StdioTransport()
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
            >>> transport = StdioTransport()
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
            >>> transport = StdioTransport()
            >>> transport.is_pooled
            False
            >>> transport_pooled = StdioTransport(session_id="pooled-123")
            >>> transport_pooled.is_pooled
            True
        """
        return self._is_pooled

    @classmethod
    async def create_pooled_session(
        cls,
        pool_manager: "SessionPoolManager",
        server_id: str,
        timeout: Optional[int] = None
    ) -> Optional["StdioTransport"]:
        """Create a new Stdio transport using a pooled session.

        This is a factory method that creates a transport instance with a session
        acquired from the pool. If pool acquisition fails, returns None.

        Args:
            pool_manager: SessionPoolManager to acquire session from
            server_id: Server ID for pool operations
            timeout: Optional timeout for pool acquisition

        Returns:
            StdioTransport instance with pooled session, or None if acquisition fails

        Examples:
            >>> # This method requires a SessionPoolManager instance
            >>> # and cannot be easily tested in doctest environment
            >>> callable(StdioTransport.create_pooled_session)
            True
        """
        try:
            session_id = await pool_manager.acquire_session(server_id, timeout=timeout)
            if not session_id:
                logger.warning(f"Failed to acquire pooled session for server {server_id}")
                return None

            transport = cls(
                session_id=session_id,
                pool_manager=pool_manager,
                server_id=server_id
            )
            transport._acquired_from_pool = True
            logger.info(f"Created Stdio transport with pooled session: {session_id} for server {server_id}")
            return transport
        except Exception as e:
            logger.error(f"Error creating pooled Stdio transport: {e}")
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
            >>> transport = StdioTransport()
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

    async def check_pool_health(self) -> bool:
        """Check if the pooled session is still healthy.

        This method verifies that the transport is connected and, if using a pooled
        session, that the pool manager is still available.

        Returns:
            True if session is healthy, False otherwise

        Examples:
            >>> # Test health check for non-pooled session
            >>> transport = StdioTransport()
            >>> transport._connected = True
            >>> import asyncio
            >>> asyncio.run(transport.check_pool_health())
            True

            >>> # Test health check when disconnected
            >>> transport = StdioTransport()
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
