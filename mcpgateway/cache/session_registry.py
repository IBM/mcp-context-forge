# -*- coding: utf-8 -*-
"""Session Registry with optional distributed state.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module provides a registry for SSE sessions with support for distributed deployment
using Redis or SQLAlchemy as optional backends for shared state between workers.

Doctest examples (memory backend only)
--------------------------------------
>>> from mcpgateway.cache.session_registry import SessionRegistry
>>> class DummyTransport:
...     pass
>>> reg = SessionRegistry(backend='memory')
>>> import asyncio
>>> asyncio.run(reg.add_session('sid', DummyTransport()))
>>> t = asyncio.run(reg.get_session('sid'))
>>> isinstance(t, DummyTransport)
True
>>> asyncio.run(reg.remove_session('sid'))
>>> asyncio.run(reg.get_session('sid')) is None
True
"""

# Standard
import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

# Third-Party
from fastapi import HTTPException, status

# First-Party
from mcpgateway import __version__
from mcpgateway.config import settings
from mcpgateway.db import get_db, SessionMessageRecord, SessionRecord
from mcpgateway.models import Implementation, InitializeResult, ServerCapabilities
from mcpgateway.services import PromptService, ResourceService, ToolService
from mcpgateway.transports import SSETransport
from mcpgateway.utils.retry_manager import ResilientHttpClient

logger = logging.getLogger(__name__)

tool_service = ToolService()
resource_service = ResourceService()
prompt_service = PromptService()

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
    """Session backend related fields"""

    def __init__(
        self,
        backend: str = "memory",
        redis_url: Optional[str] = None,
        database_url: Optional[str] = None,
        session_ttl: int = 3600,  # 1 hour
        message_ttl: int = 600,  # 10 min
    ):
        """Initialize session registry.

        Args:
            backend: "memory", "redis", "database", or "none"
            redis_url: Redis connection URL (required for redis backend)
            database_url: Database connection URL (required for database backend)
            session_ttl: Session time-to-live in seconds
            message_ttl: Message time-to-live in seconds

        Raises:
            ValueError: If backend is invalid or required URL is missing
        """

        self._backend = backend.lower()
        self._session_ttl = session_ttl
        self._message_ttl = message_ttl

        # Set up backend-specific components
        if self._backend == "memory":
            # Nothing special needed for memory backend
            self._session_message = None

        elif self._backend == "none":
            # No session tracking - this is just a dummy registry
            logger.info("Session registry initialized with 'none' backend - session tracking disabled")

        elif self._backend == "redis":
            if not REDIS_AVAILABLE:
                raise ValueError("Redis backend requested but redis package not installed")
            if not redis_url:
                raise ValueError("Redis backend requires redis_url")

            self._redis = Redis.from_url(redis_url)
            self._pubsub = self._redis.pubsub()

        elif self._backend == "database":
            if not SQLALCHEMY_AVAILABLE:
                raise ValueError("Database backend requested but SQLAlchemy not installed")
            if not database_url:
                raise ValueError("Database backend requires database_url")
        else:
            raise ValueError(f"Invalid backend: {backend}")


class SessionRegistry(SessionBackend):
    """
    Registry for SSE sessions with optional distributed state.

    Supports three backend modes:
    - memory: In-memory storage (default, no dependencies)
    - redis: Redis-backed shared storage
    - database: SQLAlchemy-backed shared storage

    In distributed mode (redis/database), session existence is tracked in the shared
    backend while transports themselves remain local to each worker process.

    Doctest (memory backend only):
    >>> from mcpgateway.cache.session_registry import SessionRegistry
    >>> class DummyTransport:
    ...     pass
    >>> reg = SessionRegistry(backend='memory')
    >>> import asyncio
    >>> asyncio.run(reg.add_session('sid', DummyTransport()))
    >>> t = asyncio.run(reg.get_session('sid'))
    >>> isinstance(t, DummyTransport)
    True
    >>> asyncio.run(reg.remove_session('sid'))
    >>> asyncio.run(reg.get_session('sid')) is None
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
        """Initialize session registry.

        Args:
            backend: "memory", "redis", "database", or "none"
            redis_url: Redis connection URL (required for redis backend)
            database_url: Database connection URL (required for database backend)
            session_ttl: Session time-to-live in seconds
            message_ttl: Message time-to-live in seconds
        """
        super().__init__(backend=backend, redis_url=redis_url, database_url=database_url, session_ttl=session_ttl, message_ttl=message_ttl)
        self._sessions: Dict[str, Any] = {}  # Local transport cache
        self._lock = asyncio.Lock()
        self._cleanup_task = None

    async def initialize(self) -> None:
        """Initialize the registry with async setup.

        Call this during application startup.
        """
        logger.info(f"Initializing session registry with backend: {self._backend}")

        if self._backend == "database":
            # Start database cleanup task
            self._cleanup_task = asyncio.create_task(self._db_cleanup_task())
            logger.info("Database cleanup task started")

        elif self._backend == "redis":
            await self._pubsub.subscribe("mcp_session_events")

        elif self._backend == "none":
            # Nothing to initialize for none backend
            pass

        # Memory backend needs session cleanup
        elif self._backend == "memory":
            self._cleanup_task = asyncio.create_task(self._memory_cleanup_task())
            logger.info("Memory cleanup task started")

    async def shutdown(self) -> None:
        """Shutdown the registry.

        Call this during application shutdown.
        """
        logger.info("Shutting down session registry")

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Close Redis connections
        if self._backend == "redis":
            try:
                await self._pubsub.aclose()
                await self._redis.aclose()
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")

    async def add_session(self, session_id: str, transport: SSETransport) -> None:
        """Add a session to the registry.

        Args:
            session_id: Unique session identifier
            transport: Transport session
        """
        # Skip for none backend
        if self._backend == "none":
            return

        async with self._lock:
            self._sessions[session_id] = transport

        if self._backend == "redis":
            # Store session marker in Redis
            try:
                await self._redis.setex(f"mcp:session:{session_id}", self._session_ttl, "1")
                # Publish event to notify other workers
                await self._redis.publish("mcp_session_events", json.dumps({"type": "add", "session_id": session_id, "timestamp": time.time()}))
            except Exception as e:
                logger.error(f"Redis error adding session {session_id}: {e}")

        elif self._backend == "database":
            # Store session in database
            try:

                def _db_add():
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
        """Get session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Transport object or None if not found
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

                def _db_check():
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

        Args:
            session_id: Session identifier
        """
        # Skip for none backend
        if self._backend == "none":
            return

        # Clean up local transport
        transport = None
        async with self._lock:
            if session_id in self._sessions:
                transport = self._sessions.pop(session_id)

        # Disconnect transport if found
        if transport:
            try:
                await transport.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting transport for session {session_id}: {e}")

        # Remove from shared backend
        if self._backend == "redis":
            try:
                await self._redis.delete(f"mcp:session:{session_id}")
                # Notify other workers
                await self._redis.publish("mcp_session_events", json.dumps({"type": "remove", "session_id": session_id, "timestamp": time.time()}))
            except Exception as e:
                logger.error(f"Redis error removing session {session_id}: {e}")

        elif self._backend == "database":
            try:

                def _db_remove():
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

    async def broadcast(self, session_id: str, message: dict) -> None:
        """Broadcast a session_id and message to a channel.

        Args:
            session_id: Session ID
            message: Message to broadcast
        """
        # Skip for none and memory backend
        if self._backend == "none":
            return

        if self._backend == "memory":
            if isinstance(message, (dict, list)):
                msg_json = json.dumps(message)
            else:
                msg_json = json.dumps(str(message))

            self._session_message = {"session_id": session_id, "message": msg_json}

        elif self._backend == "redis":
            try:
                if isinstance(message, (dict, list)):
                    msg_json = json.dumps(message)
                else:
                    msg_json = json.dumps(str(message))

                await self._redis.publish(session_id, json.dumps({"type": "message", "message": msg_json, "timestamp": time.time()}))
            except Exception as e:
                logger.error(f"Redis error during broadcast: {e}")
        elif self._backend == "database":
            try:
                if isinstance(message, (dict, list)):
                    msg_json = json.dumps(message)
                else:
                    msg_json = json.dumps(str(message))

                def _db_add():
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
        """Get session synchronously (not checking shared backend).

        This is a non-blocking method for handlers that need quick access.
        It only checks the local cache, not the shared backend.

        Args:
            session_id: Session identifier

        Returns:
            Transport object or None if not found
        """
        # Skip for none backend
        if self._backend == "none":
            return None

        return self._sessions.get(session_id)

    async def respond(
        self,
        server_id: Optional[str],
        user: json,
        session_id: str,
        base_url: str,
    ) -> None:
        """Respond to broadcast message is transport relevant to session_id is found locally

        Args:
            server_id: Server ID
            session_id: Session ID
            user: User information
            base_url: Base URL for the FastAPI request

        """

        if self._backend == "none":
            pass

        elif self._backend == "memory":
            # if self._session_message:
            transport = self.get_session_sync(session_id)
            if transport:
                message = json.loads(self._session_message.get("message"))
                await self.generate_response(message=message, transport=transport, server_id=server_id, user=user, base_url=base_url)

        elif self._backend == "redis":
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(session_id)

            try:
                async for msg in pubsub.listen():
                    if msg["type"] != "message":
                        continue
                    data = json.loads(msg["data"])
                    message = data.get("message", {})
                    if isinstance(message, str):
                        message = json.loads(message)
                    transport = self.get_session_sync(session_id)
                    if transport:
                        await self.generate_response(message=message, transport=transport, server_id=server_id, user=user, base_url=base_url)
            except asyncio.CancelledError:
                logger.info(f"PubSub listener for session {session_id} cancelled")
            finally:
                await pubsub.unsubscribe(session_id)
                await pubsub.close()
                logger.info(f"Cleaned up pubsub for session {session_id}")

        elif self._backend == "database":

            def _db_read_session(session_id):
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

            def _db_read(session_id):
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

            def _db_remove(session_id, message):
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

            async def message_check_loop(session_id):
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
                        message = json.loads(record.message)
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
        """Refresh TTLs for Redis sessions and clean up disconnected sessions."""
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
        """Periodically clean up expired database sessions."""
        logger.info("Starting database cleanup task")
        while True:
            try:
                # Clean up expired sessions every 5 minutes
                def _db_cleanup():
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
                        expiry_time = func.now() - func.make_interval(seconds=self._session_ttl)  # pylint: disable=not-callable
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
                        def _refresh_session(session_id=session_id):
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
        """Periodically clean up disconnected sessions."""
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
    async def handle_initialize_logic(self, body: dict) -> InitializeResult:
        """
        Validates the protocol version from the request body and returns an InitializeResult with server capabilities and info.

        Args:
            body (dict): The incoming request body.

        Raises:
            HTTPException: If the protocol version is missing or unsupported.

        Returns:
            InitializeResult: Initialization result with protocol version, capabilities, and server info.
        """
        protocol_version = body.get("protocol_version") or body.get("protocolVersion")
        # body.get("capabilities", {})
        # body.get("client_info") or body.get("clientInfo", {})

        if not protocol_version:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing protocol version",
                headers={"MCP-Error-Code": "-32002"},
            )

        if protocol_version != settings.protocol_version:
            logger.warning(f"Using non default protocol version: {protocol_version}")

        return InitializeResult(
            protocolVersion=settings.protocol_version,
            capabilities=ServerCapabilities(
                prompts={"listChanged": True},
                resources={"subscribe": True, "listChanged": True},
                tools={"listChanged": True},
                logging={},
                roots={"listChanged": True},
                sampling={},
            ),
            serverInfo=Implementation(name=settings.app_name, version=__version__),
            instructions=("MCP Gateway providing federated tools, resources and prompts. Use /admin interface for configuration."),
        )

    async def generate_response(self, message: json, transport: SSETransport, server_id: Optional[str], user: dict, base_url: str):
        """
        Generates response according to SSE specifications

        Args:
            message: Message JSON
            transport: Transport where message should be responded in
            server_id: Server ID
            user: User information
            base_url: Base URL for the FastAPI request

        """
        result = {}

        if "method" in message and "id" in message:
            method = message["method"]
            params = message.get("params", {})
            req_id = message["id"]
            db = next(get_db())
            if method == "initialize":
                init_result = await self.handle_initialize_logic(params)
                response = {
                    "jsonrpc": "2.0",
                    "result": init_result.model_dump(by_alias=True, exclude_none=True),
                    "id": req_id,
                }
                await transport.send_message(response)
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
            elif method == "tools/list":
                if server_id:
                    tools = await tool_service.list_server_tools(db, server_id=server_id)
                else:
                    tools = await tool_service.list_tools(db)
                result = {"tools": [t.model_dump(by_alias=True, exclude_none=True) for t in tools]}
            elif method == "resources/list":
                if server_id:
                    resources = await resource_service.list_server_resources(db, server_id=server_id)
                else:
                    resources = await resource_service.list_resources(db)
                result = {"resources": [r.model_dump(by_alias=True, exclude_none=True) for r in resources]}
            elif method == "prompts/list":
                if server_id:
                    prompts = await prompt_service.list_server_prompts(db, server_id=server_id)
                else:
                    prompts = await prompt_service.list_prompts(db)
                result = {"prompts": [p.model_dump(by_alias=True, exclude_none=True) for p in prompts]}
            elif method == "ping":
                result = {}
            elif method == "tools/call":
                rpc_input = {
                    "jsonrpc": "2.0",
                    "method": message["params"]["name"],
                    "params": message["params"]["arguments"],
                    "id": 1,
                }
                headers = {"Authorization": f"Bearer {user['token']}", "Content-Type": "application/json"}
                rpc_url = base_url + "/rpc"
                async with ResilientHttpClient(client_args={"timeout": settings.federation_timeout, "verify": not settings.skip_ssl_verify}) as client:
                    rpc_response = await client.post(
                        url=rpc_url,
                        json=rpc_input,
                        headers=headers,
                    )
                    result = rpc_response.json()
            else:
                result = {}

            response = {"jsonrpc": "2.0", "result": result, "id": req_id}
            logging.info(f"Sending sse message:{response}")
            await transport.send_message(response)
