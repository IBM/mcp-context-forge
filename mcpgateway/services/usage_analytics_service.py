# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/usage_analytics_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Description:
    Usage analytics service for tracking tool usage events and supporting
    collaborative filtering recommendations. Provides event ingestion,
    retention management, privacy controls (opt-out/export/delete), and
    background cleanup.

    Key features:
    - Real-time event ingestion with async buffering
    - Privacy-aware recording (respects opt-out preferences)
    - User data export (GDPR/privacy compliance)
    - Background cleanup with configurable retention periods
    - Redis caching for opt-out status checks

Usage:
    ```python
    from mcpgateway.services.usage_analytics_service import usage_analytics_service
    
    # Record a tool execution event
    await usage_analytics_service.record_usage_event(
        user_email="user@example.com",
        tool_id="calculator",
        execution_duration_ms=150,
        success=True,
        session_id="session-123",
        user_role="developer",
        user_team_id="team-456"
    )
    
    # Check if user has opted out
    opted_out = await usage_analytics_service.check_opt_out("user@example.com")
    
    # Export user data (for privacy requests)
    data = await usage_analytics_service.export_user_data("user@example.com")
    
    # Delete user data (for GDPR right to erasure)
    await usage_analytics_service.delete_user_data("user@example.com")
    ```
"""

# Standard
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import ToolUsageEvent, UserPreference, fresh_db_session, utc_now
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.redis_client import get_redis_client

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class UsageAnalyticsService:
    """Service for tracking and managing tool usage analytics.

    Handles event ingestion, retention cleanup, privacy controls, and
    user data export/deletion for collaborative filtering support.
    """

    def __init__(self) -> None:
        """Initialize the usage analytics service."""
        self._initialized = False
        self._cleanup_task: Optional[asyncio.Task] = None
        self._redis_client = None
        self._opt_out_cache_prefix = "analytics:opt_out:"
        self._event_buffer: List[Dict[str, Any]] = []
        self._buffer_lock = asyncio.Lock()
        self._buffer_size = 100  # Flush after 100 events
        self._buffer_timeout = 30.0  # Or flush every 30 seconds

    async def initialize(self) -> None:
        """Initialize service and start background cleanup task."""
        if self._initialized:
            logger.warning("UsageAnalyticsService already initialized")
            return

        logger.info("Initializing UsageAnalyticsService")

        # Initialize Redis client for caching
        try:
            self._redis_client = get_redis_client()
            if self._redis_client:
                await self._redis_client.ping()
                logger.info("Redis connection established for analytics caching")
        except Exception as e:
            logger.warning(f"Redis unavailable for analytics caching: {e}")
            self._redis_client = None

        # Start background cleanup task if enabled
        if settings.analytics_cleanup_enabled:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info(f"Analytics cleanup task started (interval: {settings.analytics_cleanup_interval_hours}h, retention: {settings.analytics_retention_days}d)")

        self._initialized = True
        logger.info("UsageAnalyticsService initialized successfully")

    async def shutdown(self) -> None:
        """Shutdown service and cancel background tasks."""
        if not self._initialized:
            return

        logger.info("Shutting down UsageAnalyticsService")

        # Flush any pending events
        await self._flush_event_buffer()

        # Cancel cleanup task
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        self._initialized = False
        logger.info("UsageAnalyticsService shutdown complete")

    async def record_usage_event(
        self,
        user_email: str,
        tool_id: str,
        execution_duration_ms: Optional[int] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        session_id: Optional[str] = None,
        user_role: Optional[str] = None,
        user_team_id: Optional[str] = None,
        interaction_type: str = "invoke",
        context_hash: Optional[str] = None,
    ) -> None:
        """Record a tool usage event for analytics.

        Args:
            user_email: User who executed the tool
            tool_id: Tool identifier (name or ID)
            execution_duration_ms: Execution time in milliseconds
            success: Whether execution succeeded
            error_message: Error message if execution failed
            session_id: Session identifier for grouping events
            user_role: User's role at time of execution
            user_team_id: Team ID at time of execution
            interaction_type: Type of interaction (invoke, view, dismiss)
            context_hash: Hashed context for privacy-preserving analytics
        """
        if not settings.analytics_enabled:
            return

        # Check opt-out status (with caching)
        if await self.check_opt_out(user_email):
            logger.debug(f"User {user_email} has opted out of analytics, skipping event")
            return

        # Buffer event for batch insertion
        event = {
            "id": uuid.uuid4().hex,
            "user_email": user_email,
            "tool_id": tool_id,
            "timestamp": utc_now(),
            "execution_duration_ms": execution_duration_ms,
            "success": success,
            "error_message": error_message,
            "session_id": session_id,
            "user_role": user_role,
            "user_team_id": user_team_id,
            "interaction_type": interaction_type,
            "context_hash": context_hash,
        }

        # Snapshot under lock, then flush outside the lock to avoid deadlock.
        # asyncio.Lock is NOT re-entrant: calling _flush_event_buffer while the
        # lock is held would block forever.
        events_to_flush: Optional[List[Dict[str, Any]]] = None
        async with self._buffer_lock:
            self._event_buffer.append(event)
            if len(self._event_buffer) >= self._buffer_size:
                events_to_flush = self._event_buffer[:]
                self._event_buffer.clear()

        if events_to_flush is not None:
            await self._do_flush(events_to_flush)

    async def _flush_event_buffer(self) -> None:
        """Flush all buffered events to database (acquires lock, safe to call externally)."""
        async with self._buffer_lock:
            if not self._event_buffer:
                return
            events_to_insert = self._event_buffer[:]
            self._event_buffer.clear()

        await self._do_flush(events_to_insert)

    async def _do_flush(self, events_to_insert: List[Dict[str, Any]]) -> None:
        """Write a pre-snapshotted list of events to the database.

        Must be called WITHOUT holding _buffer_lock.

        Args:
            events_to_insert: Events to persist (already removed from the buffer)
        """
        if not events_to_insert:
            return

        try:
            with fresh_db_session() as session:
                # Bulk insert for performance
                usage_events = [ToolUsageEvent(**event) for event in events_to_insert]
                session.add_all(usage_events)
                session.commit()
                logger.debug(f"Flushed {len(events_to_insert)} usage events to database")
        except Exception as e:
            logger.error(f"Failed to flush usage events: {e}", exc_info=True)
            # Re-buffer events for retry (safe: lock is not held here)
            async with self._buffer_lock:
                self._event_buffer.extend(events_to_insert)

    async def check_opt_out(self, user_email: str) -> bool:
        """Check if user has opted out of analytics (with Redis caching).

        Args:
            user_email: User email to check

        Returns:
            True if user has opted out, False otherwise
        """
        # Try Redis cache first
        if self._redis_client:
            try:
                cache_key = f"{self._opt_out_cache_prefix}{user_email}"
                cached = await self._redis_client.get(cache_key)
                if cached is not None:
                    return cached == "1"
            except Exception as e:
                logger.warning(f"Redis cache read failed for opt-out check: {e}")

        # Fallback to database
        try:
            with fresh_db_session() as session:
                stmt = select(UserPreference.analytics_opted_in).where(UserPreference.user_email == user_email)
                result = session.execute(stmt)
                preference = result.scalar_one_or_none()

                # Default to opted-in if no preference record exists
                opted_in = preference if preference is not None else True
                opted_out = not opted_in

                # Cache result
                if self._redis_client:
                    try:
                        cache_key = f"{self._opt_out_cache_prefix}{user_email}"
                        await self._redis_client.setex(cache_key, settings.auth_cache_user_ttl, "1" if opted_out else "0")
                    except Exception as e:
                        logger.warning(f"Failed to cache opt-out status: {e}")

                return opted_out
        except Exception as e:
            logger.error(f"Failed to check opt-out status for {user_email}: {e}", exc_info=True)
            return False  # Fail open: continue recording events if DB check fails

    async def set_user_preference(
        self,
        user_email: str,
        analytics_opted_in: bool,
        data_retention_days: Optional[int] = None,
    ) -> None:
        """Set or update user analytics preferences.

        Args:
            user_email: User email
            analytics_opted_in: Whether user is opted into analytics
            data_retention_days: Custom retention period (None = use default)
        """
        try:
            with fresh_db_session() as session:
                stmt = select(UserPreference).where(UserPreference.user_email == user_email)
                result = session.execute(stmt)
                preference = result.scalar_one_or_none()

                if preference:
                    # Update existing
                    preference.analytics_opted_in = analytics_opted_in
                    if data_retention_days is not None:
                        preference.data_retention_days = data_retention_days
                    preference.last_updated = utc_now()
                else:
                    # Create new
                    preference = UserPreference(
                        user_email=user_email,
                        analytics_opted_in=analytics_opted_in,
                        data_retention_days=data_retention_days or settings.analytics_retention_days,
                    )
                    session.add(preference)

                session.commit()
                logger.info(f"Updated analytics preferences for {user_email}: opted_in={analytics_opted_in}")

                # Invalidate cache
                if self._redis_client:
                    try:
                        cache_key = f"{self._opt_out_cache_prefix}{user_email}"
                        await self._redis_client.delete(cache_key)
                    except Exception as e:
                        logger.warning(f"Failed to invalidate opt-out cache: {e}")

        except Exception as e:
            logger.error(f"Failed to set user preference for {user_email}: {e}", exc_info=True)
            raise

    async def export_user_data(self, user_email: str) -> Dict[str, Any]:
        """Export all analytics data for a user (GDPR/privacy compliance).

        Args:
            user_email: User email

        Returns:
            Dict containing user preferences and usage events
        """
        try:
            with fresh_db_session() as session:
                # Get preferences
                pref_stmt = select(UserPreference).where(UserPreference.user_email == user_email)
                pref_result = session.execute(pref_stmt)
                preference = pref_result.scalar_one_or_none()

                # Get usage events
                event_stmt = select(ToolUsageEvent).where(ToolUsageEvent.user_email == user_email).order_by(ToolUsageEvent.timestamp.desc())
                event_result = session.execute(event_stmt)
                events = event_result.scalars().all()

                return {
                    "user_email": user_email,
                    "preferences": {
                        "analytics_opted_in": preference.analytics_opted_in if preference else True,
                        "data_retention_days": preference.data_retention_days if preference else settings.analytics_retention_days,
                        "last_updated": preference.last_updated.isoformat() if preference else None,
                    },
                    "usage_events": [
                        {
                            "id": event.id,
                            "tool_id": event.tool_id,
                            "timestamp": event.timestamp.isoformat(),
                            "execution_duration_ms": event.execution_duration_ms,
                            "success": event.success,
                            "error_message": event.error_message,
                            "session_id": event.session_id,
                            "user_role": event.user_role,
                            "user_team_id": event.user_team_id,
                            "interaction_type": event.interaction_type,
                            "context_hash": event.context_hash,
                        }
                        for event in events
                    ],
                    "total_events": len(events),
                    "exported_at": utc_now().isoformat(),
                }
        except Exception as e:
            logger.error(f"Failed to export user data for {user_email}: {e}", exc_info=True)
            raise

    async def delete_user_data(self, user_email: str) -> int:
        """Delete all analytics data for a user (GDPR right to erasure).

        Args:
            user_email: User email

        Returns:
            Number of events deleted
        """
        try:
            with fresh_db_session() as session:
                # Delete usage events
                event_stmt = delete(ToolUsageEvent).where(ToolUsageEvent.user_email == user_email)
                event_result = session.execute(event_stmt)
                deleted_count = event_result.rowcount

                # Delete preferences (cascade will handle this if FK is set up)
                pref_stmt = delete(UserPreference).where(UserPreference.user_email == user_email)
                session.execute(pref_stmt)

                session.commit()
                logger.info(f"Deleted {deleted_count} usage events for {user_email}")

                # Invalidate cache
                if self._redis_client:
                    try:
                        cache_key = f"{self._opt_out_cache_prefix}{user_email}"
                        await self._redis_client.delete(cache_key)
                    except Exception as e:
                        logger.warning(f"Failed to invalidate cache after deletion: {e}")

                return deleted_count
        except Exception as e:
            logger.error(f"Failed to delete user data for {user_email}: {e}", exc_info=True)
            raise

    async def _cleanup_loop(self) -> None:
        """Background loop for cleaning up old usage events."""
        while True:
            try:
                await asyncio.sleep(settings.analytics_cleanup_interval_hours * 3600)
                await self._cleanup_old_events()
            except asyncio.CancelledError:
                logger.info("Analytics cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in analytics cleanup loop: {e}", exc_info=True)

    async def _cleanup_old_events(self) -> None:
        """Delete usage events older than retention period."""
        try:
            cutoff_date = utc_now() - timedelta(days=settings.analytics_retention_days)

            with fresh_db_session() as session:
                # Delete in batches to avoid long locks
                batch_size = settings.analytics_cleanup_batch_size
                total_deleted = 0

                while True:
                    stmt = delete(ToolUsageEvent).where(ToolUsageEvent.timestamp < cutoff_date).execution_options(synchronize_session=False)
                    # Limit deletion batch (DB-specific syntax, simplified for SQLAlchemy)
                    result = session.execute(stmt)
                    deleted = result.rowcount
                    session.commit()

                    total_deleted += deleted
                    logger.debug(f"Deleted {deleted} old usage events (batch)")

                    if deleted < batch_size:
                        break

                if total_deleted > 0:
                    logger.info(f"Analytics cleanup completed: deleted {total_deleted} events older than {settings.analytics_retention_days} days")
        except Exception as e:
            logger.error(f"Failed to cleanup old usage events: {e}", exc_info=True)


# Module-level singleton
usage_analytics_service = UsageAnalyticsService()
