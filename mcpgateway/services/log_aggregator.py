# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/log_aggregator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Log Aggregation Service.

This module provides aggregation of performance metrics from structured logs
into time-windowed statistics for analysis and monitoring.
"""

# Standard
from datetime import datetime, timedelta, timezone
import logging
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple

# Third-Party
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import PerformanceMetric, SessionLocal, StructuredLogEntry

logger = logging.getLogger(__name__)


class LogAggregator:
    """Aggregates structured logs into performance metrics."""

    def __init__(self):
        """Initialize log aggregator."""
        self.aggregation_window_minutes = getattr(settings, "metrics_aggregation_window_minutes", 5)
        self.enabled = getattr(settings, "metrics_aggregation_enabled", True)

    def aggregate_performance_metrics(
        self, component: Optional[str], operation_type: Optional[str], window_start: Optional[datetime] = None, window_end: Optional[datetime] = None, db: Optional[Session] = None
    ) -> Optional[PerformanceMetric]:
        """Aggregate performance metrics for a component and operation.

        Args:
            component: Component name
            operation_type: Operation name
            window_start: Start of aggregation window (defaults to N minutes ago)
            window_end: End of aggregation window (defaults to now)
            db: Optional database session

        Returns:
            Created PerformanceMetric or None if no data
        """
        if not self.enabled:
            return None
        if not component or not operation_type:
            return None

        window_start, window_end = self._resolve_window_bounds(window_start, window_end)

        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            # Query structured logs for this component/operation in time window
            stmt = select(StructuredLogEntry).where(
                and_(
                    StructuredLogEntry.component == component,
                    StructuredLogEntry.operation_type == operation_type,
                    StructuredLogEntry.timestamp >= window_start,
                    StructuredLogEntry.timestamp < window_end,
                    StructuredLogEntry.duration_ms.isnot(None),
                )
            )

            results = db.execute(stmt).scalars().all()

            if not results:
                return None

            # Extract durations
            durations = sorted(r.duration_ms for r in results if r.duration_ms is not None)

            if not durations:
                return None

            # Calculate statistics
            count = len(durations)
            avg_duration = statistics.fmean(durations) if hasattr(statistics, "fmean") else statistics.mean(durations)
            min_duration = durations[0]
            max_duration = durations[-1]

            # Calculate percentiles
            p50 = self._percentile(durations, 0.50)
            p95 = self._percentile(durations, 0.95)
            p99 = self._percentile(durations, 0.99)

            # Count errors
            error_count = self._calculate_error_count(results)
            error_rate = error_count / count if count > 0 else 0.0

            metric = self._upsert_metric(
                component=component,
                operation_type=operation_type,
                window_start=window_start,
                window_end=window_end,
                request_count=count,
                error_count=error_count,
                error_rate=error_rate,
                avg_duration_ms=avg_duration,
                min_duration_ms=min_duration,
                max_duration_ms=max_duration,
                p50_duration_ms=p50,
                p95_duration_ms=p95,
                p99_duration_ms=p99,
                metric_metadata={
                    "sample_size": count,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                db=db,
            )

            logger.info(f"Aggregated performance metrics for {component}.{operation_type}: " f"{count} requests, {avg_duration:.2f}ms avg, {error_rate:.2%} error rate")

            return metric

        except Exception as e:
            logger.error(f"Failed to aggregate performance metrics: {e}")
            if db:
                db.rollback()
            return None

        finally:
            if should_close:
                db.close()

    def aggregate_all_components(self, window_start: Optional[datetime] = None, window_end: Optional[datetime] = None, db: Optional[Session] = None) -> List[PerformanceMetric]:
        """Aggregate metrics for all components and operations.

        Args:
            window_start: Start of aggregation window
            window_end: End of aggregation window
            db: Optional database session

        Returns:
            List of created PerformanceMetric records
        """
        if not self.enabled:
            return []

        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            window_start, window_end = self._resolve_window_bounds(window_start, window_end)

            stmt = (
                select(StructuredLogEntry.component, StructuredLogEntry.operation_type)
                .where(
                    and_(
                        StructuredLogEntry.timestamp >= window_start,
                        StructuredLogEntry.timestamp < window_end,
                        StructuredLogEntry.duration_ms.isnot(None),
                        StructuredLogEntry.operation_type.isnot(None),
                    )
                )
                .distinct()
            )

            pairs = db.execute(stmt).all()

            metrics = []
            for component, operation in pairs:
                if component and operation:
                    metric = self.aggregate_performance_metrics(component=component, operation_type=operation, window_start=window_start, window_end=window_end, db=db)
                    if metric:
                        metrics.append(metric)

            return metrics

        finally:
            if should_close:
                db.close()

    def get_recent_metrics(self, component: Optional[str] = None, operation: Optional[str] = None, hours: int = 24, db: Optional[Session] = None) -> List[PerformanceMetric]:
        """Get recent performance metrics.

        Args:
            component: Optional component filter
            operation: Optional operation filter
            hours: Hours of history to retrieve
            db: Optional database session

        Returns:
            List of PerformanceMetric records
        """
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)

            stmt = select(PerformanceMetric).where(PerformanceMetric.window_start >= since)

            if component:
                stmt = stmt.where(PerformanceMetric.component == component)
            if operation:
                stmt = stmt.where(PerformanceMetric.operation_type == operation)

            stmt = stmt.order_by(PerformanceMetric.window_start.desc())

            return db.execute(stmt).scalars().all()

        finally:
            if should_close:
                db.close()

    def get_degradation_alerts(self, threshold_multiplier: float = 1.5, hours: int = 24, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """Identify performance degradations by comparing recent vs baseline.

        Args:
            threshold_multiplier: Alert if recent is X times slower than baseline
            hours: Hours of recent data to check
            db: Optional database session

        Returns:
            List of degradation alerts with details
        """
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            baseline_cutoff = recent_cutoff - timedelta(hours=hours * 2)

            # Get unique component/operation pairs
            stmt = select(PerformanceMetric.component, PerformanceMetric.operation_type).distinct()

            pairs = db.execute(stmt).all()

            alerts = []
            for component, operation in pairs:
                # Get recent metrics
                recent_stmt = select(PerformanceMetric).where(
                    and_(PerformanceMetric.component == component, PerformanceMetric.operation_type == operation, PerformanceMetric.window_start >= recent_cutoff)
                )
                recent_metrics = db.execute(recent_stmt).scalars().all()

                # Get baseline metrics
                baseline_stmt = select(PerformanceMetric).where(
                    and_(
                        PerformanceMetric.component == component,
                        PerformanceMetric.operation_type == operation,
                        PerformanceMetric.window_start >= baseline_cutoff,
                        PerformanceMetric.window_start < recent_cutoff,
                    )
                )
                baseline_metrics = db.execute(baseline_stmt).scalars().all()

                if not recent_metrics or not baseline_metrics:
                    continue

                recent_avg = statistics.mean([m.avg_duration_ms for m in recent_metrics])
                baseline_avg = statistics.mean([m.avg_duration_ms for m in baseline_metrics])

                if recent_avg > baseline_avg * threshold_multiplier:
                    alerts.append(
                        {
                            "component": component,
                            "operation": operation,
                            "recent_avg_ms": recent_avg,
                            "baseline_avg_ms": baseline_avg,
                            "degradation_ratio": recent_avg / baseline_avg,
                            "recent_error_rate": statistics.mean([m.error_rate for m in recent_metrics]),
                            "baseline_error_rate": statistics.mean([m.error_rate for m in baseline_metrics]),
                        }
                    )

            return alerts

        finally:
            if should_close:
                db.close()

    def backfill(self, hours: float, db: Optional[Session] = None) -> int:
        """Backfill metrics for a historical time range.

        Args:
            hours: Number of hours of history to aggregate (supports fractional hours)
            db: Optional shared database session

        Returns:
            Count of performance metric windows processed
        """
        if not self.enabled or hours <= 0:
            return 0

        window_minutes = self.aggregation_window_minutes
        window_delta = timedelta(minutes=window_minutes)
        total_windows = max(1, math.ceil((hours * 60) / window_minutes))

        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            _, latest_end = self._resolve_window_bounds(None, None)
            current_start = latest_end - (window_delta * total_windows)
            processed = 0

            while current_start < latest_end:
                current_end = current_start + window_delta
                created = self.aggregate_all_components(
                    window_start=current_start,
                    window_end=current_end,
                    db=db,
                )
                if created:
                    processed += 1
                current_start = current_end

            return processed

        finally:
            if should_close:
                db.close()

    @staticmethod
    def _percentile(sorted_values: List[float], percentile: float) -> float:
        """Calculate percentile from sorted values.

        Args:
            sorted_values: Sorted list of values
            percentile: Percentile to calculate (0.0 to 1.0)

        Returns:
            float: Calculated percentile value
        """
        if not sorted_values:
            return 0.0

        if len(sorted_values) == 1:
            return float(sorted_values[0])

        k = (len(sorted_values) - 1) * percentile
        f = math.floor(k)
        c = math.ceil(k)

        if f == c:
            return float(sorted_values[int(k)])

        d0 = sorted_values[f] * (c - k)
        d1 = sorted_values[c] * (k - f)
        return float(d0 + d1)

    @staticmethod
    def _calculate_error_count(entries: List[StructuredLogEntry]) -> int:
        """Calculate error occurrences for a batch of log entries.

        Args:
            entries: List of log entries to analyze

        Returns:
            int: Count of error entries
        """
        error_levels = {"ERROR", "CRITICAL"}
        return sum(1 for entry in entries if (entry.level and entry.level.upper() in error_levels) or entry.error_details)

    def _resolve_window_bounds(
        self,
        window_start: Optional[datetime],
        window_end: Optional[datetime],
    ) -> Tuple[datetime, datetime]:
        """Resolve and normalize aggregation window bounds.

        Args:
            window_start: Start of window or None to calculate
            window_end: End of window or None for current time

        Returns:
            Tuple[datetime, datetime]: Resolved window start and end
        """
        window_delta = timedelta(minutes=self.aggregation_window_minutes)

        if window_start is not None and window_end is not None:
            resolved_start = window_start.astimezone(timezone.utc)
            resolved_end = window_end.astimezone(timezone.utc)
            if resolved_end <= resolved_start:
                resolved_end = resolved_start + window_delta
            return resolved_start, resolved_end

        if window_end is None:
            reference = datetime.now(timezone.utc)
        else:
            reference = window_end.astimezone(timezone.utc)

        reference = reference.replace(second=0, microsecond=0)
        minutes_offset = reference.minute % self.aggregation_window_minutes
        if window_end is None and minutes_offset:
            reference = reference - timedelta(minutes=minutes_offset)

        resolved_end = reference if window_end is None else reference

        if window_start is None:
            resolved_start = resolved_end - window_delta
        else:
            resolved_start = window_start.astimezone(timezone.utc)

        if resolved_end <= resolved_start:
            resolved_start = resolved_end - window_delta

        return resolved_start, resolved_end

    def _upsert_metric(
        self,
        component: str,
        operation_type: str,
        window_start: datetime,
        window_end: datetime,
        request_count: int,
        error_count: int,
        error_rate: float,
        avg_duration_ms: float,
        min_duration_ms: float,
        max_duration_ms: float,
        p50_duration_ms: float,
        p95_duration_ms: float,
        p99_duration_ms: float,
        metric_metadata: Optional[Dict[str, Any]],
        db: Session,
    ) -> PerformanceMetric:
        """Create or update a performance metric window.

        Args:
            component: Component name
            operation_type: Operation type
            window_start: Window start time
            window_end: Window end time
            request_count: Total request count
            error_count: Total error count
            error_rate: Error rate (0.0-1.0)
            avg_duration_ms: Average duration in milliseconds
            min_duration_ms: Minimum duration in milliseconds
            max_duration_ms: Maximum duration in milliseconds
            p50_duration_ms: 50th percentile duration
            p95_duration_ms: 95th percentile duration
            p99_duration_ms: 99th percentile duration
            metric_metadata: Additional metadata
            db: Database session

        Returns:
            PerformanceMetric: Created or updated metric
        """

        existing_stmt = select(PerformanceMetric).where(
            and_(
                PerformanceMetric.component == component,
                PerformanceMetric.operation_type == operation_type,
                PerformanceMetric.window_start == window_start,
                PerformanceMetric.window_end == window_end,
            )
        )

        existing_metrics = db.execute(existing_stmt).scalars().all()
        metric = existing_metrics[0] if existing_metrics else None

        if len(existing_metrics) > 1:
            logger.warning(
                "Found %s duplicate performance metric rows for %s.%s window %s-%s; pruning extras",
                len(existing_metrics),
                component,
                operation_type,
                window_start.isoformat(),
                window_end.isoformat(),
            )
            for duplicate in existing_metrics[1:]:
                db.delete(duplicate)

        if metric is None:
            metric = PerformanceMetric(
                component=component,
                operation_type=operation_type,
                window_start=window_start,
                window_end=window_end,
                window_duration_seconds=int((window_end - window_start).total_seconds()),
            )
            db.add(metric)

        metric.request_count = request_count
        metric.error_count = error_count
        metric.error_rate = error_rate
        metric.avg_duration_ms = avg_duration_ms
        metric.min_duration_ms = min_duration_ms
        metric.max_duration_ms = max_duration_ms
        metric.p50_duration_ms = p50_duration_ms
        metric.p95_duration_ms = p95_duration_ms
        metric.p99_duration_ms = p99_duration_ms
        metric.metric_metadata = metric_metadata

        db.commit()
        db.refresh(metric)
        return metric


# Global log aggregator instance
_log_aggregator: Optional[LogAggregator] = None


def get_log_aggregator() -> LogAggregator:
    """Get or create the global log aggregator instance.

    Returns:
        Global LogAggregator instance
    """
    global _log_aggregator  # pylint: disable=global-statement
    if _log_aggregator is None:
        _log_aggregator = LogAggregator()
    return _log_aggregator
