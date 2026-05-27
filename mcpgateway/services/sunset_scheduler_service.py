# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/sunset_scheduler_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Sunset Scheduler Service - Automated tool lifecycle management.

This service automatically transitions deprecated tools to sunset state when their
sunset_date is reached. It runs periodically in the background and:
- Queries tools WHERE deprecated=true AND sunset_date <= now() AND enabled=true
- Batch updates to set enabled=False for sunset tools
- Invalidates cache for sunset tools
- Logs audit trail for sunset transitions
- Tracks metrics for monitoring
"""

# Standard
import asyncio
from datetime import datetime, timezone
import logging
from typing import Optional

# Third-Party
from sqlalchemy import and_, select, update

# First-Party
from mcpgateway.cache.registry_cache import get_registry_cache
from mcpgateway.config import settings
from mcpgateway.db import fresh_db_session
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.observability_service import ObservabilityService
from mcpgateway.services.structured_logger import get_structured_logger

logger = logging.getLogger(__name__)
structured_logger = get_structured_logger()


class SunsetSchedulerService:
    """Service for automatically transitioning deprecated tools to sunset state.

    This service is designed to be idempotent and safe for concurrent execution:
    - Uses database-level atomic operations (UPDATE with WHERE clause)
    - Only processes tools that are still enabled (prevents double-processing)
    - Gracefully handles race conditions between multiple instances
    """

    def __init__(self):
        """Initialize the sunset scheduler service."""
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._interval_minutes = getattr(settings, "SUNSET_SCHEDULER_INTERVAL_MINUTES", 60)
        self._processing = False  # Flag to prevent concurrent runs within same instance
        logger.info(f"SunsetSchedulerService initialized with interval: {self._interval_minutes} minutes")

    async def start(self) -> None:
        """Start the sunset scheduler background task."""
        if self._running:
            logger.warning("SunsetSchedulerService already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_scheduler())
        logger.info("SunsetSchedulerService started")

    async def stop(self) -> None:
        """Stop the sunset scheduler background task."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SunsetSchedulerService stopped")

    async def _run_scheduler(self) -> None:
        """Run the scheduler loop with concurrent execution protection."""
        while self._running:
            try:
                # Skip if already processing (prevents overlapping runs)
                if self._processing:
                    logger.warning("Sunset scheduler already processing, skipping this run")
                    await asyncio.sleep(self._interval_minutes * 60)
                    continue

                self._processing = True
                try:
                    await self._process_sunset_tools()
                finally:
                    self._processing = False

            except Exception as e:
                logger.exception(f"Error in sunset scheduler: {e}")
                structured_logger.log(
                    level="ERROR",
                    message="sunset_scheduler_error",
                    event_type="sunset_scheduler_error",
                    component="sunset_scheduler",
                    custom_fields={
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
                self._processing = False

            # Sleep for the configured interval
            await asyncio.sleep(self._interval_minutes * 60)

    async def _process_sunset_tools(self) -> None:
        """Process tools that have reached their sunset date.

        This method is idempotent and safe for concurrent execution:
        - Uses atomic UPDATE with WHERE clause (only updates enabled=true tools)
        - Multiple instances can run simultaneously without conflicts
        - If a tool is already sunset by another instance, it's skipped

        Steps:
        1. Queries deprecated tools with sunset_date <= now() and enabled=true
        2. Atomic batch update to set enabled=False (only if still enabled)
        3. Invalidates cache for successfully sunset tools
        4. Logs audit trail for each transition
        5. Tracks metrics
        """
        with fresh_db_session() as db:
            now = datetime.now(timezone.utc)

            # Query tools that need to be sunset
            # Use index on sunset_date for efficient query
            stmt = select(DbTool).where(
                and_(
                    DbTool.deprecated is True,  # noqa: E712
                    DbTool.sunset_date <= now,
                    DbTool.enabled is True,  # noqa: E712
                )
            )

            tools_to_sunset = db.execute(stmt).scalars().all()

            if not tools_to_sunset:
                logger.debug("No tools to sunset at this time")
                return

            tool_count = len(tools_to_sunset)
            tool_ids = [tool.id for tool in tools_to_sunset]
            tool_names = [tool.name for tool in tools_to_sunset]

            logger.info(f"Processing {tool_count} tools for sunset: {tool_names}")

            # Atomic batch update to set enabled=False
            # IMPORTANT: The WHERE clause includes enabled=True to ensure idempotency
            # If another instance already sunset these tools, this update affects 0 rows
            update_stmt = (
                update(DbTool)
                .where(
                    and_(
                        DbTool.id.in_(tool_ids),
                        DbTool.enabled is True,  # noqa: E712 - Critical for idempotency
                    )
                )
                .values(enabled=False)
            )
            result = db.execute(update_stmt)
            db.commit()

            # Check how many tools were actually updated (for concurrent execution safety)
            actual_count = result.rowcount
            if actual_count < tool_count:
                logger.warning(f"Only {actual_count} of {tool_count} tools were sunset. " f"This may indicate concurrent execution or tools already sunset.")
                # Re-query to get only the tools that were actually updated
                tools_to_sunset = [t for t in tools_to_sunset if t.enabled is False]
                tool_count = actual_count

            # Invalidate tools cache (invalidates all tools at once)
            registry_cache = get_registry_cache()
            try:
                await registry_cache.invalidate_tools()
                logger.debug(f"Invalidated tools cache for {tool_count} sunset tools")
            except Exception as e:
                logger.error(f"Failed to invalidate tools cache: {e}")

            # Log audit trail for each transition
            audit_service = get_audit_trail_service()
            for tool in tools_to_sunset:
                try:
                    audit_service.log_action(
                        user_id="sunset_scheduler",
                        action="tool_sunset",
                        resource_type="tool",
                        resource_id=str(tool.id),
                        resource_name=tool.name,
                        user_email=None,
                        team_id=tool.team_id if hasattr(tool, "team_id") else None,
                        details={
                            "sunset_date": tool.sunset_date.isoformat() if tool.sunset_date else None,
                            "automated": True,
                            "timestamp": now.isoformat(),
                        },
                        db=db,
                    )
                except Exception as e:
                    logger.error(f"Failed to log audit trail for tool {tool.name}: {e}")

            # Track metrics using observability service
            try:
                obs_service = ObservabilityService()

                # Record total count of tools sunset in this batch
                obs_service.record_metric(
                    name="tool.lifecycle.sunset.count",
                    value=tool_count,
                    unit="count",
                    attributes={
                        "batch_timestamp": now.isoformat(),
                        "scheduler_run": "automated",
                    },
                )

                # Record individual tool sunset events for today's tracking
                for tool in tools_to_sunset:
                    obs_service.record_metric(
                        name="tool.lifecycle.sunset.event",
                        value=1,
                        unit="count",
                        attributes={
                            "tool_id": str(tool.id),
                            "tool_name": tool.name,
                            "sunset_date": tool.sunset_date.isoformat() if tool.sunset_date else None,
                            "timestamp": now.isoformat(),
                        },
                    )

                logger.debug(f"Recorded metrics for {tool_count} sunset tools")
            except Exception as e:
                logger.error(f"Failed to record sunset metrics: {e}")

            # Log structured info for monitoring
            structured_logger.log(
                level="INFO",
                message="Tools sunset batch completed",
                event_type="tools_sunset_batch",
                component="sunset_scheduler",
                custom_fields={
                    "tool_count": tool_count,
                    "tool_names": tool_names,
                    "timestamp": now.isoformat(),
                },
            )

            logger.info(f"Successfully sunset {tool_count} tools")


# Global singleton instance
_sunset_scheduler_service: Optional[SunsetSchedulerService] = None


def get_sunset_scheduler_service() -> SunsetSchedulerService:
    """Get the global sunset scheduler service instance.

    Returns:
        SunsetSchedulerService: The singleton service instance
    """
    global _sunset_scheduler_service
    if _sunset_scheduler_service is None:
        _sunset_scheduler_service = SunsetSchedulerService()
    return _sunset_scheduler_service
