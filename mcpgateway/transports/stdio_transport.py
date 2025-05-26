# -*- coding: utf-8 -*-
"""stdio Transport Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module implements stdio transport for MCP, handling
communication over standard input/output streams.
"""

import asyncio
import json
import logging
import sys
from typing import Any, AsyncGenerator, Dict, Optional

from mcpgateway.transports.base import Transport

logger = logging.getLogger(__name__)


class StdioTransport(Transport):
    """Transport implementation using stdio streams."""

    def __init__(self):
        """Initialize stdio transport."""
        self._stdin_reader: Optional[asyncio.StreamReader] = None
        self._stdout_writer: Optional[asyncio.StreamWriter] = None
        self._connected = False

    async def connect(self) -> None:
        """Set up stdio streams."""
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
        """Clean up stdio streams."""
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
        """
        return self._connected
