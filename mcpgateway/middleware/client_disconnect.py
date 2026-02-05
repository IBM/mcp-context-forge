# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/client_disconnect.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Client Disconnect Middleware.

Pure ASGI middleware that detects when a client (e.g., nginx reverse proxy)
closes the connection and cancels the in-flight request handler. This triggers
cleanup of all resources held by the request (DB sessions via get_db's finally
block, HTTP client connections, etc.).

Without this middleware, when nginx's proxy_read_timeout fires (e.g., 60s),
it sends FIN to the gateway but the handler keeps running — the socket enters
CLOSE_WAIT and all request memory (ORM objects, response buffers) is retained
until the handler eventually finishes. Under sustained load this causes a
death spiral: slow requests → nginx timeouts → CLOSE_WAIT accumulation →
OOM → swap thrashing → even slower requests.

This middleware breaks the cycle by cancelling the handler as soon as the
ASGI server signals disconnect, allowing finally blocks to release resources.
"""

# Standard
import asyncio
from contextlib import suppress
from typing import Tuple

# Third-Party
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# First-Party
from mcpgateway.services.logging_service import LoggingService

logger = LoggingService().get_logger(__name__)

# Paths that manage their own disconnect handling (SSE, WebSocket, streaming)
_SELF_MANAGED_PREFIXES: Tuple[str, ...] = (
    "/sse/",
    "/ws/",
    "/mcp/",
)


class ClientDisconnectMiddleware:
    """Cancel HTTP request processing when the client disconnects.

    Uses a message queue to relay ASGI ``receive`` messages to the app while
    a reader task watches for the ``http.disconnect`` event.  When disconnect
    is detected the handler task is cancelled, triggering ``finally`` blocks
    in FastAPI dependencies (e.g. ``get_db`` closing its session).

    Only applies to ``http`` scope; WebSocket and lifespan scopes are passed
    through unchanged.  SSE / WebSocket / MCP streaming paths that already
    implement their own disconnect detection are also skipped.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Skip paths that handle disconnect internally
        path: str = scope.get("path", "")
        if any(path.startswith(prefix) for prefix in _SELF_MANAGED_PREFIXES):
            await self.app(scope, receive, send)
            return

        disconnected = asyncio.Event()
        response_started = False

        # Queue relays ASGI receive messages from the reader to the app.
        recv_queue: asyncio.Queue[Message] = asyncio.Queue()

        async def _reader() -> None:
            """Read from the raw ASGI receive channel and forward to the queue.

            When ``http.disconnect`` arrives, signal via the event rather than
            forwarding — the app should not see the disconnect message since
            we cancel it instead.
            """
            try:
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        disconnected.set()
                        # Put a disconnect message in case app is waiting on receive
                        await recv_queue.put(message)
                        return
                    await recv_queue.put(message)
            except asyncio.CancelledError:
                return

        async def _receive_wrapper() -> Message:
            """Drop-in replacement for ``receive`` that reads from the queue.

            Returns:
                Message: The next ASGI message, or a disconnect message on cancellation.
            """
            try:
                return await recv_queue.get()
            except asyncio.CancelledError:
                return {"type": "http.disconnect"}

        async def _send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            # Don't send if client already gone and response hasn't started
            if disconnected.is_set() and not response_started:
                return
            try:
                await send(message)
            except Exception:
                # Client gone — send will fail, that's expected
                disconnected.set()

        reader_task = asyncio.create_task(_reader())
        handler_task = asyncio.create_task(self.app(scope, _receive_wrapper, _send_wrapper))

        async def _cancel_on_disconnect() -> None:
            """Wait for disconnect, then cancel the handler."""
            await disconnected.wait()
            if not handler_task.done():
                handler_task.cancel()

        cancel_task = asyncio.create_task(_cancel_on_disconnect())

        try:
            await handler_task
        except asyncio.CancelledError:
            if disconnected.is_set():
                logger.debug("Request cancelled: client disconnected (%s)", path)
            else:
                raise
        finally:
            # Clean up helper tasks
            for task in (reader_task, cancel_task):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
