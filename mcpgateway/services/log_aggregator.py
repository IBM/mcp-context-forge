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
import statistics
from typing import Dict, List, Optional, Tuple

# Third-Party
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import PerformanceMetric, StructuredLogEntry, SessionLocal
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


class LogAggregator:
    """Aggregates structured logs into performance metrics."""
    
    def __init__(self):
        """Initialize log aggregator."""
        self.aggregation_window_minutes = getattr(settings, "metrics_aggregation_window_minutes", 5)
        self.enabled = getattr(settings, "metrics_aggregation_enabled", True)
    
    def aggregate_performance_metrics(
        self,
        component: str,
        operation: str,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
        db: Optional[Session] = None
    ) -> Optional[PerformanceMetric]:
        """Aggregate performance metrics for a component and operation.
        
        Args:
            component: Component name
            operation: Operation name
            window_start: Start of aggregation window (defaults to N minutes ago)
            window_end: End of aggregation window (defaults to now)
            db: Optional database session
            
        Returns:
            Created PerformanceMetric or None if no data
        """
        if not self.enabled:
            return None
        
        # Default time window
        if window_end is None:
            window_end = datetime.now(timezone.utc)
        if window_start is None:
            window_start = window_end - timedelta(minutes=self.aggregation_window_minutes)
        
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True
        
        try:
            # Query structured logs for this component/operation in time window
            stmt = select(StructuredLogEntry).where(
                and_(
                    StructuredLogEntry.component == component,
                    StructuredLogEntry.category == "performance",
                    StructuredLogEntry.resource_action == operation,
                    StructuredLogEntry.timestamp >= window_start,
                    StructuredLogEntry.timestamp <= window_end,
                    StructuredLogEntry.duration_ms.isnot(None)
                )
            )
            
            results = db.execute(stmt).scalars().all()
            
            if not results:
                return None
            
            # Extract durations
            durations = [r.duration_ms for r in results if r.duration_ms is not None]
            
            if not durations:
                return None
            
            # Calculate statistics
            count = len(durations)
            total_duration = sum(durations)
            avg_duration = statistics.mean(durations)
            min_duration = min(durations)
            max_duration = max(durations)
            
            # Calculate percentiles
            sorted_durations = sorted(durations)
            p50 = self._percentile(sorted_durations, 0.50)
            p95 = self._percentile(sorted_durations, 0.95)
            p99 = self._percentile(sorted_durations, 0.99)
            
            # Count errors
            error_count = sum(1 for r in results if r.error_message is not None)
            error_rate = error_count / count if count > 0 else 0.0
            
            # Aggregate database metrics
            db_queries = [r.database_query_count for r in results if r.database_query_count is not None]
            total_db_queries = sum(db_queries) if db_queries else 0
            avg_db_queries = statistics.mean(db_queries) if db_queries else 0.0
            
            db_durations = [r.database_query_duration_ms for r in results if r.database_query_duration_ms is not None]
            total_db_duration = sum(db_durations) if db_durations else 0.0
            avg_db_duration = statistics.mean(db_durations) if db_durations else 0.0
            
            # Aggregate cache metrics
            cache_hits = sum(r.cache_hits for r in results if r.cache_hits is not None)
            cache_misses = sum(r.cache_misses for r in results if r.cache_misses is not None)
            cache_total = cache_hits + cache_misses
            cache_hit_rate = cache_hits / cache_total if cache_total > 0 else 0.0
            
            # Create performance metric
            metric = PerformanceMetric(
                component=component,
                operation=operation,
                window_start=window_start,
                window_end=window_end,
                request_count=count,
                error_count=error_count,
                error_rate=error_rate,
                total_duration_ms=total_duration,
                avg_duration_ms=avg_duration,
                min_duration_ms=min_duration,
                max_duration_ms=max_duration,
                p50_duration_ms=p50,
                p95_duration_ms=p95,
                p99_duration_ms=p99,
                total_database_queries=total_db_queries,
                avg_database_queries=avg_db_queries,
                total_database_duration_ms=total_db_duration,
                avg_database_duration_ms=avg_db_duration,
                cache_hits=cache_hits,
                cache_misses=cache_misses,
                cache_hit_rate=cache_hit_rate,
            )
            
            db.add(metric)
            db.commit()
            db.refresh(metric)
            
            logger.info(
                f"Aggregated performance metrics for {component}.{operation}: "
                f"{count} requests, {avg_duration:.2f}ms avg, {error_rate:.2%} error rate"
            )
            
            return metric
        
        except Exception as e:
            logger.error(f"Failed to aggregate performance metrics: {e}")
            if db:
                db.rollback()
            return None
        
        finally:
            if should_close:
                db.close()
    
    def aggregate_all_components(
        self,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
        db: Optional[Session] = None
    ) -> List[PerformanceMetric]:
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
            # Get unique component/operation pairs
            if window_end is None:
                window_end = datetime.now(timezone.utc)
            if window_start is None:
                window_start = window_end - timedelta(minutes=self.aggregation_window_minutes)
            
            stmt = select(
                StructuredLogEntry.component,
                StructuredLogEntry.resource_action
            ).where(
                and_(
                    StructuredLogEntry.category == "performance",
                    StructuredLogEntry.timestamp >= window_start,
                    StructuredLogEntry.timestamp <= window_end,
                    StructuredLogEntry.duration_ms.isnot(None)
                )
            ).distinct()
            
            pairs = db.execute(stmt).all()
            
            metrics = []
            for component, operation in pairs:
                if component and operation:
                    metric = self.aggregate_performance_metrics(
                        component=component,
                        operation=operation,
                        window_start=window_start,
                        window_end=window_end,
                        db=db
                    )
                    if metric:
                        metrics.append(metric)
            
            return metrics
        
        finally:
            if should_close:
                db.close()
    
    def get_recent_metrics(
        self,
        component: Optional[str] = None,
        operation: Optional[str] = None,
        hours: int = 24,
        db: Optional[Session] = None
    ) -> List[PerformanceMetric]:
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
            
            stmt = select(PerformanceMetric).where(
                PerformanceMetric.window_start >= since
            )
            
            if component:
                stmt = stmt.where(PerformanceMetric.component == component)
            if operation:
                stmt = stmt.where(PerformanceMetric.operation == operation)
            
            stmt = stmt.order_by(PerformanceMetric.window_start.desc())
            
            return db.execute(stmt).scalars().all()
        
        finally:
            if should_close:
                db.close()
    
    def get_degradation_alerts(
        self,
        threshold_multiplier: float = 1.5,
        hours: int = 24,
        db: Optional[Session] = None
    ) -> List[Dict[str, any]]:
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
            stmt = select(
                PerformanceMetric.component,
                PerformanceMetric.operation
            ).distinct()
            
            pairs = db.execute(stmt).all()
            
            alerts = []
            for component, operation in pairs:
                # Get recent metrics
                recent_stmt = select(PerformanceMetric).where(
                    and_(
                        PerformanceMetric.component == component,
                        PerformanceMetric.operation == operation,
                        PerformanceMetric.window_start >= recent_cutoff
                    )
                )
                recent_metrics = db.execute(recent_stmt).scalars().all()
                
                # Get baseline metrics
                baseline_stmt = select(PerformanceMetric).where(
                    and_(
                        PerformanceMetric.component == component,
                        PerformanceMetric.operation == operation,
                        PerformanceMetric.window_start >= baseline_cutoff,
                        PerformanceMetric.window_start < recent_cutoff
                    )
                )
                baseline_metrics = db.execute(baseline_stmt).scalars().all()
                
                if not recent_metrics or not baseline_metrics:
                    continue
                
                recent_avg = statistics.mean([m.avg_duration_ms for m in recent_metrics])
                baseline_avg = statistics.mean([m.avg_duration_ms for m in baseline_metrics])
                
                if recent_avg > baseline_avg * threshold_multiplier:
                    alerts.append({
                        "component": component,
                        "operation": operation,
                        "recent_avg_ms": recent_avg,
                        "baseline_avg_ms": baseline_avg,
                        "degradation_ratio": recent_avg / baseline_avg,
                        "recent_error_rate": statistics.mean([m.error_rate for m in recent_metrics]),
                        "baseline_error_rate": statistics.mean([m.error_rate for m in baseline_metrics]),
                    })
            
            return alerts
        
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
            Percentile value
        """
        if not sorted_values:
            return 0.0
        
        k = (len(sorted_values) - 1) * percentile
        f = int(k)
        c = f + 1
        
        if c >= len(sorted_values):
            return sorted_values[-1]
        
        d0 = sorted_values[f] * (c - k)
        d1 = sorted_values[c] * (k - f)
        
        return d0 + d1


# Global log aggregator instance
_log_aggregator: Optional[LogAggregator] = None


def get_log_aggregator() -> LogAggregator:
    """Get or create the global log aggregator instance.
    
    Returns:
        Global LogAggregator instance
    """
    global _log_aggregator
    if _log_aggregator is None:
        _log_aggregator = LogAggregator()
    return _log_aggregator
