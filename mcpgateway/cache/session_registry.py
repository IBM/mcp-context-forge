# -*- coding: utf-8 -*-
"""Session Registry with optional distributed state.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module provides a registry for SSE sessions with support for distributed deployment
using Redis or SQLAlchemy as optional backends for shared state between workers.
"""

# Standard
import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

# Third-Party
from fastapi import HTTPException, status
import httpx

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db, SessionMessageRecord, SessionRecord
from mcpgateway.models import Implementation, InitializeResult, ServerCapabilities
from mcpgateway.services import PromptService, ResourceService, ToolService
from mcpgateway.transports import SSETransport

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

        elif self._backend == "database":
            if not SQLALCHEMY_AVAILABLE:
                raise ValueError("Database backend requested but SQLAlchemy not installed")
            if not database_url:
                raise ValueError("Database backend requires database_url")
        else:
            raise ValueError(f"Invalid backend: {backend}")


class SessionRegistry(SessionBackend):
    """Registry for SSE sessions with optional distributed state.

    Supports three backend modes:
    - memory: In-memory storage (default, no dependencies)
    - redis: Redis-backed shared storage
    - database: SQLAlchemy-backed shared storage

    In distributed mode (redis/database), session existence is tracked in the shared
    backend while transports themselves remain local to each worker process.
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
            self._pubsub = self._redis.pubsub()
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
            await self._pubsub.subscribe(session_id)

            try:
                async for msg in self._pubsub.listen():
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
                await self._pubsub.unsubscribe(session_id)
                logger.info(f"Cleaned up pubsub for session {session_id}")

        elif self._backend == "database":

            def _db_read_session(session_id):
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
                        def _refresh_session():
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported protocol version: {protocol_version}",
                headers={"MCP-Error-Code": "-32003"},
            )

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
            serverInfo=Implementation(name=settings.app_name, version="1.0.0"),
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
                async with httpx.AsyncClient(timeout=settings.federation_timeout, verify=not settings.skip_ssl_verify) as client:
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
