# -*- coding: utf-8 -*-
"""
Unit-tests for `mcpgateway.transports.stdio_transport.StdioTransport`.

The real transport interacts with the running event-loop and the
process's stdin / stdout file-descriptors.  Those OS objects are tricky
to mock portably, so these tests **inject in-memory fakes** in place of
`StreamReader` and `StreamWriter`.  That lets us assert the transport's
logic (JSON encoding/decoding, connection state, error handling) without
ever touching real pipes.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

from __future__ import annotations

import asyncio
import json
from typing import List

import pytest

from mcpgateway.transports.stdio_transport import StdioTransport


# ---------------------------------------------------------------------------
# Simple in-memory stand-ins for asyncio streams
# ---------------------------------------------------------------------------


class _DummyWriter:
    """Enough of the `StreamWriter` interface for our tests."""

    def __init__(self):
        self.buffer: List[bytes] = []
        self.drain_called = False
        self.closed = False

    def write(self, data: bytes) -> None:  # noqa: D401
        self.buffer.append(data)

    async def drain(self) -> None:  # noqa: D401
        self.drain_called = True

    def close(self) -> None:  # noqa: D401
        self.closed = True

    async def wait_closed(self) -> None:  # noqa: D401
        return


class _DummyReader:
    """Yield bytes from an internal list each time `.readline()` is awaited."""

    def __init__(self, lines: list[str]):
        self._lines = [l.encode() + b"\n" for l in lines]

    async def readline(self) -> bytes:  # noqa: D401
        await asyncio.sleep(0)           # let the event-loop breathe
        return self._lines.pop(0) if self._lines else b""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def transport():
    """Provide an *unconnected* StdioTransport for each test."""
    return StdioTransport()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_happy_path(transport):
    """
    `send_message()` should JSON-encode + newline-terminate the dict,
    push it to the writer, and await `drain()`.
    """
    writer = _DummyWriter()
    transport._stdout_writer = writer          # type: ignore[attr-defined]
    transport._connected = True               # type: ignore[attr-defined]

    payload = {"key": "value", "n": 123}
    await transport.send_message(payload)

    assert writer.drain_called is True
    assert len(writer.buffer) == 1
    raw = writer.buffer[0]
    # newline-terminated and round-trips through json
    assert raw.endswith(b"\n")
    assert json.loads(raw.decode().rstrip("\n")) == payload


@pytest.mark.asyncio
async def test_send_message_not_connected_raises(transport):
    """Calling `send_message()` without a writer should raise RuntimeError."""
    with pytest.raises(RuntimeError):
        await transport.send_message({"oops": 1})


@pytest.mark.asyncio
async def test_receive_message_decodes_until_eof(transport):
    reader = _DummyReader(['{"a":1}', '{"b":2}'])   # two JSON lines then EOF
    transport._stdin_reader = reader                # type: ignore[attr-defined]
    transport._connected = True                     # type: ignore[attr-defined]

    messages = [m async for m in transport.receive_message()]

    assert messages == [{"a": 1}, {"b": 2}]


@pytest.mark.asyncio
async def test_receive_message_not_connected_raises(transport):
    with pytest.raises(RuntimeError):
        async for _ in transport.receive_message():  # pragma: no cover
            pass


@pytest.mark.asyncio
async def test_disconnect_closes_writer_and_flags_state(transport):
    writer = _DummyWriter()
    transport._stdout_writer = writer               # type: ignore[attr-defined]
    transport._connected = True                     # type: ignore[attr-defined]

    await transport.disconnect()

    assert writer.closed is True
    assert await transport.is_connected() is False


@pytest.mark.asyncio
async def test_is_connected_reports_state(transport):
    transport._connected = False                    # type: ignore[attr-defined]
    assert await transport.is_connected() is False
    transport._connected = True                     # type: ignore[attr-defined]
    assert await transport.is_connected() is True
