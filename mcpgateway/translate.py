# -*- coding: utf-8 -*-

'''Location: ./mcpgateway/translate.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Manav Gupta

r"""Bridges between different MCP transport protocols.
This module provides bidirectional bridging between MCP servers that communicate
via different transport protocols: stdio/JSON-RPC, HTTP/SSE, and streamable HTTP.
It enables exposing local MCP servers over HTTP or consuming remote endpoints
as local stdio servers.

The bridge supports multiple modes of operation:
- stdio to SSE: Expose a local stdio MCP server over HTTP/SSE
- SSE to stdio: Bridge a remote SSE endpoint to local stdio
- stdio to streamable HTTP: Expose a local stdio MCP server via streamable HTTP
- streamable HTTP to stdio: Bridge a remote streamable HTTP endpoint to local stdio

Examples:
    Programmatic usage:

    >>> import asyncio
    >>> from mcpgateway.translate import start_stdio
    >>> asyncio.run(start_stdio("uvx mcp-server-git", 9000, "info", None, "127.0.0.1"))  # doctest: +SKIP

    Test imports and configuration:

    >>> from mcpgateway.translate import MCPServer, StreamableHTTPSessionManager
    >>> isinstance(MCPServer, type)
    True
    >>> isinstance(StreamableHTTPSessionManager, type)
    True
    >>> from mcpgateway.translate import KEEP_ALIVE_INTERVAL
    >>> KEEP_ALIVE_INTERVAL > 0
    True
    >>> from mcpgateway.translate import DEFAULT_KEEPALIVE_ENABLED
    >>> isinstance(DEFAULT_KEEPALIVE_ENABLED, bool)
    True

    Test Starlette imports:

    >>> from mcpgateway.translate import Starlette, Route
    >>> isinstance(Starlette, type)
    True
    >>> isinstance(Route, type)
    True

    Test logging setup:

    >>> from mcpgateway.translate import LOGGER, logging_service
    >>> LOGGER is not None
    True
    >>> logging_service is not None
    True
    >>> hasattr(LOGGER, 'info')
    True
    >>> hasattr(LOGGER, 'error')
    True
    >>> hasattr(LOGGER, 'debug')
    True

    Test utility classes:

    >>> from mcpgateway.translate import _PubSub, StdIOEndpoint
    >>> pubsub = _PubSub()
    >>> hasattr(pubsub, 'publish')
    True
    >>> hasattr(pubsub, 'subscribe')
    True
    >>> hasattr(pubsub, 'unsubscribe')
    True

Usage:
    Command line usage::

        # 1. Expose an MCP server that talks JSON-RPC on stdio at :9000/sse
        python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000

        # 2. Bridge a remote SSE endpoint to local stdio
        python3 -m mcpgateway.translate --sse "https://example.com/sse" \
                --stdioCommand "uvx mcp-client"

        # 3. Expose stdio server via streamable HTTP at :9000/mcp
        python3 -m mcpgateway.translate --streamableHttp "uvx mcp-server-git" \
                --port 9000 --stateless --jsonResponse

        # 4. Connect to remote streamable HTTP endpoint
        python3 -m mcpgateway.translate \
                --streamableHttp "https://example.com/mcp" \
                --oauth2Bearer "your-token"

        # 5. Test SSE endpoint
        curl -N http://localhost:9000/sse          # receive the stream

        # 6. Send a test echo request to SSE endpoint
        curl -X POST http://localhost:9000/message \
             -H 'Content-Type: application/json'   \
             -d '{"jsonrpc":"2.0","id":1,"method":"echo","params":{"value":"hi"}}'

        # 7. Test streamable HTTP endpoint
        curl -X POST http://localhost:9000/mcp \
             -H 'Content-Type: application/json' \
             -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"demo","version":"0.0.1"}}}'

    The SSE stream emits JSON-RPC responses as ``event: message`` frames and sends
    regular ``event: keepalive`` frames (default every 30s) to prevent timeouts.

    Streamable HTTP supports both stateful (with session management) and stateless
    modes, and can return either JSON responses or SSE streams.
"""
'''

# Future
from __future__ import annotations

# Standard
import argparse
import asyncio
from contextlib import suppress
import logging
import os
import shlex
import signal
import sys
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlencode
import uuid

# Third-Party
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from mcp.server import Server as MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
import orjson
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send
import uvicorn

try:
    # Third-Party
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

# First-Party
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.translate_header_utils import extract_env_vars_from_headers, NormalizedMappings, parse_header_mappings
from mcpgateway.utils.orjson_response import ORJSONResponse

# Initialize logging service first
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.translate")
CONTENT_TYPE = os.getenv("FORGE_CONTENT_TYPE", "application/json")
# headers = {"Content-Type": CONTENT_TYPE}
# Import settings for default keepalive interval
try:
    # First-Party
    from mcpgateway.config import settings

    DEFAULT_KEEP_ALIVE_INTERVAL = settings.sse_keepalive_interval
    DEFAULT_KEEPALIVE_ENABLED = settings.sse_keepalive_enabled
    DEFAULT_SSL_VERIFY = not settings.skip_ssl_verify
except ImportError:
    # Fallback if config not available
    DEFAULT_KEEP_ALIVE_INTERVAL = 30
    DEFAULT_KEEPALIVE_ENABLED = True
    DEFAULT_SSL_VERIFY = True  # Verify SSL by default when config unavailable

KEEP_ALIVE_INTERVAL = DEFAULT_KEEP_ALIVE_INTERVAL  # seconds - from config or fallback to 30
__all__ = ["main"]  # for console-script entry-point


# ---------------------------------------------------------------------------#
# Helpers - trivial in-process Pub/Sub                                       #
# ---------------------------------------------------------------------------#
class _PubSub:
    """Very small fan-out helper - one async Queue per subscriber.

    This class implements a simple publish-subscribe pattern using asyncio queues
    for distributing messages from stdio subprocess to multiple SSE clients.

    Examples:
        >>> import asyncio
        >>> async def test_pubsub():
        ...     pubsub = _PubSub()
        ...     q = pubsub.subscribe()
        ...     await pubsub.publish("hello")
        ...     result = await q.get()
        ...     pubsub.unsubscribe(q)
        ...     return result
        >>> asyncio.run(test_pubsub())
        'hello'
    """

    def __init__(self) -> None:
        """Initialize a new publish-subscribe system.

        Creates an empty list of subscriber queues. Each subscriber will
        receive their own asyncio.Queue for receiving published messages.

        Examples:
            >>> pubsub = _PubSub()
            >>> isinstance(pubsub._subscribers, list)
            True
            >>> len(pubsub._subscribers)
            0
            >>> hasattr(pubsub, '_subscribers')
            True
        """
        self._subscribers: List[asyncio.Queue[str]] = []

    async def publish(self, data: str) -> None:
        """Publish data to all subscribers.

        Dead queues (full) are automatically removed from the subscriber list.

        Args:
            data: The data string to publish to all subscribers.

        Examples:
            >>> import asyncio
            >>> async def test_publish():
            ...     pubsub = _PubSub()
            ...     await pubsub.publish("test")  # No subscribers, no error
            ...     return True
            >>> asyncio.run(test_publish())
            True

            >>> # Test queue full handling
            >>> async def test_full_queue():
            ...     pubsub = _PubSub()
            ...     # Create a queue with size 1
            ...     q = asyncio.Queue(maxsize=1)
            ...     pubsub._subscribers = [q]
            ...     # Fill the queue
            ...     await q.put("first")
            ...     # This should remove the full queue
            ...     await pubsub.publish("second")
            ...     return len(pubsub._subscribers)
            >>> asyncio.run(test_full_queue())
            0
        """
        dead: List[asyncio.Queue[str]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            with suppress(ValueError):
                self._subscribers.remove(q)

    def subscribe(self) -> "asyncio.Queue[str]":
        """Subscribe to published data.

        Creates a new queue for receiving published messages with a maximum
        size of 1024 items.

        Returns:
            asyncio.Queue[str]: A queue that will receive published data.

        Examples:
            >>> pubsub = _PubSub()
            >>> q = pubsub.subscribe()
            >>> isinstance(q, asyncio.Queue)
            True
            >>> q.maxsize
            1024
            >>> len(pubsub._subscribers)
            1
            >>> pubsub._subscribers[0] is q
            True
        """
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=1024)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue[str]") -> None:
        """Unsubscribe from published data.

        Removes the queue from the subscriber list. Safe to call even if
        the queue is not in the list.

        Args:
            q: The queue to unsubscribe from published data.

        Examples:
            >>> pubsub = _PubSub()
            >>> q = pubsub.subscribe()
            >>> pubsub.unsubscribe(q)
            >>> pubsub.unsubscribe(q)  # No error on double unsubscribe
        """
        with suppress(ValueError):
            self._subscribers.remove(q)


# ---------------------------------------------------------------------------#
# StdIO endpoint (child process ↔ async queues)                              #
# ---------------------------------------------------------------------------#
class StdIOEndpoint:
    """Wrap a child process whose stdin/stdout speak line-delimited JSON-RPC.

    This class manages a subprocess that communicates via stdio using JSON-RPC
    protocol, pumping messages between the subprocess and a pubsub system.

    Examples:
        >>> import asyncio
        >>> async def test_stdio():
        ...     pubsub = _PubSub()
        ...     stdio = StdIOEndpoint("echo hello", pubsub)
        ...     # Would start a real subprocess
        ...     return isinstance(stdio, StdIOEndpoint)
        >>> asyncio.run(test_stdio())
        True
    """

    def __init__(self, cmd: str, pubsub: _PubSub, env_vars: Optional[Dict[str, str]] = None, header_mappings: Optional[NormalizedMappings] = None) -> None:
        """Initialize a stdio endpoint for subprocess communication.

        Sets up the endpoint with the command to run and the pubsub system
        for message distribution. The subprocess is not started until start()
        is called.

        Args:
            cmd: The command string to execute as a subprocess.
            pubsub: The publish-subscribe system for distributing subprocess
                output to SSE clients.
            env_vars: Optional dictionary of environment variables to set
                when starting the subprocess.
            header_mappings: Optional mapping of HTTP headers to environment variable names
                for dynamic environment injection.

        Examples:
            >>> pubsub = _PubSub()
            >>> endpoint = StdIOEndpoint("echo hello", pubsub)
            >>> endpoint._cmd
            'echo hello'
            >>> endpoint._proc is None
            True
            >>> isinstance(endpoint._pubsub, _PubSub)
            True
            >>> endpoint._stdin is None
            True
            >>> endpoint._pump_task is None
            True
            >>> endpoint._pubsub is pubsub
            True
        """
        self._cmd = cmd
        self._pubsub = pubsub
        self._env_vars = env_vars or {}
        self._header_mappings = header_mappings
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._stdin: Optional[asyncio.StreamWriter] = None
        self._pump_task: Optional[asyncio.Task[None]] = None

    async def start(self, additional_env_vars: Optional[Dict[str, str]] = None) -> None:
        """Start the stdio subprocess with custom environment variables.

        Creates the subprocess and starts the stdout pump task. The subprocess
        is created with stdin/stdout pipes and stderr passed through.

        Args:
            additional_env_vars: Optional dictionary of additional environment
                variables to set when starting the subprocess. These will be
                combined with the environment variables set during initialization.

        Raises:
            RuntimeError: If the subprocess fails to create stdin/stdout pipes.

        Examples:
            >>> import asyncio # doctest: +SKIP
            >>> async def test_start(): # doctest: +SKIP
            ...     pubsub = _PubSub()
            ...     stdio = StdIOEndpoint("cat", pubsub)
            ...     # await stdio.start()  # doctest: +SKIP
            ...     return True
            >>> asyncio.run(test_start()) # doctest: +SKIP
            True
        """
        # Stop existing subprocess before starting a new one
        if self._proc is not None:
            await self.stop()

        LOGGER.info(f"Starting stdio subprocess: {self._cmd}")

        # Build environment from base + configured + additional
        env = os.environ.copy()
        env.update(self._env_vars)
        if additional_env_vars:
            env.update(additional_env_vars)

        # System-critical environment variables that must never be cleared
        system_critical_vars = {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "PYTHONHOME", "PYTHONPATH"}

        # Clear any mapped env vars that weren't provided in headers to avoid inheritance
        if self._header_mappings:
            for env_var_name in self._header_mappings.values():
                if env_var_name not in (additional_env_vars or {}) and env_var_name not in system_critical_vars:
                    # Delete the variable instead of setting to empty string to avoid
                    # breaking subprocess initialization
                    env.pop(env_var_name, None)

        LOGGER.debug(f"Subprocess environment variables: {list(env.keys())}")
        self._proc = await asyncio.create_subprocess_exec(
            *shlex.split(self._cmd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=sys.stderr,  # passthrough for visibility
            env=env,  # 🔑 Add environment variable support
        )

        # Explicit error checking
        if not self._proc.stdin or not self._proc.stdout:
            raise RuntimeError(f"Failed to create subprocess with stdin/stdout pipes for command: {self._cmd}")

        LOGGER.debug("Subprocess started successfully")

        self._stdin = self._proc.stdin
        self._pump_task = asyncio.create_task(self._pump_stdout())

    async def stop(self) -> None:
        """Stop the stdio subprocess.

        Terminates the subprocess gracefully with a 5-second timeout,
        then cancels the pump task.

        Examples:
            >>> import asyncio
            >>> async def test_stop():
            ...     pubsub = _PubSub()
            ...     stdio = StdIOEndpoint("cat", pubsub)
            ...     await stdio.stop()  # Safe to call even if not started
            ...     return True
            >>> asyncio.run(test_stop())
            True
        """
        if self._proc is None:
            return

        # Check if process is still running
        try:
            if self._proc.returncode is not None:
                # Process already terminated
                LOGGER.info(f"Subprocess (pid={self._proc.pid}) already terminated")
                self._proc = None
                self._stdin = None
                return
        except (ProcessLookupError, AttributeError):
            # Process doesn't exist or is already cleaned up
            LOGGER.info("Subprocess already cleaned up")
            self._proc = None
            self._stdin = None
            return

        LOGGER.info(f"Stopping subprocess (pid={self._proc.pid})")
        try:
            self._proc.terminate()
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._proc.wait(), timeout=5)
        except ProcessLookupError:
            # Process already terminated
            LOGGER.info("Subprocess already terminated")
        finally:
            if self._pump_task:
                self._pump_task.cancel()
                # Wait for pump task to actually finish, suppressing all exceptions
                # since the pump task logs its own errors. Use BaseException to catch
                # CancelledError which inherits from BaseException in Python 3.8+
                with suppress(BaseException):
                    await self._pump_task
            self._proc = None
            self._stdin = None  # Reset stdin too!

    def is_running(self) -> bool:
        """Check if the stdio subprocess is currently running.

        Returns:
            True if the subprocess is running, False otherwise.

        Examples:
            >>> import asyncio
            >>> async def test_is_running():
            ...     pubsub = _PubSub()
            ...     stdio = StdIOEndpoint("cat", pubsub)
            ...     return stdio.is_running()
            >>> asyncio.run(test_is_running())
            False
        """
        return self._proc is not None

    async def send(self, raw: str) -> None:
        """Send data to the subprocess stdin.

        Args:
            raw: The raw data string to send to the subprocess.

        Raises:
            RuntimeError: If the stdio endpoint is not started.

        Examples:
            >>> import asyncio
            >>> async def test_send():
            ...     pubsub = _PubSub()
            ...     stdio = StdIOEndpoint("cat", pubsub)
            ...     try:
            ...         await stdio.send("test")
            ...     except RuntimeError as e:
            ...         return str(e)
            >>> asyncio.run(test_send())
            'stdio endpoint not started'
        """
        if not self._stdin:
            raise RuntimeError("stdio endpoint not started")
        LOGGER.debug(f"→ stdio: {raw.strip()}")
        self._stdin.write(raw.encode())
        await self._stdin.drain()

    async def _pump_stdout(self) -> None:
        """Pump stdout from subprocess to pubsub.

        Continuously reads lines from the subprocess stdout and publishes them
        to the pubsub system. Runs until EOF or exception.

        Raises:
            RuntimeError: If process or stdout is not properly initialized.
            Exception: For any other error encountered while pumping stdout.
        """
        if not self._proc or not self._proc.stdout:
            raise RuntimeError("Process not properly initialized: missing stdout")

        reader = self._proc.stdout
        try:
            while True:
                line = await reader.readline()
                if not line:  # EOF
                    break
                text = line.decode(errors="replace")
                LOGGER.debug(f"← stdio: {text.strip()}")
                await self._pubsub.publish(text)
        except ConnectionResetError:  # pragma: no cover --subprocess terminated
            # Subprocess terminated abruptly - this is expected behavior
            LOGGER.debug("stdout pump: subprocess connection closed")
        except Exception:  # pragma: no cover --best-effort logging
            LOGGER.exception("stdout pump crashed - terminating bridge")
            raise


# ---------------------------------------------------------------------------#
# SSE Event Parser                                                           #
# ---------------------------------------------------------------------------#
class SSEEvent:
    """Represents a Server-Sent Event with proper field parsing.

    Attributes:
        event: The event type (e.g., 'message', 'keepalive', 'endpoint')
        data: The event data payload
        event_id: Optional event ID
        retry: Optional retry interval in milliseconds
    """

    def __init__(self, event: str = "message", data: str = "", event_id: Optional[str] = None, retry: Optional[int] = None):
        """Initialize an SSE event.

        Args:
            event: Event type, defaults to "message"
            data: Event data payload
            event_id: Optional event ID
            retry: Optional retry interval in milliseconds
        """
        self.event = event
        self.data = data
        self.event_id = event_id
        self.retry = retry

    @classmethod
    def parse_sse_line(cls, line: str, current_event: Optional["SSEEvent"] = None) -> Tuple[Optional["SSEEvent"], bool]:
        """Parse a single SSE line and update or create an event.

        Args:
            line: The SSE line to parse
            current_event: The current event being built (if any)

        Returns:
            Tuple of (event, is_complete) where event is the SSEEvent object
            and is_complete indicates if the event is ready to be processed
        """
        line = line.rstrip("\n\r")

        # Empty line signals end of event
        if not line:
            if current_event and current_event.data:
                return current_event, True
            return None, False

        # Comment line
        if line.startswith(":"):
            return current_event, False

        # Parse field
        if ":" in line:
            field, value = line.split(":", 1)
            value = value.lstrip(" ")  # Remove leading space if present
        else:
            field = line
            value = ""

        # Create event if needed
        if current_event is None:
            current_event = cls()

        # Update fields
        if field == "event":
            current_event.event = value
        elif field == "data":
            if current_event.data:
                current_event.data += "\n" + value
            else:
                current_event.data = value
        elif field == "id":
            current_event.event_id = value
        elif field == "retry":
            try:
                current_event.retry = int(value)
            except ValueError:
                pass  # Ignore invalid retry values

        return current_event, False


# ---------------------------------------------------------------------------#
# FastAPI app exposing /sse  &  /message                                     #
# ---------------------------------------------------------------------------#


def _build_fastapi(
    pubsub: _PubSub,
    stdio: StdIOEndpoint,
    keep_alive: float = KEEP_ALIVE_INTERVAL,
    sse_path: str = "/sse",
    message_path: str = "/message",
    cors_origins: Optional[List[str]] = None,
    header_mappings: Optional[NormalizedMappings] = None,
) -> FastAPI:
    """Build FastAPI application with SSE and message endpoints.

    Creates a FastAPI app with SSE streaming endpoint and message posting
    endpoint for bidirectional communication with the stdio subprocess.

    Args:
        pubsub: The publish/subscribe system for message routing.
        stdio: The stdio endpoint for subprocess communication.
        keep_alive: Interval in seconds for keepalive messages. Defaults to KEEP_ALIVE_INTERVAL.
        sse_path: Path for the SSE endpoint. Defaults to "/sse".
        message_path: Path for the message endpoint. Defaults to "/message".
        cors_origins: Optional list of CORS allowed origins.
        header_mappings: Optional mapping of HTTP headers to environment variables.

    Returns:
        FastAPI: The configured FastAPI application.

    Examples:
        >>> pubsub = _PubSub()
        >>> stdio = StdIOEndpoint("cat", pubsub)
        >>> app = _build_fastapi(pubsub, stdio)
        >>> isinstance(app, FastAPI)
        True
        >>> "/sse" in [r.path for r in app.routes]
        True
        >>> "/message" in [r.path for r in app.routes]
        True
        >>> "/healthz" in [r.path for r in app.routes]
        True

        >>> # Test with custom paths
        >>> app2 = _build_fastapi(pubsub, stdio, sse_path="/events", message_path="/send")
        >>> "/events" in [r.path for r in app2.routes]
        True
        >>> "/send" in [r.path for r in app2.routes]
        True

        >>> # Test CORS middleware is added
        >>> app3 = _build_fastapi(pubsub, stdio, cors_origins=["http://example.com"])
        >>> # Check that middleware stack includes CORSMiddleware
        >>> any("CORSMiddleware" in str(m) for m in app3.user_middleware)
        True
    """
    app = FastAPI()

    # Add CORS middleware if origins specified
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ----- GET /sse ---------------------------------------------------------#
    @app.get(sse_path)
    async def get_sse(request: Request) -> EventSourceResponse:  # noqa: D401
        """Stream subprocess stdout to any number of SSE clients.

        Args:
            request (Request): The incoming ``GET`` request that will be
                upgraded to a Server-Sent Events (SSE) stream.

        Returns:
            EventSourceResponse: A streaming response that forwards JSON-RPC
            messages from the child process and emits periodic ``keepalive``
            frames so that clients and proxies do not time out.
        """
        # Extract environment variables from headers if dynamic env is enabled
        additional_env_vars = {}
        if header_mappings:
            request_headers = dict(request.headers)
            additional_env_vars = extract_env_vars_from_headers(request_headers, header_mappings)

            # Restart stdio endpoint with new environment variables
            if additional_env_vars:
                LOGGER.info(f"Restarting stdio endpoint with {len(additional_env_vars)} environment variables")
                await stdio.stop()  # Stop existing process
                await stdio.start(additional_env_vars)  # Start with new env vars

        queue = pubsub.subscribe()
        session_id = uuid.uuid4().hex

        async def event_gen() -> AsyncIterator[Dict[str, Any]]:
            """Generate Server-Sent Events for the SSE stream.

            Yields SSE events in the following sequence:
            1. An 'endpoint' event with the message posting URL (required by MCP spec)
            2. An immediate 'keepalive' event to confirm the stream is active
            3. 'message' events containing JSON-RPC responses from the subprocess
            4. Periodic 'keepalive' events to prevent timeouts

            The generator runs until the client disconnects or the server shuts down.
            Automatically unsubscribes from the pubsub system on completion.

            Yields:
                Dict[str, Any]: SSE event dictionaries containing:
                    - event: The event type ('endpoint', 'message', or 'keepalive')
                    - data: The event payload (URL, JSON-RPC message, or empty object)
                    - retry: Retry interval in milliseconds for reconnection

            Examples:
                >>> import asyncio
                >>> async def test_event_gen():
                ...     # This is tested indirectly through the SSE endpoint
                ...     return True
                >>> asyncio.run(test_event_gen())
                True
            """
            # 1️⃣ Mandatory "endpoint" bootstrap required by the MCP spec
            endpoint_url = f"{str(request.base_url).rstrip('/')}{message_path}?session_id={session_id}"
            yield {
                "event": "endpoint",
                "data": endpoint_url,
                "retry": int(keep_alive * 1000),
            }

            # 2️⃣ Immediate keepalive so clients know the stream is alive (if enabled in config)
            if DEFAULT_KEEPALIVE_ENABLED:
                yield {"event": "keepalive", "data": "{}", "retry": keep_alive * 1000}

            try:
                while True:
                    if await request.is_disconnected():
                        break

                    try:
                        timeout = keep_alive if DEFAULT_KEEPALIVE_ENABLED else None
                        msg = await asyncio.wait_for(queue.get(), timeout)
                        yield {"event": "message", "data": msg.rstrip()}
                    except asyncio.TimeoutError:
                        if DEFAULT_KEEPALIVE_ENABLED:
                            yield {
                                "event": "keepalive",
                                "data": "{}",
                                "retry": keep_alive * 1000,
                            }
            finally:
                if pubsub:
                    pubsub.unsubscribe(queue)

        return EventSourceResponse(
            event_gen(),
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # disable proxy buffering
            },
        )

    # ----- POST /message ----------------------------------------------------#
    @app.post(message_path, status_code=status.HTTP_202_ACCEPTED)
    async def post_message(raw: Request, session_id: str | None = None) -> Response:  # noqa: D401
        """Forward a raw JSON-RPC request to the stdio subprocess.

        Args:
            raw (Request): The incoming ``POST`` request whose body contains
                a single JSON-RPC message.
            session_id (str | None): The SSE session identifier that originated
                this back-channel call (present when the client obtained the
                endpoint URL from an ``endpoint`` bootstrap frame).

        Returns:
            Response: ``202 Accepted`` if the payload is forwarded successfully,
            or ``400 Bad Request`` when the body is not valid JSON.
        """
        _ = session_id  # Unused but required for API compatibility

        # Extract environment variables from headers if dynamic env is enabled
        additional_env_vars = {}
        if header_mappings:
            request_headers = dict(raw.headers)
            additional_env_vars = extract_env_vars_from_headers(request_headers, header_mappings)

            # Restart stdio endpoint with new environment variables
            if additional_env_vars:
                LOGGER.info(f"Restarting stdio endpoint with {len(additional_env_vars)} environment variables")
                await stdio.stop()  # Stop existing process
                await stdio.start(additional_env_vars)  # Start with new env vars
                await asyncio.sleep(0.5)  # Give process time to initialize

        # Ensure stdio endpoint is running
        if not stdio.is_running():
            LOGGER.info("Starting stdio endpoint (was not running)")
            await stdio.start()
            await asyncio.sleep(0.5)  # Give process time to initialize

        payload = await raw.body()
        try:
            orjson.loads(payload)  # validate
        except Exception as exc:  # noqa: BLE001
            return PlainTextResponse(
                f"Invalid JSON payload: {exc}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        await stdio.send(payload.decode().rstrip() + "\n")
        return PlainTextResponse("forwarded", status_code=status.HTTP_202_ACCEPTED)

    # ----- Liveness ---------------------------------------------------------#
    @app.get("/healthz")
    async def health() -> Response:  # noqa: D401
        """Health check endpoint.

        Returns:
            Response: A plain text response with "ok" status.
        """
        return PlainTextResponse("ok")

    return app


# ---------------------------------------------------------------------------#
# CLI & orchestration                                                        #
# ---------------------------------------------------------------------------#


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command line arguments.

    Validates mutually exclusive source options and sets defaults for
    port and logging configuration.

    Args:
        argv: Sequence of command line arguments.

    Returns:
        argparse.Namespace: Parsed command line arguments.

    Raises:
        NotImplementedError: If streamableHttp option is specified.

    Examples:
        >>> args = _parse_args(["--stdio", "cat", "--port", "9000"])
        >>> args.stdio
        'cat'
        >>> args.port
        9000
        >>> args.logLevel
        'info'
        >>> args.host
        '127.0.0.1'
        >>> args.cors is None
        True
        >>> args.oauth2Bearer is None
        True

        >>> # Test default parameters
        >>> args = _parse_args(["--stdio", "cat"])
        >>> args.port
        8000
        >>> args.host
        '127.0.0.1'
        >>> args.logLevel
        'info'

        >>> # Test connect-sse mode
        >>> args = _parse_args(["--connect-sse", "http://example.com/sse"])
        >>> args.connect_sse
        'http://example.com/sse'
        >>> args.stdio is None
        True

        >>> # Test CORS configuration
        >>> args = _parse_args(["--stdio", "cat", "--cors", "https://app.com", "https://web.com"])
        >>> args.cors
        ['https://app.com', 'https://web.com']

        >>> # Test OAuth2 Bearer token
        >>> args = _parse_args(["--connect-sse", "http://example.com", "--oauth2Bearer", "token123"])
        >>> args.oauth2Bearer
        'token123'

        >>> # Test custom host and log level
        >>> args = _parse_args(["--stdio", "cat", "--host", "0.0.0.0", "--logLevel", "debug"])
        >>> args.host
        '0.0.0.0'
        >>> args.logLevel
        'debug'

        >>> # Test expose protocols
        >>> args = _parse_args(["--stdio", "uvx mcp-server-git", "--expose-sse", "--expose-streamable-http"])
        >>> args.stdio
        'uvx mcp-server-git'
        >>> args.expose_sse
        True
        >>> args.expose_streamable_http
        True
        >>> args.stateless
        False
        >>> args.jsonResponse
        False

        >>> # Test new parameters
        >>> args = _parse_args(["--stdio", "cat", "--ssePath", "/events", "--messagePath", "/send", "--keepAlive", "60"])
        >>> args.ssePath
        '/events'
        >>> args.messagePath
        '/send'
        >>> args.keepAlive
        60

        >>> # Test connect-sse with stdio command
        >>> args = _parse_args(["--connect-sse", "http://example.com/sse", "--stdioCommand", "uvx mcp-server-git"])
        >>> args.stdioCommand
        'uvx mcp-server-git'

        >>> # Test connect-sse without stdio command (allowed)
        >>> args = _parse_args(["--connect-sse", "http://example.com/sse"])
        >>> args.stdioCommand is None
        True
    """
    p = argparse.ArgumentParser(
        prog="mcpgateway.translate",
        description="Bridges between different MCP transport protocols: stdio, SSE, and streamable HTTP.",
    )

    # Source/destination options
    p.add_argument("--stdio", help='Local command to run, e.g. "uvx mcp-server-git"')
    p.add_argument("--connect-sse", dest="connect_sse", help="Connect to remote SSE endpoint URL")
    p.add_argument("--connect-streamable-http", dest="connect_streamable_http", help="Connect to remote streamable HTTP endpoint URL")
    p.add_argument("--grpc", type=str, help="gRPC server target (host:port) to expose")
    p.add_argument("--connect-grpc", type=str, help="Remote gRPC endpoint to connect to")

    # Protocol exposure options (can be combined)
    p.add_argument("--expose-sse", action="store_true", help="Expose via SSE protocol (endpoints: /sse and /message)")
    p.add_argument("--expose-streamable-http", action="store_true", help="Expose via streamable HTTP protocol (endpoint: /mcp)")

    # gRPC configuration options
    p.add_argument("--grpc-tls", action="store_true", help="Enable TLS for gRPC connection")
    p.add_argument("--grpc-cert", type=str, help="Path to TLS certificate for gRPC")
    p.add_argument("--grpc-key", type=str, help="Path to TLS key for gRPC")
    p.add_argument("--grpc-metadata", action="append", help="gRPC metadata (KEY=VALUE, repeatable)")

    p.add_argument("--port", type=int, default=8000, help="HTTP port to bind")
    p.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    p.add_argument(
        "--logLevel",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Log level",
    )
    p.add_argument(
        "--cors",
        nargs="*",
        help="CORS allowed origins (e.g., --cors https://app.example.com)",
    )
    p.add_argument(
        "--oauth2Bearer",
        help="OAuth2 Bearer token for authentication",
    )

    # New configuration options
    p.add_argument(
        "--ssePath",
        default="/sse",
        help="SSE endpoint path (default: /sse)",
    )
    p.add_argument(
        "--messagePath",
        default="/message",
        help="Message endpoint path (default: /message)",
    )
    p.add_argument(
        "--keepAlive",
        type=int,
        default=KEEP_ALIVE_INTERVAL,
        help=f"Keep-alive interval in seconds (default: {KEEP_ALIVE_INTERVAL})",
    )

    # For SSE to stdio mode
    p.add_argument(
        "--stdioCommand",
        help="Command to run when bridging SSE/streamableHttp to stdio (optional with --sse or --streamableHttp)",
    )

    # Dynamic environment variable injection
    p.add_argument("--enable-dynamic-env", action="store_true", help="Enable dynamic environment variable injection from HTTP headers")
    p.add_argument(
        "--header-to-env",
        action="append",
        default=[],
        help="Map HTTP header to environment variable (format: HEADER=ENV_VAR, can be used multiple times). Case-insensitive duplicates are rejected (e.g., Authorization and authorization cannot both be mapped).",
    )

    # For streamable HTTP mode
    p.add_argument(
        "--stateless",
        action="store_true",
        help="Use stateless mode for streamable HTTP (default: False)",
    )
    p.add_argument(
        "--jsonResponse",
        action="store_true",
        help="Return JSON responses instead of SSE streams for streamable HTTP (default: False)",
    )

    args = p.parse_args(argv)
    # streamableHttp is now supported, no need to raise NotImplementedError
    return args


async def _run_stdio_to_sse(
    cmd: str,
    port: int,
    log_level: str = "info",
    cors: Optional[List[str]] = None,
    host: str = "127.0.0.1",
    sse_path: str = "/sse",
    message_path: str = "/message",
    keep_alive: float = KEEP_ALIVE_INTERVAL,
    header_mappings: Optional[NormalizedMappings] = None,
) -> None:
    """Run stdio to SSE bridge.

    Starts a subprocess and exposes it via HTTP/SSE endpoints. Handles graceful
    shutdown on SIGINT/SIGTERM.

    Args:
        cmd: The command to run as a stdio subprocess.
        port: The port to bind the HTTP server to.
        log_level: The logging level to use. Defaults to "info".
        cors: Optional list of CORS allowed origins.
        host: The host interface to bind to. Defaults to "127.0.0.1" for security.
        sse_path: Path for the SSE endpoint. Defaults to "/sse".
        message_path: Path for the message endpoint. Defaults to "/message".
        keep_alive: Keep-alive interval in seconds. Defaults to KEEP_ALIVE_INTERVAL.
        header_mappings: Optional mapping of HTTP headers to environment variables.

    Examples:
        >>> import asyncio # doctest: +SKIP
        >>> async def test_run(): # doctest: +SKIP
        ...     await _run_stdio_to_sse("cat", 9000)  # doctest: +SKIP
        ...     return True
        >>> asyncio.run(test_run()) # doctest: +SKIP
        True
    """
    pubsub = _PubSub()
    stdio = StdIOEndpoint(cmd, pubsub, header_mappings=header_mappings)
    await stdio.start()

    app = _build_fastapi(pubsub, stdio, keep_alive=keep_alive, sse_path=sse_path, message_path=message_path, cors_origins=cors, header_mappings=header_mappings)
    config = uvicorn.Config(
        app,
        host=host,  # Changed from hardcoded "0.0.0.0"
        port=port,
        log_level=log_level,
        lifespan="off",
    )
    uvicorn_server = uvicorn.Server(config)

    shutting_down = asyncio.Event()  # 🔄 make shutdown idempotent

    async def _shutdown() -> None:
        """Handle graceful shutdown of the stdio bridge.

        Performs shutdown operations in the correct order:
        1. Sets a flag to prevent multiple shutdown attempts
        2. Stops the stdio subprocess
        3. Shuts down the HTTP server

        This function is idempotent - multiple calls will only execute
        the shutdown sequence once.

        Examples:
            >>> import asyncio
            >>> async def test_shutdown():
            ...     # Shutdown is tested as part of the main run flow
            ...     return True
            >>> asyncio.run(test_shutdown())
            True
        """
        if shutting_down.is_set():
            return
        shutting_down.set()
        LOGGER.info("Shutting down ...")
        await stdio.stop()
        # Graceful shutdown by setting the shutdown event
        # Use getattr to safely access should_exit attribute
        setattr(uvicorn_server, "should_exit", getattr(uvicorn_server, "should_exit", False) or True)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):  # Windows lacks add_signal_handler
            loop.add_signal_handler(sig, lambda *_: asyncio.create_task(_shutdown()))

    LOGGER.info(f"Bridge ready → http://{host}:{port}{sse_path}")
    await uvicorn_server.serve()
    await _shutdown()  # final cleanup


async def _run_sse_to_stdio(url: str, oauth2_bearer: Optional[str] = None, timeout: float = 30.0, stdio_command: Optional[str] = None, max_retries: int = 5, initial_retry_delay: float = 1.0) -> None:
    """Run SSE to stdio bridge.

    Connects to a remote SSE endpoint and bridges it to local stdio.
    Implements proper bidirectional message flow with error handling and retries.

    Args:
        url: The SSE endpoint URL to connect to.
        oauth2_bearer: Optional OAuth2 bearer token for authentication. Defaults to None.
        timeout: HTTP client timeout in seconds. Defaults to 30.0.
        stdio_command: Optional command to run for local stdio processing.
            If not provided, will simply print SSE messages to stdout.
        max_retries: Maximum number of connection retry attempts. Defaults to 5.
        initial_retry_delay: Initial delay between retries in seconds. Defaults to 1.0.

    Raises:
        ImportError: If httpx package is not available.
        RuntimeError: If the subprocess fails to create stdin/stdout pipes.
        Exception: For any unexpected error in SSE stream processing.

    Examples:
        >>> import asyncio
        >>> async def test_sse():
        ...     try:
        ...         await _run_sse_to_stdio("http://example.com/sse", None)  # doctest: +SKIP
        ...     except ImportError as e:
        ...         return "httpx" in str(e)
        >>> asyncio.run(test_sse())  # Would return True if httpx not installed # doctest: +SKIP
    """
    if not httpx:
        raise ImportError("httpx package is required for SSE to stdio bridging")

    headers = {}
    if oauth2_bearer:
        headers["Authorization"] = f"Bearer {oauth2_bearer}"

    # If no stdio command provided, use simple mode (just print to stdout)
    if not stdio_command:
        LOGGER.warning("No --stdioCommand provided, running in simple mode (SSE to stdout only)")
        # First-Party
        from mcpgateway.services.http_client_service import get_isolated_http_client  # pylint: disable=import-outside-toplevel

        async with get_isolated_http_client(timeout=timeout, headers=headers, verify=DEFAULT_SSL_VERIFY, connect_timeout=10.0, write_timeout=timeout, pool_timeout=timeout) as client:
            await _simple_sse_pump(client, url, max_retries, initial_retry_delay)
        return

    # Start the stdio subprocess
    process = await asyncio.create_subprocess_exec(
        *shlex.split(stdio_command),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=sys.stderr,
    )

    if not process.stdin or not process.stdout:
        raise RuntimeError(f"Failed to create subprocess with stdin/stdout pipes for command: {stdio_command}")

    # Store the message endpoint URL once received
    message_endpoint: Optional[str] = None

    async def read_stdout(client: httpx.AsyncClient) -> None:
        """Read lines from subprocess stdout and POST to message endpoint.

        Continuously reads JSON-RPC requests from the subprocess stdout
        and POSTs them to the remote message endpoint obtained from the
        SSE stream's endpoint event.

        Args:
            client: The HTTP client to use for POSTing messages.

        Raises:
            RuntimeError: If the process stdout stream is not available.

        Examples:
            >>> import asyncio
            >>> async def test_read():
            ...     # This is tested as part of the SSE to stdio flow
            ...     return True
            >>> asyncio.run(test_read())
            True
        """
        if not process.stdout:
            raise RuntimeError("Process stdout not available")

        while True:
            if not process.stdout:
                raise RuntimeError("Process stdout not available")
            line = await process.stdout.readline()
            if not line:
                break

            text = line.decode().strip()
            if not text:
                continue

            LOGGER.debug(f"← stdio: {text}")

            # Wait for endpoint URL if not yet received
            retry_count = 0
            while not message_endpoint and retry_count < 30:  # 30 second timeout
                await asyncio.sleep(1)
                retry_count += 1

            if not message_endpoint:
                LOGGER.error("No message endpoint received from SSE stream")
                continue

            # POST the JSON-RPC request to the message endpoint
            try:
                response = await client.post(message_endpoint, content=text, headers={"Content-Type": "application/json"})
                if response.status_code != 202:
                    LOGGER.warning(f"Message endpoint returned {response.status_code}: {response.text}")
            except Exception as e:
                LOGGER.error(f"Failed to POST to message endpoint: {e}")

    async def pump_sse_to_stdio(client: httpx.AsyncClient) -> None:
        """Stream SSE data from remote endpoint to subprocess stdin.

        Connects to the remote SSE endpoint with retry logic and forwards
        message events to the subprocess stdin. Properly parses SSE events
        and handles endpoint, message, and keepalive event types.

        Args:
            client: The HTTP client to use for SSE streaming.

        Raises:
            HTTPStatusError: If the SSE endpoint returns a non-200 status code.
            Exception: For unexpected errors in SSE stream processing.

        Examples:
            >>> import asyncio
            >>> async def test_pump():
            ...     # This is tested as part of the SSE to stdio flow
            ...     return True
            >>> asyncio.run(test_pump())
            True
        """
        nonlocal message_endpoint
        retry_delay = initial_retry_delay
        retry_count = 0

        while retry_count < max_retries:
            try:
                LOGGER.info(f"Connecting to SSE endpoint: {url}")

                async with client.stream("GET", url) as response:
                    # Check status code if available (real httpx response)
                    if hasattr(response, "status_code") and response.status_code != 200:
                        if httpx:
                            raise httpx.HTTPStatusError(f"SSE endpoint returned {response.status_code}", request=response.request, response=response)
                        raise Exception(f"SSE endpoint returned {response.status_code}")

                    # Reset retry counter on successful connection
                    retry_count = 0
                    retry_delay = initial_retry_delay
                    current_event: Optional[SSEEvent] = None

                    async for line in response.aiter_lines():
                        event, is_complete = SSEEvent.parse_sse_line(line, current_event)
                        current_event = event

                        if is_complete and current_event:
                            LOGGER.debug(f"SSE event: {current_event.event} - {current_event.data[:100]}...")

                            if current_event.event == "endpoint":
                                # Store the message endpoint URL
                                message_endpoint = current_event.data
                                LOGGER.info(f"Received message endpoint: {message_endpoint}")

                            elif current_event.event == "message":
                                # Forward JSON-RPC responses to stdio
                                if process.stdin:
                                    process.stdin.write((current_event.data + "\n").encode())
                                    await process.stdin.drain()
                                    LOGGER.debug(f"→ stdio: {current_event.data}")

                            elif current_event.event == "keepalive":
                                # Log keepalive but don't forward
                                LOGGER.debug("Received keepalive")

                            # Reset for next event
                            current_event = None

            except Exception as e:
                # Check if it's one of the expected httpx exceptions
                if httpx and isinstance(e, (httpx.ConnectError, httpx.HTTPStatusError, httpx.ReadTimeout)):
                    retry_count += 1
                    if retry_count >= max_retries:
                        LOGGER.error(f"Max retries ({max_retries}) exceeded. Giving up.")
                        raise

                    LOGGER.warning(f"Connection error: {e}. Retrying in {retry_delay}s... (attempt {retry_count}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30)  # Exponential backoff, max 30s
                else:
                    LOGGER.error(f"Unexpected error in SSE stream: {e}")
                    raise

    # Run both tasks concurrently
    # First-Party
    from mcpgateway.services.http_client_service import get_isolated_http_client  # pylint: disable=import-outside-toplevel

    async with get_isolated_http_client(timeout=timeout, headers=headers, verify=DEFAULT_SSL_VERIFY, connect_timeout=10.0, write_timeout=timeout, pool_timeout=timeout) as client:
        try:
            await asyncio.gather(read_stdout(client), pump_sse_to_stdio(client))
        except Exception as e:
            LOGGER.error(f"Bridge error: {e}")
            raise
        finally:
            # Clean up subprocess
            if process.returncode is None:
                process.terminate()
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=5)


async def _run_stdio_to_streamable_http(
    cmd: str,
    port: int,
    log_level: str = "info",
    cors: Optional[List[str]] = None,
    host: str = "127.0.0.1",
    stateless: bool = False,
    json_response: bool = False,
) -> None:
    """Run stdio to streamable HTTP bridge.

    Starts a subprocess and exposes it via streamable HTTP endpoint. Handles graceful
    shutdown on SIGINT/SIGTERM.

    Args:
        cmd: The command to run as a stdio subprocess.
        port: The port to bind the HTTP server to.
        log_level: The logging level to use. Defaults to "info".
        cors: Optional list of CORS allowed origins.
        host: The host interface to bind to. Defaults to "127.0.0.1" for security.
        stateless: Whether to use stateless mode for streamable HTTP. Defaults to False.
        json_response: Whether to return JSON responses instead of SSE streams. Defaults to False.

    Raises:
        ImportError: If MCP server components are not available.
        RuntimeError: If subprocess fails to create stdin/stdout pipes.

    Examples:
        >>> import asyncio
        >>> async def test_streamable_http():
        ...     # Would start a real subprocess and HTTP server
        ...     cmd = "echo hello"
        ...     port = 9000
        ...     # This would normally run the server
        ...     return True
        >>> asyncio.run(test_streamable_http())
        True
    """
    # MCP components are available, proceed with setup

    LOGGER.info(f"Starting stdio to streamable HTTP bridge for command: {cmd}")

    # Create a simple MCP server that will proxy to stdio subprocess
    mcp_server = MCPServer(name="stdio-proxy")

    # Create subprocess for stdio communication
    process = await asyncio.create_subprocess_exec(
        *shlex.split(cmd),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=sys.stderr,
    )

    if not process.stdin or not process.stdout:
        raise RuntimeError(f"Failed to create subprocess with stdin/stdout pipes for command: {cmd}")

    # Set up the streamable HTTP session manager with the server
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        stateless=stateless,
        json_response=json_response,
    )

    # Create Starlette app to host the streamable HTTP endpoint
    async def handle_mcp(request: Request) -> None:
        """Handle MCP requests via streamable HTTP.

        Args:
            request: The incoming HTTP request from Starlette.

        Examples:
            >>> async def test_handle():
            ...     # Mock request handling
            ...     class MockRequest:
            ...         scope = {"type": "http"}
            ...         async def receive(self): return {}
            ...         async def send(self, msg): return None
            ...     req = MockRequest()
            ...     # Would handle the request via session manager
            ...     return req is not None
            >>> import asyncio
            >>> asyncio.run(test_handle())
            True
        """
        # The session manager handles all the protocol details - Note: I don't like accessing _send directly -JPS
        await session_manager.handle_request(request.scope, request.receive, request._send)  # pylint: disable=W0212

    routes = [
        Route("/mcp", handle_mcp, methods=["GET", "POST"]),
        Route("/healthz", lambda request: PlainTextResponse("ok"), methods=["GET"]),
    ]

    app = Starlette(routes=routes)

    # Add CORS middleware if specified
    if cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Run the server with Uvicorn
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        lifespan="off",
    )
    uvicorn_server = uvicorn.Server(config)

    shutting_down = asyncio.Event()

    async def _shutdown() -> None:
        """Handle graceful shutdown of the streamable HTTP bridge."""
        if shutting_down.is_set():
            return
        shutting_down.set()
        LOGGER.info("Shutting down streamable HTTP bridge...")
        if process.returncode is None:
            process.terminate()
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), 5)
        # Graceful shutdown by setting the shutdown event
        # Use getattr to safely access should_exit attribute
        setattr(uvicorn_server, "should_exit", getattr(uvicorn_server, "should_exit", False) or True)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):  # Windows lacks add_signal_handler
            loop.add_signal_handler(sig, lambda *_: asyncio.create_task(_shutdown()))

    # Pump messages between stdio and HTTP
    async def pump_stdio_to_http() -> None:
        """Forward messages from subprocess stdout to HTTP responses.

        Examples:
            >>> async def test():
            ...     # This would pump messages in real usage
            ...     return True
            >>> import asyncio
            >>> asyncio.run(test())
            True
        """
        while True:
            try:
                if not process.stdout:
                    raise RuntimeError("Process stdout not available")
                line = await process.stdout.readline()
                if not line:
                    break
                # The session manager will handle routing to appropriate HTTP responses
                # This would need proper integration with session_manager's internal queue
                LOGGER.debug(f"Received from subprocess: {line.decode().strip()}")
            except Exception as e:
                LOGGER.error(f"Error reading from subprocess: {e}")
                break

    async def pump_http_to_stdio(data: str) -> None:
        """Forward HTTP requests to subprocess stdin.

        Args:
            data: The data string to send to subprocess stdin.

        Examples:
            >>> async def test_pump():
            ...     # Would pump data to subprocess
            ...     data = '{"method": "test"}'
            ...     # In real use, would write to process.stdin
            ...     return len(data) > 0
            >>> import asyncio
            >>> asyncio.run(test_pump())
            True
        """
        if not process.stdin:
            raise RuntimeError("Process stdin not available")
        process.stdin.write(data.encode() + b"\n")
        await process.stdin.drain()

    # Note: pump_http_to_stdio will be used when stdio-to-HTTP bridge is fully implemented
    _ = pump_http_to_stdio

    # Start the pump task
    pump_task = asyncio.create_task(pump_stdio_to_http())

    try:
        LOGGER.info(f"Streamable HTTP bridge ready → http://{host}:{port}/mcp")
        await uvicorn_server.serve()
    finally:
        pump_task.cancel()
        await _shutdown()


async def _run_streamable_http_to_stdio(
    url: str,
    oauth2_bearer: Optional[str] = None,
    timeout: float = 30.0,
    stdio_command: Optional[str] = None,
    max_retries: int = 5,
    initial_retry_delay: float = 1.0,
) -> None:
    """Run streamable HTTP to stdio bridge.

    Connects to a remote streamable HTTP endpoint and bridges it to local stdio.
    Implements proper bidirectional message flow with error handling and retries.

    Args:
        url: The streamable HTTP endpoint URL to connect to.
        oauth2_bearer: Optional OAuth2 bearer token for authentication. Defaults to None.
        timeout: HTTP client timeout in seconds. Defaults to 30.0.
        stdio_command: Optional command to run for local stdio processing.
            If not provided, will simply print messages to stdout.
        max_retries: Maximum number of connection retry attempts. Defaults to 5.
        initial_retry_delay: Initial delay between retries in seconds. Defaults to 1.0.

    Raises:
        ImportError: If httpx package is not available.
        RuntimeError: If the subprocess fails to create stdin/stdout pipes.
        Exception: For any unexpected error during bridging operations.
    """
    if not httpx:
        raise ImportError("httpx package is required for streamable HTTP to stdio bridging")

    headers = {}
    if oauth2_bearer:
        headers["Authorization"] = f"Bearer {oauth2_bearer}"

    # Ensure URL ends with /mcp if not already
    if not url.endswith("/mcp"):
        url = url.rstrip("/") + "/mcp"

    # If no stdio command provided, use simple mode (just print to stdout)
    if not stdio_command:
        LOGGER.warning("No --stdioCommand provided, running in simple mode (streamable HTTP to stdout only)")
        # First-Party
        from mcpgateway.services.http_client_service import get_isolated_http_client  # pylint: disable=import-outside-toplevel

        async with get_isolated_http_client(timeout=timeout, headers=headers, verify=DEFAULT_SSL_VERIFY, connect_timeout=10.0, write_timeout=timeout, pool_timeout=timeout) as client:
            await _simple_streamable_http_pump(client, url, max_retries, initial_retry_delay)
        return

    # Start the stdio subprocess
    process = await asyncio.create_subprocess_exec(
        *shlex.split(stdio_command),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=sys.stderr,
    )

    if not process.stdin or not process.stdout:
        raise RuntimeError(f"Failed to create subprocess with stdin/stdout pipes for command: {stdio_command}")

    async def read_stdout(client: httpx.AsyncClient) -> None:
        """Read lines from subprocess stdout and POST to streamable HTTP endpoint.

        Args:
            client: The HTTP client to use for POSTing messages.

        Raises:
            RuntimeError: If the process stdout stream is not available.
        """
        if not process.stdout:
            raise RuntimeError("Process stdout not available")

        while True:
            if not process.stdout:
                raise RuntimeError("Process stdout not available")
            line = await process.stdout.readline()
            if not line:
                break

            text = line.decode().strip()
            if not text:
                continue

            LOGGER.debug(f"← stdio: {text}")

            # POST the JSON-RPC request to the streamable HTTP endpoint
            try:
                if CONTENT_TYPE == "application/x-www-form-urlencoded":
                    # If text is JSON, parse and encode as form
                    try:
                        payload = orjson.loads(text)
                        body = urlencode(payload)
                    except Exception:
                        body = text
                    response = await client.post(url, content=body, headers=headers)
                else:
                    response = await client.post(url, content=text, headers=headers)
                if response.status_code == 200:
                    # Handle JSON response
                    response_data = response.text
                    if response_data and process.stdin:
                        process.stdin.write((response_data + "\n").encode())
                        await process.stdin.drain()
                        LOGGER.debug(f"→ stdio: {response_data}")
                else:
                    LOGGER.warning(f"Streamable HTTP endpoint returned {response.status_code}: {response.text}")
            except Exception as e:
                LOGGER.error(f"Failed to POST to streamable HTTP endpoint: {e}")

    async def pump_streamable_http_to_stdio(client: httpx.AsyncClient) -> None:
        """Stream data from remote streamable HTTP endpoint to subprocess stdin.

        Args:
            client: The HTTP client to use for streamable HTTP streaming.

        Raises:
            httpx.HTTPStatusError: If the streamable HTTP endpoint returns a non-200 status code.
            Exception: For unexpected errors in streamable HTTP stream processing.
        """
        retry_delay = initial_retry_delay
        retry_count = 0

        while retry_count < max_retries:
            try:
                LOGGER.info(f"Connecting to streamable HTTP endpoint: {url}")

                # For streamable HTTP, we need to handle both SSE streams and JSON responses
                # Try SSE first (for stateful sessions or when SSE is preferred)
                async with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as response:
                    if response.status_code != 200:
                        if httpx:
                            raise httpx.HTTPStatusError(f"Streamable HTTP endpoint returned {response.status_code}", request=response.request, response=response)
                        raise Exception(f"Streamable HTTP endpoint returned {response.status_code}")

                    # Reset retry counter on successful connection
                    retry_count = 0
                    retry_delay = initial_retry_delay

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]  # Remove "data: " prefix
                            if data and process.stdin:
                                process.stdin.write((data + "\n").encode())
                                await process.stdin.drain()
                                LOGGER.debug(f"→ stdio: {data}")

            except Exception as e:
                if httpx and isinstance(e, (httpx.ConnectError, httpx.HTTPStatusError, httpx.ReadTimeout)):
                    retry_count += 1
                    if retry_count >= max_retries:
                        LOGGER.error(f"Max retries ({max_retries}) exceeded. Giving up.")
                        raise

                    LOGGER.warning(f"Connection error: {e}. Retrying in {retry_delay}s... (attempt {retry_count}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30)  # Exponential backoff, max 30s
                else:
                    LOGGER.error(f"Unexpected error in streamable HTTP stream: {e}")
                    raise

    # Run both tasks concurrently
    # First-Party
    from mcpgateway.services.http_client_service import get_isolated_http_client  # pylint: disable=import-outside-toplevel

    async with get_isolated_http_client(timeout=timeout, headers=headers, verify=DEFAULT_SSL_VERIFY, connect_timeout=10.0, write_timeout=timeout, pool_timeout=timeout) as client:
        try:
            await asyncio.gather(read_stdout(client), pump_streamable_http_to_stdio(client))
        except Exception as e:
            LOGGER.error(f"Bridge error: {e}")
            raise
        finally:
            # Clean up subprocess
            if process.returncode is None:
                process.terminate()
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=5)


async def _simple_streamable_http_pump(client: "Any", url: str, max_retries: int, initial_retry_delay: float) -> None:
    """Simple streamable HTTP pump that just prints messages to stdout.

    Used when no stdio command is provided to bridge streamable HTTP to stdout directly.

    Args:
        client: The HTTP client to use for streamable HTTP streaming.
        url: The streamable HTTP endpoint URL to connect to.
        max_retries: Maximum number of connection retry attempts.
        initial_retry_delay: Initial delay between retries in seconds.

    Raises:
        Exception: For unexpected errors in streamable HTTP stream processing including
            HTTPStatusError if the endpoint returns a non-200 status code.
    """
    retry_delay = initial_retry_delay
    retry_count = 0

    while retry_count < max_retries:
        try:
            LOGGER.info(f"Connecting to streamable HTTP endpoint: {url}")

            # Try to get SSE stream
            async with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as response:
                if response.status_code != 200:
                    if httpx:
                        raise httpx.HTTPStatusError(f"Streamable HTTP endpoint returned {response.status_code}", request=response.request, response=response)
                    raise Exception(f"Streamable HTTP endpoint returned {response.status_code}")

                # Reset retry counter on successful connection
                retry_count = 0
                retry_delay = initial_retry_delay

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]  # Remove "data: " prefix
                        if data:
                            print(data)
                            LOGGER.debug(f"Received: {data}")

        except Exception as e:
            if httpx and isinstance(e, (httpx.ConnectError, httpx.HTTPStatusError, httpx.ReadTimeout)):
                retry_count += 1
                if retry_count >= max_retries:
                    LOGGER.error(f"Max retries ({max_retries}) exceeded. Giving up.")
                    raise

                LOGGER.warning(f"Connection error: {e}. Retrying in {retry_delay}s... (attempt {retry_count}/{max_retries})")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)  # Exponential backoff, max 30s
            else:
                LOGGER.error(f"Unexpected error in streamable HTTP stream: {e}")
                raise


async def _run_multi_protocol_server(  # pylint: disable=too-many-positional-arguments
    cmd: str,
    port: int,
    log_level: str = "info",
    cors: Optional[List[str]] = None,
    host: str = "127.0.0.1",
    expose_sse: bool = False,
    expose_streamable_http: bool = False,
    sse_path: str = "/sse",
    message_path: str = "/message",
    keep_alive: float = KEEP_ALIVE_INTERVAL,
    stateless: bool = False,
    json_response: bool = False,
    header_mappings: Optional[NormalizedMappings] = None,
) -> None:
    """Run a stdio server and expose it via multiple protocols simultaneously.

    Args:
        cmd: The command to run as a stdio subprocess.
        port: The port to bind the HTTP server to.
        log_level: The logging level to use. Defaults to "info".
        cors: Optional list of CORS allowed origins.
        host: The host interface to bind to. Defaults to "127.0.0.1".
        expose_sse: Whether to expose via SSE protocol.
        expose_streamable_http: Whether to expose via streamable HTTP protocol.
        sse_path: Path for SSE endpoint. Defaults to "/sse".
        message_path: Path for message endpoint. Defaults to "/message".
        keep_alive: Keep-alive interval for SSE. Defaults to KEEP_ALIVE_INTERVAL.
        stateless: Whether to use stateless mode for streamable HTTP.
        json_response: Whether to return JSON responses for streamable HTTP.
        header_mappings: Optional mapping of HTTP headers to environment variables.
    """
    LOGGER.info(f"Starting multi-protocol server for command: {cmd}")
    LOGGER.info(f"Protocols: SSE={expose_sse}, StreamableHTTP={expose_streamable_http}")

    # Create a shared pubsub whenever either protocol needs stdout observations
    pubsub = _PubSub() if (expose_sse or expose_streamable_http) else None

    # Create the stdio endpoint
    stdio = StdIOEndpoint(cmd, pubsub, header_mappings=header_mappings) if (expose_sse or expose_streamable_http) and pubsub else None

    # Create fastapi app and middleware
    app = FastAPI()

    # Add CORS middleware if specified
    if cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Start stdio if at least one transport requires it
    if stdio:
        await stdio.start()

    # SSE endpoints
    if expose_sse and stdio and pubsub:

        @app.get(sse_path)
        async def get_sse(request: Request) -> EventSourceResponse:
            """SSE endpoint.

            Args:
                request: The incoming HTTP request.

            Returns:
                EventSourceResponse: Server-sent events stream.
            """
            if not pubsub:
                raise RuntimeError("PubSub not available")

            # Extract environment variables from headers if dynamic env is enabled
            additional_env_vars = {}
            if header_mappings and stdio:
                request_headers = dict(request.headers)
                additional_env_vars = extract_env_vars_from_headers(request_headers, header_mappings)

                # Restart stdio endpoint with new environment variables
                if additional_env_vars:
                    LOGGER.info(f"Restarting stdio endpoint with {len(additional_env_vars)} environment variables")
                    await stdio.stop()  # Stop existing process
                    await stdio.start(additional_env_vars)  # Start with new env vars

            queue = pubsub.subscribe()
            session_id = uuid.uuid4().hex

            async def event_gen() -> AsyncIterator[Dict[str, Any]]:
                """Generate SSE events for the client.

                Yields:
                    Dict[str, Any]: SSE event data with event type and payload.
                """
                endpoint_url = f"{str(request.base_url).rstrip('/')}{message_path}?session_id={session_id}"
                yield {
                    "event": "endpoint",
                    "data": endpoint_url,
                    "retry": int(keep_alive * 1000),
                }

                if DEFAULT_KEEPALIVE_ENABLED:
                    yield {"event": "keepalive", "data": "{}", "retry": keep_alive * 1000}

                try:
                    while True:
                        if await request.is_disconnected():
                            break

                        try:
                            timeout = keep_alive if DEFAULT_KEEPALIVE_ENABLED else None
                            msg = await asyncio.wait_for(queue.get(), timeout)
                            yield {"event": "message", "data": msg.rstrip()}
                        except asyncio.TimeoutError:
                            if DEFAULT_KEEPALIVE_ENABLED:
                                yield {
                                    "event": "keepalive",
                                    "data": "{}",
                                    "retry": keep_alive * 1000,
                                }
                finally:
                    if pubsub:
                        pubsub.unsubscribe(queue)

            return EventSourceResponse(
                event_gen(),
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        @app.post(message_path, status_code=status.HTTP_202_ACCEPTED)
        async def post_message(raw: Request, session_id: str | None = None) -> Response:
            """Message endpoint for SSE.

            Args:
                raw: The incoming HTTP request.
                session_id: Optional session ID for correlation.

            Returns:
                Response: Acknowledgement of message receipt.
            """
            _ = session_id

            # Extract environment variables from headers if dynamic env is enabled
            additional_env_vars = {}
            if header_mappings and stdio:
                request_headers = dict(raw.headers)
                additional_env_vars = extract_env_vars_from_headers(request_headers, header_mappings)

                # Only restart if we have new environment variables
                if additional_env_vars:
                    LOGGER.info(f"Restarting stdio endpoint with {len(additional_env_vars)} environment variables")
                    await stdio.stop()  # Stop existing process
                    await stdio.start(additional_env_vars)  # Start with new env vars
                    await asyncio.sleep(0.5)  # Give process time to initialize

            # Ensure stdio endpoint is running
            if stdio and not stdio.is_running():
                LOGGER.info("Starting stdio endpoint (was not running)")
                await stdio.start()
                await asyncio.sleep(0.5)  # Give process time to initialize

            payload = await raw.body()
            try:
                orjson.loads(payload)
            except Exception as exc:
                return PlainTextResponse(
                    f"Invalid JSON payload: {exc}",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if not stdio:
                raise RuntimeError("Stdio endpoint not available")
            await stdio.send(payload.decode().rstrip() + "\n")
            return PlainTextResponse("forwarded", status_code=status.HTTP_202_ACCEPTED)

    # Add health check
    @app.get("/healthz")
    async def health() -> Response:
        """Health check endpoint.

        Returns:
            Response: Health status response.
        """
        return PlainTextResponse("ok")

    # Streamable HTTP support
    streamable_server = None
    streamable_manager = None
    streamable_context = None

    # Keep a reference to the original FastAPI app so we can wrap it with an ASGI
    # layer that delegates `/mcp` scopes to the StreamableHTTPSessionManager if present.
    original_app = app

    if expose_streamable_http:
        # Create an MCP server instance
        streamable_server = MCPServer("stdio-proxy")

        # Set up the streamable HTTP session manager
        streamable_manager = StreamableHTTPSessionManager(
            app=streamable_server,
            stateless=stateless,
            json_response=json_response,
        )

        # Register POST /mcp on the FastAPI app as the canonical client->server POST
        # path for Streamable HTTP. This forwards JSON-RPC notifications/requests to stdio.
        @original_app.post("/mcp")
        async def mcp_post(request: Request) -> Response:
            """
            Handles POST requests to the `/mcp` endpoint, forwarding JSON payloads to stdio
            and optionally waiting for a correlated response.

            The request body is expected to be a JSON object or newline-delimited JSON.
            If the JSON includes an "id" field, the function attempts to match it with
            a response from stdio using a pubsub queue, within a timeout period.

            Args:
                request (Request): The incoming FastAPI request containing the JSON payload.

            Returns:
                Response: A FastAPI Response object.
                    - 200 OK with matched JSON response if correlation succeeds.
                    - 202 Accepted if no matching response is received in time or for notifications.
                    - 400 Bad Request if the payload is not valid JSON.

            Example:
                >>> import httpx
                >>> response = httpx.post("http://localhost:8000/mcp", json={"id": 123, "method": "ping"})
                >>> response.status_code in (200, 202)
                True
                >>> response.text  # May be the matched JSON or "accepted"
                '{"id": 123, "result": "pong"}'  # or "accepted"
            """
            # Read and validate JSON
            body = await request.body()
            try:
                obj = orjson.loads(body)
            except Exception as exc:
                return PlainTextResponse(f"Invalid JSON payload: {exc}", status_code=status.HTTP_400_BAD_REQUEST)

            # Forward raw newline-delimited JSON to stdio
            if not stdio:
                raise RuntimeError("Stdio endpoint not available")
            await stdio.send(body.decode().rstrip() + "\n")

            # If it's a request (has an id) -> attempt to correlate response from stdio
            if isinstance(obj, dict) and "id" in obj:
                if not pubsub:
                    return PlainTextResponse("accepted", status_code=status.HTTP_202_ACCEPTED)

                queue = pubsub.subscribe()
                try:
                    timeout = 10.0  # seconds; tuneable
                    deadline = asyncio.get_event_loop().time() + timeout
                    while True:
                        remaining = max(0.0, deadline - asyncio.get_event_loop().time())
                        if remaining == 0:
                            break
                        try:
                            msg = await asyncio.wait_for(queue.get(), timeout=remaining)
                        except asyncio.TimeoutError:
                            break

                        # stdio stdout lines may contain JSON objects or arrays
                        try:
                            parsed = orjson.loads(msg)
                        except (orjson.JSONDecodeError, ValueError):
                            # not JSON -> skip
                            continue

                        candidates = parsed if isinstance(parsed, list) else [parsed]
                        for candidate in candidates:
                            if isinstance(candidate, dict) and candidate.get("id") == obj.get("id"):
                                # return the matched response as JSON
                                return ORJSONResponse(candidate)

                    # timeout -> accept and return 202
                    return PlainTextResponse("accepted (no response yet)", status_code=status.HTTP_202_ACCEPTED)
                finally:
                    if pubsub:
                        pubsub.unsubscribe(queue)

            # Notification -> return 202
            return PlainTextResponse("accepted", status_code=status.HTTP_202_ACCEPTED)

        # ASGI wrapper to route GET/other /mcp scopes to streamable_manager.handle_request
        async def mcp_asgi_wrapper(scope: Scope, receive: Receive, send: Send) -> None:
            """
            ASGI middleware that intercepts HTTP requests to the `/mcp` endpoint.

            If the request is an HTTP call to `/mcp` and a `streamable_manager` is available,
            it can handle the request (currently commented out). All other requests are
            passed to the original FastAPI application.

            Args:
                scope (Scope): The ASGI scope dictionary containing request metadata.
                receive (Receive): An awaitable that yields incoming ASGI events.
                send (Send): An awaitable used to send ASGI events.
            """
            if scope.get("type") == "http" and scope.get("path") == "/mcp" and streamable_manager:
                # Let StreamableHTTPSessionManager handle session-oriented streaming
                # await streamable_manager.handle_request(scope, receive, send)
                await original_app(scope, receive, send)
            else:
                # Delegate everything else to the original FastAPI app
                await original_app(scope, receive, send)

        # Replace the app used by uvicorn with the ASGI wrapper
        app = mcp_asgi_wrapper  # type: ignore[assignment]

    # ---------------------- Server lifecycle ----------------------
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        lifespan="off",
    )
    server = uvicorn.Server(config)

    shutting_down = asyncio.Event()

    async def _shutdown() -> None:
        """Handle graceful shutdown."""
        if shutting_down.is_set():
            return
        shutting_down.set()
        LOGGER.info("Shutting down multi-protocol server...")
        if stdio:
            await stdio.stop()
        # Streamable HTTP cleanup handled by server shutdown
        # Graceful shutdown by setting the shutdown event
        # Use getattr to safely access should_exit attribute
        setattr(server, "should_exit", getattr(server, "should_exit", False) or True)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, lambda *_: asyncio.create_task(_shutdown()))

    # If we have a streamable manager, start its context so it can accept ASGI /mcp
    if streamable_manager:
        streamable_context = streamable_manager.run()
        await streamable_context.__aenter__()  # pylint: disable=unnecessary-dunder-call,no-member

    # Log available endpoints
    endpoints = []
    if expose_sse:
        endpoints.append(f"SSE: http://{host}:{port}{sse_path}")
    if expose_streamable_http:
        endpoints.append(f"StreamableHTTP: http://{host}:{port}/mcp")

    LOGGER.info(f"Multi-protocol server ready → {', '.join(endpoints)}")

    try:
        await server.serve()
    finally:
        await _shutdown()
        # Clean up streamable HTTP context
        if streamable_context:
            await streamable_context.__aexit__(None, None, None)  # pylint: disable=unnecessary-dunder-call,no-member


async def _simple_sse_pump(client: "Any", url: str, max_retries: int, initial_retry_delay: float) -> None:
    """Simple SSE pump that just prints messages to stdout.

    Used when no stdio command is provided to bridge SSE to stdout directly.

    Args:
        client: The HTTP client to use for SSE streaming.
        url: The SSE endpoint URL to connect to.
        max_retries: Maximum number of connection retry attempts.
        initial_retry_delay: Initial delay between retries in seconds.

    Raises:
        HTTPStatusError: If the SSE endpoint returns a non-200 status code.
        Exception: For unexpected errors in SSE stream processing.
    """
    retry_delay = initial_retry_delay
    retry_count = 0

    while retry_count < max_retries:
        try:
            LOGGER.info(f"Connecting to SSE endpoint: {url}")

            async with client.stream("GET", url) as response:
                # Check status code if available (real httpx response)
                if hasattr(response, "status_code") and response.status_code != 200:
                    if httpx:
                        raise httpx.HTTPStatusError(f"SSE endpoint returned {response.status_code}", request=response.request, response=response)
                    raise Exception(f"SSE endpoint returned {response.status_code}")

                # Reset retry counter on successful connection
                retry_count = 0
                retry_delay = initial_retry_delay
                current_event: Optional[SSEEvent] = None

                async for line in response.aiter_lines():
                    event, is_complete = SSEEvent.parse_sse_line(line, current_event)
                    current_event = event

                    if is_complete and current_event:
                        if current_event.event == "endpoint":
                            LOGGER.info(f"Received message endpoint: {current_event.data}")
                        elif current_event.event == "message":
                            # Just print the message to stdout
                            print(current_event.data)
                        elif current_event.event == "keepalive":
                            LOGGER.debug("Received keepalive")

                        # Reset for next event
                        current_event = None

        except Exception as e:
            # Check if it's one of the expected httpx exceptions
            if httpx and isinstance(e, (httpx.ConnectError, httpx.HTTPStatusError, httpx.ReadTimeout)):
                retry_count += 1
                if retry_count >= max_retries:
                    LOGGER.error(f"Max retries ({max_retries}) exceeded. Giving up.")
                    raise

                LOGGER.warning(f"Connection error: {e}. Retrying in {retry_delay}s... (attempt {retry_count}/{max_retries})")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)  # Exponential backoff, max 30s
            else:
                LOGGER.error(f"Unexpected error in SSE stream: {e}")
                raise


def start_streamable_http_stdio(
    cmd: str,
    port: int,
    log_level: str,
    cors: Optional[List[str]],
    host: str = "127.0.0.1",
    stateless: bool = False,
    json_response: bool = False,
) -> None:
    """Start stdio to streamable HTTP bridge.

    Entry point for starting a stdio to streamable HTTP bridge server.

    Args:
        cmd: The command to run as a stdio subprocess.
        port: The port to bind the HTTP server to.
        log_level: The logging level to use.
        cors: Optional list of CORS allowed origins.
        host: The host interface to bind to. Defaults to "127.0.0.1".
        stateless: Whether to use stateless mode. Defaults to False.
        json_response: Whether to return JSON responses. Defaults to False.

    Returns:
        None: This function does not return a value.
    """
    return asyncio.run(_run_stdio_to_streamable_http(cmd, port, log_level, cors, host, stateless, json_response))


def start_streamable_http_client(url: str, bearer_token: Optional[str] = None, timeout: float = 30.0, stdio_command: Optional[str] = None) -> None:
    """Start streamable HTTP to stdio bridge.

    Entry point for starting a streamable HTTP to stdio bridge client.

    Args:
        url: The streamable HTTP endpoint URL to connect to.
        bearer_token: Optional OAuth2 bearer token for authentication. Defaults to None.
        timeout: HTTP client timeout in seconds. Defaults to 30.0.
        stdio_command: Optional command to run for local stdio processing.

    Returns:
        None: This function does not return a value.
    """
    return asyncio.run(_run_streamable_http_to_stdio(url, bearer_token, timeout, stdio_command))


def start_stdio(
    cmd: str, port: int, log_level: str, cors: Optional[List[str]], host: str = "127.0.0.1", sse_path: str = "/sse", message_path: str = "/message", keep_alive: float = KEEP_ALIVE_INTERVAL
) -> None:
    """Start stdio bridge.

    Entry point for starting a stdio to SSE bridge server.

    Args:
        cmd: The command to run as a stdio subprocess.
        port: The port to bind the HTTP server to.
        log_level: The logging level to use.
        cors: Optional list of CORS allowed origins.
        host: The host interface to bind to. Defaults to "127.0.0.1".
        sse_path: Path for the SSE endpoint. Defaults to "/sse".
        message_path: Path for the message endpoint. Defaults to "/message".
        keep_alive: Keep-alive interval in seconds. Defaults to KEEP_ALIVE_INTERVAL.

    Returns:
        None: This function does not return a value.

    Examples:
        >>> # Test parameter validation
        >>> isinstance(KEEP_ALIVE_INTERVAL, int)
        True
        >>> KEEP_ALIVE_INTERVAL > 0
        True
        >>> start_stdio("uvx mcp-server-git", 9000, "info", None)  # doctest: +SKIP
    """
    return asyncio.run(_run_stdio_to_sse(cmd, port, log_level, cors, host, sse_path, message_path, keep_alive))


def start_sse(url: str, bearer_token: Optional[str] = None, timeout: float = 30.0, stdio_command: Optional[str] = None) -> None:
    """Start SSE bridge.

    Entry point for starting an SSE to stdio bridge client.

    Examples:
        >>> # Test parameter defaults
        >>> timeout_default = 30.0
        >>> isinstance(timeout_default, float)
        True
        >>> timeout_default > 0
        True

    Args:
        url: The SSE endpoint URL to connect to.
        bearer_token: Optional OAuth2 bearer token for authentication. Defaults to None.
        timeout: HTTP client timeout in seconds. Defaults to 30.0.
        stdio_command: Optional command to run for local stdio processing.

    Returns:
        None: This function does not return a value.

    Examples:
        >>> start_sse("http://example.com/sse", "token123")  # doctest: +SKIP
    """
    return asyncio.run(_run_sse_to_stdio(url, bearer_token, timeout, stdio_command))


def main(argv: Optional[Sequence[str]] | None = None) -> None:
    """Entry point for the translate module.

    Configures logging, parses arguments, and starts the appropriate bridge
    based on command line options. Handles keyboard interrupts gracefully.

    Args:
        argv: Optional sequence of command line arguments. If None, uses sys.argv[1:].

    Examples:
        >>> # Test argument parsing
        >>> try:
        ...     main(["--stdio", "cat", "--port", "9000"])  # doctest: +SKIP
        ... except SystemExit:
        ...     pass  # Would normally start the server
    """
    args = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        level=getattr(logging, args.logLevel.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Parse header mappings if dynamic environment injection is enabled
    # Pre-normalize mappings once at startup for O(1) lookups per request
    header_mappings: NormalizedMappings | None = None
    if getattr(args, "enable_dynamic_env", False):
        try:
            raw_mappings = parse_header_mappings(getattr(args, "header_to_env", []))
            header_mappings = NormalizedMappings(raw_mappings)
            LOGGER.info(f"Dynamic environment injection enabled with {len(header_mappings)} header mappings")
        except Exception as e:
            LOGGER.error(f"Failed to parse header mappings: {e}")
            raise

    try:
        # Handle gRPC server exposure
        if getattr(args, "grpc", None):
            # First-Party
            from mcpgateway.translate_grpc import expose_grpc_via_sse  # pylint: disable=import-outside-toplevel

            # Parse metadata
            metadata = {}
            if getattr(args, "grpc_metadata", None):
                for item in args.grpc_metadata:
                    if "=" in item:
                        key, value = item.split("=", 1)
                        metadata[key] = value

            asyncio.run(
                expose_grpc_via_sse(
                    target=args.grpc,
                    port=args.port,
                    tls_enabled=getattr(args, "grpc_tls", False),
                    tls_cert=getattr(args, "grpc_cert", None),
                    tls_key=getattr(args, "grpc_key", None),
                    metadata=metadata,
                )
            )

        # Handle local stdio server exposure
        elif args.stdio:
            # Check which protocols to expose
            expose_sse = getattr(args, "expose_sse", False)
            expose_streamable_http = getattr(args, "expose_streamable_http", False)

            # If no protocol specified, default to SSE for backward compatibility
            if not expose_sse and not expose_streamable_http:
                expose_sse = True

            # Use multi-protocol server
            asyncio.run(
                _run_multi_protocol_server(
                    cmd=args.stdio,
                    port=args.port,
                    log_level=args.logLevel,
                    cors=args.cors,
                    host=args.host,
                    expose_sse=expose_sse,
                    expose_streamable_http=expose_streamable_http,
                    sse_path=getattr(args, "ssePath", "/sse"),
                    message_path=getattr(args, "messagePath", "/message"),
                    keep_alive=getattr(args, "keepAlive", KEEP_ALIVE_INTERVAL),
                    stateless=getattr(args, "stateless", False),
                    json_response=getattr(args, "jsonResponse", False),
                    header_mappings=header_mappings,
                )
            )

        # Handle remote connection modes
        elif getattr(args, "connect_sse", None):
            start_sse(args.connect_sse, args.oauth2Bearer, 30.0, args.stdioCommand)
        elif getattr(args, "connect_streamable_http", None):
            start_streamable_http_client(args.connect_streamable_http, args.oauth2Bearer, 30.0, args.stdioCommand)
        elif getattr(args, "connect_grpc", None):
            print("Error: --connect-grpc mode not yet implemented. Use --grpc to expose a gRPC server.", file=sys.stderr)
            sys.exit(1)
        else:
            print("Error: Must specify either --stdio (to expose local server), --grpc (to expose gRPC server), or --connect-sse/--connect-streamable-http (to connect to remote)", file=sys.stderr)
            sys.exit(1)
    except KeyboardInterrupt:
        print("")  # restore shell prompt
        sys.exit(0)
    except (NotImplementedError, ImportError) as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":  # python3 -m mcpgateway.translate ...
    main()
