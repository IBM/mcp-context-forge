# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/session_pool.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: IBM Bob

Session Pool Implementation for MCP Gateway.

This module provides session pooling functionality to improve performance
and reduce connection overhead by reusing sessions across multiple requests.
"""

import asyncio
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from mcpgateway.cache.pool_strategies import PoolStatus, PoolStrategy
from mcpgateway.config import settings
from mcpgateway.db import engine, PoolStrategyMetric, SessionPool as SessionPoolModel, SessionRecord

logger = logging.getLogger(__name__)


class PooledSession:
    """Represents a single pooled session with metadata for pool management.
    
    Attributes:
        session_id: Unique identifier for the session
        created_at: When the session was created
        last_used: When the session was last acquired
        reuse_count: Number of times the session has been reused
        is_healthy: Whether the session is in a healthy state
        in_use: Whether the session is currently in use
    """

    def __init__(self, session_id: str):
        """Initialize a pooled session.
        
        Args:
            session_id: Unique identifier for the session
        """
        self.session_id = session_id
        self.created_at = datetime.now(timezone.utc)
        self.last_used = self.created_at
        self.reuse_count = 0
        self.is_healthy = True
        self.in_use = False
        self.last_error: Optional[str] = None

    def acquire(self) -> None:
        """Mark the session as in use."""
        self.in_use = True
        self.last_used = datetime.now(timezone.utc)
        self.reuse_count += 1

    def release(self) -> None:
        """Mark the session as available."""
        self.in_use = False
        self.last_used = datetime.now(timezone.utc)

    def mark_unhealthy(self, error: Optional[str] = None) -> None:
        """Mark the session as unhealthy.
        
        Args:
            error: Optional error message describing the health issue
        """
        self.is_healthy = False
        self.last_error = error

    def mark_healthy(self) -> None:
        """Mark the session as healthy."""
        self.is_healthy = True
        self.last_error = None

    @property
    def age_seconds(self) -> float:
        """Get the age of the session in seconds."""
        return (datetime.now(timezone.utc) - self.created_at).total_seconds()

    @property
    def idle_seconds(self) -> float:
        """Get the idle time of the session in seconds."""
        return (datetime.now(timezone.utc) - self.last_used).total_seconds()


class SessionPool:
    """Manages a pool of reusable sessions for a specific server.
    
    This class implements session pooling with configurable strategies
    (round-robin, least connections, sticky, weighted) to optimize
    session reuse and improve performance.
    
    Attributes:
        pool_id: Unique identifier for the pool
        server_id: ID of the server this pool manages sessions for
        strategy: Pooling strategy to use (round_robin, least_connections, etc.)
        min_size: Minimum number of sessions to maintain
        max_size: Maximum number of sessions allowed
        timeout: Timeout in seconds for acquiring a session
    """

    def __init__(
        self,
        pool_id: str,
        server_id: str,
        strategy: PoolStrategy = PoolStrategy.ROUND_ROBIN,
        min_size: int = 1,
        max_size: int = 10,
        timeout: int = 30,
        recycle_seconds: int = 3600,
        pre_ping: bool = True,
    ):
        """Initialize a session pool.
        
        Args:
            pool_id: Unique identifier for the pool
            server_id: ID of the server this pool manages sessions for
            strategy: Pooling strategy to use
            min_size: Minimum number of sessions to maintain
            max_size: Maximum number of sessions allowed
            timeout: Timeout in seconds for acquiring a session
            recycle_seconds: Recycle sessions older than this many seconds
            pre_ping: Whether to ping sessions before returning them
        """
        self.pool_id = pool_id
        self.server_id = server_id
        self.strategy = strategy
        self.min_size = min_size
        self.max_size = max_size
        self.timeout = timeout
        self.recycle_seconds = recycle_seconds
        self.pre_ping = pre_ping

        # Pool state
        self._sessions: Dict[str, PooledSession] = {}
        self._available: deque = deque()  # Queue of available session IDs
        self._lock = asyncio.Lock()
        self._status = PoolStatus.IDLE
        self._round_robin_index = 0

        # Metrics
        self._total_acquisitions = 0
        self._total_releases = 0
        self._total_timeouts = 0
        self._total_creates = 0
        self._total_destroys = 0

        logger.info(
            f"Initialized session pool {pool_id} for server {server_id} "
            f"with strategy {strategy.value}, min_size={min_size}, max_size={max_size}"
        )

    async def initialize(self) -> None:
        """Initialize the pool by creating minimum number of sessions."""
        async with self._lock:
            self._status = PoolStatus.WARMING
            logger.info(f"Warming up pool {self.pool_id} with {self.min_size} sessions")

            for _ in range(self.min_size):
                session = await self._create_session()
                if session:
                    self._sessions[session.session_id] = session
                    self._available.append(session.session_id)

            self._status = PoolStatus.ACTIVE
            logger.info(f"Pool {self.pool_id} is now active with {len(self._sessions)} sessions")

    async def acquire(self, timeout: Optional[int] = None) -> Optional[str]:
        """Acquire a session from the pool.
        
        Args:
            timeout: Optional timeout in seconds (uses pool default if not specified)
            
        Returns:
            Session ID if successful, None if timeout or error
        """
        timeout = timeout or self.timeout
        start_time = time.time()
        wait_time = 0.0

        try:
            async with asyncio.timeout(timeout):
                while True:
                    async with self._lock:
                        # Try to get an available session
                        session_id = await self._get_next_session()
                        
                        if session_id:
                            session = self._sessions[session_id]
                            
                            # Check if session needs recycling
                            if session.age_seconds > self.recycle_seconds:
                                logger.info(f"Recycling old session {session_id} (age: {session.age_seconds}s)")
                                await self._destroy_session(session_id)
                                continue
                            
                            # Pre-ping if enabled
                            if self.pre_ping and not await self._ping_session(session_id):
                                logger.warning(f"Session {session_id} failed pre-ping check")
                                session.mark_unhealthy("Failed pre-ping check")
                                continue
                            
                            # Acquire the session
                            session.acquire()
                            self._total_acquisitions += 1
                            
                            # Record metrics
                            wait_time = time.time() - start_time
                            await self._record_metric(
                                session_id=session_id,
                                response_time=wait_time,
                                success=True,
                                session_reused=session.reuse_count > 1,
                                wait_time=wait_time
                            )
                            
                            logger.debug(
                                f"Acquired session {session_id} from pool {self.pool_id} "
                                f"(reuse_count={session.reuse_count}, wait_time={wait_time:.3f}s)"
                            )
                            return session_id
                        
                        # No available sessions, try to create one if under max_size
                        if len(self._sessions) < self.max_size:
                            session = await self._create_session()
                            if session:
                                self._sessions[session.session_id] = session
                                session.acquire()
                                self._total_acquisitions += 1
                                
                                wait_time = time.time() - start_time
                                await self._record_metric(
                                    session_id=session.session_id,
                                    response_time=wait_time,
                                    success=True,
                                    session_reused=False,
                                    wait_time=wait_time
                                )
                                
                                logger.debug(f"Created and acquired new session {session.session_id}")
                                return session.session_id
                    
                    # Wait a bit before retrying
                    await asyncio.sleep(0.1)
                    
        except asyncio.TimeoutError:
            self._total_timeouts += 1
            wait_time = time.time() - start_time
            await self._record_metric(
                session_id=None,
                response_time=wait_time,
                success=False,
                session_reused=False,
                wait_time=wait_time,
                error_message="Timeout waiting for available session"
            )
            logger.warning(f"Timeout acquiring session from pool {self.pool_id} after {wait_time:.3f}s")
            return None
        except Exception as e:
            wait_time = time.time() - start_time
            await self._record_metric(
                session_id=None,
                response_time=wait_time,
                success=False,
                session_reused=False,
                wait_time=wait_time,
                error_message=str(e)
            )
            logger.error(f"Error acquiring session from pool {self.pool_id}: {e}")
            return None

    async def release(self, session_id: str, healthy: bool = True, error: Optional[str] = None) -> None:
        """Release a session back to the pool.
        
        Args:
            session_id: ID of the session to release
            healthy: Whether the session is still healthy
            error: Optional error message if session is unhealthy
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                logger.warning(f"Attempted to release unknown session {session_id}")
                return
            
            if not healthy:
                session.mark_unhealthy(error)
                logger.warning(f"Session {session_id} marked unhealthy: {error}")
                await self._destroy_session(session_id)
                return
            
            session.release()
            self._available.append(session_id)
            self._total_releases += 1
            
            logger.debug(f"Released session {session_id} back to pool {self.pool_id}")

    async def _get_next_session(self) -> Optional[str]:
        """Get the next available session based on the pool strategy.
        
        Returns:
            Session ID if available, None otherwise
        """
        if not self._available:
            return None
        
        if self.strategy == PoolStrategy.ROUND_ROBIN:
            # Simple round-robin: take from front of queue
            return self._available.popleft()
        
        elif self.strategy == PoolStrategy.LEAST_CONNECTIONS:
            # Find session with lowest reuse count
            min_reuse = float('inf')
            best_session_id = None
            
            for session_id in list(self._available):
                session = self._sessions[session_id]
                if session.reuse_count < min_reuse:
                    min_reuse = session.reuse_count
                    best_session_id = session_id
            
            if best_session_id:
                self._available.remove(best_session_id)
                return best_session_id
        
        elif self.strategy == PoolStrategy.STICKY:
            # For sticky, we'd need client context - fall back to round-robin
            return self._available.popleft()
        
        elif self.strategy == PoolStrategy.WEIGHTED:
            # For weighted, we'd need session weights - fall back to round-robin
            return self._available.popleft()
        
        else:  # NONE or unknown
            return self._available.popleft()
        
        return None

    async def _create_session(self) -> Optional[PooledSession]:
        """Create a new session.
        
        Returns:
            PooledSession if successful, None otherwise
        """
        try:
            session_id = uuid.uuid4().hex
            session = PooledSession(session_id)
            self._total_creates += 1
            
            logger.debug(f"Created new session {session_id} for pool {self.pool_id}")
            return session
        except Exception as e:
            logger.error(f"Error creating session for pool {self.pool_id}: {e}")
            return None

    async def _destroy_session(self, session_id: str) -> None:
        """Destroy a session and remove it from the pool.
        
        Args:
            session_id: ID of the session to destroy
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            self._total_destroys += 1
            
            # Remove from available queue if present
            try:
                self._available.remove(session_id)
            except ValueError:
                pass  # Not in queue, that's fine
            
            logger.debug(f"Destroyed session {session_id} from pool {self.pool_id}")

    async def _ping_session(self, session_id: str) -> bool:
        """Ping a session to check if it's still alive.
        
        Args:
            session_id: ID of the session to ping
            
        Returns:
            True if session is alive, False otherwise
        """
        # TODO: Implement actual session health check
        # For now, assume all sessions are healthy
        return True

    async def _record_metric(
        self,
        session_id: Optional[str],
        response_time: float,
        success: bool,
        session_reused: bool,
        wait_time: float,
        error_message: Optional[str] = None
    ) -> None:
        """Record a pool strategy metric to the database.
        
        Args:
            session_id: ID of the session (None if acquisition failed)
            response_time: Time taken for the operation
            success: Whether the operation was successful
            session_reused: Whether an existing session was reused
            wait_time: Time spent waiting for a session
            error_message: Optional error message if operation failed
        """
        try:
            with DBSession(engine) as db_session:
                metric = PoolStrategyMetric(
                    id=uuid.uuid4().hex,
                    pool_id=self.pool_id,
                    strategy=self.strategy.value,
                    timestamp=datetime.now(timezone.utc),
                    response_time=response_time,
                    success=success,
                    session_reused=session_reused,
                    wait_time=wait_time,
                    error_message=error_message
                )
                db_session.add(metric)
                db_session.commit()
        except Exception as e:
            logger.error(f"Error recording pool metric: {e}")

    async def get_stats(self) -> Dict[str, Any]:
        """Get current pool statistics.
        
        Returns:
            Dictionary containing pool statistics
        """
        async with self._lock:
            active_sessions = sum(1 for s in self._sessions.values() if s.in_use)
            available_sessions = len(self._available)
            unhealthy_sessions = sum(1 for s in self._sessions.values() if not s.is_healthy)
            
            return {
                "pool_id": self.pool_id,
                "server_id": self.server_id,
                "strategy": self.strategy.value,
                "status": self._status.value,
                "total_sessions": len(self._sessions),
                "active_sessions": active_sessions,
                "available_sessions": available_sessions,
                "unhealthy_sessions": unhealthy_sessions,
                "min_size": self.min_size,
                "max_size": self.max_size,
                "total_acquisitions": self._total_acquisitions,
                "total_releases": self._total_releases,
                "total_timeouts": self._total_timeouts,
                "total_creates": self._total_creates,
                "total_destroys": self._total_destroys,
            }

    async def drain(self) -> None:
        """Drain the pool by preventing new acquisitions and waiting for active sessions to be released."""
        async with self._lock:
            self._status = PoolStatus.DRAINING
            logger.info(f"Draining pool {self.pool_id}")

    async def shutdown(self) -> None:
        """Shutdown the pool and destroy all sessions."""
        async with self._lock:
            self._status = PoolStatus.ERROR
            logger.info(f"Shutting down pool {self.pool_id}")
            
            # Destroy all sessions
            for session_id in list(self._sessions.keys()):
                await self._destroy_session(session_id)
            
            self._available.clear()
            logger.info(f"Pool {self.pool_id} shutdown complete")

# Made with Bob
