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
from collections import deque
import logging
import time
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, Optional
import uuid

# Third-Party
import anyio
from anyio._backends._asyncio import CancelScope
from fastapi import Request
import orjson
from sse_starlette.sse import EventSourceResponse as BaseEventSourceResponse
from starlette.types import Receive, Scope, Send

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.transports.base import Transport

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


# =============================================================================
# MONKEY-PATCH: Fix anyio's _deliver_cancellation spin loop (anyio#695)
# =============================================================================
# anyio's _deliver_cancellation can spin at 100% CPU when tasks don't respond
# to CancelledError. This monkey-patch adds a max iteration limit to prevent
# indefinite spinning. After the limit is reached, we give up delivering
# cancellation and let the scope exit (tasks will be orphaned but won't spin).
#
# See: https://github.com/agronholm/anyio/issues/695
# =============================================================================

_CANCEL_DELIVERY_MAX_ITERATIONS = 100  # Max call_soon iterations before giving up
_original_deliver_cancellation = CancelScope._deliver_cancellation  # type: ignore[attr-defined]  # pylint: disable=protected-access


def _patched_deliver_cancellation(self: CancelScope, origin: CancelScope) -> bool:  # pylint: disable=protected-access
    """Patched _deliver_cancellation with max iteration limit to prevent spin.

    This wraps anyio's original _deliver_cancellation to track iteration count
    and give up after a maximum number of attempts. This prevents the CPU spin
    loop that occurs when tasks don't respond to CancelledError.

    Args:
        self: The cancel scope being processed.
        origin: The cancel scope that originated the cancellation.

    Returns:
        True if delivery should be retried, False if done or max iterations reached.
    """
    # Track iteration count on the origin scope (the one that initiated cancel)
    if not hasattr(origin, "_delivery_iterations"):
        origin._delivery_iterations = 0  # type: ignore[attr-defined]  # pylint: disable=protected-access

    origin._delivery_iterations += 1  # type: ignore[attr-defined]  # pylint: disable=protected-access

    # Check if we've exceeded the maximum iterations
    if origin._delivery_iterations > _CANCEL_DELIVERY_MAX_ITERATIONS:  # type: ignore[attr-defined]  # pylint: disable=protected-access
        # Log warning and give up - this prevents indefinite spin
        logger.warning(
            "anyio cancel delivery exceeded %d iterations - giving up to prevent CPU spin. "
            "Some tasks may not have been properly cancelled.",
            _CANCEL_DELIVERY_MAX_ITERATIONS,
        )
        # Clear the cancel handle to stop further retries
        if hasattr(self, "_cancel_handle") and self._cancel_handle is not None:  # pylint: disable=protected-access
            self._cancel_handle = None  # pylint: disable=protected-access
        return False  # Don't retry

    # Call the original implementation
    return _original_deliver_cancellation(self, origin)


# Apply the monkey-patch
CancelScope._deliver_cancellation = _patched_deliver_cancellation  # type: ignore[method-assign]  # pylint: disable=protected-access
logger.debug("Applied anyio _deliver_cancellation monkey-patch to prevent CPU spin loops")


def _get_sse_cleanup_timeout() -> float:
    """Get SSE task group cleanup timeout from config.

    This timeout controls how long to wait for SSE task group tasks to respond
    to cancellation before forcing cleanup. Prevents CPU spin loops in anyio's
    _deliver_cancellation when tasks don't properly handle CancelledError.

    Returns:
        Cleanup timeout in seconds (default: 5.0)
    """
    try:
        return settings.sse_task_group_cleanup_timeout
    except Exception:
        return 5.0  # Fallback default


class EventSourceResponse(BaseEventSourceResponse):
    """Patched EventSourceResponse with CPU spin detection.

    This mitigates a CPU spin loop issue (anyio#695) where _deliver_cancellation
    spins at 100% CPU when tasks in the SSE task group don't respond to
    cancellation.

    Instead of trying to timeout the task group (which would affect normal
    SSE connections), we copy the __call__ method and add a deadline to
    the cancel scope to ensure cleanup doesn't hang indefinitely.

    See:
    - https://github.com/agronholm/anyio/issues/695
    - https://github.com/anthropics/claude-agent-sdk-python/issues/378
    """

    def enable_compression(self, force: bool = False) -> None:  # noqa: ARG002
        """Enable compression (no-op for SSE streams).

        SSE streams don't support compression as per sse_starlette.
        This override prevents NotImplementedError from parent class.

        Args:
            force: Ignored - compression not supported for SSE.
        """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle SSE request with cancel scope deadline to prevent spin.

        This method is copied from sse_starlette with one key modification:
        the task group's cancel_scope gets a deadline set when cancellation
        starts, preventing indefinite spinning if tasks don't respond.

        Args:
            scope: ASGI scope dictionary.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        # Copy of sse_starlette.sse.EventSourceResponse.__call__ with deadline fix
        async with anyio.create_task_group() as task_group:
            # Add deadline to cancel scope to prevent indefinite spin on cleanup
            # The deadline is set far in the future initially, and only becomes
            # relevant if the scope is cancelled and cleanup takes too long

            async def cancel_on_finish(coro: Callable[[], Awaitable[None]]) -> None:
                await coro()
                # When cancelling, set a deadline to prevent indefinite spin
                # if other tasks don't respond to cancellation
                task_group.cancel_scope.deadline = anyio.current_time() + _get_sse_cleanup_timeout()
                task_group.cancel_scope.cancel()

            task_group.start_soon(cancel_on_finish, lambda: self._stream_response(send))
            task_group.start_soon(cancel_on_finish, lambda: self._ping(send))
            task_group.start_soon(cancel_on_finish, self._listen_for_exit_signal)

            if self.data_sender_callable:
                task_group.start_soon(self.data_sender_callable)

            # Wait for the client to disconnect last
            task_group.start_soon(cancel_on_finish, lambda: self._listen_for_disconnect(receive))

        if self.background is not None:
            await self.background()


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

    async def create_sse_response(
        self,
        request: Request,
        on_disconnect_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> EventSourceResponse:
        """Create SSE response for streaming.

        Args:
            request: FastAPI request (used for disconnection detection)
            on_disconnect_callback: Optional async callback to run when client disconnects.
                Used for defensive cleanup (e.g., cancelling respond tasks).

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
            consecutive_rapid_yields = 0  # Track consecutive fast yields for simpler detection

            def check_rapid_yield() -> bool:
                """Check if yields are happening too fast.

                Returns:
                    True if spin loop detected and should disconnect, False otherwise.
                """
                nonlocal last_yield_time, consecutive_rapid_yields
                now = time.monotonic()
                time_since_last = now - last_yield_time
                last_yield_time = now

                # Track consecutive rapid yields (< 100ms apart)
                # This catches spin loops even without full deque analysis
                if time_since_last < 0.1:
                    consecutive_rapid_yields += 1
                    if consecutive_rapid_yields >= 10:  # 10 consecutive fast yields = definite spin
                        logger.error("SSE spin loop detected (%d consecutive rapid yields, last interval %.3fs), client disconnected: %s", consecutive_rapid_yields, time_since_last, self._session_id)
                        return True
                else:
                    consecutive_rapid_yields = 0  # Reset on normal-speed yield

                # Also use deque-based detection for more nuanced analysis
                if yield_timestamps is None:
                    return False
                yield_timestamps.append(now)
                if time_since_last < 0.01:  # Less than 10ms between yields is very fast
                    if len(yield_timestamps) > settings.sse_rapid_yield_max:
                        oldest = yield_timestamps[0]
                        elapsed = now - oldest
                        if elapsed < rapid_yield_window_sec:
                            logger.error(
                                "SSE rapid yield detected (%d yields in %.3fs, last interval %.3fs), client disconnected: %s", len(yield_timestamps), elapsed, time_since_last, self._session_id
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
                            # Note: We don't clear yield_timestamps here. The deque has maxlen
                            # which automatically drops old entries. Clearing would prevent
                            # detection of spin loops where yields happen faster than expected.

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
                # CRITICAL: Also invoke disconnect callback on generator end (Finding 3)
                # This covers server-initiated close, errors, and cancellation - not just client close
                if on_disconnect_callback:
                    try:
                        await on_disconnect_callback()
                    except Exception as e:
                        logger.warning("Disconnect callback in finally failed for %s: %s", self._session_id, e)

        async def on_client_close(_scope: dict) -> None:
            """Handle client close event from sse_starlette."""
            logger.info("SSE client close handler called: %s", self._session_id)
            self._client_gone.set()

            # Defensive cleanup via callback (if provided)
            if on_disconnect_callback:
                try:
                    await on_disconnect_callback()
                except Exception as e:
                    logger.warning("Disconnect callback failed for %s: %s", self._session_id, e)

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
            # Callback when client closes - helps detect disconnects that ASGI server
            # may not properly propagate via request.is_disconnected()
            client_close_handler_callable=on_client_close,
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
