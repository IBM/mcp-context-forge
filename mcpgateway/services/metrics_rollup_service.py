# -*- coding: utf-8 -*-
"""Metrics Rollup Service for hourly aggregation of raw metrics.

This service provides automatic rollup of raw metrics into hourly summaries,
enabling efficient historical queries without scanning millions of raw records.

Features:
- Hourly aggregation with percentile calculation
- Upsert logic to handle re-runs safely
- Background task for periodic rollup
- Optional deletion of raw metrics after rollup
- PostgreSQL and SQLite support

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Type

# Third-Party
from sqlalchemy import and_, case, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import (
    A2AAgent,
    A2AAgentMetric,
    A2AAgentMetricsHourly,
    fresh_db_session,
    Prompt,
    PromptMetric,
    PromptMetricsHourly,
    Resource,
    ResourceMetric,
    ResourceMetricsHourly,
    Server,
    ServerMetric,
    ServerMetricsHourly,
    Tool,
    ToolMetric,
    ToolMetricsHourly,
)

logger = logging.getLogger(__name__)


@dataclass
class RollupResult:
    """Result of a rollup operation for a single table."""

    table_name: str
    hours_processed: int
    records_aggregated: int
    rollups_created: int
    rollups_updated: int
    raw_deleted: int
    duration_seconds: float
    error: Optional[str] = None


@dataclass
class RollupSummary:
    """Summary of all rollup operations."""

    total_hours_processed: int
    total_records_aggregated: int
    total_rollups_created: int
    total_rollups_updated: int
    tables: Dict[str, RollupResult]
    duration_seconds: float
    started_at: datetime
    completed_at: datetime


@dataclass
class HourlyAggregation:
    """Aggregated metrics for a single hour."""

    entity_id: str
    entity_name: str
    hour_start: datetime
    total_count: int
    success_count: int
    failure_count: int
    min_response_time: Optional[float]
    max_response_time: Optional[float]
    avg_response_time: Optional[float]
    p50_response_time: Optional[float]
    p95_response_time: Optional[float]
    p99_response_time: Optional[float]
    interaction_type: Optional[str] = None  # For A2A agents


class MetricsRollupService:
    """Service for rolling up raw metrics into hourly summaries.

    This service provides:
    - Hourly aggregation of raw metrics into summary tables
    - Percentile calculation (p50, p95, p99)
    - Upsert logic to handle re-runs safely
    - Optional deletion of raw metrics after rollup
    - Background task for periodic rollup

    Configuration (via environment variables):
    - METRICS_ROLLUP_ENABLED: Enable automatic rollup (default: True)
    - METRICS_ROLLUP_INTERVAL_HOURS: Hours between rollup runs (default: 1)
    - METRICS_DELETE_RAW_AFTER_ROLLUP: Delete raw after rollup (default: True)
    - METRICS_DELETE_RAW_AFTER_ROLLUP_HOURS: Hours after which to delete if rollup exists (default: 1)
    """

    # Table configuration: (name, raw_model, hourly_model, entity_model, entity_id_col, entity_name_col)
    METRIC_TABLES = [
        ("tool_metrics", ToolMetric, ToolMetricsHourly, Tool, "tool_id", "name"),
        ("resource_metrics", ResourceMetric, ResourceMetricsHourly, Resource, "resource_id", "name"),
        ("prompt_metrics", PromptMetric, PromptMetricsHourly, Prompt, "prompt_id", "name"),
        ("server_metrics", ServerMetric, ServerMetricsHourly, Server, "server_id", "name"),
        ("a2a_agent_metrics", A2AAgentMetric, A2AAgentMetricsHourly, A2AAgent, "a2a_agent_id", "name"),
    ]

    def __init__(
        self,
        rollup_interval_hours: Optional[int] = None,
        enabled: Optional[bool] = None,
        delete_raw_after_rollup: Optional[bool] = None,
        delete_raw_after_rollup_hours: Optional[int] = None,
    ):
        """Initialize the metrics rollup service.

        Args:
            rollup_interval_hours: Hours between rollup runs (default: from settings or 1)
            enabled: Whether rollup is enabled (default: from settings or True)
            delete_raw_after_rollup: Delete raw metrics after rollup (default: from settings or True)
            delete_raw_after_rollup_hours: Hours after which to delete raw if rollup exists (default: from settings or 1)
        """
        self.rollup_interval_hours = rollup_interval_hours or getattr(settings, "metrics_rollup_interval_hours", 1)
        self.enabled = enabled if enabled is not None else getattr(settings, "metrics_rollup_enabled", True)
        self.delete_raw_after_rollup = delete_raw_after_rollup if delete_raw_after_rollup is not None else getattr(settings, "metrics_delete_raw_after_rollup", True)
        self.delete_raw_after_rollup_hours = delete_raw_after_rollup_hours or getattr(settings, "metrics_delete_raw_after_rollup_hours", 1)

        # Check if using PostgreSQL
        self._is_postgresql = settings.database_url.startswith("postgresql")

        # Background task
        self._rollup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_lock = threading.Lock()
        self._pause_count = 0
        self._pause_reason: Optional[str] = None

        # Stats
        self._total_rollups = 0
        self._rollup_runs = 0

        logger.info(
            f"MetricsRollupService initialized: enabled={self.enabled}, "
            f"interval_hours={self.rollup_interval_hours}, "
            f"delete_raw={self.delete_raw_after_rollup}, "
            f"postgresql={self._is_postgresql}"
        )

    def pause(self, reason: str = "maintenance") -> None:
        """Pause background rollup execution.

        Args:
            reason: Reason for pausing the rollup task.
        """
        with self._pause_lock:
            self._pause_count += 1
            self._pause_reason = reason
            self._pause_event.set()

    def resume(self) -> None:
        """Resume background rollup execution."""
        with self._pause_lock:
            if self._pause_count > 0:
                self._pause_count -= 1
            if self._pause_count <= 0:
                self._pause_count = 0
                self._pause_reason = None
                self._pause_event.clear()

    @contextmanager
    def pause_during(self, reason: str = "maintenance"):
        """Pause rollups for the duration of the context manager.

        Args:
            reason: Reason for pausing the rollup task.

        Yields:
            None
        """
        self.pause(reason)
        try:
            yield
        finally:
            self.resume()

    async def start(self) -> None:
        """Start the background rollup task."""
        if not self.enabled:
            logger.info("MetricsRollupService disabled, skipping start")
            return

        if self._rollup_task is None or self._rollup_task.done():
            self._shutdown_event.clear()
            self._rollup_task = asyncio.create_task(self._rollup_loop())
            logger.info("MetricsRollupService background task started")

    async def shutdown(self) -> None:
        """Shutdown the rollup service."""
        logger.info("MetricsRollupService shutting down...")

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel the rollup task
        if self._rollup_task:
            self._rollup_task.cancel()
            try:
                await self._rollup_task
            except asyncio.CancelledError:
                pass

        logger.info(f"MetricsRollupService shutdown complete: " f"total_rollups={self._total_rollups}, rollup_runs={self._rollup_runs}")

    async def _rollup_loop(self) -> None:
        """Background task that periodically rolls up metrics.

        Includes smart backfill detection: if the service has been down for more
        than 24 hours, it will automatically detect the gap and roll up all
        unprocessed hours up to the configured maximum (retention period).

        Raises:
            asyncio.CancelledError: When the task is cancelled during shutdown.
        """
        logger.info(f"Metrics rollup loop started (interval={self.rollup_interval_hours}h)")

        # Calculate interval in seconds
        interval_seconds = self.rollup_interval_hours * 3600
        # On first run, do a backfill check
        first_run = True

        while not self._shutdown_event.is_set():
            try:
                # Wait for interval or shutdown (skip wait on first run for immediate backfill)
                if not first_run:
                    try:
                        await asyncio.wait_for(
                            self._shutdown_event.wait(),
                            timeout=interval_seconds,
                        )
                        # Shutdown signaled
                        break
                    except asyncio.TimeoutError:
                        # Normal timeout, proceed to rollup
                        pass

                if self._pause_event.is_set():
                    logger.info(f"Metrics rollup paused ({self._pause_reason or 'maintenance'}), skipping this cycle")
                    try:
                        await asyncio.wait_for(self._shutdown_event.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        pass
                    continue

                # Determine hours_back based on whether this is first run or normal run
                if first_run:
                    # On first run, detect backfill gap (may scan entire retention period)
                    hours_back = await asyncio.to_thread(self._detect_backfill_hours)
                    if hours_back > 24:
                        logger.info(f"Backfill detected: rolling up {hours_back} hours of unprocessed metrics")
                    first_run = False
                else:
                    # Normal runs: only process recent hours to catch late-arriving data
                    # Configurable via METRICS_ROLLUP_LATE_DATA_HOURS (default: 1 hour)
                    # This avoids walking through entire retention period every interval
                    hours_back = getattr(settings, "metrics_rollup_late_data_hours", 1)

                # Run rollup for the calculated time range
                summary = await self.rollup_all(hours_back=hours_back)
                self._rollup_runs += 1
                self._total_rollups += summary.total_rollups_created

                if summary.total_rollups_created > 0 or summary.total_rollups_updated > 0:
                    logger.info(
                        f"Metrics rollup #{self._rollup_runs}: created {summary.total_rollups_created}, "
                        f"updated {summary.total_rollups_updated} rollups "
                        f"from {summary.total_records_aggregated} records in {summary.duration_seconds:.2f}s"
                    )

            except asyncio.CancelledError:
                logger.debug("Rollup loop cancelled")
                raise
            except Exception as e:
                logger.error(f"Error in metrics rollup loop: {e}", exc_info=True)
                # Continue the loop despite errors
                await asyncio.sleep(60)

    def _detect_backfill_hours(self) -> int:
        """Detect how many hours back we need to roll up.

        Checks for the earliest unprocessed raw metric and calculates how many
        hours of backfill are needed. Returns a minimum of 24 hours and caps at
        the retention period to avoid excessive processing.

        Returns:
            int: Number of hours to roll up (minimum 24, maximum retention days * 24)
        """
        retention_days = getattr(settings, "metrics_retention_days", 30)
        max_hours = retention_days * 24  # Cap at retention period

        try:
            with fresh_db_session() as db:
                # Find the earliest raw metric timestamp across all tables
                earliest_raw = None

                for _, raw_model, _hourly_model, _, _, _ in self.METRIC_TABLES:
                    # Get earliest unprocessed raw metric (where no rollup exists for that hour)
                    result = db.execute(select(func.min(raw_model.timestamp))).scalar()

                    if result and (earliest_raw is None or result < earliest_raw):
                        earliest_raw = result

                if earliest_raw is None:
                    # No raw metrics, use default
                    return 24

                # Calculate hours since earliest raw metric
                now = datetime.now(timezone.utc)
                hours_since_earliest = int((now - earliest_raw).total_seconds() / 3600) + 1

                # Clamp between 24 and max_hours
                return max(24, min(hours_since_earliest, max_hours))

        except Exception as e:
            logger.warning(f"Error detecting backfill hours: {e}, using default 24")
            return 24

    async def rollup_all(
        self,
        hours_back: int = 24,
        force_reprocess: bool = False,
    ) -> RollupSummary:
        """Roll up all metrics tables for the specified time range.

        Args:
            hours_back: How many hours back to look for unprocessed metrics (default: 24)
            force_reprocess: Reprocess even if rollup already exists (default: False)

        Returns:
            RollupSummary: Summary of rollup operations
        """
        started_at = datetime.now(timezone.utc)
        start_time = time.monotonic()

        # Calculate time range (process completed hours only, not current hour)
        now = datetime.now(timezone.utc)
        # Round down to start of current hour
        current_hour_start = now.replace(minute=0, second=0, microsecond=0)
        # Go back hours_back from the start of current hour
        start_hour = current_hour_start - timedelta(hours=hours_back)
        results: Dict[str, RollupResult] = {}
        total_hours = 0
        total_records = 0
        total_created = 0
        total_updated = 0

        for table_name, raw_model, hourly_model, entity_model, entity_id_col, entity_name_col in self.METRIC_TABLES:
            result = await asyncio.to_thread(
                self._rollup_table,
                table_name,
                raw_model,
                hourly_model,
                entity_model,
                entity_id_col,
                entity_name_col,
                start_hour,
                current_hour_start,
                force_reprocess,
            )
            results[table_name] = result
            total_hours += result.hours_processed
            total_records += result.records_aggregated
            total_created += result.rollups_created
            total_updated += result.rollups_updated

        duration = time.monotonic() - start_time
        completed_at = datetime.now(timezone.utc)

        return RollupSummary(
            total_hours_processed=total_hours,
            total_records_aggregated=total_records,
            total_rollups_created=total_created,
            total_rollups_updated=total_updated,
            tables=results,
            duration_seconds=duration,
            started_at=started_at,
            completed_at=completed_at,
        )

    def _rollup_table(
        self,
        table_name: str,
        raw_model: Type,
        hourly_model: Type,
        entity_model: Type,
        entity_id_col: str,
        entity_name_col: str,
        start_hour: datetime,
        end_hour: datetime,
        force_reprocess: bool,  # pylint: disable=unused-argument
    ) -> RollupResult:
        """Roll up metrics for a single table.

        Note: As of the late-data fix, rollup always re-aggregates when raw data exists,
        regardless of whether a rollup already exists. This ensures late-arriving metrics
        are properly included. The force_reprocess parameter is kept for API compatibility.

        Args:
            table_name: Name of the table being processed
            raw_model: SQLAlchemy model for raw metrics
            hourly_model: SQLAlchemy model for hourly rollups
            entity_model: SQLAlchemy model for the entity (Tool, Resource, etc.)
            entity_id_col: Name of the entity ID column in raw model
            entity_name_col: Name of the entity name column in entity model
            start_hour: Start of time range
            end_hour: End of time range (exclusive)
            force_reprocess: Kept for API compatibility (behavior now always re-processes)

        Returns:
            RollupResult: Result of the rollup operation
        """
        start_time = time.monotonic()
        hours_processed = 0
        records_aggregated = 0
        rollups_created = 0
        rollups_updated = 0
        raw_deleted = 0
        error_msg = None

        is_a2a = table_name == "a2a_agent_metrics"

        try:
            with fresh_db_session() as db:
                # Process each hour in the range
                current = start_hour
                while current < end_hour:
                    hour_end = current + timedelta(hours=1)

                    # Check if we have raw metrics for this hour
                    # pylint: disable=not-callable
                    raw_count = (
                        db.execute(
                            select(func.count())
                            .select_from(raw_model)
                            .where(
                                and_(
                                    raw_model.timestamp >= current,
                                    raw_model.timestamp < hour_end,
                                )
                            )
                        ).scalar()
                        or 0
                    )

                    if raw_count > 0:
                        # Always re-aggregate when there's raw data, even if rollup exists.
                        # This ensures late-arriving metrics (buffer flush, ingestion lag) are included.
                        # The _aggregate_hour queries ALL raw data for the hour, and _upsert_rollup
                        # handles updating existing rollups correctly.

                        # Aggregate metrics for this hour
                        aggregations = self._aggregate_hour(
                            db,
                            raw_model,
                            entity_model,
                            entity_id_col,
                            entity_name_col,
                            current,
                            hour_end,
                            is_a2a,
                        )
                        # Upsert rollups
                        for agg in aggregations:
                            created, updated = self._upsert_rollup(
                                db,
                                hourly_model,
                                entity_id_col,
                                agg,
                                is_a2a,
                            )
                            rollups_created += created
                            rollups_updated += updated
                            records_aggregated += agg.total_count

                        hours_processed += 1

                        # Delete raw metrics if configured
                        if self.delete_raw_after_rollup:
                            delete_cutoff = datetime.now(timezone.utc) - timedelta(hours=self.delete_raw_after_rollup_hours)
                            if hour_end < delete_cutoff:
                                deleted = self._delete_raw_metrics(db, raw_model, current, hour_end)
                                raw_deleted += deleted

                    current = hour_end

                db.commit()

        except Exception as e:
            logger.error(f"Error rolling up {table_name}: {e}", exc_info=True)
            error_msg = str(e)

        duration = time.monotonic() - start_time

        if rollups_created + rollups_updated > 0:
            logger.debug(f"Rolled up {table_name}: {records_aggregated} records -> " f"{rollups_created} new, {rollups_updated} updated rollups")

        return RollupResult(
            table_name=table_name,
            hours_processed=hours_processed,
            records_aggregated=records_aggregated,
            rollups_created=rollups_created,
            rollups_updated=rollups_updated,
            raw_deleted=raw_deleted,
            duration_seconds=duration,
            error=error_msg,
        )

    def _aggregate_hour(
        self,
        db: Session,
        raw_model: Type,
        entity_model: Type,
        entity_id_col: str,
        entity_name_col: str,
        hour_start: datetime,
        hour_end: datetime,
        is_a2a: bool,
    ) -> List[HourlyAggregation]:
        """Aggregate raw metrics for a single hour using optimized bulk queries.

        Uses a single GROUP BY query to get basic aggregations (count, min, max, avg,
        success count) for all entities at once, minimizing database round trips.
        Percentiles are calculated by loading response times in a single bulk query.

        Args:
            db: Database session
            raw_model: SQLAlchemy model for raw metrics
            entity_model: SQLAlchemy model for the entity
            entity_id_col: Name of the entity ID column
            entity_name_col: Name of the entity name column
            hour_start: Start of the hour
            hour_end: End of the hour
            is_a2a: Whether this is A2A agent metrics (has interaction_type)

        Returns:
            List[HourlyAggregation]: Aggregated metrics for each entity

        Raises:
            Exception: If aggregation fails due to a database query or processing error.
        """
        try:
            entity_id_attr = getattr(raw_model, entity_id_col)
            entity_name_attr = getattr(entity_model, entity_name_col)

            time_filter = and_(
                raw_model.timestamp >= hour_start,
                raw_model.timestamp < hour_end,
            )

            aggregations: list = []
            if self._is_postgresql and settings.use_postgresdb_percentiles:
                # ---- build SELECT and GROUP BY dynamically (CRITICAL FIX) ----
                select_cols = [
                    entity_id_attr.label("entity_id"),
                    func.coalesce(entity_name_attr, "unknown").label("entity_name"),
                ]
                group_by_cols = [
                    entity_id_attr,
                    entity_name_attr,
                ]

                if is_a2a:
                    select_cols.append(raw_model.interaction_type.label("interaction_type"))
                    group_by_cols.append(raw_model.interaction_type)

                # pylint: disable=not-callable
                agg_query = (
                    select(
                        *select_cols,
                        func.count(raw_model.id).label("total_count"),
                        func.sum(case((raw_model.is_success.is_(True), 1), else_=0)).label("success_count"),
                        func.min(raw_model.response_time).label("min_rt"),
                        func.max(raw_model.response_time).label("max_rt"),
                        func.avg(raw_model.response_time).label("avg_rt"),
                        func.percentile_cont(0.50).within_group(raw_model.response_time).label("p50_rt"),
                        func.percentile_cont(0.95).within_group(raw_model.response_time).label("p95_rt"),
                        func.percentile_cont(0.99).within_group(raw_model.response_time).label("p99_rt"),
                    )
                    .select_from(raw_model)
                    .join(entity_model, entity_model.id == entity_id_attr, isouter=True)
                    .where(time_filter)
                    .group_by(*group_by_cols)
                )
                # pylint: enable=not-callable
                for row in db.execute(agg_query).yield_per(settings.yield_batch_size):
                    aggregations.append(
                        HourlyAggregation(
                            entity_id=row.entity_id,
                            entity_name=row.entity_name,
                            hour_start=hour_start,
                            total_count=row.total_count,
                            success_count=row.success_count,
                            failure_count=row.total_count - row.success_count,
                            min_response_time=row.min_rt,
                            max_response_time=row.max_rt,
                            avg_response_time=row.avg_rt,
                            p50_response_time=row.p50_rt,
                            p95_response_time=row.p95_rt,
                            p99_response_time=row.p99_rt,
                            interaction_type=row.interaction_type if is_a2a else None,
                        )
                    )
            else:
                # Build group by columns
                if is_a2a:
                    group_cols = [entity_id_attr, raw_model.interaction_type]
                else:
                    group_cols = [entity_id_attr]

                # Time filter for this hour
                time_filter = and_(
                    raw_model.timestamp >= hour_start,
                    raw_model.timestamp < hour_end,
                )

                # OPTIMIZED: Single bulk query for basic aggregations per entity
                # pylint: disable=not-callable
                agg_query = (
                    select(
                        *group_cols,
                        func.count(raw_model.id).label("total_count"),
                        func.sum(case((raw_model.is_success.is_(True), 1), else_=0)).label("success_count"),
                        func.min(raw_model.response_time).label("min_rt"),
                        func.max(raw_model.response_time).label("max_rt"),
                        func.avg(raw_model.response_time).label("avg_rt"),
                    )
                    .where(time_filter)
                    .group_by(*group_cols)
                )

                # Store aggregation results by entity key
                agg_results = {}
                for row in db.execute(agg_query).yield_per(settings.yield_batch_size):
                    entity_id = row[0]
                    interaction_type = row[1] if is_a2a else None
                    key = (entity_id, interaction_type) if is_a2a else entity_id

                    agg_results[key] = {
                        "entity_id": entity_id,
                        "interaction_type": interaction_type,
                        "total_count": row.total_count or 0,
                        "success_count": row.success_count or 0,
                        "min_rt": row.min_rt,
                        "max_rt": row.max_rt,
                        "avg_rt": row.avg_rt,
                    }

                if not agg_results:
                    return []

                # OPTIMIZED: Bulk load entity names in one query
                entity_ids = list(set(r["entity_id"] for r in agg_results.values()))
                entity_names = {}
                if entity_ids:
                    entities = db.execute(select(entity_model.id, getattr(entity_model, entity_name_col)).where(entity_model.id.in_(entity_ids)))  # .fetchall()
                    entity_names = {e[0]: e[1] for e in entities}

                # OPTIMIZED: Bulk load all response times for percentile calculation
                # Load all response times for the hour in one query, grouped by entity
                rt_query = (
                    select(
                        *group_cols,
                        raw_model.response_time,
                    )
                    .where(time_filter)
                    .order_by(*group_cols, raw_model.response_time)
                )

                # Group response times by entity
                response_times_by_entity: Dict[Any, List[float]] = {}
                for row in db.execute(rt_query).yield_per(settings.yield_batch_size):
                    entity_id = row[0]
                    interaction_type = row[1] if is_a2a else None
                    key = (entity_id, interaction_type) if is_a2a else entity_id
                    rt = row.response_time if not is_a2a else row[2]

                    if key not in response_times_by_entity:
                        response_times_by_entity[key] = []
                    if rt is not None:
                        response_times_by_entity[key].append(rt)

                # Build aggregation results with percentiles
                aggregations = []
                for key, agg in agg_results.items():
                    entity_id = agg["entity_id"]
                    interaction_type = agg["interaction_type"]

                    # Get entity name
                    entity_name = entity_names.get(entity_id, "unknown")

                    # Get response times for percentile calculation
                    response_times = response_times_by_entity.get(key, [])

                    # Calculate percentiles (response_times are already sorted from ORDER BY)
                    if response_times:
                        p50_rt = self._percentile(response_times, 50)
                        p95_rt = self._percentile(response_times, 95)
                        p99_rt = self._percentile(response_times, 99)
                    else:
                        p50_rt = p95_rt = p99_rt = None

                    aggregations.append(
                        HourlyAggregation(
                            entity_id=entity_id,
                            entity_name=entity_name,
                            hour_start=hour_start,
                            total_count=agg["total_count"],
                            success_count=agg["success_count"],
                            failure_count=agg["total_count"] - agg["success_count"],
                            min_response_time=agg["min_rt"],
                            max_response_time=agg["max_rt"],
                            avg_response_time=agg["avg_rt"],
                            p50_response_time=p50_rt,
                            p95_response_time=p95_rt,
                            p99_response_time=p99_rt,
                            interaction_type=interaction_type,
                        )
                    )
            return aggregations
        except Exception:
            logger.exception(
                "Failed to aggregate hourly metrics",
                extra={
                    "hour_start": hour_start,
                    "hour_end": hour_end,
                    "raw_model": raw_model.__name__,
                    "entity_model": entity_model.__name__,
                    "is_a2a": is_a2a,
                },
            )
            raise

    def _percentile(self, sorted_data: List[float], percentile: int) -> float:
        """Calculate percentile from sorted data.

        Args:
            sorted_data: Sorted list of values
            percentile: Percentile to calculate (0-100)

        Returns:
            float: The percentile value
        """
        if not sorted_data:
            return 0.0

        k = (len(sorted_data) - 1) * percentile / 100
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_data) else f

        if f == c:
            return sorted_data[f]
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])

    def _upsert_rollup(
        self,
        db: Session,
        hourly_model: Type,
        entity_id_col: str,
        agg: HourlyAggregation,
        is_a2a: bool,
    ) -> Tuple[int, int]:
        """
        Insert or update a single hourly rollup record using a DB-aware UPSERT.
        This function is concurrency-safe for PostgreSQL and SQLite.
        Falls back to Python SELECT+UPDATE/INSERT for unsupported DBs

        This function is concurrency-safe and enforces uniqueness at the database level.

        Args:
            db (Session): Active SQLAlchemy database session.
            hourly_model (Type): ORM model representing the hourly rollup table.
            entity_id_col (str): Name of the entity ID column (e.g. "tool_id", "agent_id").
            agg (HourlyAggregation): Aggregated hourly metrics for a single entity.
            is_a2a (bool): Whether interaction_type should be included in the uniqueness key.

        Returns:
            Tuple[int, int]: Best-effort (inserted_count, updated_count) values for logging only.

        Raises:
            SQLAlchemyError: If the database UPSERT operation fails.
        """
        try:
            # Resolve name column
            name_col_map = {
                "tool_id": "tool_name",
                "resource_id": "resource_name",
                "prompt_id": "prompt_name",
                "server_id": "server_name",
            }
            name_col = name_col_map.get(entity_id_col, "agent_name")

            # Normalizing
            hour_start = agg.hour_start.replace(minute=0, second=0, microsecond=0)

            values = {
                entity_id_col: agg.entity_id,
                name_col: agg.entity_name,
                "hour_start": hour_start,
                "total_count": agg.total_count,
                "success_count": agg.success_count,
                "failure_count": agg.failure_count,
                "min_response_time": agg.min_response_time,
                "max_response_time": agg.max_response_time,
                "avg_response_time": agg.avg_response_time,
                "p50_response_time": agg.p50_response_time,
                "p95_response_time": agg.p95_response_time,
                "p99_response_time": agg.p99_response_time,
            }

            if is_a2a:
                values["interaction_type"] = agg.interaction_type

            dialect = db.bind.dialect.name if db.bind else "unknown"
            conflict_cols = [
                getattr(hourly_model, entity_id_col),
                hourly_model.hour_start,
            ]

            if is_a2a:
                conflict_cols.append(hourly_model.interaction_type)

            logger.debug(
                "Upserting hourly rollup",
                extra={
                    "dialect": dialect,
                    "entity_id_col": entity_id_col,
                    "entity_id": agg.entity_id,
                    "hour_start": hour_start.isoformat(),
                    "is_a2a": is_a2a,
                },
            )

            if dialect == "postgresql":
                # =======================
                # PostgreSQL
                # =======================
                stmt = pg_insert(hourly_model).values(**values)
                update_cols = {k: stmt.excluded[k] for k in values if k not in (entity_id_col, "hour_start", "interaction_type")}
                stmt = stmt.on_conflict_do_update(
                    index_elements=conflict_cols,
                    set_=update_cols,
                )

                db.execute(stmt)
                return (0, 1)

            if "sqlite" in dialect:
                # =======================
                # SQLite
                # =======================
                stmt = sqlite_insert(hourly_model).values(**values)

                update_cols = {k: stmt.excluded[k] for k in values if k not in (entity_id_col, "hour_start", "interaction_type")}

                stmt = stmt.on_conflict_do_update(
                    index_elements=conflict_cols,
                    set_=update_cols,
                )

                db.execute(stmt)
                return (0, 1)

            logger.warning(
                "Dialect does not support native UPSERT. Using Python fallback with conflict handling.",
                extra={"dialect": dialect},
            )
            # Use savepoint to avoid rolling back the entire transaction on conflict
            savepoint = db.begin_nested()
            try:
                db.add(hourly_model(**values))
                db.flush()  # Force INSERT now
                savepoint.commit()
                return (1, 0)
            except IntegrityError:
                savepoint.rollback()  # Only roll back the savepoint, not the whole transaction
                logger.info(
                    "Insert conflict detected in fallback path. Retrying as update.",
                    extra={
                        "entity_id_col": entity_id_col,
                        "entity_id": agg.entity_id,
                        "hour_start": hour_start.isoformat(),
                        "is_a2a": is_a2a,
                    },
                )

                entity_id_attr = getattr(hourly_model, entity_id_col)

                filters = [
                    entity_id_attr == agg.entity_id,
                    hourly_model.hour_start == hour_start,
                ]

                if is_a2a:
                    filters.append(hourly_model.interaction_type == agg.interaction_type)

                existing = db.execute(select(hourly_model).where(and_(*filters))).scalar_one()

                for key, value in values.items():
                    if key not in (entity_id_col, "hour_start", "interaction_type"):
                        setattr(existing, key, value)

                return (0, 1)

        except SQLAlchemyError:
            logger.exception(
                "Failed to upsert hourly rollup",
                extra={
                    "entity_id_col": entity_id_col,
                    "entity_id": agg.entity_id,
                    "hour_start": hour_start.isoformat(),
                    "is_a2a": is_a2a,
                },
            )
            raise

    def _delete_raw_metrics(
        self,
        db: Session,
        raw_model: Type,
        hour_start: datetime,
        hour_end: datetime,
    ) -> int:
        """Delete raw metrics for a given hour after rollup.

        Args:
            db: Database session
            raw_model: SQLAlchemy model for raw metrics
            hour_start: Start of the hour
            hour_end: End of the hour

        Returns:
            int: Number of records deleted
        """
        result = db.execute(
            delete(raw_model).where(
                and_(
                    raw_model.timestamp >= hour_start,
                    raw_model.timestamp < hour_end,
                )
            )
        )
        return result.rowcount

    def get_stats(self) -> dict:
        """Get rollup service statistics.

        Returns:
            dict: Rollup statistics
        """
        return {
            "enabled": self.enabled,
            "rollup_interval_hours": self.rollup_interval_hours,
            "delete_raw_after_rollup": self.delete_raw_after_rollup,
            "delete_raw_after_rollup_hours": self.delete_raw_after_rollup_hours,
            "total_rollups": self._total_rollups,
            "rollup_runs": self._rollup_runs,
            "is_postgresql": self._is_postgresql,
        }


# Singleton instance
_metrics_rollup_service: Optional[MetricsRollupService] = None


def get_metrics_rollup_service() -> MetricsRollupService:
    """Get or create the singleton MetricsRollupService instance.

    Returns:
        MetricsRollupService: The singleton rollup service instance
    """
    global _metrics_rollup_service  # pylint: disable=global-statement
    if _metrics_rollup_service is None:
        _metrics_rollup_service = MetricsRollupService()
    return _metrics_rollup_service


def get_metrics_rollup_service_if_initialized() -> Optional[MetricsRollupService]:
    """Return the rollup service instance if it has been created.

    Returns:
        The rollup service instance or None if not initialized.
    """
    return _metrics_rollup_service
