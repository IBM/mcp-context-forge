# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/sse_transport.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

SSE Transport Implementation.
This module implements Server-Sent Events (SSE) transport for MCP,
providing server-to-client streaming with proper session management.
"""

# Standard
import asyncio
import logging
import time
from collections import deque
from typing import Any, AsyncGenerator, Dict, Optional
import uuid

# Third-Party
from fastapi import Request
import orjson
from sse_starlette.sse import EventSourceResponse

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.transports.base import Transport

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Pre-computed SSE frame components for performance
_SSE_EVENT_PREFIX = b"event: "
_SSE_DATA_PREFIX = b"\r\ndata: "
_SSE_RETRY_PREFIX = b"\r\nretry: "
_SSE_FRAME_END = b"\r\n\r\n"


def _build_sse_frame(event: bytes, data: bytes, retry: int) -> bytes:
    """Build SSE frame as bytes to avoid encode/decode overhead.

    Args:
        event: SSE event type as bytes (e.g., b'message', b'keepalive', b'error')
        data: JSON data as bytes (from orjson.dumps)
        retry: Retry timeout in milliseconds

    Returns:
        Complete SSE frame as bytes

    Note:
        Uses hardcoded CRLF (\\r\\n) separators matching sse_starlette's
        ServerSentEvent.DEFAULT_SEPARATOR. If custom separators are ever
        needed, this function would need to accept a sep parameter.

    Examples:
        >>> _build_sse_frame(b"message", b'{"test": 1}', 15000)
        b'event: message\\r\\ndata: {"test": 1}\\r\\nretry: 15000\\r\\n\\r\\n'

        >>> _build_sse_frame(b"keepalive", b"{}", 15000)
        b'event: keepalive\\r\\ndata: {}\\r\\nretry: 15000\\r\\n\\r\\n'
    """
    return _SSE_EVENT_PREFIX + event + _SSE_DATA_PREFIX + data + _SSE_RETRY_PREFIX + str(retry).encode() + _SSE_FRAME_END


class SSETransport(Transport):
    """Transport implementation using Server-Sent Events with proper session management.

    This transport implementation uses Server-Sent Events (SSE) for real-time
    communication between the MCP gateway and clients. It provides streaming
    capabilities with automatic session management and keepalive support.

    Examples:
        >>> # Create SSE transport with default URL
        >>> transport = SSETransport()
        >>> transport
        <mcpgateway.transports.sse_transport.SSETransport object at ...>

        >>> # Create SSE transport with custom URL
        >>> transport = SSETransport("http://localhost:8080")
        >>> transport._base_url
        'http://localhost:8080'

        >>> # Check initial connection state
        >>> import asyncio
        >>> asyncio.run(transport.is_connected())
        False

        >>> # Verify it's a proper Transport subclass
        >>> isinstance(transport, Transport)
        True
        >>> issubclass(SSETransport, Transport)
        True

        >>> # Check session ID generation
        >>> transport.session_id
        '...'
        >>> len(transport.session_id) > 0
        True

        >>> # Verify required methods exist
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

    def __init__(self, base_url: str = None):
        """Initialize SSE transport.

        Args:
            base_url: Base URL for client message endpoints

        Examples:
            >>> # Test default initialization
            >>> transport = SSETransport()
            >>> transport._connected
            False
            >>> transport._message_queue is not None
            True
            >>> transport._client_gone is not None
            True
            >>> len(transport._session_id) > 0
            True

            >>> # Test custom base URL
            >>> transport = SSETransport("https://api.example.com")
            >>> transport._base_url
            'https://api.example.com'

            >>> # Test session ID uniqueness
            >>> transport1 = SSETransport()
            >>> transport2 = SSETransport()
            >>> transport1.session_id != transport2.session_id
            True
        """
        self._base_url = base_url or f"http://{settings.host}:{settings.port}"
        self._connected = False
        self._message_queue = asyncio.Queue()
        self._client_gone = asyncio.Event()
        self._session_id = str(uuid.uuid4())

        logger.info("Creating SSE transport with base_url=%s, session_id=%s", self._base_url, self._session_id)

    async def connect(self) -> None:
        """Set up SSE connection.

        Examples:
            >>> # Test connection setup
            >>> transport = SSETransport()
            >>> import asyncio
            >>> asyncio.run(transport.connect())
            >>> transport._connected
            True
            >>> asyncio.run(transport.is_connected())
            True
        """
        self._connected = True
        logger.info("SSE transport connected: %s", self._session_id)

    async def disconnect(self) -> None:
        """Clean up SSE connection.

        Examples:
            >>> # Test disconnection
            >>> transport = SSETransport()
            >>> import asyncio
            >>> asyncio.run(transport.connect())
            >>> asyncio.run(transport.disconnect())
            >>> transport._connected
            False
            >>> transport._client_gone.is_set()
            True
            >>> asyncio.run(transport.is_connected())
            False

            >>> # Test disconnection when already disconnected
            >>> transport = SSETransport()
            >>> asyncio.run(transport.disconnect())
            >>> transport._connected
            False
        """
        if self._connected:
            self._connected = False
            self._client_gone.set()
            logger.info("SSE transport disconnected: %s", self._session_id)

    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send a message over SSE.

        Args:
            message: Message to send

        Raises:
            RuntimeError: If transport is not connected
            Exception: If unable to put message to queue

        Examples:
            >>> # Test sending message when connected
            >>> transport = SSETransport()
            >>> import asyncio
            >>> asyncio.run(transport.connect())
            >>> message = {"jsonrpc": "2.0", "method": "test", "id": 1}
            >>> asyncio.run(transport.send_message(message))
            >>> transport._message_queue.qsize()
            1

            >>> # Test sending message when not connected
            >>> transport = SSETransport()
            >>> try:
            ...     asyncio.run(transport.send_message({"test": "message"}))
            ... except RuntimeError as e:
            ...     print("Expected error:", str(e))
            Expected error: Transport not connected

            >>> # Test message format validation
            >>> transport = SSETransport()
            >>> asyncio.run(transport.connect())
            >>> valid_message = {"jsonrpc": "2.0", "method": "initialize", "params": {}}
            >>> isinstance(valid_message, dict)
            True
            >>> "jsonrpc" in valid_message
            True

            >>> # Test exception handling in queue put
            >>> transport = SSETransport()
            >>> asyncio.run(transport.connect())
            >>> # Create a full queue to trigger exception
            >>> transport._message_queue = asyncio.Queue(maxsize=1)
            >>> asyncio.run(transport._message_queue.put({"dummy": "message"}))
            >>> # Now queue is full, next put should fail
            >>> try:
            ...     asyncio.run(asyncio.wait_for(transport.send_message({"test": "message"}), timeout=0.1))
            ... except asyncio.TimeoutError:
            ...     print("Queue full as expected")
            Queue full as expected
        """
        if not self._connected:
            raise RuntimeError("Transport not connected")

        try:
            await self._message_queue.put(message)
            logger.debug("Message queued for SSE: %s, method=%s", self._session_id, message.get("method", "(response)"))
        except Exception as e:
            logger.error("Failed to queue message: %s", e)
            raise

    async def receive_message(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receive messages from the client over SSE transport.

        This method implements a continuous message-receiving pattern for SSE transport.
        Since SSE is primarily a server-to-client communication channel, this method
        yields an initial initialize placeholder message and then enters a waiting loop.
        The actual client messages are received via a separate HTTP POST endpoint
        (not handled in this method).

        The method will continue running until either:
        1. The connection is explicitly disconnected (client_gone event is set)
        2. The receive loop is cancelled from outside

        Yields:
            Dict[str, Any]: JSON-RPC formatted messages. The first yielded message is always
                an initialize placeholder with the format:
                {"jsonrpc": "2.0", "method": "initialize", "id": 1}

        Raises:
            RuntimeError: If the transport is not connected when this method is called
            asyncio.CancelledError: When the SSE receive loop is cancelled externally

        Examples:
            >>> # Test receive message when connected
            >>> transport = SSETransport()
            >>> import asyncio
            >>> asyncio.run(transport.connect())
            >>> async def test_receive():
            ...     async for msg in transport.receive_message():
            ...         return msg
            ...     return None
            >>> result = asyncio.run(test_receive())
            >>> result
            {'jsonrpc': '2.0', 'method': 'initialize', 'id': 1}

            >>> # Test receive message when not connected
            >>> transport = SSETransport()
            >>> try:
            ...     async def test_receive():
            ...         async for msg in transport.receive_message():
            ...             pass
            ...     asyncio.run(test_receive())
            ... except RuntimeError as e:
            ...     print("Expected error:", str(e))
            Expected error: Transport not connected

            >>> # Verify generator behavior
            >>> transport = SSETransport()
            >>> import inspect
            >>> inspect.isasyncgenfunction(transport.receive_message)
            True
        """
        if not self._connected:
            raise RuntimeError("Transport not connected")

        # For SSE, we set up a loop to wait for messages which are delivered via POST
        # Most messages come via the POST endpoint, but we yield an initial initialize placeholder
        # to keep the receive loop running
        yield {"jsonrpc": "2.0", "method": "initialize", "id": 1}

        # Continue waiting for cancellation
        try:
            while not self._client_gone.is_set():
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info("SSE receive loop cancelled for session %s", self._session_id)
            raise
        finally:
            logger.info("SSE receive loop ended for session %s", self._session_id)

    async def _get_message_with_timeout(self, timeout: Optional[float]) -> Optional[Dict[str, Any]]:
        """Get message from queue with timeout, returns None on timeout.

        Uses asyncio.wait() to avoid TimeoutError exception overhead.

        Args:
            timeout: Timeout in seconds, or None for no timeout

        Returns:
            Message dict if received, None if timeout occurred

        Raises:
            asyncio.CancelledError: If the operation is cancelled externally
        """
        if timeout is None:
            return await self._message_queue.get()

        get_task = asyncio.create_task(self._message_queue.get())
        try:
            done, _ = await asyncio.wait({get_task}, timeout=timeout)
        except asyncio.CancelledError:
            get_task.cancel()
            try:
                await get_task
            except asyncio.CancelledError:
                pass
            raise

        if get_task in done:
            return get_task.result()

        # Timeout - cancel pending task, but return the result if it completed in the race window.
        get_task.cancel()
        try:
            return await get_task
        except asyncio.CancelledError:
            return None

    async def is_connected(self) -> bool:
        """Check if transport is connected.

        Returns:
            True if connected

        Examples:
            >>> # Test initial state
            >>> transport = SSETransport()
            >>> import asyncio
            >>> asyncio.run(transport.is_connected())
            False

            >>> # Test after connection
            >>> transport = SSETransport()
            >>> asyncio.run(transport.connect())
            >>> asyncio.run(transport.is_connected())
            True

            >>> # Test after disconnection
            >>> transport = SSETransport()
            >>> asyncio.run(transport.connect())
            >>> asyncio.run(transport.disconnect())
            >>> asyncio.run(transport.is_connected())
            False
        """
        return self._connected

    async def create_sse_response(self, request: Request) -> EventSourceResponse:
        """Create SSE response for streaming.

        Args:
            request: FastAPI request (used for disconnection detection)

        Returns:
            SSE response object

        Examples:
            >>> # Test SSE response creation
            >>> transport = SSETransport("http://localhost:8000")
            >>> # Note: This method requires a FastAPI Request object
            >>> # and cannot be easily tested in doctest environment
            >>> callable(transport.create_sse_response)
            True
        """
        endpoint_url = f"{self._base_url}/message?session_id={self._session_id}"

        async def event_generator():
            """Generate SSE events.

            Yields:
                SSE event as bytes (pre-formatted SSE frame)
            """
            # Send the endpoint event first
            yield _build_sse_frame(b"endpoint", endpoint_url.encode(), settings.sse_retry_timeout)

            # Send keepalive immediately to help establish connection (if enabled)
            if settings.sse_keepalive_enabled:
                yield _build_sse_frame(b"keepalive", b"{}", settings.sse_retry_timeout)

            consecutive_errors = 0
            max_consecutive_errors = 3  # Exit after 3 consecutive errors (likely client disconnected)

            # Rapid yield detection: If we're yielding faster than expected, client is likely disconnected
            # but ASGI server isn't properly signaling it. Track yield timestamps in a sliding window.
            yield_timestamps: deque = deque(maxlen=settings.sse_rapid_yield_max + 1) if settings.sse_rapid_yield_max > 0 else None
            rapid_yield_window_sec = settings.sse_rapid_yield_window_ms / 1000.0
            last_yield_time = time.monotonic()

            def check_rapid_yield() -> bool:
                """Check if yields are happening too fast, return True if should disconnect."""
                nonlocal last_yield_time
                if yield_timestamps is None:
                    return False
                now = time.monotonic()
                yield_timestamps.append(now)
                # Also check time since last yield - if < 10ms, that's suspicious
                time_since_last = now - last_yield_time
                last_yield_time = now
                if time_since_last < 0.01:  # Less than 10ms between yields is very fast
                    if len(yield_timestamps) > settings.sse_rapid_yield_max:
                        oldest = yield_timestamps[0]
                        elapsed = now - oldest
                        if elapsed < rapid_yield_window_sec:
                            logger.error(
                                "SSE rapid yield detected (%d yields in %.3fs, last interval %.3fs), client disconnected: %s",
                                len(yield_timestamps), elapsed, time_since_last, self._session_id
                            )
                            return True
                return False

            try:
                while not self._client_gone.is_set():
                    # Check if client has disconnected via request state
                    if await request.is_disconnected():
                        logger.info("SSE client disconnected (detected via request): %s", self._session_id)
                        self._client_gone.set()
                        break

                    try:
                        # Use timeout-based polling only when keepalive is enabled
                        if not settings.sse_keepalive_enabled:
                            message = await self._message_queue.get()
                        else:
                            message = await self._get_message_with_timeout(settings.sse_keepalive_interval)

                        if message is not None:
                            json_bytes = orjson.dumps(message, option=orjson.OPT_SERIALIZE_NUMPY)

                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug("Sending SSE message: %s", json_bytes.decode())

                            yield _build_sse_frame(b"message", json_bytes, settings.sse_retry_timeout)
                            consecutive_errors = 0  # Reset on successful send

                            # Check for rapid yields after message send
                            if check_rapid_yield():
                                self._client_gone.set()
                                break
                        elif settings.sse_keepalive_enabled:
                            # Timeout - send keepalive
                            yield _build_sse_frame(b"keepalive", b"{}", settings.sse_retry_timeout)
                            consecutive_errors = 0  # Reset on successful send
                            # Check for rapid yields after keepalive too
                            if check_rapid_yield():
                                self._client_gone.set()
                                break
                            # We waited for the timeout, so reset rapid yield detection
                            if yield_timestamps is not None:
                                yield_timestamps.clear()

                    except GeneratorExit:
                        # Client disconnected - generator is being closed
                        logger.info("SSE generator exit (client disconnected): %s", self._session_id)
                        self._client_gone.set()
                        break
                    except Exception as e:
                        consecutive_errors += 1
                        logger.warning("Error processing SSE message (attempt %d/%d): %s", consecutive_errors, max_consecutive_errors, e)
                        if consecutive_errors >= max_consecutive_errors:
                            logger.info("SSE too many consecutive errors, assuming client disconnected: %s", self._session_id)
                            self._client_gone.set()
                            break
                        # Don't yield error frame - it could cause more errors if client is gone

            except asyncio.CancelledError:
                logger.info("SSE event generator cancelled: %s", self._session_id)
                self._client_gone.set()
            except GeneratorExit:
                logger.info("SSE generator exit: %s", self._session_id)
                self._client_gone.set()
            except Exception as e:
                logger.error("SSE event generator error: %s", e)
                self._client_gone.set()
            finally:
                logger.info("SSE event generator completed: %s", self._session_id)
                self._client_gone.set()  # Always set client_gone on exit to clean up

        return EventSourceResponse(
            event_generator(),
            status_code=200,
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",
                "X-MCP-SSE": "true",
            },
            # Timeout for ASGI send() calls - protects against sends that hang indefinitely
            # when client connection is in a bad state (e.g., client stopped reading but TCP
            # connection not yet closed). Does NOT affect MCP server response times.
            # Set to 0 to disable. Default matches keepalive interval.
            send_timeout=settings.sse_send_timeout if settings.sse_send_timeout > 0 else None,
        )

    async def _client_disconnected(self, _request: Request) -> bool:
        """Check if client has disconnected.

        Args:
            _request: FastAPI Request object

        Returns:
            bool: True if client disconnected

        Examples:
            >>> # Test client disconnected check
            >>> transport = SSETransport()
            >>> import asyncio
            >>> asyncio.run(transport._client_disconnected(None))
            False

            >>> # Test after setting client gone
            >>> transport = SSETransport()
            >>> transport._client_gone.set()
            >>> asyncio.run(transport._client_disconnected(None))
            True
        """
        # We only check our internal client_gone flag
        # We intentionally don't check connection_lost on the request
        # as it can be unreliable and cause premature closures
        return self._client_gone.is_set()

    @property
    def session_id(self) -> str:
        """
        Get the session ID for this transport.

        Returns:
            str: session_id

        Examples:
            >>> # Test session ID property
            >>> transport = SSETransport()
            >>> session_id = transport.session_id
            >>> isinstance(session_id, str)
            True
            >>> len(session_id) > 0
            True
            >>> session_id == transport._session_id
            True

            >>> # Test session ID uniqueness
            >>> transport1 = SSETransport()
            >>> transport2 = SSETransport()
            >>> transport1.session_id != transport2.session_id
            True
        """
        return self._session_id
