# -*- coding: utf-8 -*-
"""Metrics Cleanup Service for automatic deletion of old metrics.

This service provides automatic and manual cleanup of old metrics data to prevent
unbounded table growth and maintain query performance.

Features:
- Batched deletion to prevent long locks
- Configurable retention period
- Background task for periodic cleanup
- Manual cleanup trigger via admin API
- Per-table cleanup with statistics

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Dict, Optional

# Third-Party
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import (
    A2AAgentMetric,
    A2AAgentMetricsHourly,
    fresh_db_session,
    PromptMetric,
    PromptMetricsHourly,
    ResourceMetric,
    ResourceMetricsHourly,
    ServerMetric,
    ServerMetricsHourly,
    ToolMetric,
    ToolMetricsHourly,
)
from mcpgateway.services import Priority, task_scheduler
from mcpgateway.services.metrics_rollup_service import get_metrics_rollup_service_if_initialized

logger = logging.getLogger(__name__)


def delete_metrics_in_batches(db: Session, model_class, filter_column, entity_id, batch_size: Optional[int] = None) -> int:
    """Delete metrics rows for a specific entity in batches within the current transaction.

    Args:
        db: Database session.
        model_class: SQLAlchemy model to delete from.
        filter_column: Column used to filter by entity_id.
        entity_id: Entity identifier to delete metrics for.
        batch_size: Optional batch size override.

    Returns:
        int: Total rows deleted.
    """
    effective_batch_size = batch_size or getattr(settings, "metrics_cleanup_batch_size", 10000)
    total_deleted = 0

    while True:
        subq = select(model_class.id).where(filter_column == entity_id).limit(effective_batch_size)
        delete_stmt = delete(model_class).where(model_class.id.in_(subq))
        result = db.execute(delete_stmt)

        rowcount = result.rowcount
        batch_deleted = rowcount if isinstance(rowcount, int) else 0
        total_deleted += batch_deleted

        if batch_deleted <= 0 or batch_deleted < effective_batch_size:
            break

    return total_deleted


@contextmanager
def pause_rollup_during_purge(reason: str = "purge_metrics"):
    """Pause rollup task while purging metrics to reduce race conditions.

    Args:
        reason: Reason for pausing the rollup task.

    Yields:
        None
    """
    rollup_service = get_metrics_rollup_service_if_initialized()
    if rollup_service:
        rollup_service.pause(reason)
    try:
        yield
    finally:
        if rollup_service:
            rollup_service.resume()


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""

    table_name: str
    deleted_count: int
    remaining_count: int
    cutoff_date: datetime
    duration_seconds: float
    error: Optional[str] = None


@dataclass
class CleanupSummary:
    """Summary of all cleanup operations."""

    total_deleted: int
    tables: Dict[str, CleanupResult]
    duration_seconds: float
    started_at: datetime
    completed_at: datetime


class MetricsCleanupService:
    """Service for cleaning up old metrics data.

    This service provides:
    - Batched deletion of old metrics (prevents long locks)
    - Configurable retention period per table type
    - Background task for periodic cleanup
    - Manual cleanup trigger
    - Cleanup statistics and reporting

    Configuration (via environment variables):
    - METRICS_CLEANUP_ENABLED: Enable automatic cleanup (default: True)
    - METRICS_RETENTION_DAYS: Days to retain raw metrics (default: 7)
    - METRICS_CLEANUP_INTERVAL_HOURS: Hours between cleanup runs (default: 1)
    - METRICS_CLEANUP_BATCH_SIZE: Batch size for deletion (default: 10000)
    - METRICS_DELETE_RAW_AFTER_ROLLUP: Delete raw after rollup exists (default: True)
    - METRICS_DELETE_RAW_AFTER_ROLLUP_HOURS: Hours after which to delete if rollup exists (default: 1)
    """

    # Map of raw metric tables to their hourly rollup counterparts
    METRIC_TABLES = [
        ("tool_metrics", ToolMetric, ToolMetricsHourly, "tool_id"),
        ("resource_metrics", ResourceMetric, ResourceMetricsHourly, "resource_id"),
        ("prompt_metrics", PromptMetric, PromptMetricsHourly, "prompt_id"),
        ("server_metrics", ServerMetric, ServerMetricsHourly, "server_id"),
        ("a2a_agent_metrics", A2AAgentMetric, A2AAgentMetricsHourly, "a2a_agent_id"),
    ]

    def __init__(
        self,
        retention_days: Optional[int] = None,
        batch_size: Optional[int] = None,
        cleanup_interval_hours: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        """Initialize the metrics cleanup service.

        Args:
            retention_days: Days to retain raw metrics (default: from settings or 7)
            batch_size: Batch size for deletion (default: from settings or 10000)
            cleanup_interval_hours: Hours between cleanup runs (default: from settings or 1)
            enabled: Whether cleanup is enabled (default: from settings or True)
        """
        self.retention_days = retention_days or getattr(settings, "metrics_retention_days", 7)
        self.batch_size = batch_size or getattr(settings, "metrics_cleanup_batch_size", 10000)
        self.cleanup_interval_hours = cleanup_interval_hours or getattr(settings, "metrics_cleanup_interval_hours", 1)
        self.enabled = enabled if enabled is not None else getattr(settings, "metrics_cleanup_enabled", True)

        # Raw deletion after rollup is handled by MetricsRollupService; stored for stats/reporting.
        self.delete_raw_after_rollup = getattr(settings, "metrics_delete_raw_after_rollup", True)
        self.delete_raw_after_rollup_hours = getattr(settings, "metrics_delete_raw_after_rollup_hours", 1)

        # Rollup retention
        self.rollup_retention_days = getattr(settings, "metrics_rollup_retention_days", 365)

        # Background task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Stats
        self._total_cleaned = 0
        self._cleanup_runs = 0

        logger.info(
            f"MetricsCleanupService initialized: enabled={self.enabled}, " f"retention_days={self.retention_days}, batch_size={self.batch_size}, " f"interval_hours={self.cleanup_interval_hours}"
        )

    async def start(self) -> None:
        """Start the background cleanup task."""
        if not self.enabled:
            logger.info("MetricsCleanupService disabled, skipping start")
            return

        if self._cleanup_task is None or self._cleanup_task.done():
            self._shutdown_event.clear()
            self._cleanup_task = task_scheduler.schedule(self._cleanup_loop, Priority.NORMAL)
            logger.info("MetricsCleanupService background task started")

    async def shutdown(self) -> None:
        """Shutdown the cleanup service."""
        logger.info("MetricsCleanupService shutting down...")

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel the cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info(f"MetricsCleanupService shutdown complete: " f"total_cleaned={self._total_cleaned}, cleanup_runs={self._cleanup_runs}")

    async def _cleanup_loop(self) -> None:
        """Background task that periodically cleans up old metrics.

        Raises:
            asyncio.CancelledError: When the task is cancelled during shutdown.
        """
        logger.info(f"Metrics cleanup loop started (interval={self.cleanup_interval_hours}h)")

        # Calculate interval in seconds
        interval_seconds = self.cleanup_interval_hours * 3600

        while not self._shutdown_event.is_set():
            try:
                # Wait for interval or shutdown
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=interval_seconds,
                    )
                    # Shutdown signaled
                    break
                except asyncio.TimeoutError:
                    # Normal timeout, proceed to cleanup
                    pass

                # Run cleanup
                summary = await self.cleanup_all()
                self._cleanup_runs += 1
                self._total_cleaned += summary.total_deleted

                if summary.total_deleted > 0:
                    logger.info(f"Metrics cleanup #{self._cleanup_runs}: deleted {summary.total_deleted} records " f"in {summary.duration_seconds:.2f}s")

            except asyncio.CancelledError:
                logger.debug("Cleanup loop cancelled")
                raise
            except Exception as e:
                logger.error(f"Error in metrics cleanup loop: {e}", exc_info=True)
                # Continue the loop despite errors
                await asyncio.sleep(60)

    async def cleanup_all(
        self,
        retention_days: Optional[int] = None,
        include_rollup: bool = True,
    ) -> CleanupSummary:
        """Clean up all old metrics across all tables.

        Args:
            retention_days: Override retention period (optional). Use 0 to delete all.
            include_rollup: Also clean up old rollup tables

        Returns:
            CleanupSummary: Summary of cleanup operations
        """
        started_at = datetime.now(timezone.utc)
        start_time = time.monotonic()

        # Use provided retention_days if set (including 0), otherwise use default
        retention = retention_days if retention_days is not None else self.retention_days
        # For retention=0 (delete all), use current time without hour-alignment to delete everything
        # Otherwise, hour-align cutoff to match query service's get_retention_cutoff() and prevent gaps
        if retention == 0:
            cutoff = datetime.now(timezone.utc) + timedelta(hours=1)  # Future time ensures all data is deleted
        else:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=retention)).replace(minute=0, second=0, microsecond=0)

        results: Dict[str, CleanupResult] = {}
        total_deleted = 0

        # Clean up raw metrics tables
        for table_name, model_class, _, _ in self.METRIC_TABLES:
            result = await asyncio.to_thread(
                self._cleanup_table,
                model_class,
                table_name,
                cutoff,
            )
            results[table_name] = result
            total_deleted += result.deleted_count

        # Clean up rollup tables if enabled
        if include_rollup:
            # If retention_days is explicitly 0 (delete all), also delete all rollups
            # Otherwise use the rollup retention period
            if retention_days is not None and retention_days == 0:
                rollup_cutoff = datetime.now(timezone.utc)  # Delete all rollups too
            else:
                rollup_cutoff = datetime.now(timezone.utc) - timedelta(days=self.rollup_retention_days)
            for table_name, _, hourly_model_class, _ in self.METRIC_TABLES:
                hourly_table_name = f"{table_name}_hourly"
                result = await asyncio.to_thread(
                    self._cleanup_table,
                    hourly_model_class,
                    hourly_table_name,
                    rollup_cutoff,
                    timestamp_column="hour_start",
                )
                results[hourly_table_name] = result
                total_deleted += result.deleted_count

        duration = time.monotonic() - start_time
        completed_at = datetime.now(timezone.utc)

        return CleanupSummary(
            total_deleted=total_deleted,
            tables=results,
            duration_seconds=duration,
            started_at=started_at,
            completed_at=completed_at,
        )

    def _cleanup_table(
        self,
        model_class,
        table_name: str,
        cutoff: datetime,
        timestamp_column: str = "timestamp",
    ) -> CleanupResult:
        """Clean up old records from a single table using batched deletion.

        Args:
            model_class: SQLAlchemy model class
            table_name: Table name for logging
            cutoff: Delete records older than this timestamp
            timestamp_column: Name of the timestamp column

        Returns:
            CleanupResult: Result of the cleanup operation
        """
        start_time = time.monotonic()
        total_deleted = 0
        error_msg = None

        try:
            with fresh_db_session() as db:
                timestamp_col = getattr(model_class, timestamp_column)

                # Delete in batches to prevent long locks
                while True:
                    # Get batch of IDs to delete
                    stmt = select(model_class.id).where(timestamp_col < cutoff).limit(self.batch_size)
                    ids_to_delete = [row[0] for row in db.execute(stmt).fetchall()]

                    if not ids_to_delete:
                        break

                    # Delete batch
                    delete_stmt = delete(model_class).where(model_class.id.in_(ids_to_delete))
                    result = db.execute(delete_stmt)
                    db.commit()

                    batch_deleted = result.rowcount
                    total_deleted += batch_deleted

                    logger.debug(f"Cleaned {batch_deleted} records from {table_name}")

                    # If we deleted less than batch size, we're done
                    if batch_deleted < self.batch_size:
                        break

                # Get remaining count
                remaining_count = db.execute(select(func.count()).select_from(model_class)).scalar() or 0  # pylint: disable=not-callable

        except Exception as e:
            logger.error(f"Error cleaning up {table_name}: {e}")
            error_msg = str(e)
            remaining_count = -1

        duration = time.monotonic() - start_time

        if total_deleted > 0:
            logger.info(f"Cleaned {total_deleted} records from {table_name} (cutoff: {cutoff})")

        return CleanupResult(
            table_name=table_name,
            deleted_count=total_deleted,
            remaining_count=remaining_count,
            cutoff_date=cutoff,
            duration_seconds=duration,
            error=error_msg,
        )

    async def cleanup_table(
        self,
        table_type: str,
        retention_days: Optional[int] = None,
    ) -> CleanupResult:
        """Clean up old records from a specific table.

        Args:
            table_type: One of 'tool', 'resource', 'prompt', 'server', 'a2a_agent'
            retention_days: Override retention period (optional). Use 0 to delete all.

        Returns:
            CleanupResult: Result of the cleanup operation

        Raises:
            ValueError: If table_type is not recognized
        """
        table_map = {
            "tool": ("tool_metrics", ToolMetric),
            "resource": ("resource_metrics", ResourceMetric),
            "prompt": ("prompt_metrics", PromptMetric),
            "server": ("server_metrics", ServerMetric),
            "a2a_agent": ("a2a_agent_metrics", A2AAgentMetric),
        }

        if table_type not in table_map:
            raise ValueError(f"Unknown table type: {table_type}. Must be one of: {list(table_map.keys())}")

        table_name, model_class = table_map[table_type]
        # Use provided retention_days if set (including 0), otherwise use default
        retention = retention_days if retention_days is not None else self.retention_days
        # For retention=0 (delete all), use current time without hour-alignment to delete everything
        # Otherwise, hour-align cutoff to match query service's get_retention_cutoff() and prevent gaps
        if retention == 0:
            cutoff = datetime.now(timezone.utc) + timedelta(hours=1)  # Future time ensures all data is deleted
        else:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=retention)).replace(minute=0, second=0, microsecond=0)

        return await asyncio.to_thread(
            self._cleanup_table,
            model_class,
            table_name,
            cutoff,
        )

    def get_stats(self) -> dict:
        """Get cleanup service statistics.

        Returns:
            dict: Cleanup statistics
        """
        return {
            "enabled": self.enabled,
            "retention_days": self.retention_days,
            "rollup_retention_days": self.rollup_retention_days,
            "batch_size": self.batch_size,
            "cleanup_interval_hours": self.cleanup_interval_hours,
            "total_cleaned": self._total_cleaned,
            "cleanup_runs": self._cleanup_runs,
            "delete_raw_after_rollup": self.delete_raw_after_rollup,
            "delete_raw_after_rollup_hours": self.delete_raw_after_rollup_hours,
        }

    async def get_table_sizes(self) -> Dict[str, int]:
        """Get the current size of all metrics tables.

        Returns:
            Dict[str, int]: Table name to row count mapping
        """
        sizes = {}

        def _get_sizes() -> Dict[str, int]:
            with fresh_db_session() as db:
                for table_name, model_class, hourly_class, _ in self.METRIC_TABLES:
                    # pylint: disable=not-callable
                    sizes[table_name] = db.execute(select(func.count()).select_from(model_class)).scalar() or 0
                    hourly_name = f"{table_name}_hourly"
                    sizes[hourly_name] = db.execute(select(func.count()).select_from(hourly_class)).scalar() or 0
            return sizes

        return await asyncio.to_thread(_get_sizes)


# Singleton instance
_metrics_cleanup_service: Optional[MetricsCleanupService] = None


def get_metrics_cleanup_service() -> MetricsCleanupService:
    """Get or create the singleton MetricsCleanupService instance.

    Returns:
        MetricsCleanupService: The singleton cleanup service instance
    """
    global _metrics_cleanup_service  # pylint: disable=global-statement
    if _metrics_cleanup_service is None:
        _metrics_cleanup_service = MetricsCleanupService()
    return _metrics_cleanup_service
