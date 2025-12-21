# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/session_registry.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Session Registry with optional distributed state.
This module provides a registry for SSE sessions with support for distributed deployment
using Redis or SQLAlchemy as optional backends for shared state between workers.

The SessionRegistry class manages server-sent event (SSE) sessions across multiple
worker processes, enabling horizontal scaling of MCP gateway deployments. It supports
three backend modes:

- **memory**: In-memory storage for single-process deployments (default)
- **redis**: Redis-backed shared storage for multi-worker deployments
- **database**: SQLAlchemy-backed shared storage using any supported database

In distributed mode (redis/database), session existence is tracked in the shared
backend while transport objects remain local to each worker process. This allows
workers to know about sessions on other workers and route messages appropriately.

Examples:
    Basic usage with memory backend:

    >>> from mcpgateway.cache.session_registry import SessionRegistry
    >>> class DummyTransport:
    ...     async def disconnect(self):
    ...         pass
    ...     async def is_connected(self):
    ...         return True
    >>> import asyncio
    >>> reg = SessionRegistry(backend='memory')
    >>> transport = DummyTransport()
    >>> asyncio.run(reg.add_session('sid123', transport))
    >>> found = asyncio.run(reg.get_session('sid123'))
    >>> isinstance(found, DummyTransport)
    True
    >>> asyncio.run(reg.remove_session('sid123'))
    >>> asyncio.run(reg.get_session('sid123')) is None
    True

    Broadcasting messages:

    >>> reg = SessionRegistry(backend='memory')
    >>> asyncio.run(reg.broadcast('sid123', {'method': 'ping', 'id': 1}))
    >>> reg._session_message is not None
    True
"""

# Standard
import asyncio
from asyncio import Task
from datetime import datetime, timedelta, timezone
import logging
import time
import traceback
from typing import Any, Dict, Optional
from urllib.parse import urlparse
import uuid

# Third-Party
from fastapi import HTTPException, status
import orjson

# First-Party
from mcpgateway import __version__
from mcpgateway.common.models import Implementation, InitializeResult, ServerCapabilities
from mcpgateway.config import settings
from mcpgateway.db import get_db, SessionMessageRecord, SessionRecord
from mcpgateway.services import PromptService, ResourceService, ToolService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.transports import SSETransport
from mcpgateway.utils.create_jwt_token import create_jwt_token
from mcpgateway.utils.redis_client import get_redis_client
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.validation.jsonrpc import JSONRPCError

# Initialize logging service first
logging_service: LoggingService = LoggingService()
logger = logging_service.get_logger(__name__)

tool_service: ToolService = ToolService()
resource_service: ResourceService = ResourceService()
prompt_service: PromptService = PromptService()

try:
    # Third-Party
    from redis.asyncio import Redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    # Third-Party
    from sqlalchemy import func

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


class SessionBackend:
    """Base class for session registry backend configuration.

    This class handles the initialization and configuration of different backend
    types for session storage. It validates backend requirements and sets up
    necessary connections for Redis or database backends.

    Attributes:
        _backend: The backend type ('memory', 'redis', 'database', or 'none')
        _session_ttl: Time-to-live for sessions in seconds
        _message_ttl: Time-to-live for messages in seconds
        _redis: Redis connection instance (redis backend only)
        _pubsub: Redis pubsub instance (redis backend only)
        _session_message: Temporary message storage (memory backend only)

    Examples:
        >>> backend = SessionBackend(backend='memory')
        >>> backend._backend
        'memory'
        >>> backend._session_ttl
        3600

        >>> try:
        ...     backend = SessionBackend(backend='redis')
        ... except ValueError as e:
        ...     str(e)
        'Redis backend requires redis_url'
    """

    def __init__(
        self,
        backend: str = "memory",
        redis_url: Optional[str] = None,
        database_url: Optional[str] = None,
        session_ttl: int = 3600,  # 1 hour
        message_ttl: int = 600,  # 10 min
    ):
        """Initialize session backend configuration.

        Args:
            backend: Backend type. Must be one of 'memory', 'redis', 'database', or 'none'.
                - 'memory': In-memory storage, suitable for single-process deployments
                - 'redis': Redis-backed storage for multi-worker deployments
                - 'database': SQLAlchemy-backed storage for multi-worker deployments
                - 'none': No session tracking (dummy registry)
            redis_url: Redis connection URL. Required when backend='redis'.
                Format: 'redis://[:password]@host:port/db'
            database_url: Database connection URL. Required when backend='database'.
                Format depends on database type (e.g., 'postgresql://user:pass@host/db')
            session_ttl: Session time-to-live in seconds. Sessions are automatically
                cleaned up after this duration of inactivity. Default: 3600 (1 hour).
            message_ttl: Message time-to-live in seconds. Undelivered messages are
                removed after this duration. Default: 600 (10 minutes).

        Raises:
            ValueError: If backend is invalid, required URL is missing, or required packages are not installed.

        Examples:
            >>> # Memory backend (default)
            >>> backend = SessionBackend()
            >>> backend._backend
            'memory'

            >>> # Redis backend requires URL
            >>> try:
            ...     backend = SessionBackend(backend='redis')
            ... except ValueError as e:
            ...     'redis_url' in str(e)
            True

            >>> # Invalid backend
            >>> try:
            ...     backend = SessionBackend(backend='invalid')
            ... except ValueError as e:
            ...     'Invalid backend' in str(e)
            True
        """

        self._backend = backend.lower()
        self._session_ttl = session_ttl
        self._message_ttl = message_ttl

        # Set up backend-specific components
        if self._backend == "memory":
            # Nothing special needed for memory backend
            self._session_message: dict[str, Any] | None = None

        elif self._backend == "none":
            # No session tracking - this is just a dummy registry
            logger.info("Session registry initialized with 'none' backend - session tracking disabled")

        elif self._backend == "redis":
            if not REDIS_AVAILABLE:
                raise ValueError("Redis backend requested but redis package not installed")
            if not redis_url:
                raise ValueError("Redis backend requires redis_url")

            # Redis client is set in initialize() via the shared factory
            self._redis: Optional[Redis] = None
            self._pubsub = None

        elif self._backend == "database":
            if not SQLALCHEMY_AVAILABLE:
                raise ValueError("Database backend requested but SQLAlchemy not installed")
            if not database_url:
                raise ValueError("Database backend requires database_url")
        else:
            raise ValueError(f"Invalid backend: {backend}")


class SessionRegistry(SessionBackend):
    """Registry for SSE sessions with optional distributed state.

    This class manages server-sent event (SSE) sessions, providing methods to add,
    remove, and query sessions. It supports multiple backend types for different
    deployment scenarios:

    - **Single-process deployments**: Use 'memory' backend (default)
    - **Multi-worker deployments**: Use 'redis' or 'database' backend
    - **Testing/development**: Use 'none' backend to disable session tracking

    The registry maintains a local cache of transport objects while using the
    shared backend to track session existence across workers. This enables
    horizontal scaling while keeping transport objects process-local.

    Attributes:
        _sessions: Local dictionary mapping session IDs to transport objects
        _lock: Asyncio lock for thread-safe access to _sessions
        _cleanup_task: Background task for cleaning up expired sessions

    Examples:
        >>> import asyncio
        >>> from mcpgateway.cache.session_registry import SessionRegistry
        >>>
        >>> class MockTransport:
        ...     async def disconnect(self):
        ...         print("Disconnected")
        ...     async def is_connected(self):
        ...         return True
        ...     async def send_message(self, msg):
        ...         print(f"Sent: {msg}")
        >>>
        >>> # Create registry and add session
        >>> reg = SessionRegistry(backend='memory')
        >>> transport = MockTransport()
        >>> asyncio.run(reg.add_session('test123', transport))
        >>>
        >>> # Retrieve session
        >>> found = asyncio.run(reg.get_session('test123'))
        >>> found is transport
        True
        >>>
        >>> # Remove session
        >>> asyncio.run(reg.remove_session('test123'))
        Disconnected
        >>> asyncio.run(reg.get_session('test123')) is None
        True
    """

    def __init__(
        self,
        backend: str = "memory",
        redis_url: Optional[str] = None,
        database_url: Optional[str] = None,
        session_ttl: int = 3600,  # 1 hour
        message_ttl: int = 600,  # 10 min
    ):
        """Initialize session registry with specified backend.

        Args:
            backend: Backend type. Must be one of 'memory', 'redis', 'database', or 'none'.
            redis_url: Redis connection URL. Required when backend='redis'.
            database_url: Database connection URL. Required when backend='database'.
            session_ttl: Session time-to-live in seconds. Default: 3600.
            message_ttl: Message time-to-live in seconds. Default: 600.

        Examples:
            >>> # Default memory backend
            >>> reg = SessionRegistry()
            >>> reg._backend
            'memory'
            >>> isinstance(reg._sessions, dict)
            True

            >>> # Redis backend with custom TTL
            >>> try:
            ...     reg = SessionRegistry(
            ...         backend='redis',
            ...         redis_url='redis://localhost:6379',
            ...         session_ttl=7200
            ...     )
            ... except ValueError:
            ...     pass  # Redis may not be available
        """
        super().__init__(backend=backend, redis_url=redis_url, database_url=database_url, session_ttl=session_ttl, message_ttl=message_ttl)
        self._sessions: Dict[str, Any] = {}  # Local transport cache
        self._client_capabilities: Dict[str, Dict[str, Any]] = {}  # Client capabilities by session_id
        self._lock = asyncio.Lock()
        self._cleanup_task: Task | None = None

    async def initialize(self) -> None:
        """Initialize the registry with async setup.

        This method performs asynchronous initialization tasks that cannot be done
        in __init__. It starts background cleanup tasks and sets up pubsub
        subscriptions for distributed backends.

        Call this during application startup after creating the registry instance.

        Examples:
            >>> import asyncio
            >>> reg = SessionRegistry(backend='memory')
            >>> asyncio.run(reg.initialize())
            >>> reg._cleanup_task is not None
            True
            >>>
            >>> # Cleanup
            >>> asyncio.run(reg.shutdown())
        """
        logger.info(f"Initializing session registry with backend: {self._backend}")

        if self._backend == "database":
            # Start database cleanup task
            self._cleanup_task = asyncio.create_task(self._db_cleanup_task())
            logger.info("Database cleanup task started")

        elif self._backend == "redis":
            # Get shared Redis client from factory
            self._redis = await get_redis_client()
            if self._redis:
                self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe("mcp_session_events")
                logger.info("Session registry connected to shared Redis client")

        elif self._backend == "none":
            # Nothing to initialize for none backend
            pass

        # Memory backend needs session cleanup
        elif self._backend == "memory":
            self._cleanup_task = asyncio.create_task(self._memory_cleanup_task())
            logger.info("Memory cleanup task started")

    async def shutdown(self) -> None:
        """Shutdown the registry and clean up resources.

        This method cancels background tasks and closes connections to external
        services. Call this during application shutdown to ensure clean termination.

        Examples:
            >>> import asyncio
            >>> reg = SessionRegistry()
            >>> asyncio.run(reg.initialize())
            >>> task_was_created = reg._cleanup_task is not None
            >>> asyncio.run(reg.shutdown())
            >>> # After shutdown, cleanup task should be handled (cancelled or done)
            >>> task_was_created and (reg._cleanup_task.cancelled() or reg._cleanup_task.done())
            True
        """
        logger.info("Shutting down session registry")

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Close Redis pubsub (but not the shared client)
        if self._backend == "redis" and getattr(self, "_pubsub", None):
            try:
                await self._pubsub.aclose()
            except Exception as e:
                logger.error(f"Error closing Redis pubsub: {e}")
            # Don't close self._redis - it's the shared client managed by redis_client.py
            self._redis = None
            self._pubsub = None

    async def add_session(self, session_id: str, transport: SSETransport) -> None:
        """Add a session to the registry.

        Stores the session in both the local cache and the distributed backend
        (if configured). For distributed backends, this notifies other workers
        about the new session.

        Args:
            session_id: Unique session identifier. Should be a UUID or similar
                unique string to avoid collisions.
            transport: SSE transport object for this session. Must implement
                the SSETransport interface.

        Examples:
            >>> import asyncio
            >>> from mcpgateway.cache.session_registry import SessionRegistry
            >>>
            >>> class MockTransport:
            ...     async def disconnect(self):
            ...         print(f"Transport disconnected")
            ...     async def is_connected(self):
            ...         return True
            >>>
            >>> reg = SessionRegistry()
            >>> transport = MockTransport()
            >>> asyncio.run(reg.add_session('test-456', transport))
            >>>
            >>> # Found in local cache
            >>> found = asyncio.run(reg.get_session('test-456'))
            >>> found is transport
            True
            >>>
            >>> # Remove session
            >>> asyncio.run(reg.remove_session('test-456'))
            Transport disconnected
        """
        # Skip for none backend
        if self._backend == "none":
            return

        async with self._lock:
            self._sessions[session_id] = transport

        if self._backend == "redis":
            # Store session marker in Redis
            if not self._redis:
                logger.warning(f"Redis client not initialized, skipping distributed session tracking for {session_id}")
                return
            try:
                await self._redis.setex(f"mcp:session:{session_id}", self._session_ttl, "1")
                # Publish event to notify other workers
                await self._redis.publish("mcp_session_events", orjson.dumps({"type": "add", "session_id": session_id, "timestamp": time.time()}))
            except Exception as e:
                logger.error(f"Redis error adding session {session_id}: {e}")

        elif self._backend == "database":
            # Store session in database
            try:

                def _db_add() -> None:
                    """Store session record in the database.

                    Creates a new SessionRecord entry in the database for tracking
                    distributed session state. Uses a fresh database connection from
                    the connection pool.

                    This inner function is designed to be run in a thread executor
                    to avoid blocking the async event loop during database I/O.

                    Raises:
                        Exception: Any database error is re-raised after rollback.
                            Common errors include duplicate session_id (unique constraint)
                            or database connection issues.

                    Examples:
                        >>> # This function is called internally by add_session()
                        >>> # When executed, it creates a database record:
                        >>> # SessionRecord(session_id='abc123', created_at=now())
                    """
                    db_session = next(get_db())
                    try:
                        session_record = SessionRecord(session_id=session_id)
                        db_session.add(session_record)
                        db_session.commit()
                    except Exception as ex:
                        db_session.rollback()
                        raise ex
                    finally:
                        db_session.close()

                await asyncio.to_thread(_db_add)
            except Exception as e:
                logger.error(f"Database error adding session {session_id}: {e}")

        logger.info(f"Added session: {session_id}")

    async def get_session(self, session_id: str) -> Any:
        """Get session transport by ID.

        First checks the local cache for the transport object. If not found locally
        but using a distributed backend, checks if the session exists on another
        worker.

        Args:
            session_id: Session identifier to look up.

        Returns:
            SSETransport object if found locally, None if not found or exists
            on another worker.

        Examples:
            >>> import asyncio
            >>> from mcpgateway.cache.session_registry import SessionRegistry
            >>>
            >>> class MockTransport:
            ...     pass
            >>>
            >>> reg = SessionRegistry()
            >>> transport = MockTransport()
            >>> asyncio.run(reg.add_session('test-456', transport))
            >>>
            >>> # Found in local cache
            >>> found = asyncio.run(reg.get_session('test-456'))
            >>> found is transport
            True
            >>>
            >>> # Not found
            >>> asyncio.run(reg.get_session('nonexistent')) is None
            True
        """
        # Skip for none backend
        if self._backend == "none":
            return None

        # First check local cache
        async with self._lock:
            transport = self._sessions.get(session_id)
            if transport:
                logger.info(f"Session {session_id} exists in local cache")
                return transport

        # If not in local cache, check if it exists in shared backend
        if self._backend == "redis":
            if not self._redis:
                return None
            try:
                exists = await self._redis.exists(f"mcp:session:{session_id}")
                session_exists = bool(exists)
                if session_exists:
                    logger.info(f"Session {session_id} exists in Redis but not in local cache")
                return None  # We don't have the transport locally
            except Exception as e:
                logger.error(f"Redis error checking session {session_id}: {e}")
                return None

        elif self._backend == "database":
            try:

                def _db_check() -> bool:
                    """Check if a session exists in the database.

                    Queries the SessionRecord table to determine if a session with
                    the given session_id exists. This is used when the session is not
                    found in the local cache to check if it exists on another worker.

                    This inner function is designed to be run in a thread executor
                    to avoid blocking the async event loop during database queries.

                    Returns:
                        bool: True if the session exists in the database, False otherwise.

                    Examples:
                        >>> # This function is called internally by get_session()
                        >>> # Returns True if SessionRecord with session_id exists
                        >>> # Returns False if no matching record found
                    """
                    db_session = next(get_db())
                    try:
                        record = db_session.query(SessionRecord).filter(SessionRecord.session_id == session_id).first()
                        return record is not None
                    finally:
                        db_session.close()

                exists = await asyncio.to_thread(_db_check)
                if exists:
                    logger.info(f"Session {session_id} exists in database but not in local cache")
                return None
            except Exception as e:
                logger.error(f"Database error checking session {session_id}: {e}")
                return None

        return None

    async def remove_session(self, session_id: str) -> None:
        """Remove a session from the registry.

        Removes the session from both local cache and distributed backend.
        If a transport is found locally, it will be disconnected before removal.
        For distributed backends, notifies other workers about the removal.

        Args:
            session_id: Session identifier to remove.

        Examples:
            >>> import asyncio
            >>> from mcpgateway.cache.session_registry import SessionRegistry
            >>>
            >>> class MockTransport:
            ...     async def disconnect(self):
            ...         print(f"Transport disconnected")
            ...     async def is_connected(self):
            ...         return True
            >>>
            >>> reg = SessionRegistry()
            >>> transport = MockTransport()
            >>> asyncio.run(reg.add_session('remove-test', transport))
            >>> asyncio.run(reg.remove_session('remove-test'))
            Transport disconnected
            >>>
            >>> # Session no longer exists
            >>> asyncio.run(reg.get_session('remove-test')) is None
            True
        """
        # Skip for none backend
        if self._backend == "none":
            return

        # Clean up local transport
        transport = None
        async with self._lock:
            if session_id in self._sessions:
                transport = self._sessions.pop(session_id)
            # Also clean up client capabilities
            if session_id in self._client_capabilities:
                self._client_capabilities.pop(session_id)
                logger.debug(f"Removed capabilities for session {session_id}")

        # Disconnect transport if found
        if transport:
            try:
                await transport.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting transport for session {session_id}: {e}")

        # Remove from shared backend
        if self._backend == "redis":
            if not self._redis:
                return
            try:
                await self._redis.delete(f"mcp:session:{session_id}")
                # Notify other workers
                await self._redis.publish("mcp_session_events", orjson.dumps({"type": "remove", "session_id": session_id, "timestamp": time.time()}))
            except Exception as e:
                logger.error(f"Redis error removing session {session_id}: {e}")

        elif self._backend == "database":
            try:

                def _db_remove() -> None:
                    """Delete session record from the database.

                    Removes the SessionRecord entry with the specified session_id
                    from the database. This is called when a session is being
                    terminated or has expired.

                    This inner function is designed to be run in a thread executor
                    to avoid blocking the async event loop during database operations.

                    Raises:
                        Exception: Any database error is re-raised after rollback.
                            This includes connection errors or constraint violations.

                    Examples:
                        >>> # This function is called internally by remove_session()
                        >>> # Deletes the SessionRecord where session_id matches
                        >>> # No error if session_id doesn't exist (idempotent)
                    """
                    db_session = next(get_db())
                    try:
                        db_session.query(SessionRecord).filter(SessionRecord.session_id == session_id).delete()
                        db_session.commit()
                    except Exception as ex:
                        db_session.rollback()
                        raise ex
                    finally:
                        db_session.close()

                await asyncio.to_thread(_db_remove)
            except Exception as e:
                logger.error(f"Database error removing session {session_id}: {e}")

        logger.info(f"Removed session: {session_id}")

    async def broadcast(self, session_id: str, message: Dict[str, Any]) -> None:
        """Broadcast a message to a session.

        Sends a message to the specified session. The behavior depends on the backend:

        - **memory**: Stores message temporarily for local delivery
        - **redis**: Publishes message to Redis channel for the session
        - **database**: Stores message in database for polling by worker with session
        - **none**: No operation

        This method is used for inter-process communication in distributed deployments.

        Args:
            session_id: Target session identifier.
            message: Message to broadcast. Can be a dict, list, or any JSON-serializable object.

        Examples:
            >>> import asyncio
            >>> from mcpgateway.cache.session_registry import SessionRegistry
            >>>
            >>> reg = SessionRegistry(backend='memory')
            >>> message = {'method': 'tools/list', 'id': 1}
            >>> asyncio.run(reg.broadcast('session-789', message))
            >>>
            >>> # Message stored for memory backend
            >>> reg._session_message is not None
            True
            >>> reg._session_message['session_id']
            'session-789'
            >>> orjson.loads(reg._session_message['message'])['message'] == message
            True
        """
        # Skip for none backend only
        if self._backend == "none":
            return

        def _build_payload(msg: Any) -> str:
            """Build a JSON payload for message broadcasting.

            Args:
                msg: Message to wrap in payload envelope.

            Returns:
                JSON-encoded string containing type, message, and timestamp.
            """
            payload = {"type": "message", "message": msg, "timestamp": time.time()}
            return orjson.dumps(payload).decode()

        if self._backend == "memory":
            payload_json = _build_payload(message)
            self._session_message: Dict[str, Any] | None = {"session_id": session_id, "message": payload_json}

        elif self._backend == "redis":
            if not self._redis:
                logger.warning(f"Redis client not initialized, cannot broadcast to {session_id}")
                return
            try:
                broadcast_payload = {
                    "type": "message",
                    "message": message,  # Keep as original type, not pre-encoded
                    "timestamp": time.time(),
                }
                # Single encode
                payload_json = orjson.dumps(broadcast_payload)
                await self._redis.publish(session_id, payload_json)  # Single encode
            except Exception as e:
                logger.error(f"Redis error during broadcast: {e}")
        elif self._backend == "database":
            try:
                msg_json = _build_payload(message)

                def _db_add() -> None:
                    """Store message in the database for inter-process communication.

                    Creates a new SessionMessageRecord entry containing the session_id
                    and serialized message. This enables message passing between
                    different worker processes through the shared database.

                    This inner function is designed to be run in a thread executor
                    to avoid blocking the async event loop during database writes.

                    Raises:
                        Exception: Any database error is re-raised after rollback.
                            Common errors include database connection issues or
                            constraints violations.

                    Examples:
                        >>> # This function is called internally by broadcast()
                        >>> # Creates a record like:
                        >>> # SessionMessageRecord(
                        >>> #     session_id='abc123',
                        >>> #     message='{"method": "ping", "id": 1}',
                        >>> #     created_at=now()
                        >>> # )
                    """
                    db_session = next(get_db())
                    try:
                        message_record = SessionMessageRecord(session_id=session_id, message=msg_json)
                        db_session.add(message_record)
                        db_session.commit()
                    except Exception as ex:
                        db_session.rollback()
                        raise ex
                    finally:
                        db_session.close()

                await asyncio.to_thread(_db_add)
            except Exception as e:
                logger.error(f"Database error during broadcast: {e}")

    def get_session_sync(self, session_id: str) -> Any:
        """Get session synchronously from local cache only.

        This is a non-blocking method that only checks the local cache,
        not the distributed backend. Use this when you need quick access
        and know the session should be local.

        Args:
            session_id: Session identifier to look up.

        Returns:
            SSETransport object if found in local cache, None otherwise.

        Examples:
            >>> from mcpgateway.cache.session_registry import SessionRegistry
            >>> import asyncio
            >>>
            >>> class MockTransport:
            ...     pass
            >>>
            >>> reg = SessionRegistry()
            >>> transport = MockTransport()
            >>> asyncio.run(reg.add_session('sync-test', transport))
            >>>
            >>> # Synchronous lookup
            >>> found = reg.get_session_sync('sync-test')
            >>> found is transport
            True
            >>>
            >>> # Not found
            >>> reg.get_session_sync('nonexistent') is None
            True
        """
        # Skip for none backend
        if self._backend == "none":
            return None

        return self._sessions.get(session_id)

    async def respond(
        self,
        server_id: Optional[str],
        user: Dict[str, Any],
        session_id: str,
        base_url: str,
    ) -> None:
        """Process and respond to broadcast messages for a session.

        This method listens for messages directed to the specified session and
        generates appropriate responses. The listening mechanism depends on the backend:

        - **memory**: Checks the temporary message storage
        - **redis**: Subscribes to Redis pubsub channel
        - **database**: Polls database for new messages

        When a message is received and the transport exists locally, it processes
        the message and sends the response through the transport.

        Args:
            server_id: Optional server identifier for scoped operations.
            user: User information including authentication token.
            session_id: Session identifier to respond for.
            base_url: Base URL for API calls (used for RPC endpoints).

        Examples:
            >>> import asyncio
            >>> from mcpgateway.cache.session_registry import SessionRegistry
            >>>
            >>> # This method is typically called internally by the SSE handler
            >>> reg = SessionRegistry()
            >>> user = {'token': 'test-token'}
            >>> # asyncio.run(reg.respond(None, user, 'session-id', 'http://localhost'))
        """

        if self._backend == "none":
            pass

        elif self._backend == "memory":
            transport = self.get_session_sync(session_id)
            if transport and self._session_message:
                data = orjson.loads(self._session_message.get("message"))
                if isinstance(data, dict) and "message" in data:
                    message = data["message"]
                else:
                    message = data
                await self.generate_response(message=message, transport=transport, server_id=server_id, user=user, base_url=base_url)

        elif self._backend == "redis":
            if not self._redis:
                logger.warning(f"Redis client not initialized, cannot respond to {session_id}")
                return
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(session_id)

            try:
                async for msg in pubsub.listen():
                    if msg["type"] != "message":
                        continue
                    data = orjson.loads(msg["data"])
                    message = data.get("message", {})
                    transport = self.get_session_sync(session_id)
                    if transport:
                        await self.generate_response(message=message, transport=transport, server_id=server_id, user=user, base_url=base_url)
            except asyncio.CancelledError:
                logger.info(f"PubSub listener for session {session_id} cancelled")
            finally:
                await pubsub.unsubscribe(session_id)
                try:
                    await pubsub.aclose()
                except AttributeError:
                    await pubsub.close()
                logger.info(f"Cleaned up pubsub for session {session_id}")

        elif self._backend == "database":

            def _db_read_session(session_id: str) -> SessionRecord | None:
                """Check if session still exists in the database.

                Queries the SessionRecord table to verify that the session
                is still active. Used in the message polling loop to determine
                when to stop checking for messages.

                This inner function is designed to be run in a thread executor
                to avoid blocking the async event loop during database reads.

                Args:
                    session_id: The session identifier to look up.

                Returns:
                    SessionRecord: The session record if found, None otherwise.

                Raises:
                    Exception: Any database error is re-raised after rollback.

                Examples:
                    >>> # This function is called internally by message_check_loop()
                    >>> # Returns SessionRecord object if session exists
                    >>> # Returns None if session has been removed
                """
                db_session = next(get_db())
                try:
                    # Delete sessions that haven't been accessed for TTL seconds
                    result = db_session.query(SessionRecord).filter_by(session_id=session_id).first()
                    return result
                except Exception as ex:
                    db_session.rollback()
                    raise ex
                finally:
                    db_session.close()

            def _db_read(session_id: str) -> SessionMessageRecord | None:
                """Read pending message for a session from the database.

                Retrieves the first (oldest) unprocessed message for the given
                session_id from the SessionMessageRecord table. Messages are
                processed in FIFO order.

                This inner function is designed to be run in a thread executor
                to avoid blocking the async event loop during database queries.

                Args:
                    session_id: The session identifier to read messages for.

                Returns:
                    SessionMessageRecord: The oldest message record if found, None otherwise.

                Raises:
                    Exception: Any database error is re-raised after rollback.

                Examples:
                    >>> # This function is called internally by message_check_loop()
                    >>> # Returns SessionMessageRecord with message data
                    >>> # Returns None if no pending messages
                """
                db_session = next(get_db())
                try:
                    # Delete sessions that haven't been accessed for TTL seconds
                    result = db_session.query(SessionMessageRecord).filter_by(session_id=session_id).first()
                    return result
                except Exception as ex:
                    db_session.rollback()
                    raise ex
                finally:
                    db_session.close()

            def _db_remove(session_id: str, message: str) -> None:
                """Remove processed message from the database.

                Deletes a specific message record after it has been successfully
                processed and sent to the transport. This prevents duplicate
                message delivery.

                This inner function is designed to be run in a thread executor
                to avoid blocking the async event loop during database deletes.

                Args:
                    session_id: The session identifier the message belongs to.
                    message: The exact message content to remove (must match exactly).

                Raises:
                    Exception: Any database error is re-raised after rollback.

                Examples:
                    >>> # This function is called internally after message processing
                    >>> # Deletes the specific SessionMessageRecord entry
                    >>> # Log: "Removed message from mcp_messages table"
                """
                db_session = next(get_db())
                try:
                    db_session.query(SessionMessageRecord).filter(SessionMessageRecord.session_id == session_id).filter(SessionMessageRecord.message == message).delete()
                    db_session.commit()
                    logger.info("Removed message from mcp_messages table")
                except Exception as ex:
                    db_session.rollback()
                    raise ex
                finally:
                    db_session.close()

            async def message_check_loop(session_id: str) -> None:
                """Poll database for messages and deliver to local transport.

                Continuously checks the database for new messages directed to
                the specified session_id. When messages are found and the
                transport exists locally, delivers the message and removes it
                from the database. Exits when the session no longer exists.

                This coroutine runs as a background task for each active session
                using database backend, enabling message delivery across worker
                processes.

                Args:
                    session_id: The session identifier to monitor for messages.

                Examples:
                    >>> # This function is called as a task by respond()
                    >>> # asyncio.create_task(message_check_loop('abc123'))
                    >>> # Polls every 0.1 seconds until session is removed
                    >>> # Delivers messages to transport and cleans up database
                """
                while True:
                    record = await asyncio.to_thread(_db_read, session_id)

                    if record:
                        data = orjson.loads(record.message)
                        if isinstance(data, dict) and "message" in data:
                            message = data["message"]
                        else:
                            message = data
                        transport = self.get_session_sync(session_id)
                        if transport:
                            logger.info("Ready to respond")
                            await self.generate_response(message=message, transport=transport, server_id=server_id, user=user, base_url=base_url)

                            await asyncio.to_thread(_db_remove, session_id, record.message)

                    session_exists = await asyncio.to_thread(_db_read_session, session_id)
                    if not session_exists:
                        break

                    await asyncio.sleep(0.1)

            asyncio.create_task(message_check_loop(session_id))

    async def _refresh_redis_sessions(self) -> None:
        """Refresh TTLs for Redis sessions and clean up disconnected sessions.

        This internal method is used by the Redis backend to maintain session state.
        It checks all local sessions, refreshes TTLs for connected sessions, and
        removes disconnected ones.
        """
        if not self._redis:
            return
        try:
            # Check all local sessions
            local_transports = {}
            async with self._lock:
                local_transports = self._sessions.copy()

            for session_id, transport in local_transports.items():
                try:
                    if await transport.is_connected():
                        # Refresh TTL in Redis
                        await self._redis.expire(f"mcp:session:{session_id}", self._session_ttl)
                    else:
                        # Remove disconnected session
                        await self.remove_session(session_id)
                except Exception as e:
                    logger.error(f"Error refreshing session {session_id}: {e}")

        except Exception as e:
            logger.error(f"Error in Redis session refresh: {e}")

    async def _db_cleanup_task(self) -> None:
        """Background task to clean up expired database sessions.

        Runs periodically (every 5 minutes) to remove expired sessions from the
        database and refresh timestamps for active sessions. This prevents the
        database from accumulating stale session records.

        The task also verifies that local sessions still exist in the database
        and removes them locally if they've been deleted elsewhere.
        """
        logger.info("Starting database cleanup task")
        while True:
            try:
                # Clean up expired sessions every 5 minutes
                def _db_cleanup() -> int:
                    """Remove expired sessions from the database.

                    Deletes all SessionRecord entries that haven't been accessed
                    within the session TTL period. Uses database-specific date
                    arithmetic to calculate expiry time.

                    This inner function is designed to be run in a thread executor
                    to avoid blocking the async event loop during bulk deletes.

                    Returns:
                        int: Number of expired session records deleted.

                    Raises:
                        Exception: Any database error is re-raised after rollback.

                    Examples:
                        >>> # This function is called periodically by _db_cleanup_task()
                        >>> # Deletes sessions older than session_ttl seconds
                        >>> # Returns count of deleted records for logging
                        >>> # Log: "Cleaned up 5 expired database sessions"
                    """
                    db_session = next(get_db())
                    try:
                        # Delete sessions that haven't been accessed for TTL seconds
                        # Use Python datetime for database-agnostic expiry calculation
                        expiry_time = datetime.now(timezone.utc) - timedelta(seconds=self._session_ttl)
                        result = db_session.query(SessionRecord).filter(SessionRecord.last_accessed < expiry_time).delete()
                        db_session.commit()
                        return result
                    except Exception as ex:
                        db_session.rollback()
                        raise ex
                    finally:
                        db_session.close()

                deleted = await asyncio.to_thread(_db_cleanup)
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} expired database sessions")

                # Check local sessions against database
                local_transports = {}
                async with self._lock:
                    local_transports = self._sessions.copy()

                for session_id, transport in local_transports.items():
                    try:
                        if not await transport.is_connected():
                            await self.remove_session(session_id)
                            continue

                        # Refresh session in database
                        def _refresh_session(session_id: str = session_id) -> bool:
                            """Update session's last accessed timestamp in the database.

                            Refreshes the last_accessed field for an active session to
                            prevent it from being cleaned up as expired. This is called
                            periodically for all local sessions with active transports.

                            This inner function is designed to be run in a thread executor
                            to avoid blocking the async event loop during database updates.

                            Args:
                                session_id: The session identifier to refresh (default from closure).

                            Returns:
                                bool: True if the session was found and updated, False if not found.

                            Raises:
                                Exception: Any database error is re-raised after rollback.

                            Examples:
                                >>> # This function is called for each active local session
                                >>> # Updates SessionRecord.last_accessed to current time
                                >>> # Returns True if session exists and was refreshed
                                >>> # Returns False if session no longer exists in database
                            """
                            db_session = next(get_db())
                            try:
                                session = db_session.query(SessionRecord).filter(SessionRecord.session_id == session_id).first()

                                if session:
                                    # Update last_accessed
                                    session.last_accessed = func.now()  # pylint: disable=not-callable
                                    db_session.commit()
                                    return True
                                return False
                            except Exception as ex:
                                db_session.rollback()
                                raise ex
                            finally:
                                db_session.close()

                        session_exists = await asyncio.to_thread(_refresh_session)
                        if not session_exists:
                            # Session no longer in database, remove locally
                            await self.remove_session(session_id)

                    except Exception as e:
                        logger.error(f"Error checking session {session_id}: {e}")

                await asyncio.sleep(300)  # Run every 5 minutes

            except asyncio.CancelledError:
                logger.info("Database cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in database cleanup task: {e}")
                await asyncio.sleep(600)  # Sleep longer on error

    async def _memory_cleanup_task(self) -> None:
        """Background task to clean up disconnected sessions in memory backend.

        Runs periodically (every minute) to check all local sessions and remove
        those that are no longer connected. This prevents memory leaks from
        accumulating disconnected transport objects.
        """
        logger.info("Starting memory cleanup task")
        while True:
            try:
                # Check all local sessions
                local_transports = {}
                async with self._lock:
                    local_transports = self._sessions.copy()

                for session_id, transport in local_transports.items():
                    try:
                        if not await transport.is_connected():
                            await self.remove_session(session_id)
                    except Exception as e:
                        logger.error(f"Error checking session {session_id}: {e}")
                        await self.remove_session(session_id)

                await asyncio.sleep(60)  # Run every minute

            except asyncio.CancelledError:
                logger.info("Memory cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in memory cleanup task: {e}")
                await asyncio.sleep(300)  # Sleep longer on error

    # Handle initialize logic
    async def handle_initialize_logic(self, body: Dict[str, Any], session_id: Optional[str] = None) -> InitializeResult:
        """Process MCP protocol initialization request.

        Validates the protocol version and returns server capabilities and information.
        This method implements the MCP (Model Context Protocol) initialization handshake.

        Args:
            body: Request body containing protocol_version and optional client_info.
                Expected keys: 'protocol_version' or 'protocolVersion', 'capabilities'.
            session_id: Optional session ID to associate client capabilities with.

        Returns:
            InitializeResult containing protocol version, server capabilities, and server info.

        Raises:
            HTTPException: If protocol_version is missing (400 Bad Request with MCP error code -32002).

        Examples:
            >>> import asyncio
            >>> from mcpgateway.cache.session_registry import SessionRegistry
            >>>
            >>> reg = SessionRegistry()
            >>> body = {'protocol_version': '2025-06-18'}
            >>> result = asyncio.run(reg.handle_initialize_logic(body))
            >>> result.protocol_version
            '2025-06-18'
            >>> result.server_info.name
            'MCP_Gateway'
            >>>
            >>> # Missing protocol version
            >>> try:
            ...     asyncio.run(reg.handle_initialize_logic({}))
            ... except HTTPException as e:
            ...     e.status_code
            400
        """
        protocol_version = body.get("protocol_version") or body.get("protocolVersion")
        client_capabilities = body.get("capabilities", {})
        # body.get("client_info") or body.get("clientInfo", {})

        if not protocol_version:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing protocol version",
                headers={"MCP-Error-Code": "-32002"},
            )

        if protocol_version != settings.protocol_version:
            logger.warning(f"Using non default protocol version: {protocol_version}")

        # Store client capabilities if session_id provided
        if session_id and client_capabilities:
            await self.store_client_capabilities(session_id, client_capabilities)
            logger.debug(f"Stored capabilities for session {session_id}: {client_capabilities}")

        return InitializeResult(
            protocolVersion=protocol_version,
            capabilities=ServerCapabilities(
                prompts={"listChanged": True},
                resources={"subscribe": True, "listChanged": True},
                tools={"listChanged": True},
                logging={},
                completions={},  # Advertise completions capability per MCP spec
            ),
            serverInfo=Implementation(name=settings.app_name, version=__version__),
            instructions=("MCP Gateway providing federated tools, resources and prompts. Use /admin interface for configuration."),
        )

    async def store_client_capabilities(self, session_id: str, capabilities: Dict[str, Any]) -> None:
        """Store client capabilities for a session.

        Args:
            session_id: The session ID
            capabilities: Client capabilities dictionary from initialize request
        """
        async with self._lock:
            self._client_capabilities[session_id] = capabilities
        logger.debug(f"Stored capabilities for session {session_id}")

    async def get_client_capabilities(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get client capabilities for a session.

        Args:
            session_id: The session ID

        Returns:
            Client capabilities dictionary, or None if not found
        """
        async with self._lock:
            return self._client_capabilities.get(session_id)

    async def has_elicitation_capability(self, session_id: str) -> bool:
        """Check if a session has elicitation capability.

        Args:
            session_id: The session ID

        Returns:
            True if session supports elicitation, False otherwise
        """
        capabilities = await self.get_client_capabilities(session_id)
        if not capabilities:
            return False
        # Check if elicitation capability exists in client capabilities
        return bool(capabilities.get("elicitation"))

    async def get_elicitation_capable_sessions(self) -> list[str]:
        """Get list of session IDs that support elicitation.

        Returns:
            List of session IDs with elicitation capability
        """
        async with self._lock:
            capable_sessions = []
            for session_id, capabilities in self._client_capabilities.items():
                if capabilities.get("elicitation"):
                    # Verify session still exists
                    if session_id in self._sessions:
                        capable_sessions.append(session_id)
            return capable_sessions

    async def generate_response(self, message: Dict[str, Any], transport: SSETransport, server_id: Optional[str], user: Dict[str, Any], base_url: str) -> None:
        """Generate and send response for incoming MCP protocol message.

        Processes MCP protocol messages and generates appropriate responses based on
        the method. Supports various MCP methods including initialization, tool/resource/prompt
        listing, tool invocation, and ping.

        Args:
            message: Incoming MCP message as JSON. Must contain 'method' and 'id' fields.
            transport: SSE transport to send responses through.
            server_id: Optional server ID for scoped operations.
            user: User information containing authentication token.
            base_url: Base URL for constructing RPC endpoints.

        Examples:
            >>> import asyncio
            >>> from mcpgateway.cache.session_registry import SessionRegistry
            >>>
            >>> class MockTransport:
            ...     async def send_message(self, msg):
            ...         print(f"Response: {msg['method'] if 'method' in msg else msg.get('result', {})}")
            >>>
            >>> reg = SessionRegistry()
            >>> transport = MockTransport()
            >>> message = {"method": "ping", "id": 1}
            >>> user = {"token": "test-token"}
            >>> # asyncio.run(reg.generate_response(message, transport, None, user, "http://localhost"))
            >>> # Response: {}
        """
        result = {}

        if "method" in message and "id" in message:
            method = message["method"]
            params = message.get("params", {})
            params["server_id"] = server_id
            req_id = message["id"]

            rpc_input = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": req_id,
            }
            # Get the token from the current authentication context
            # The user object doesn't contain the token directly, we need to reconstruct it
            # Since we don't have access to the original headers here, we need a different approach
            # We'll extract the token from the session or create a new admin token
            token = None
            try:
                if hasattr(user, "get") and "auth_token" in user:
                    token = user["auth_token"]
                else:
                    # Fallback: create an admin token for internal RPC calls
                    now = datetime.now(timezone.utc)
                    payload = {
                        "sub": user.get("email", "system"),
                        "iss": settings.jwt_issuer,
                        "aud": settings.jwt_audience,
                        "iat": int(now.timestamp()),
                        "jti": str(uuid.uuid4()),
                        "user": {
                            "email": user.get("email", "system"),
                            "full_name": user.get("full_name", "System"),
                            "is_admin": True,  # Internal calls should have admin access
                            "auth_provider": "internal",
                        },
                    }
                    # Generate token using centralized token creation
                    token = await create_jwt_token(payload)

                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                # Extract root URL from base_url (remove /servers/{id} path)
                parsed_url = urlparse(base_url)
                # Preserve the path up to the root path (before /servers/{id})
                path_parts = parsed_url.path.split("/")
                if "/servers/" in parsed_url.path:
                    # Find the index of 'servers' and take everything before it
                    try:
                        servers_index = path_parts.index("servers")
                        root_path = "/" + "/".join(path_parts[1:servers_index]).strip("/")
                        if root_path == "/":
                            root_path = ""
                    except ValueError:
                        root_path = ""
                else:
                    root_path = parsed_url.path.rstrip("/")

                root_url = f"{parsed_url.scheme}://{parsed_url.netloc}{root_path}"
                rpc_url = root_url + "/rpc"

                logger.info(f"SSE RPC: Making call to {rpc_url} with method={method}, params={params}")

                async with ResilientHttpClient(client_args={"timeout": settings.federation_timeout, "verify": not settings.skip_ssl_verify}) as client:
                    logger.info(f"SSE RPC: Sending request to {rpc_url}")
                    rpc_response = await client.post(
                        url=rpc_url,
                        json=rpc_input,
                        headers=headers,
                    )
                    logger.info(f"SSE RPC: Got response status {rpc_response.status_code}")
                    result = rpc_response.json()
                    logger.info(f"SSE RPC: Response content: {result}")
                    result = result.get("result", {})

                response = {"jsonrpc": "2.0", "result": result, "id": req_id}
            except JSONRPCError as e:
                logger.error(f"SSE RPC: JSON-RPC error: {e}")
                result = e.to_dict()
                response = {"jsonrpc": "2.0", "error": result["error"], "id": req_id}
            except Exception as e:
                logger.error(f"SSE RPC: Exception during RPC call: {type(e).__name__}: {e}")
                logger.error(f"SSE RPC: Traceback: {traceback.format_exc()}")
                result = {"code": -32000, "message": "Internal error", "data": str(e)}
                response = {"jsonrpc": "2.0", "error": result, "id": req_id}

            logging.debug(f"Sending sse message:{response}")
            await transport.send_message(response)

            if message["method"] == "initialize":
                await transport.send_message(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {},
                    }
                )
                notifications = [
                    "tools/list_changed",
                    "resources/list_changed",
                    "prompts/list_changed",
                ]
                for notification in notifications:
                    await transport.send_message(
                        {
                            "jsonrpc": "2.0",
                            "method": f"notifications/{notification}",
                            "params": {},
                        }
                    )
