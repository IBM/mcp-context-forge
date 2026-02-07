# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/unix/test_protocol.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for Unix socket protocol utilities.
Tests for length-prefixed message encoding/decoding.
"""

# Standard
import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# Check if grpc/protobuf is available
try:
    # First-Party
    from mcpgateway.plugins.framework.external.unix.protocol import (
        ProtocolError,
        read_message,
        write_message,
        write_message_async,
    )
    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False
    json_format = None  # type: ignore
    Struct = None  # type: ignore

pytestmark = pytest.mark.skipif(not HAS_GRPC, reason="grpc not installed (required for protobuf)")
class TestWriteMessage:
    """Tests for write_message function."""

    def test_write_message_basic(self):
        """Test writing a basic message."""
        data = b"Hello, World!"
        mock_writer = MagicMock()
        written_data = []
        mock_writer.write = MagicMock(side_effect=lambda x: written_data.append(x))

        write_message(mock_writer, data)

        # Check that write was called
        mock_writer.write.assert_called_once()
        result = written_data[0]

        # Check length prefix (4 bytes, big-endian)
        length = struct.unpack(">I", result[:4])[0]
        assert length == len(data)

        # Check payload
        assert result[4:] == data

    def test_write_message_empty(self):
        """Test writing an empty message."""
        data = b""
        mock_writer = MagicMock()
        written_data = []
        mock_writer.write = MagicMock(side_effect=lambda x: written_data.append(x))

        write_message(mock_writer, data)

        result = written_data[0]
        length = struct.unpack(">I", result[:4])[0]
        assert length == 0
        assert result == b"\x00\x00\x00\x00"

    def test_write_message_large(self):
        """Test writing a large message."""
        data = b"x" * 100000
        mock_writer = MagicMock()
        written_data = []
        mock_writer.write = MagicMock(side_effect=lambda x: written_data.append(x))

        write_message(mock_writer, data)

        result = written_data[0]
        length = struct.unpack(">I", result[:4])[0]
        assert length == 100000
        assert result[4:] == data


class TestWriteMessageAsync:
    """Tests for write_message_async function."""

    @pytest.mark.asyncio
    async def test_write_message_async_basic(self):
        """Test async writing a basic message."""
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        data = b"Hello, World!"
        await write_message_async(mock_writer, data)

        # Verify write was called with length-prefixed message
        mock_writer.write.assert_called_once()
        written = mock_writer.write.call_args[0][0]
        length = struct.unpack(">I", written[:4])[0]
        assert length == len(data)
        assert written[4:] == data

        # Verify drain was called
        mock_writer.drain.assert_called_once()


class TestReadMessage:
    """Tests for read_message function."""

    @pytest.mark.asyncio
    async def test_read_message_basic(self):
        """Test reading a basic message."""
        data = b"Hello, World!"
        length_prefix = struct.pack(">I", len(data))

        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=[length_prefix, data])

        result = await read_message(mock_reader)

        assert result == data

    @pytest.mark.asyncio
    async def test_read_message_with_timeout(self):
        """Test reading with timeout."""
        data = b"Hello!"
        length_prefix = struct.pack(">I", len(data))

        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=[length_prefix, data])

        result = await read_message(mock_reader, timeout=5.0)

        assert result == data

    @pytest.mark.asyncio
    async def test_read_message_timeout_error(self):
        """Test read timeout raises TimeoutError."""
        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=asyncio.TimeoutError())

        with pytest.raises(asyncio.TimeoutError):
            await read_message(mock_reader, timeout=0.1)

    @pytest.mark.asyncio
    async def test_read_message_incomplete_read(self):
        """Test handling incomplete read."""
        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=asyncio.IncompleteReadError(b"", 4))

        with pytest.raises(asyncio.IncompleteReadError):
            await read_message(mock_reader)

    @pytest.mark.asyncio
    async def test_read_message_zero_length(self):
        """Test reading a zero-length message."""
        length_prefix = struct.pack(">I", 0)

        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=[length_prefix, b""])

        result = await read_message(mock_reader)

        assert result == b""

    @pytest.mark.asyncio
    async def test_read_message_large(self):
        """Test reading a large message."""
        data = b"x" * 100000
        length_prefix = struct.pack(">I", len(data))

        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=[length_prefix, data])

        result = await read_message(mock_reader)

        assert result == data
        assert len(result) == 100000


class TestProtocolError:
    """Tests for ProtocolError exception."""

    def test_protocol_error_message(self):
        """Test ProtocolError has message."""
        error = ProtocolError("Invalid message format")
        assert str(error) == "Invalid message format"

    def test_protocol_error_inheritance(self):
        """Test ProtocolError inherits from Exception."""
        error = ProtocolError("Test error")
        assert isinstance(error, Exception)


class TestRoundTrip:
    """Tests for round-trip encoding/decoding."""

    @pytest.mark.asyncio
    async def test_round_trip_basic(self):
        """Test encoding then decoding a message."""
        original_data = b"Test message for round trip"

        # Encode using mock writer to capture the output
        mock_writer = MagicMock()
        written_data = []
        mock_writer.write = MagicMock(side_effect=lambda x: written_data.append(x))
        write_message(mock_writer, original_data)
        encoded = written_data[0]

        # Create a mock reader that returns the encoded data
        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=[encoded[:4], encoded[4:]])

        # Decode
        decoded = await read_message(mock_reader)

        assert decoded == original_data

    @pytest.mark.asyncio
    async def test_round_trip_protobuf(self):
        """Test round-trip with actual protobuf message."""
        from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2

        # Create a protobuf message
        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        original_data = request.SerializeToString()

        # Encode using mock writer to capture the output
        mock_writer = MagicMock()
        written_data = []
        mock_writer.write = MagicMock(side_effect=lambda x: written_data.append(x))
        write_message(mock_writer, original_data)
        encoded = written_data[0]

        # Create a mock reader
        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=[encoded[:4], encoded[4:]])

        # Decode
        decoded = await read_message(mock_reader)

        # Parse back to protobuf
        parsed_request = plugin_service_pb2.InvokeHookRequest()
        parsed_request.ParseFromString(decoded)

        assert parsed_request.hook_type == "tool_pre_invoke"
        assert parsed_request.plugin_name == "TestPlugin"


class TestProtocolLimits:
    """Tests for protocol size limits."""

    def test_write_message_exceeds_max_size(self):
        """Test write_message raises ProtocolError for oversized messages."""
        from mcpgateway.plugins.framework.external.unix.protocol import MAX_MESSAGE_SIZE

        data = b"x" * (MAX_MESSAGE_SIZE + 1)
        mock_writer = MagicMock()

        with pytest.raises(ProtocolError, match="exceeds maximum"):
            write_message(mock_writer, data)

    @pytest.mark.asyncio
    async def test_read_message_exceeds_max_size(self):
        """Test read_message raises ProtocolError for oversized messages."""
        from mcpgateway.plugins.framework.external.unix.protocol import MAX_MESSAGE_SIZE

        # Encode a length prefix larger than MAX_MESSAGE_SIZE
        oversized_length = MAX_MESSAGE_SIZE + 1
        length_prefix = struct.pack(">I", oversized_length)

        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(return_value=length_prefix)

        with pytest.raises(ProtocolError, match="exceeds maximum"):
            await read_message(mock_reader)

    @pytest.mark.asyncio
    async def test_write_message_async_no_drain(self):
        """Test write_message_async with drain=False."""
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        data = b"Hello!"
        await write_message_async(mock_writer, data, drain=False)

        mock_writer.write.assert_called_once()
        mock_writer.drain.assert_not_called()
