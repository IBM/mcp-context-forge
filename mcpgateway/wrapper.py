# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/wrapper.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

MCP Gateway Wrapper.
MCP Client (stdio) <-> MCP Gateway Bridge

This module implements a wrapper stdio bridge that facilitates
interaction between the MCP client and the MCP gateway.
It provides several functionalities, including listing tools,
invoking tools, managing resources, retrieving prompts,
and handling tool calls via the MCP gateway.

- All JSON-RPC traffic is written to stdout.
- All logs/diagnostics are written to stderr, ensuring clean separation.

Environment Variables
---------------------
- **MCP_SERVER_URL** (or `--url`): Gateway MCP endpoint URL.
- **MCP_AUTH** (or `--auth`): Authorization header value.
- **MCP_TOOL_CALL_TIMEOUT** (or `--timeout`): Response timeout in seconds (default: 60).
- **MCP_WRAPPER_LOG_LEVEL** (or `--log-level`): Logging level, or OFF to disable.
- **CONCURRENCY**: Max concurrent tool calls (default: 10).

Example usage:
--------------

Method 1: Using environment variables
    $ export MCP_SERVER_URL='http://localhost:4444/servers/UUID/mcp'
    $ export MCP_AUTH='Bearer <token>'
    $ export MCP_TOOL_CALL_TIMEOUT=120
    $ export MCP_WRAPPER_LOG_LEVEL=DEBUG
    $ python3 -m mcpgateway.wrapper

Method 2: Using command-line arguments
    $ python3 -m mcpgateway.wrapper --url 'http://localhost:4444/servers/UUID/mcp' --auth 'Bearer <token>' --timeout 120 --log-level DEBUG
"""

# Future
from __future__ import annotations

# Standard
import argparse
import asyncio
from contextlib import suppress
from dataclasses import dataclass
import errno
import logging
import os
import signal
import sys
from typing import Any, AsyncIterator, Dict, List, Optional, Union
from urllib.parse import urlencode

# Third-Party
import httpx
import orjson

# First-Party
from mcpgateway.utils.retry_manager import ResilientHttpClient

# -----------------------
# Configuration Defaults
# -----------------------
DEFAULT_CONCURRENCY = int(os.environ.get("CONCURRENCY", "10"))
DEFAULT_CONNECT_TIMEOUT = 15
DEFAULT_RESPONSE_TIMEOUT = float(os.environ.get("MCP_TOOL_CALL_TIMEOUT", "60"))

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INTERNAL_ERROR = -32603
JSONRPC_SERVER_ERROR = -32000

CONTENT_TYPE = os.getenv("FORGE_CONTENT_TYPE", "application/json")

# Global logger
logger = logging.getLogger("mcpgateway.wrapper")
logger.addHandler(logging.StreamHandler(sys.stderr))
logger.propagate = False
logger.disabled = True  # default: disabled

# Shutdown flag
_shutdown = asyncio.Event()


def _mark_shutdown():
    """Mark the shutdown flag for graceful termination.
    This is triggered when stdin closes, stdout fails, or a signal is caught.

    Args:
        None

    Examples:
        >>> _mark_shutdown()  # doctest: +ELLIPSIS
        >>> shutting_down()
        True
        >>> # Reset for following doctests:
        >>> _ = _shutdown.clear()
    """
    if not _shutdown.is_set():
        _shutdown.set()


def shutting_down() -> bool:
    """Check whether the server is shutting down.

    Args:
        None

    Returns:
        bool: True if shutdown has been triggered, False otherwise.

    Examples:
        >>> shutting_down()
        False
    """
    return _shutdown.is_set()


# -----------------------
# Utilities
# -----------------------
def setup_logging(level: Optional[str]) -> None:
    """Configure logging for the wrapper.

    Args:
        level: Logging level (e.g. "INFO", "DEBUG"), or OFF/None to disable.

    Examples:
        >>> setup_logging("DEBUG")
        >>> logger.disabled
        False
        >>> setup_logging("OFF")
        >>> logger.disabled
        True
    """
    if not level:
        logger.disabled = True
        return

    log_level = level.strip().upper()
    if log_level in {"OFF", "NONE", "DISABLE", "FALSE", "0"}:
        logger.disabled = True
        return

    logger.setLevel(getattr(logging, log_level, logging.INFO))
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    for handler in logger.handlers:
        handler.setFormatter(formatter)
    logger.disabled = False


def convert_url(url: str) -> str:
    """Normalize an MCP server URL.

    - If it ends with `/sse`, replace with `/mcp`.
    - If it ends with `/mcp` already, leave it.
    - Otherwise, append `/mcp`.

    Args:
        url: The input server URL.

    Returns:
        str: Normalized MCP URL.

    Examples:
        >>> convert_url("http://localhost:4444/servers/uuid")
        'http://localhost:4444/servers/uuid/mcp/'
        >>> convert_url("http://localhost:4444/servers/uuid/sse")
        'http://localhost:4444/servers/uuid/mcp/'
        >>> convert_url("http://localhost:4444/servers/uuid/mcp")
        'http://localhost:4444/servers/uuid/mcp/'
    """
    if url.endswith("/mcp") or url.endswith("/mcp/"):
        if url.endswith("/mcp"):
            return url + "/"
        return url
    if url.endswith("/sse"):
        return url.replace("/sse", "/mcp/")
    return url + "/mcp/"


def send_to_stdout(obj: Union[dict, str, bytes]) -> None:
    """Write JSON-serializable object to stdout.

    Args:
        obj: Object to serialize and write. Falls back to str() if JSON fails.

    Notes:
        If writing fails (e.g., broken pipe), triggers shutdown.
    """
    try:
        # orjson.dumps returns bytes
        line = orjson.dumps(obj)
    except Exception:
        if isinstance(obj, bytes):
            line = obj
        else:
            line = str(obj).encode("utf-8")
    try:
        # Check if sys.stdout has buffer attribute
        # If not (eg. some mocks), fall back to write str
        if hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(line + b"\n")
            sys.stdout.buffer.flush()
        else:
            # Fallback for testing environments that mock sys.stdout but not buffer
            sys.stdout.write(line.decode("utf-8") + "\n")
            sys.stdout.flush()
    except OSError as e:
        if e.errno in (errno.EPIPE, errno.EINVAL):
            _mark_shutdown()
        else:
            _mark_shutdown()


def make_error(message: str, code: int = JSONRPC_INTERNAL_ERROR, data: Any = None) -> dict:
    """Construct a JSON-RPC error response.

    Args:
        message: Error message.
        code: JSON-RPC error code (default -32603).
        data: Optional extra error data.

    Returns:
        dict: JSON-RPC error object.

    Examples:
        >>> make_error("Invalid input", code=-32600)
        {'jsonrpc': '2.0', 'id': 'bridge', 'error': {'code': -32600, 'message': 'Invalid input'}}
        >>> make_error("Oops", data={"info": 1})["error"]["data"]
        {'info': 1}
    """
    err: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": "bridge",
        "error": {"code": code, "message": message},
    }
    if data is not None:
        err["error"]["data"] = data
    return err


async def stdin_reader(queue: "asyncio.Queue[Union[dict, list, str, None]]") -> None:
    """Read lines from stdin and push parsed JSON into a queue.

    Args:
        queue: Target asyncio.Queue where parsed messages are enqueued.

    Notes:
        - On EOF, pushes None and triggers shutdown.
        - Invalid JSON produces a JSON-RPC error object.

    Examples:
        >>> # Example pattern (not executed): asyncio.create_task(stdin_reader(q))
        >>> True
        True
    """
    while True:
        # read bytes directly if possible
        if hasattr(sys.stdin, "buffer"):
            line = await asyncio.to_thread(sys.stdin.buffer.readline)
        else:
            # Fallback
            line_str = await asyncio.to_thread(sys.stdin.readline)
            line = line_str.encode("utf-8") if line_str else b""

        if not line:
            await queue.put(None)
            _mark_shutdown()
            break

        line = line.strip()
        if not line:
            continue
        try:
            # orjson.loads accepts bytes
            obj = orjson.loads(line)
        except Exception:
            # Decode for error message if needed
            try:
                line_str = line.decode("utf-8", errors="replace")
            except Exception:
                line_str = str(line)
            obj = make_error("Invalid JSON from stdin", JSONRPC_PARSE_ERROR, line_str)
        await queue.put(obj)


# -----------------------
# Stream Parsers
# -----------------------
async def ndjson_lines(resp: httpx.Response) -> AsyncIterator[bytes]:
    """Parse newline-delimited JSON (NDJSON) from an HTTP response.

    Args:
        resp: httpx.Response with NDJSON content.

    Yields:
        bytes: Individual JSON lines as bytes.

    Examples:
        >>> # This function is a parser for network streams; doctest uses patterns only.
        >>> True
        True
    """
    # read bytes directly if possible
    partial_line = b""
    async for chunk in resp.aiter_bytes():
        if shutting_down():
            break
        if not chunk:
            continue

        # Split chunk into lines, handling partial line from previous chunk
        lines = (partial_line + chunk).split(b"\n")

        # The last element is always the new partial line (might be empty if chunk ended with newline)
        partial_line = lines.pop()

        for line in lines:
            if line.strip():
                yield line.strip()

    # Process remaining partial line
    if partial_line.strip():
        yield partial_line.strip()


async def sse_events(resp: httpx.Response) -> AsyncIterator[bytes]:
    """Parse Server-Sent Events (SSE) from an HTTP response.

    Args:
        resp: httpx.Response with SSE content.

    Yields:
        bytes: Event payload data lines (joined).
    """
    partial_line = b""
    event_lines: List[bytes] = []

    async for chunk in resp.aiter_bytes():
        if shutting_down():
            break
        if not chunk:
            continue

        # Split chunk into lines
        lines = (partial_line + chunk).split(b"\n")
        partial_line = lines.pop()

        for line in lines:
            line = line.rstrip(b"\r")
            if not line:
                if event_lines:
                    yield b"\n".join(event_lines)
                    event_lines = []
                continue
            if line.startswith(b":"):
                continue

            if b":" in line:
                field, value = line.split(b":", 1)
                value = value.lstrip(b" ")
            else:
                field, value = line, b""

            if field == b"data":
                event_lines.append(value)

    # Process remaining partial line if any (though standard SSE ends with \n\n)
    if partial_line:
        line = partial_line.rstrip(b"\r")
        # Process the partial line same as above
        if line and not line.startswith(b":"):
            if b":" in line:
                field, value = line.split(b":", 1)
                value = value.lstrip(b" ")
            else:
                field, value = line, b""
            if field == b"data":
                event_lines.append(value)

    # Always yield any remaining accumulated event data
    if event_lines:
        yield b"\n".join(event_lines)


# -----------------------
# Core HTTP forwarder
# -----------------------
async def forward_once(
    client: ResilientHttpClient,
    settings: "Settings",
    payload: Union[str, Dict[str, Any], List[Any]],
) -> None:
    """Forward a single JSON-RPC payload to the MCP gateway and stream responses.

    The function:
    - Sets content negotiation headers (JSON, NDJSON, SSE)
    - Adds Authorization header when configured
    - Streams the gateway response and forwards every JSON object to stdout
      (supports application/json, application/x-ndjson, and text/event-stream)

    Args:
        client: Resilient HTTP client used to make the request.
        settings: Bridge configuration (URL, auth, timeouts).
        payload: JSON-RPC request payload as str/dict/list.
    """
    if shutting_down():
        return

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json, application/x-ndjson, text/event-stream",
    }
    if settings.auth_header:
        headers["Authorization"] = settings.auth_header

    # Step 1: Decide content type (manual override > auto-detect)
    content_type = getattr(settings, "content_type", None) or CONTENT_TYPE

    if content_type == "application/x-www-form-urlencoded":
        # Always encode as form data
        if isinstance(payload, dict):
            body = urlencode(payload)
        else:
            body = str(payload)
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    elif content_type == "application/json":
        # Force JSON
        body = payload if isinstance(payload, str) else orjson.dumps(payload).decode()
        headers["Content-Type"] = "application/json; charset=utf-8"

    else:
        # Auto-detect
        if isinstance(payload, dict) and all(isinstance(v, (str, int, float, bool, type(None))) for v in payload.values()):
            body = urlencode(payload)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = payload if isinstance(payload, str) else orjson.dumps(payload).decode()
            headers["Content-Type"] = "application/json; charset=utf-8"

    body_bytes = body.encode("utf-8")

    # Step 2: Send request and process response
    async with client.stream("POST", settings.server_url, data=body_bytes, headers=headers) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        status = resp.status_code
        logger.debug("HTTP %s %s", status, ctype)

        if shutting_down():
            return

        if status < 200 or status >= 300:
            send_to_stdout(make_error(f"HTTP {status}", code=status))
            return

        async def _process_line(line: Union[str, bytes]):
            """
            Asynchronously processes a single line of text/bytes, expected to be a valid JSON.

            If the system is shutting down, the function returns immediately.
            Otherwise, it attempts to parse the line as JSON and sends the resulting object to stdout.
            If parsing fails, logs a warning and sends a standardized error response to stdout.

            Args:
                line (Union[str, bytes]): Valid JSON object (bytes optimized).
            """
            if shutting_down():
                return
            try:
                # orjson.loads accepts bytes or str
                obj = orjson.loads(line)
                send_to_stdout(obj)
            except Exception:
                logger.warning("Invalid JSON from server: %s", line)
                # Ensure line is str for error message
                line_str = line if isinstance(line, str) else str(line)
                send_to_stdout(make_error("Invalid JSON from server", JSONRPC_PARSE_ERROR, line_str))

        # Step 3: Handle response content types
        if "event-stream" in ctype:
            async for data_payload in sse_events(resp):
                if shutting_down():
                    break
                if not data_payload:
                    continue
                await _process_line(data_payload)
            return

        if "x-ndjson" in ctype or "ndjson" in ctype:
            async for line in ndjson_lines(resp):
                if shutting_down():
                    break
                await _process_line(line)
            return

        if "application/json" in ctype:
            raw = await resp.aread()
            if not shutting_down():
                # raw is bytes
                try:
                    send_to_stdout(orjson.loads(raw))
                except Exception:
                    send_to_stdout(make_error("Invalid JSON response", JSONRPC_PARSE_ERROR, raw.decode("utf-8", "replace")))
            return

        # Fallback: try parsing as NDJSON
        async for line in ndjson_lines(resp):
            if shutting_down():
                break
            await _process_line(line)


async def make_request(
    client: ResilientHttpClient,
    settings: "Settings",
    payload: Union[str, Dict[str, Any], List[Any]],
    *,
    max_retries: int = 5,
    base_delay: float = 0.25,
) -> None:
    """Make a gateway request with retry/backoff around a single forward attempt.

    Args:
        client: Resilient HTTP client used to make the request.
        settings: Bridge configuration (URL, auth, timeouts).
        payload: JSON-RPC request payload as str/dict/list.
        max_retries: Maximum retry attempts upon exceptions (default 5).
        base_delay: Base delay in seconds for exponential backoff (default 0.25).
    """
    attempt = 0
    while not shutting_down():
        try:
            await forward_once(client, settings, payload)
            return
        except Exception as e:
            if shutting_down():
                return
            logger.warning("Network or unexpected error in forward_once: %s", e)
            attempt += 1
            if attempt > max_retries:
                send_to_stdout(make_error("max retries exceeded", JSONRPC_SERVER_ERROR))
                return
            delay = min(base_delay * (2 ** (attempt - 1)), 8.0)
            await asyncio.sleep(delay)


# -----------------------
# Main loop & CLI
# -----------------------
@dataclass
class Settings:
    """Bridge configuration settings.

    Args:
        server_url: MCP server URL
        auth_header: Authorization header (optional)
        connect_timeout: HTTP connect timeout in seconds
        response_timeout: Max response wait in seconds
        concurrency: Max concurrent tool calls
        log_level: Logging verbosity

    Examples:
        >>> s = Settings("http://x/mcp", "Bearer token", 5, 10, 2, "DEBUG")
        >>> s.server_url
        'http://x/mcp'
        >>> s.concurrency
        2
    """

    server_url: str
    auth_header: Optional[str]
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    response_timeout: float = DEFAULT_RESPONSE_TIMEOUT
    concurrency: int = DEFAULT_CONCURRENCY
    log_level: Optional[str] = None


async def main_async(settings: Settings) -> None:
    """Main async loop: reads stdin JSON lines and forwards them to the gateway.

    - Spawns a reader task that pushes parsed lines to a queue.
    - Uses a semaphore to cap concurrent requests.
    - Creates tasks to forward each queued payload.
    - Gracefully shuts down on EOF or signals.

    Args:
        settings: Bridge configuration settings.

    Examples:
        >>> # Smoke-test structure only; no network or stdin in doctest.
        >>> settings = Settings("http://x/mcp", None)
        >>> async def _run_once():
        ...     q = asyncio.Queue()
        ...     # Immediately signal shutdown by marking the queue end:
        ...     await q.put(None)
        ...     _mark_shutdown()
        ...     # Minimal run: create then cancel tasks cleanly.
        ...     await asyncio.sleep(0)
        >>> # Note: We avoid running main_async here due to stdin/network.
        >>> True
        True
    """
    queue: "asyncio.Queue[Union[dict, list, str, None]]" = asyncio.Queue()
    reader_task = asyncio.create_task(stdin_reader(queue))

    sem = asyncio.Semaphore(settings.concurrency)

    httpx_timeout = httpx.Timeout(
        connect=settings.connect_timeout,
        read=settings.response_timeout,
        write=settings.response_timeout,
        pool=settings.response_timeout,
    )

    client_args = {"timeout": httpx_timeout, "http2": True}
    resilient = ResilientHttpClient(
        max_retries=5,
        base_backoff=0.25,
        max_delay=8.0,
        jitter_max=0.25,
        client_args=client_args,
    )

    tasks: set[asyncio.Task[None]] = set()
    try:
        while not shutting_down():
            item = await queue.get()
            if item is None:
                break

            async def _worker(payload=item):
                """
                Executes an asynchronous request with concurrency control.

                Acquires a semaphore to limit the number of concurrent executions.
                If the system is not shutting down, sends the given payload using `make_request`.

                Args:
                    payload (Any): The data to be sent in the request. Defaults to `item`.
                """
                async with sem:
                    if not shutting_down():
                        await make_request(resilient, settings, payload)

            t = asyncio.create_task(_worker())
            tasks.add(t)
            t.add_done_callback(lambda fut, s=tasks: s.discard(fut))

        _mark_shutdown()
        for t in list(tasks):
            t.cancel()
        if tasks:
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks)
    finally:
        reader_task.cancel()
        with suppress(Exception):
            await reader_task
        with suppress(Exception):
            await resilient.aclose()


def parse_args() -> Settings:
    """Parse CLI arguments and environment variables into Settings.

    Recognized flags:
        --url / MCP_SERVER_URL
        --auth / MCP_AUTH
        --timeout / MCP_TOOL_CALL_TIMEOUT
        --log-level / MCP_WRAPPER_LOG_LEVEL

    Returns:
        Settings: Parsed and normalized configuration.

    Examples:
        >>> import sys, os
        >>> _argv = sys.argv
        >>> sys.argv = ["prog", "--url", "http://localhost:4444/servers/u"]
        >>> try:
        ...     s = parse_args()
        ...     s.server_url.endswith("/mcp/")
        ... finally:
        ...     sys.argv = _argv
        True
    """
    parser = argparse.ArgumentParser(description="Stdio MCP Client <-> MCP HTTP Bridge")
    parser.add_argument("--url", default=os.environ.get("MCP_SERVER_URL"), help="MCP server URL (env: MCP_SERVER_URL)")
    parser.add_argument("--auth", default=os.environ.get("MCP_AUTH"), help="Authorization header value (env: MCP_AUTH)")
    parser.add_argument("--timeout", default=os.environ.get("MCP_TOOL_CALL_TIMEOUT"), help="Response timeout in seconds")
    parser.add_argument(
        "--log-level",
        default=os.environ.get("MCP_WRAPPER_LOG_LEVEL", "INFO"),
        help="Enable logging at this level (case-insensitive, default: disabled)",
    )
    args = parser.parse_args()

    if not args.url:
        print("Error: MCP server URL must be provided via --url or MCP_SERVER_URL", file=sys.stderr)
        sys.exit(2)

    server_url = convert_url(args.url)
    response_timeout = float(args.timeout) if args.timeout else DEFAULT_RESPONSE_TIMEOUT

    return Settings(
        server_url=server_url,
        auth_header=args.auth,
        connect_timeout=DEFAULT_CONNECT_TIMEOUT,
        response_timeout=response_timeout,
        log_level=args.log_level,
        concurrency=DEFAULT_CONCURRENCY,
    )


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Install SIGINT/SIGTERM handlers that trigger graceful shutdown.

    Args:
        loop: The asyncio event loop to attach handlers to.

    Examples:
        >>> import asyncio
        >>> loop = asyncio.new_event_loop()
        >>> _install_signal_handlers(loop)  # doctest: +ELLIPSIS
        >>> loop.close()
    """
    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _mark_shutdown)


def main() -> None:
    """Entry point for the MCP stdio wrapper.

    - Parses args/env vars into Settings
    - Configures logging
    - Runs the async main loop with signal handling

    Args:
        None
    """
    settings = parse_args()
    setup_logging(settings.log_level)
    if not logger.disabled:
        logger.info("Starting MCP stdio wrapper -> %s", settings.server_url)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)

    try:
        loop.run_until_complete(main_async(settings))
    finally:
        loop.run_until_complete(asyncio.sleep(0))
        with suppress(Exception):
            loop.close()
        if not logger.disabled:
            logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
