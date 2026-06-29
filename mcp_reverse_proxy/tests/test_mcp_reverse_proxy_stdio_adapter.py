# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/tests/test_mcp_reverse_proxy_stdio_adapter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the stdio reverse proxy transport adapter.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from unittest.mock import AsyncMock, Mock

# Third-Party
import pytest

# First-Party
from mcp_reverse_proxy.transports.stdio_adapter import StdioAdapter


class FakeStdout:
    """Simple stdout fake backed by queued byte lines."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        """Return the next configured line or EOF."""
        if self._lines:
            return self._lines.pop(0)
        return b""


class FakeStdin:
    """Simple stdin fake recording written bytes."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.drain = AsyncMock()

    def write(self, data: bytes) -> None:
        """Record write calls."""
        self.writes.append(data)


@pytest.mark.asyncio
async def test_start_launches_subprocess_and_starts_stdout_reader(monkeypatch) -> None:
    """Start should spawn the subprocess and create the stdout reader task."""
    stdin = FakeStdin()
    stdout = FakeStdout([])
    process = Mock()
    process.stdin = stdin
    process.stdout = stdout
    process.stderr = None
    process.pid = 1234
    process.returncode = None

    create_subprocess_mock = AsyncMock(return_value=process)
    stdout_task = asyncio.create_task(asyncio.sleep(10))
    create_task_mock = Mock(return_value=stdout_task)
    sleep_mock = AsyncMock()

    monkeypatch.setattr("mcp_reverse_proxy.transports.stdio_adapter.asyncio.create_subprocess_exec", create_subprocess_mock)
    monkeypatch.setattr("mcp_reverse_proxy.transports.stdio_adapter.asyncio.create_task", create_task_mock)
    monkeypatch.setattr("mcp_reverse_proxy.transports.stdio_adapter.asyncio.sleep", sleep_mock)

    adapter = StdioAdapter("python -m example")

    await adapter.start()

    create_subprocess_mock.assert_awaited_once()
    assert create_subprocess_mock.await_args.args[:3] == ("python", "-m", "example")
    assert adapter.process is process
    assert adapter._stdout_reader_task is create_task_mock.return_value
    sleep_mock.assert_awaited_once_with(0.5)

    stdout_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stdout_task


@pytest.mark.asyncio
async def test_start_raises_runtime_error_when_command_missing(monkeypatch) -> None:
    """Missing command errors should be wrapped in a RuntimeError."""
    create_subprocess_mock = AsyncMock(side_effect=FileNotFoundError("missing"))
    monkeypatch.setattr("mcp_reverse_proxy.transports.stdio_adapter.asyncio.create_subprocess_exec", create_subprocess_mock)

    adapter = StdioAdapter("does-not-exist")

    with pytest.raises(RuntimeError, match="Command not found: does-not-exist"):
        await adapter.start()


@pytest.mark.asyncio
async def test_start_raises_runtime_error_when_process_exits_immediately(monkeypatch) -> None:
    """Processes that die during startup should raise a clear RuntimeError."""
    process = Mock()
    process.stdin = FakeStdin()
    process.stdout = FakeStdout([])
    process.pid = 1234
    process.returncode = 7

    monkeypatch.setattr(
        "mcp_reverse_proxy.transports.stdio_adapter.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    stdout_task = asyncio.create_task(asyncio.sleep(10))
    monkeypatch.setattr("mcp_reverse_proxy.transports.stdio_adapter.asyncio.create_task", Mock(return_value=stdout_task))
    monkeypatch.setattr("mcp_reverse_proxy.transports.stdio_adapter.asyncio.sleep", AsyncMock())

    adapter = StdioAdapter("python -m crash")

    with pytest.raises(RuntimeError, match="Subprocess terminated immediately after start"):
        await adapter.start()

    stdout_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stdout_task


@pytest.mark.asyncio
async def test_stop_cancels_reader_and_terminates_running_process(monkeypatch) -> None:
    """Stop should cancel the reader task and terminate a live process."""
    adapter = StdioAdapter("python -m example")
    process = Mock()
    process.pid = 4321
    process.returncode = None
    process.wait = AsyncMock(side_effect=[None])

    reader_task = asyncio.create_task(asyncio.sleep(10))
    adapter.process = process
    adapter._stdout_reader_task = reader_task

    wait_for_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("mcp_reverse_proxy.transports.stdio_adapter.asyncio.wait_for", wait_for_mock)

    await adapter.stop()

    process.terminate.assert_called_once_with()
    wait_for_mock.assert_awaited_once()
    process.kill.assert_called_once_with()


@pytest.mark.asyncio
async def test_stop_force_kills_process_after_timeout(monkeypatch) -> None:
    """Stop should kill the process when graceful termination times out."""
    adapter = StdioAdapter("python -m example")
    process = Mock()
    process.pid = 4321
    process.returncode = None
    process.wait = AsyncMock(side_effect=[None, None])

    adapter.process = process
    adapter._stdout_reader_task = None

    async def fake_wait_for(awaitable, timeout: float):
        await awaitable
        raise asyncio.TimeoutError()

    monkeypatch.setattr("mcp_reverse_proxy.transports.stdio_adapter.asyncio.wait_for", fake_wait_for)

    await adapter.stop()

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.await_count == 2


@pytest.mark.asyncio
async def test_send_writes_newline_delimited_message_and_drains() -> None:
    """Send should write a newline-delimited message to stdin."""
    adapter = StdioAdapter("python -m example")
    stdin = FakeStdin()
    process = Mock()
    process.stdin = stdin
    process.returncode = None
    adapter.process = process

    await adapter.send('{"jsonrpc":"2.0","id":1}')

    assert stdin.writes == [b'{"jsonrpc":"2.0","id":1}\n']
    stdin.drain.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_raises_when_process_not_running() -> None:
    """Send should fail when no subprocess is available."""
    adapter = StdioAdapter("python -m example")

    with pytest.raises(RuntimeError, match="Subprocess not running"):
        await adapter.send("{}")


@pytest.mark.asyncio
async def test_send_raises_when_process_has_already_terminated() -> None:
    """Terminated processes should fail before attempting to write to stdin."""
    adapter = StdioAdapter("python -m example")
    stdin = FakeStdin()
    process = Mock()
    process.stdin = stdin
    process.returncode = 9
    adapter.process = process

    with pytest.raises(RuntimeError, match="Subprocess terminated with exit code 9"):
        await adapter.send("{}")


@pytest.mark.asyncio
async def test_send_wraps_broken_pipe_with_return_code() -> None:
    """Broken pipes during write should be surfaced as runtime errors with exit code context."""
    adapter = StdioAdapter("python -m example")
    stdin = FakeStdin()
    stdin.drain = AsyncMock(side_effect=BrokenPipeError())
    process = Mock()
    process.stdin = stdin
    process.returncode = None
    adapter.process = process

    with pytest.raises(RuntimeError, match="Subprocess stdin closed"):
        await adapter.send("{}")


@pytest.mark.asyncio
async def test_read_stdout_forwards_non_empty_messages_and_skips_blank_lines() -> None:
    """Stdout reader should ignore blank lines and forward decoded messages."""
    adapter = StdioAdapter("python -m example")
    handler = AsyncMock()
    adapter.add_message_handler(handler)

    process = Mock()
    process.stdout = FakeStdout([b'{"jsonrpc":"2.0"}\n', b"\n", b'{"jsonrpc":"2.0","id":1}\n', b""])
    adapter.process = process

    await adapter._read_stdout()

    assert handler.await_count == 2
    handler.assert_any_await('{"jsonrpc":"2.0"}')
    handler.assert_any_await('{"jsonrpc":"2.0","id":1}')


@pytest.mark.asyncio
async def test_read_stdout_continues_when_handler_raises() -> None:
    """A failing handler should not prevent later handlers from running."""
    adapter = StdioAdapter("python -m example")
    failing_handler = AsyncMock(side_effect=RuntimeError("boom"))
    successful_handler = AsyncMock()
    adapter.add_message_handler(failing_handler)
    adapter.add_message_handler(successful_handler)

    process = Mock()
    process.stdout = FakeStdout([b'{"jsonrpc":"2.0"}\n', b""])
    adapter.process = process

    await adapter._read_stdout()

    failing_handler.assert_awaited_once_with('{"jsonrpc":"2.0"}')
    successful_handler.assert_awaited_once_with('{"jsonrpc":"2.0"}')


@pytest.mark.asyncio
async def test_read_stdout_returns_immediately_without_stdout() -> None:
    """Reader should no-op when process stdout is unavailable."""
    adapter = StdioAdapter("python -m example")
    adapter.process = Mock(stdout=None)

    await adapter._read_stdout()
