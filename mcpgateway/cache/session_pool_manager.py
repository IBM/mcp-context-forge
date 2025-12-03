# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/session_pool_manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Session Pool Manager for MCP Gateway.

This module provides centralized management of session pools across multiple
servers, including pool lifecycle management, health monitoring, and automatic
strategy optimization based on performance metrics.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session as DBSession

from mcpgateway.cache.pool_strategies import PoolStatus, PoolStrategy, recommend_strategy
from mcpgateway.cache.session_pool import SessionPool
from mcpgateway.config import settings
from mcpgateway.db import engine, PoolStrategyMetric, Server, SessionPool as SessionPoolModel

logger = logging.getLogger(__name__)


class SessionPoolManager:
    """Manages session pools across multiple servers.
    
    This class provides centralized management of session pools, including:
    - Pool creation and lifecycle management
    - Health monitoring and automatic recovery
    - Strategy optimization based on performance metrics
    - Pool statistics and reporting
    
    Attributes:
        pools: Dictionary mapping pool IDs to SessionPool instances
        enabled: Whether session pooling is globally enabled
    """

    def __init__(self):
        """Initialize the session pool manager."""
        self._pools: Dict[str, SessionPool] = {}
        self._lock = asyncio.Lock()
        self._monitoring_task: Optional[asyncio.Task] = None
        self._optimization_task: Optional[asyncio.Task] = None
        self._enabled = settings.session_pool_enabled
        
        logger.info(
            f"Initialized SessionPoolManager (enabled={self._enabled},"
            f"default_strategy={settings.session_pool_strategy})")
        
        # Graceful degradation
        self._overflow_pool: Optional[SessionPool] = None
        self._emergency_mode = False
        self._direct_connection_count = 0
        

    async def initialize(self) -> None:
        """Initialize the pool manager and load existing pools from database."""
        if not self._enabled:
            logger.info("Session pooling is disabled")
            return
        
        logger.info("Initializing SessionPoolManager")
        
        # Load existing pools from database
        await self._load_pools_from_db()
        
        # Start background tasks
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        if settings.pool_strategy_auto_adjust:
            self._optimization_task = asyncio.create_task(self._optimization_loop())
        
        logger.info(f"SessionPoolManager initialized with {len(self._pools)} pools")

    async def shutdown(self) -> None:
        """Shutdown the pool manager and all managed pools."""
        logger.info("Shutting down SessionPoolManager")
        
        # Cancel background tasks
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        if self._optimization_task:
            self._optimization_task.cancel()
            try:
                await self._optimization_task
            except asyncio.CancelledError:
                pass
        
        # Shutdown all pools
        async with self._lock:
            for pool in self._pools.values():
                await pool.shutdown()
            self._pools.clear()
        
        logger.info("SessionPoolManager shutdown complete")

    async def get_or_create_pool(
        self,
        server_id: str,
        strategy: Optional[PoolStrategy] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
    ) -> Optional[SessionPool]:
        """Get an existing pool for a server or create a new one.
        
        Args:
            server_id: ID of the server
            strategy: Optional pooling strategy (uses server config if not specified)
            min_size: Optional minimum pool size (uses server config if not specified)
            max_size: Optional maximum pool size (uses server config if not specified)
            
        Returns:
            SessionPool instance if successful, None otherwise
        """
        if not self._enabled:
            return None
        
        async with self._lock:
            # Check if pool already exists for this server
            for pool in self._pools.values():
                if pool.server_id == server_id:
                    return pool
            
            # Load server configuration
            server_config = await self._get_server_config(server_id)
            if not server_config:
                logger.error(f"Server {server_id} not found")
                return None
            
            # Check if pooling is enabled for this server
            if not server_config.get("pool_enabled", False):
                logger.debug(f"Pooling not enabled for server {server_id}")
                return None
            
            # Create new pool
            pool_id = uuid.uuid4().hex
            pool_strategy = strategy or PoolStrategy(server_config.get("pool_strategy", settings.session_pool_strategy))
            pool_min_size = min_size or server_config.get("pool_min_size", 1)
            pool_max_size = max_size or server_config.get("pool_max_size", settings.session_pool_size)
            
            pool = SessionPool(
                pool_id=pool_id,
                server_id=server_id,
                strategy=pool_strategy,
                min_size=pool_min_size,
                max_size=pool_max_size,
                timeout=server_config.get("pool_timeout", 30),
                recycle_seconds=server_config.get("pool_recycle", 3600),
                pre_ping=server_config.get("pool_pre_ping", True),
            )
            
            # Initialize the pool
            await pool.initialize()
            
            # Store in database
            await self._save_pool_to_db(pool, server_config.get("name", f"Server {server_id}"))
            
            # Add to managed pools
            self._pools[pool_id] = pool
            
            logger.info(f"Created new pool {pool_id} for server {server_id}")
            return pool

    async def get_pool_for_server(self, server_id: str) -> Optional[SessionPool]:
        """Get the pool for a specific server.
        
        Args:
            server_id: ID of the server
            
        Returns:
            SessionPool instance if found, None otherwise
        """
        async with self._lock:
            for pool in self._pools.values():
                if pool.server_id == server_id:
                    return pool
        return None

    async def acquire_session(self, server_id: str, timeout: Optional[int] = None) -> Optional[str]:
        """Acquire a session from the pool for a specific server.
        
        Args:
            server_id: ID of the server
            timeout: Optional timeout in seconds
            
        Returns:
            Session ID if successful, None otherwise
        """
        pool = await self.get_or_create_pool(server_id)
        if not pool:
            return None
        
        return await pool.acquire(timeout=timeout)

    async def release_session(
        self,
        server_id: str,
        session_id: str,
        healthy: bool = True,
        error: Optional[str] = None
    ) -> None:
        """Release a session back to the pool.
        
        Args:
            server_id: ID of the server
            session_id: ID of the session to release
            healthy: Whether the session is still healthy
            error: Optional error message if session is unhealthy
        """
        pool = await self.get_pool_for_server(server_id)
        if pool:
            await pool.release(session_id, healthy=healthy, error=error)

    async def get_pool_stats(self, server_id: Optional[str] = None) -> List[Dict]:
        """Get statistics for all pools or a specific server's pool.
        
        Args:
            server_id: Optional server ID to filter by
            
        Returns:
            List of pool statistics dictionaries
        """
        stats = []
        async with self._lock:
            for pool in self._pools.values():
                if server_id is None or pool.server_id == server_id:
                    pool_stats = await pool.get_stats()
                    stats.append(pool_stats)
        return stats

    def has_pool(self, server_id: str) -> bool:
        """Check if a pool exists for the given server.
        
        Args:
            server_id: ID of the server
            
        Returns:
            True if pool exists, False otherwise
        """
        for pool in self._pools.values():
            if pool.server_id == server_id:
                return True
        return False

    async def drain_pool(self, server_id: str, timeout: int = 30) -> None:
        """Drain a pool by preventing new acquisitions and waiting for active sessions.
        
        Args:
            server_id: ID of the server
            timeout: Maximum time to wait for active sessions to complete
        """
        pool = await self.get_pool_for_server(server_id)
        if pool:
            logger.info(f"Draining pool for server {server_id}")
            await pool.drain()
            logger.info(f"Pool for server {server_id} drained successfully")

    async def remove_pool(self, server_id: str) -> None:
        """Remove and shutdown a pool for a server.
        
        Args:
            server_id: ID of the server
        """
        async with self._lock:
            pool_to_remove = None
            pool_id_to_remove = None
            
            for pool_id, pool in self._pools.items():
                if pool.server_id == server_id:
                    pool_to_remove = pool
                    pool_id_to_remove = pool_id
                    break
            
            if pool_to_remove and pool_id_to_remove:
                logger.info(f"Removing pool {pool_id_to_remove} for server {server_id}")
                await pool_to_remove.shutdown()
                del self._pools[pool_id_to_remove]
                logger.info(f"Pool for server {server_id} removed successfully")

    async def optimize_pool_strategy(self, server_id: str) -> Optional[PoolStrategy]:
        """Analyze pool performance and recommend optimal strategy.
        
        Args:
            server_id: ID of the server
            
        Returns:
            Recommended PoolStrategy if optimization is possible, None otherwise
        """
        pool = await self.get_pool_for_server(server_id)
        if not pool:
            return None
        
        # Get recent metrics for this pool
        metrics = await self._get_pool_metrics(pool.pool_id, hours=24)
        if not metrics:
            logger.debug(f"No metrics available for pool {pool.pool_id}")
            return None
        
        # Calculate average response times by strategy
        strategy_performance = {}
        for metric in metrics:
            strategy = metric["strategy"]
            if strategy not in strategy_performance:
                strategy_performance[strategy] = []
            strategy_performance[strategy].append(metric["response_time"])
        
        # Calculate averages
        avg_response_times = {
            strategy: sum(times) / len(times)
            for strategy, times in strategy_performance.items()
        }
        
        # Get pool stats for context
        stats = await pool.get_stats()
        
        # Use recommendation function
        recommended = recommend_strategy(
            avg_response_time=avg_response_times.get(pool.strategy.value, 0.0),
            active_connections=stats["active_sessions"],
            total_connections=stats["total_sessions"],
            error_rate=stats["total_timeouts"] / max(stats["total_acquisitions"], 1)
        )
        
        if recommended != pool.strategy:
            logger.info(
                f"Recommending strategy change for pool {pool.pool_id}: "
                f"{pool.strategy.value} -> {recommended.value}"
            )
        
        return recommended

    async def _load_pools_from_db(self) -> None:
        """Load existing pools from the database."""
        try:
            with DBSession(engine) as db_session:
                stmt = select(SessionPoolModel).where(SessionPoolModel.is_active == True)
                result = db_session.execute(stmt)
                pool_models = result.scalars().all()
                
                for pool_model in pool_models:
                    try:
                        pool = SessionPool(
                            pool_id=pool_model.id,
                            server_id=pool_model.server_id,
                            strategy=PoolStrategy(pool_model.strategy),
                            min_size=pool_model.min_size,
                            max_size=pool_model.max_size,
                            timeout=pool_model.timeout,
                        )
                        await pool.initialize()
                        self._pools[pool_model.id] = pool
                        logger.info(f"Loaded pool {pool_model.id} from database")
                    except Exception as e:
                        logger.error(f"Error loading pool {pool_model.id}: {e}")
                
        except Exception as e:
            logger.error(f"Error loading pools from database: {e}")

    async def _save_pool_to_db(self, pool: SessionPool, name: str) -> None:
        """Save a pool to the database.
        
        Args:
            pool: SessionPool instance to save
            name: Name for the pool
        """
        try:
            with DBSession(engine) as db_session:
                pool_model = SessionPoolModel(
                    id=pool.pool_id,
                    server_id=pool.server_id,
                    name=name,
                    strategy=pool.strategy.value,
                    size=pool.max_size,
                    min_size=pool.min_size,
                    max_size=pool.max_size,
                    timeout=pool.timeout,
                    active_sessions=0,
                    available_sessions=0,
                    total_acquisitions=0,
                    total_releases=0,
                    total_timeouts=0,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    is_active=True,
                )
                db_session.add(pool_model)
                db_session.commit()
                logger.debug(f"Saved pool {pool.pool_id} to database")
        except Exception as e:
            logger.error(f"Error saving pool to database: {e}")

    async def _get_server_config(self, server_id: str) -> Optional[Dict]:
        """Get server configuration from database.
        
        Args:
            server_id: ID of the server
            
        Returns:
            Dictionary of server configuration if found, None otherwise
        """
        try:
            with DBSession(engine) as db_session:
                stmt = select(Server).where(Server.id == server_id)
                result = db_session.execute(stmt)
                server = result.scalar_one_or_none()
                
                if not server:
                    return None
                
                return {
                    "name": server.name,
                    "pool_enabled": server.pool_enabled,
                    "pool_strategy": server.pool_strategy,
                    "pool_size": server.pool_size,
                    "pool_min_size": server.pool_min_size,
                    "pool_max_size": server.pool_max_size,
                    "pool_timeout": server.pool_timeout,
                    "pool_recycle": server.pool_recycle,
                    "pool_pre_ping": server.pool_pre_ping,
                    "pool_auto_adjust": server.pool_auto_adjust,
                    "pool_response_threshold": server.pool_response_threshold,
                }
        except Exception as e:
            logger.error(f"Error getting server config: {e}")
            return None

    async def _get_pool_metrics(self, pool_id: str, hours: int = 24) -> List[Dict]:
        """Get recent metrics for a pool.
        
        Args:
            pool_id: ID of the pool
            hours: Number of hours of history to retrieve
            
        Returns:
            List of metric dictionaries
        """
        try:
            with DBSession(engine) as db_session:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
                stmt = (
                    select(PoolStrategyMetric)
                    .where(
                        PoolStrategyMetric.pool_id == pool_id,
                        PoolStrategyMetric.timestamp >= cutoff
                    )
                    .order_by(PoolStrategyMetric.timestamp.desc())
                )
                result = db_session.execute(stmt)
                metrics = result.scalars().all()
                
                return [
                    {
                        "strategy": m.strategy,
                        "timestamp": m.timestamp,
                        "response_time": m.response_time,
                        "success": m.success,
                        "session_reused": m.session_reused,
                        "wait_time": m.wait_time,
                        "error_message": m.error_message,
                    }
                    for m in metrics
                ]
        except Exception as e:
            logger.error(f"Error getting pool metrics: {e}")
            return []

    async def _monitoring_loop(self) -> None:
        """Background task to monitor pool health and update database."""
        logger.info("Starting pool monitoring loop")
        
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                async with self._lock:
                    for pool_id, pool in self._pools.items():
                        try:
                            stats = await pool.get_stats()
                            
                            # Update database with current stats
                            with DBSession(engine) as db_session:
                                stmt = select(SessionPoolModel).where(SessionPoolModel.id == pool_id)
                                result = db_session.execute(stmt)
                                pool_model = result.scalar_one_or_none()
                                
                                if pool_model:
                                    pool_model.active_sessions = stats["active_sessions"]
                                    pool_model.available_sessions = stats["available_sessions"]
                                    pool_model.total_acquisitions = stats["total_acquisitions"]
                                    pool_model.total_releases = stats["total_releases"]
                                    pool_model.total_timeouts = stats["total_timeouts"]
                                    pool_model.updated_at = datetime.now(timezone.utc)
                                    db_session.commit()
                            
                            # Log health warnings
                            if stats["unhealthy_sessions"] > 0:
                                logger.warning(
                                    f"Pool {pool_id} has {stats['unhealthy_sessions']} unhealthy sessions"
                                )
                            
                            if stats["total_timeouts"] > stats["total_acquisitions"] * 0.1:
                                logger.warning(
                                    f"Pool {pool_id} has high timeout rate: "
                                    f"{stats['total_timeouts']}/{stats['total_acquisitions']}"
                                )
                        
                        except Exception as e:
                            logger.error(f"Error monitoring pool {pool_id}: {e}")
            
            except asyncio.CancelledError:
                logger.info("Pool monitoring loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")

    async def _optimization_loop(self) -> None:
        """Background task to optimize pool strategies based on performance."""
        logger.info("Starting pool optimization loop")
        
        while True:
            try:
                await asyncio.sleep(3600)  # Check every hour
                
                async with self._lock:
                    for pool in self._pools.values():
                        try:
                            recommended = await self.optimize_pool_strategy(pool.server_id)
                            
                            if recommended and recommended != pool.strategy:
                                # Get server config to check if auto-adjust is enabled
                                server_config = await self._get_server_config(pool.server_id)
                                if server_config and server_config.get("pool_auto_adjust", False):
                                    logger.info(
                                        f"Auto-adjusting pool {pool.pool_id} strategy: "
                                        f"{pool.strategy.value} -> {recommended.value}"
                                    )
                                    # Note: Changing strategy would require recreating the pool
                                    # For now, just log the recommendation
                        
                        except Exception as e:
                            logger.error(f"Error optimizing pool {pool.pool_id}: {e}")
            
            except asyncio.CancelledError:
                logger.info("Pool optimization loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in optimization loop: {e}")


# Global pool manager instance
_pool_manager: Optional[SessionPoolManager] = None


async def get_pool_manager() -> SessionPoolManager:
    """Get the global pool manager instance.
    
    Returns:
        SessionPoolManager instance
    """
    global _pool_manager
    if _pool_manager is None:
        _pool_manager = SessionPoolManager()
        await _pool_manager.initialize()
    return _pool_manager


async def shutdown_pool_manager() -> None:
    """Shutdown the global pool manager instance."""
    global _pool_manager
    if _pool_manager is not None:
        await _pool_manager.shutdown()
        _pool_manager = None

# Made with Bob
