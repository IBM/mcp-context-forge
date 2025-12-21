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
import sys
from typing import Any, AsyncGenerator, Dict, Optional

# Third-Party
import orjson

# First-Party
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.transports.base import Transport

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

    def __init__(self):
        """Initialize stdio transport.

        Examples:
            >>> # Create transport instance
            >>> transport = StdioTransport()
            >>> transport._stdin_reader is None
            True
            >>> transport._stdout_writer is None
            True
            >>> transport._connected
            False
        """
        self._stdin_reader: Optional[asyncio.StreamReader] = None
        self._stdout_writer: Optional[asyncio.StreamWriter] = None
        self._connected = False

    async def connect(self) -> None:
        """Set up stdio streams.

        Examples:
            >>> # Note: This method requires actual stdio streams
            >>> # and cannot be easily tested in doctest environment
            >>> transport = StdioTransport()
            >>> # The connect method exists and is callable
            >>> callable(transport.connect)
            True
        """
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
        logger.info("stdio transport connected")

    async def disconnect(self) -> None:
        """Clean up stdio streams.

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
        logger.info("stdio transport disconnected")

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
            data = orjson.dumps(message).decode()
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
                message = orjson.loads(line.strip())
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
