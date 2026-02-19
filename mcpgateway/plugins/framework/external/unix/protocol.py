# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/unix/protocol.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Protocol helpers for length-prefixed message framing over Unix sockets.

This module provides simple, efficient message framing using a 4-byte
big-endian length prefix followed by the message payload.

Wire format: [4-byte length (big-endian)][payload bytes]

Examples:
    Writing a message:

    >>> import asyncio
    >>> from mcpgateway.plugins.framework.external.unix.protocol import write_message, read_message

    Reading and writing work as inverse operations:

    >>> # In an async context with reader/writer streams
    >>> # write_message(writer, b"hello")
    >>> # data = await read_message(reader)  # returns b"hello"
"""

# Standard
import asyncio
import struct
from typing import Optional

# 4-byte big-endian unsigned int for length prefix
LENGTH_FORMAT = ">I"
LENGTH_SIZE = 4

# Maximum message size (16 MB) to prevent memory exhaustion
MAX_MESSAGE_SIZE = 16 * 1024 * 1024


class ProtocolError(Exception):
    """Raised when a protocol-level error occurs."""


async def read_message(reader: asyncio.StreamReader, timeout: Optional[float] = None) -> bytes:
    """Read a length-prefixed message from the stream.

    Args:
        reader: The async stream reader.
        timeout: Optional timeout in seconds for the read operation.

    Returns:
        The message payload as bytes.

    Raises:
        ProtocolError: If the message is malformed or too large.
        asyncio.IncompleteReadError: If the connection is closed mid-read.
        asyncio.TimeoutError: If the read times out.

    Examples:
        >>> # In an async context
        >>> # data = await read_message(reader)
        >>> # data = await read_message(reader, timeout=5.0)
    """

    async def _read() -> bytes:
        """Read and validate a length-prefixed message from the stream.

        Returns:
            The data read from the message stream as bytes.

        Raises:
            ProtocolError: If the message is too large.

        """
        # Read 4-byte length prefix
        length_bytes = await reader.readexactly(LENGTH_SIZE)
        length = struct.unpack(LENGTH_FORMAT, length_bytes)[0]

        # Validate message size
        if length > MAX_MESSAGE_SIZE:
            raise ProtocolError(f"Message size {length} exceeds maximum {MAX_MESSAGE_SIZE}")

        if length == 0:
            return b""

        # Read the message payload
        return await reader.readexactly(length)

    if timeout is not None:
        return await asyncio.wait_for(_read(), timeout=timeout)
    return await _read()


def write_message(writer: asyncio.StreamWriter, data: bytes) -> None:
    """Write a length-prefixed message to the stream.

    This writes the message to the buffer but does not flush. Call
    `await writer.drain()` after writing to ensure delivery.

    Args:
        writer: The async stream writer.
        data: The message payload to write.

    Raises:
        ProtocolError: If the message is too large.

    Examples:
        >>> # In an async context
        >>> # write_message(writer, b"hello")
        >>> # await writer.drain()
    """
    if len(data) > MAX_MESSAGE_SIZE:
        raise ProtocolError(f"Message size {len(data)} exceeds maximum {MAX_MESSAGE_SIZE}")

    length = struct.pack(LENGTH_FORMAT, len(data))
    writer.write(length + data)


async def write_message_async(writer: asyncio.StreamWriter, data: bytes, drain: bool = True) -> None:
    """Write a length-prefixed message and optionally drain.

    Args:
        writer: The async stream writer.
        data: The message payload to write.
        drain: Whether to drain the write buffer (default True).

    Raises:
        ProtocolError: If the message is too large.

    Examples:
        >>> # In an async context
        >>> # await write_message_async(writer, b"hello")
    """
    write_message(writer, data)
    if drain:
        await writer.drain()
