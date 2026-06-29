# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/transports/stdio_adapter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Stdio transport adapter for local MCP servers.
Wraps subprocess communication via stdin/stdout.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from contextlib import suppress
import shlex
import sys
from typing import Awaitable, Callable, List, Optional

# First-Party
from mcp_reverse_proxy.base import McpServerTransport
from mcp_reverse_proxy.logging_config import LoggingService

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcp_reverse_proxy.transports.stdio_adapter")


class StdioAdapter(McpServerTransport):
    """Transport adapter for stdio-based MCP servers.

    Manages subprocess lifecycle and stdio stream communication.
    """

    def __init__(self, command: str):
        """Initialize stdio adapter.

        Args:
            command: The command to run as a subprocess.
        """
        self.command = command
        self.process: Optional[asyncio.subprocess.Process] = None
        self._stdout_reader_task: Optional[asyncio.Task[None]] = None
        self._message_handlers: List[Callable[[str], Awaitable[None]]] = []

    async def start(self) -> None:
        """Start the stdio subprocess."""
        LOGGER.info(f"Starting local MCP server: {self.command}")

        try:
            self.process = await asyncio.create_subprocess_exec(
                *shlex.split(self.command),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=sys.stderr,
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"Command not found: {self.command}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to start subprocess '{self.command}': {e}") from e

        if not self.process.stdin or not self.process.stdout:
            raise RuntimeError(f"Failed to create subprocess with stdio: {self.command}")

        self._stdout_reader_task = asyncio.create_task(self._read_stdout())
        LOGGER.info(f"Local MCP server started (PID: {self.process.pid})")

        # Give the process a moment to initialize and check if it crashes immediately
        # Use a longer delay to catch processes that fail during startup
        await asyncio.sleep(0.5)
        if self.process.returncode is not None:
            raise RuntimeError(f"Subprocess terminated immediately after start (exit code: {self.process.returncode}). " f"Command: {self.command}")

    async def stop(self) -> None:
        """Stop the stdio subprocess gracefully."""
        if not self.process:
            return

        LOGGER.info(f"Stopping local MCP server (PID: {self.process.pid})")

        if self._stdout_reader_task:
            self._stdout_reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stdout_reader_task

        # Check if process is already terminated before trying to terminate it
        if self.process.returncode is None:
            try:
                self.process.terminate()
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.process.wait(), timeout=5)

                if self.process.returncode is None:
                    LOGGER.warning("Force killing subprocess")
                    self.process.kill()
                    await self.process.wait()
            except ProcessLookupError:
                # Process already terminated, this is fine
                LOGGER.debug("Process already terminated")
        else:
            LOGGER.debug(f"Process already terminated with exit code {self.process.returncode}")

    async def send(self, message: str) -> None:
        """Send a message to the subprocess stdin."""
        if not self.process or not self.process.stdin:
            raise RuntimeError("Subprocess not running")

        # Check if process has terminated
        if self.process.returncode is not None:
            raise RuntimeError(f"Subprocess terminated with exit code {self.process.returncode}")

        LOGGER.debug(f"→ stdio: {message[:200]}...")
        try:
            self.process.stdin.write((message + "\n").encode())
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            # Process terminated while we were trying to write
            returncode = self.process.returncode if self.process else "unknown"
            raise RuntimeError(f"Subprocess stdin closed (process exit code: {returncode})") from e

    def add_message_handler(self, handler: Callable[[str], Awaitable[None]]) -> None:
        """Add a handler for messages from stdout."""
        self._message_handlers.append(handler)

    async def _read_stdout(self) -> None:
        """Read messages from subprocess stdout."""
        if not self.process or not self.process.stdout:
            return

        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break

                message = line.decode().strip()
                if not message:
                    continue

                LOGGER.debug(f"← stdio: {message[:200]}...")

                for handler in self._message_handlers:
                    try:
                        await handler(message)
                    except Exception as e:
                        LOGGER.error(f"Handler error: {e}")

        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            raise
        except Exception as e:
            LOGGER.error(f"Error reading stdout: {e}")
