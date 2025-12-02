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
from datetime import datetime
import json
from typing import Any, AsyncGenerator, Dict, Optional
import uuid

# Third-Party
from fastapi import Request
from sse_starlette.sse import EventSourceResponse

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.transports.base import Transport

# TYPE_CHECKING import to avoid circular dependency
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from mcpgateway.cache.session_pool_manager import SessionPoolManager

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


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

    def __init__(self, base_url: str = None, session_id: str = None, pool_manager: Optional["SessionPoolManager"] = None, server_id: Optional[str] = None):
        """Initialize SSE transport.

        Args:
            base_url: Base URL for client message endpoints
            session_id: Optional session ID for pooled sessions. If not provided, generates a new UUID.
            pool_manager: Optional SessionPoolManager for pool-aware operations
            server_id: Optional server ID for pool operations

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

            >>> # Test with provided session ID (for pooling)
            >>> pooled_id = "pooled-session-123"
            >>> transport = SSETransport(session_id=pooled_id)
            >>> transport.session_id
            'pooled-session-123'
        """
        self._base_url = base_url or f"http://{settings.host}:{settings.port}"
        self._connected = False
        self._message_queue = asyncio.Queue()
        self._client_gone = asyncio.Event()
        self._session_id = session_id or str(uuid.uuid4())
        self._is_pooled = session_id is not None
        self._pool_manager = pool_manager
        self._server_id = server_id
        self._acquired_from_pool = False

        logger.info(f"Creating SSE transport with base_url={self._base_url}, session_id={self._session_id}, pooled={self._is_pooled}, server_id={self._server_id}")

    async def connect(self, pool_manager: Optional["SessionPoolManager"] = None, server_id: Optional[str] = None) -> None:
        """Set up SSE connection, optionally using a pooled session.

        Args:
            pool_manager: Optional SessionPoolManager to acquire session from pool
            server_id: Optional server ID for pool operations

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
        # Update pool manager and server ID if provided
        if pool_manager:
            self._pool_manager = pool_manager
        if server_id:
            self._server_id = server_id

        # Try to acquire from pool if pool manager and server ID are available
        if self._pool_manager and self._server_id and not self._is_pooled:
            try:
                pooled_session_id = await self._pool_manager.acquire_session(self._server_id)
                if pooled_session_id:
                    self._session_id = pooled_session_id
                    self._is_pooled = True
                    self._acquired_from_pool = True
                    logger.info(f"SSE transport acquired pooled session: {self._session_id} for server {self._server_id}")
            except Exception as e:
                logger.warning(f"Failed to acquire pooled session, using new session: {e}")

        self._connected = True
        logger.info(f"SSE transport connected: {self._session_id}")

    async def disconnect(self, pool_manager: Optional["SessionPoolManager"] = None, server_id: Optional[str] = None, healthy: bool = True, error: Optional[str] = None) -> None:
        """Clean up SSE connection and release session back to pool if applicable.

        Args:
            pool_manager: Optional SessionPoolManager to release session back to pool
            server_id: Optional server ID for pool operations
            healthy: Whether the session is still healthy (default: True)
            error: Optional error message if session is unhealthy

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

            # Release session back to pool if it was acquired from pool
            if self._acquired_from_pool and self._pool_manager and self._server_id:
                try:
                    await self._pool_manager.release_session(
                        self._server_id,
                        self._session_id,
                        healthy=healthy,
                        error=error
                    )
                    logger.info(f"SSE transport released pooled session: {self._session_id} for server {self._server_id}")
                except Exception as e:
                    logger.error(f"Failed to release pooled session: {e}")

            logger.info(f"SSE transport disconnected: {self._session_id}")

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
            logger.debug(f"Message queued for SSE: {self._session_id}, method={message.get('method', '(response)')}")
        except Exception as e:
            logger.error(f"Failed to queue message: {e}")
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
            logger.info(f"SSE receive loop cancelled for session {self._session_id}")
            raise
        finally:
            logger.info(f"SSE receive loop ended for session {self._session_id}")

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

    async def create_sse_response(self, _request: Request) -> EventSourceResponse:
        """Create SSE response for streaming.

        Args:
            _request: FastAPI request

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
                SSE event
            """
            # Send the endpoint event first
            yield {
                "event": "endpoint",
                "data": endpoint_url,
                "retry": settings.sse_retry_timeout,
            }

            # Send keepalive immediately to help establish connection (if enabled)
            if settings.sse_keepalive_enabled:
                yield {
                    "event": "keepalive",
                    "data": "{}",
                    "retry": settings.sse_retry_timeout,
                }

            try:
                while not self._client_gone.is_set():
                    try:
                        # Wait for messages with a timeout for keepalives
                        timeout = settings.sse_keepalive_interval if settings.sse_keepalive_enabled else None
                        message = await asyncio.wait_for(
                            self._message_queue.get(),
                            timeout=timeout,  # Configurable timeout for keepalives (some tools require more timeout for execution)
                        )

                        data = json.dumps(message, default=lambda obj: (obj.strftime("%Y-%m-%d %H:%M:%S") if isinstance(obj, datetime) else TypeError("Type not serializable")))

                        # logger.info(f"Sending SSE message: {data[:100]}...")
                        logger.debug(f"Sending SSE message: {data}")

                        yield {
                            "event": "message",
                            "data": data,
                            "retry": settings.sse_retry_timeout,
                        }
                    except asyncio.TimeoutError:
                        # Send keepalive on timeout (if enabled)
                        if settings.sse_keepalive_enabled:
                            yield {
                                "event": "keepalive",
                                "data": "{}",
                                "retry": settings.sse_retry_timeout,
                            }
                    except Exception as e:
                        logger.error(f"Error processing SSE message: {e}")
                        yield {
                            "event": "error",
                            "data": json.dumps({"error": str(e)}),
                            "retry": settings.sse_retry_timeout,
                        }
            except asyncio.CancelledError:
                logger.info(f"SSE event generator cancelled: {self._session_id}")
            except Exception as e:
                logger.error(f"SSE event generator error: {e}")
            finally:
                logger.info(f"SSE event generator completed: {self._session_id}")
                # We intentionally don't set client_gone here to allow queued messages to be processed

        return EventSourceResponse(
            event_generator(),
            status_code=200,
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",
                "X-MCP-SSE": "true",
            },
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

    @property
    def is_pooled(self) -> bool:
        """
        Check if this transport is using a pooled session.

        Returns:
            bool: True if session is from a pool, False otherwise

        Examples:
            >>> # Test non-pooled transport
            >>> transport = SSETransport()
            >>> transport.is_pooled
            False

            >>> # Test pooled transport
            >>> transport = SSETransport(session_id="pooled-123")
            >>> transport.is_pooled
            True
        """
        return self._is_pooled

    @classmethod
    async def create_pooled_session(
        cls,
        pool_manager: "SessionPoolManager",
        server_id: str,
        base_url: str = None,
        timeout: Optional[int] = None
    ) -> Optional["SSETransport"]:
        """Create a new SSE transport using a pooled session.

        This is a factory method that creates a transport instance with a session
        acquired from the pool. If pool acquisition fails, returns None.

        Args:
            pool_manager: SessionPoolManager to acquire session from
            server_id: Server ID for pool operations
            base_url: Optional base URL for client message endpoints
            timeout: Optional timeout for pool acquisition

        Returns:
            SSETransport instance with pooled session, or None if acquisition fails

        Examples:
            >>> # This method requires a SessionPoolManager instance
            >>> # and cannot be easily tested in doctest environment
            >>> callable(SSETransport.create_pooled_session)
            True
        """
        try:
            session_id = await pool_manager.acquire_session(server_id, timeout=timeout)
            if not session_id:
                logger.warning(f"Failed to acquire pooled session for server {server_id}")
                return None

            transport = cls(
                base_url=base_url,
                session_id=session_id,
                pool_manager=pool_manager,
                server_id=server_id
            )
            transport._acquired_from_pool = True
            logger.info(f"Created SSE transport with pooled session: {session_id} for server {server_id}")
            return transport
        except Exception as e:
            logger.error(f"Error creating pooled SSE transport: {e}")
            return None

    async def get_or_create_session(
        self,
        pool_manager: Optional["SessionPoolManager"] = None,
        server_id: Optional[str] = None
    ) -> str:
        """Get existing session ID or create a new one, with pool fallback.

        This method attempts to use a pooled session if pool_manager and server_id
        are provided. If pool acquisition fails, it falls back to the current session ID
        or generates a new one.

        Args:
            pool_manager: Optional SessionPoolManager to acquire session from pool
            server_id: Optional server ID for pool operations

        Returns:
            Session ID (either pooled or new)

        Examples:
            >>> # Test with no pool manager
            >>> transport = SSETransport()
            >>> import asyncio
            >>> session_id = asyncio.run(transport.get_or_create_session())
            >>> isinstance(session_id, str)
            True
            >>> len(session_id) > 0
            True
        """
        # If already have a session, return it
        if self._session_id and self._is_pooled:
            return self._session_id

        # Try to acquire from pool
        if pool_manager and server_id:
            try:
                pooled_id = await pool_manager.acquire_session(server_id)
                if pooled_id:
                    self._session_id = pooled_id
                    self._is_pooled = True
                    self._acquired_from_pool = True
                    self._pool_manager = pool_manager
                    self._server_id = server_id
                    logger.info(f"Acquired pooled session: {pooled_id} for server {server_id}")
                    return pooled_id
            except Exception as e:
                logger.warning(f"Failed to acquire pooled session, using fallback: {e}")

        # Fallback to existing or new session
        if not self._session_id:
            self._session_id = str(uuid.uuid4())
            logger.info(f"Created new session: {self._session_id}")

        return self._session_id

    async def check_pool_health(self) -> bool:
        """Check if the pooled session is still healthy.

        This method verifies that the transport is connected and, if using a pooled
        session, that the pool manager is still available.

        Returns:
            True if session is healthy, False otherwise

        Examples:
            >>> # Test health check for non-pooled session
            >>> transport = SSETransport()
            >>> import asyncio
            >>> asyncio.run(transport.connect())
            >>> asyncio.run(transport.check_pool_health())
            True

            >>> # Test health check when disconnected
            >>> transport = SSETransport()
            >>> asyncio.run(transport.check_pool_health())
            False
        """
        if not self._connected:
            return False

        # If using a pooled session, verify pool manager is available
        if self._is_pooled and self._acquired_from_pool:
            if not self._pool_manager or not self._server_id:
                logger.warning(f"Pooled session {self._session_id} missing pool manager or server ID")
                return False

        return True
