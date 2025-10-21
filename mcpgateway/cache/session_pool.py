# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/session_pool.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Session Pool
"""

import asyncio
import time
import logging
from typing import Dict, Optional, Any
from enum import Enum
from dataclasses import dataclass
from mcpgateway.cache.session_registry import SessionRegistry
from mcpgateway.config import settings
from mcpgateway.transports.sse_transport import SSETransport
from mcpgateway.transports.websocket_transport import WebSocketTransport
from mcpgateway.transports.base import Transport


logger = logging.getLogger(__name__)


class TransportType(Enum):
    """Enumeration of supported transport types."""
    SSE = "sse"
    WEBSOCKET = "websocket"


@dataclass
class PoolKey:
    """Structured key for session pooling with proper hashing."""
    user_id: str
    server_id: str
    transport_type: TransportType

    def __hash__(self):
        """Compute hash based on user_id, server_id, and transport_type."""
        return hash((self.user_id, self.server_id, self.transport_type))

    def __eq__(self, other):
        """Equality check based on user_id, server_id, and transport_type."""
        return (isinstance(other, PoolKey) and
                self.user_id == other.user_id and
                self.server_id == other.server_id and
                self.transport_type == other.transport_type)


class PooledSession:
    """Wrapper around transport for pooling and metrics tracking."""
    def __init__(self, transport: Transport, user_id: str, server_id: str, transport_type: TransportType):
        """Initialize pooled session wrapper."""
        self.transport = transport
        self.user_id = user_id
        self.server_id = server_id
        self.transport_type = transport_type
        self.created_at = time.time()
        self.last_used = time.time()
        self.use_count = 0
        self.active_connections = 0
        self.state_snapshot: Optional[Dict[str, Any]] = None  # For state continuity
        self._respond_task: Optional[asyncio.Task] = None

    @property
    def age(self) -> float:
        """Get the age of the session in seconds."""
        return time.time() - self.created_at

    @property
    def idle_time(self) -> float:
        """Get the idle time of the session in seconds."""
        return time.time() - self.last_used

    def capture_state(self) -> None:
        """Capture current session state for continuity."""
        # For SSE transport, we might want to capture initialization status
        if hasattr(self.transport, '_intialization_complete'):
            self.state_snapshot = {
                'intialization_complete': getattr(self.transport, '_intialization_complete', False),
                'last_activity': getattr(self.transport, '_last_activity', time.time())
            }
            logger.debug("Captured state for session %s", self.transport.session_id)

    def restore_state(self) -> None:
        """Restore session state if available."""
        if self.state_snapshot:
            if hasattr(self.transport, '_intialization_complete') and 'intialization_complete' in self.state_snapshot:
                self.transport._intialization_complete = self.state_snapshot['intialization_complete']
            if hasattr(self.transport, '_last_activity') and 'last_activity' in self.state_snapshot:
                self.transport._last_activity = self.state_snapshot['last_activity']
            logger.debug("Restored state for session %s", self.transport.session_id)


class SessionPool:
    """Enhanced session pool with multi-transport support and state continuity."""

    # Transport class mapping
    TRANSPORT_CLASSES = {
        TransportType.SSE: SSETransport,
        TransportType.WEBSOCKET: WebSocketTransport,
    }

    def __init__(self, session_registry: SessionRegistry):
        """Initialize the session pool."""
        self._registry = session_registry
        self._pool: Dict[PoolKey, PooledSession] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._metrics = {
            "created": 0,
            "reused": 0,
            "expired": 0,
            "cleaned": 0,
            "state_restored": 0,
            "connection_errors": 0,
        }

        # Start cleanup task if session pooling is enabled
        if settings.session_pooling_enabled:
            self._start_cleanup_task()
            logger.info("Session pool initialized with cleanup interval=%s sec",
                        settings.session_pool_cleanup_interval)

    # --------------------------------------------------------------------------
    # Core pooling logic with multi-transport support
    # --------------------------------------------------------------------------

    async def get_or_create_session(self, user_id: str, server_id: str, base_url: str,
                                    transport_type: TransportType) -> Transport:
        """Get an existing session for (user, server, transport) or create a new one."""
        if not settings.session_pooling_enabled:
            logger.debug("Session pooling disabled, creating fresh session.")
            return await self._create_new_session(user_id, server_id, base_url, transport_type)

        pool_key = PoolKey(user_id=user_id, server_id=server_id, transport_type=transport_type)
        async with self._lock:
            # Try to reuse a valid session
            if pool_key in self._pool:
                session = self._pool[pool_key]
                if await self._is_session_valid(session):
                    session.last_used = time.time()
                    session.use_count += 1
                    self._metrics["reused"] += 1

                    # Restore session state for continuity
                    session.restore_state()
                    if session.state_snapshot:
                        self._metrics["state_restored"] += 1

                    logger.debug(
                        "Reusing pooled session for user=%s server=%s type=%s (use_count=%s)",
                        user_id, server_id, transport_type.value, session.use_count,
                    )
                    return session.transport
                else:
                    await self._cleanup_session(pool_key, session)

            # Otherwise, create a new session
            new_session = await self._create_new_session(user_id, server_id, base_url, transport_type)
            self._pool[pool_key] = new_session
            return new_session.transport

    async def _create_new_session(self, user_id: str, server_id: str, base_url: str,
                                  transport_type: TransportType) -> PooledSession:
        """Create and register a brand new transport session."""
        try:
            # Create transport instance based on type
            transport_class = self.TRANSPORT_CLASSES.get(transport_type)
            if not transport_class:
                raise ValueError(f"Unsupported transport type: {transport_type}")

            # Create transport with pooling enabled
            if transport_type == TransportType.SSE:
                transport = transport_class(base_url=base_url, pooled=True, pool_key=f"{user_id}:{server_id}")
            else:
                # For WebSocket, we'll need the actual WebSocket object which is provided later
                # This is a placeholder - actual WebSocket creation happens in the endpoint
                transport = transport_class  # This will be handled differently for WebSocket

            # For SSE, we need to connect and register the session
            if transport_type == TransportType.SSE:
                await transport.connect()
                await self._registry.add_session(transport.session_id, transport, pooled=True)

            session = PooledSession(transport, user_id, server_id, transport_type)
            self._metrics["created"] += 1

            logger.info("Created new %s session for user=%s server=%s (session_id=%s)",
                        transport_type.value, 
                        user_id, 
                        server_id, 
                        transport.session_id)
            return session

        except Exception as e:
            self._metrics["connection_errors"] += 1
            logger.error("Failed to create new session: %s", e)
            raise

    # --------------------------------------------------------------------------
    # Validation & State Management
    # --------------------------------------------------------------------------

    async def _is_session_valid(self, session: PooledSession) -> bool:
        """Check whether a pooled session is still alive and eligible for reuse."""
        try:
            if not await session.transport.is_connected():
                logger.debug("Session %s disconnected.", session.transport.session_id)
                return False

            if session.age > settings.session_pool_ttl:
                logger.debug("Session %s expired (age=%s).", session.transport.session_id, session.age)
                return False

            if session.idle_time > settings.session_pool_max_idle_time:
                logger.debug("Session %s idle too long (idle_time=%s).",
                             session.transport.session_id, session.idle_time)
                return False

            # Additional transport-specific validation
            if hasattr(session.transport, 'validate_session'):
                if not await session.transport.validate_session():
                    logger.debug("Session %s failed transport-specific validation.",
                                 session.transport.session_id)
                    return False

            return True

        except Exception as e:
            logger.exception("Error validating session: %s", e)
            return False

    async def _cleanup_session(self, pool_key: PoolKey, session: PooledSession) -> None:
        """Safely close and remove a single session."""
        try:
            # Capture final state before cleanup
            session.capture_state()

            await session.transport.disconnect()
            self._metrics["cleaned"] += 1
            logger.info(
                "Cleaned up session %s (user=%s, server=%s, type=%s)",
                session.transport.session_id, session.user_id, session.server_id,
                session.transport_type.value
            )
        except Exception as e:
            logger.exception("Error during session cleanup: %s", e)

        # Remove from registry and pool
        await self._registry.remove_session(session.transport.session_id)

        if pool_key in self._pool:
            del self._pool[pool_key]

    async def cleanup_expired_sessions(self):
        """Periodic background task to clean up stale or expired sessions."""
        while True:
            try:
                async with self._lock:
                    now = time.time()
                    total_cleaned = 0
                    for pool_key, session in list(self._pool.items()):
                        if (
                            (now - session.last_used) > settings.session_pool_max_idle_time
                            or (now - session.created_at) > settings.session_pool_ttl
                            or not await session.transport.is_connected()
                        ):
                            await self._cleanup_session(pool_key, session)
                            total_cleaned += 1
                    if total_cleaned:
                        logger.debug("Session cleanup completed. %s sessions removed.", total_cleaned)

                # Log metrics periodically
                if settings.session_pool_metrics_enabled:
                    logger.info("Session pool metrics: %s", self._metrics)

            except Exception as e:
                logger.exception("Error during periodic session cleanup: %s", e)

            await asyncio.sleep(settings.session_pool_cleanup_interval)

    # --------------------------------------------------------------------------
    # State continuity and management
    # --------------------------------------------------------------------------

    async def capture_all_states(self) -> Dict[str, Any]:
        """Capture states from all active sessions for persistence."""
        states = {}
        async with self._lock:
            for pool_key, session in self._pool.items():
                if await session.transport.is_connected():
                    session.capture_state()
                    if session.state_snapshot:
                        states[session.transport.session_id] = {
                            'state': session.state_snapshot,
                            'user_id': session.user_id,
                            'server_id': session.server_id,
                            'transport_type': session.transport_type.value,
                            'last_used': session.last_used
                        }
        return states

    async def restore_session_state(self, session_id: str, state: Dict[str, Any]) -> bool:
        """Restore state to a specific session."""
        async with self._lock:
            for pool_key, session in self._pool.items():
                if session.transport.session_id == session_id:
                    session.state_snapshot = state.get('state')
                    session.restore_state()
                    self._metrics["state_restored"] += 1
                    logger.info("Restored state to session %s", session_id)
                    return True
        return False

    # --------------------------------------------------------------------------
    # Metrics and monitoring
    # --------------------------------------------------------------------------

    def get_pool_stats(self) -> Dict[str, Any]:
        """Get comprehensive pool statistics."""
        stats = {
            "metrics": self._metrics.copy(),
            "active_sessions": len(self._pool),
            "pool_keys": list(str(k) for k in self._pool.keys())
        }

        return stats

    # --------------------------------------------------------------------------
    # Lifecycle management
    # --------------------------------------------------------------------------

    def _start_cleanup_task(self):
        """Start background cleanup if enabled."""
        if not self._cleanup_task or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self.cleanup_expired_sessions())
            logger.info("Session cleanup task started (interval=%s).",
                        settings.session_pool_cleanup_interval)

    async def shutdown(self):
        """Gracefully stop the session pool and cleanup task."""
        logger.info("Shutting down session pool...")

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            for pool_key, session in list(self._pool.items()):
                await self._cleanup_session(pool_key, session)
            self._pool.clear()

        logger.info("Session pool shut down. Final metrics: %s", self._metrics)
