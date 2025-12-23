# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/performance_tracker.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Performance Tracking Service.

This module provides performance tracking and analytics for all operations
across the MCP Gateway, enabling identification of bottlenecks and
optimization opportunities.
"""

# Standard
from collections import defaultdict, deque
from contextlib import contextmanager
import logging
import statistics
import time
from typing import Any, Dict, Generator, Optional

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.correlation_id import get_correlation_id

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """Tracks and analyzes performance metrics across requests.

    Provides context managers for tracking operation timing,
    aggregation of metrics, and threshold-based alerting.
    """

    def __init__(self):
        """Initialize performance tracker."""
        # Max buffer size per operation type - must be set before creating deque factory
        self.max_samples = getattr(settings, "perf_max_samples_per_operation", 1000)

        # Use deque with maxlen for O(1) automatic eviction instead of O(n) pop(0)
        self.operation_timings: Dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.max_samples))

        # Performance thresholds (seconds) from settings or defaults
        self.performance_thresholds = {
            "database_query": getattr(settings, "perf_threshold_database_query", 0.1),
            "tool_invocation": getattr(settings, "perf_threshold_tool_invocation", 2.0),
            "authentication": getattr(settings, "perf_threshold_authentication", 0.5),
            "cache_operation": getattr(settings, "perf_threshold_cache_operation", 0.01),
            "a2a_task": getattr(settings, "perf_threshold_a2a_task", 5.0),
            "request_total": getattr(settings, "perf_threshold_request_total", 10.0),
            "resource_fetch": getattr(settings, "perf_threshold_resource_fetch", 1.0),
            "prompt_processing": getattr(settings, "perf_threshold_prompt_processing", 0.5),
        }

    @contextmanager
    def track_operation(self, operation_name: str, component: Optional[str] = None, log_slow: bool = True, extra_context: Optional[Dict[str, Any]] = None) -> Generator[None, None, None]:
        """Context manager to track operation performance.

        Args:
            operation_name: Name of the operation being tracked
            component: Component/module name for context
            log_slow: Whether to log operations exceeding thresholds
            extra_context: Additional context to include in logs

        Yields:
            None

        Raises:
            Exception: Any exception from the tracked operation is re-raised

        Example:
            >>> tracker = PerformanceTracker()
            >>> with tracker.track_operation("database_query", component="tool_service"):
            ...     # Perform database operation
            ...     pass
        """
        start_time = time.time()
        correlation_id = get_correlation_id()
        error_occurred = False

        try:
            yield
        except Exception:
            error_occurred = True
            raise
        finally:
            duration = time.time() - start_time

            # Record timing (deque automatically evicts oldest when at maxlen)
            self.operation_timings[operation_name].append(duration)

            # Check threshold and log if needed
            threshold = self.performance_thresholds.get(operation_name, float("inf"))
            threshold_exceeded = duration > threshold

            if log_slow and threshold_exceeded:
                context = {
                    "operation": operation_name,
                    "duration_ms": duration * 1000,
                    "threshold_ms": threshold * 1000,
                    "exceeded_by_ms": (duration - threshold) * 1000,
                    "component": component,
                    "correlation_id": correlation_id,
                    "error_occurred": error_occurred,
                }
                if extra_context:
                    context.update(extra_context)

                logger.warning(f"Slow operation detected: {operation_name} took {duration*1000:.2f}ms " f"(threshold: {threshold*1000:.2f}ms)", extra=context)

    def record_timing(self, operation_name: str, duration: float, component: Optional[str] = None, extra_context: Optional[Dict[str, Any]] = None) -> None:
        """Manually record a timing measurement.

        Args:
            operation_name: Name of the operation
            duration: Duration in seconds
            component: Component/module name
            extra_context: Additional context
        """
        # Record timing (deque automatically evicts oldest when at maxlen)
        self.operation_timings[operation_name].append(duration)

        # Check threshold
        threshold = self.performance_thresholds.get(operation_name, float("inf"))
        if duration > threshold:
            context = {
                "operation": operation_name,
                "duration_ms": duration * 1000,
                "threshold_ms": threshold * 1000,
                "component": component,
                "correlation_id": get_correlation_id(),
            }
            if extra_context:
                context.update(extra_context)

            logger.warning(f"Slow operation: {operation_name} took {duration*1000:.2f}ms", extra=context)

    def get_performance_summary(self, operation_name: Optional[str] = None, min_samples: int = 1) -> Dict[str, Any]:
        """Get performance summary for analytics.

        Args:
            operation_name: Specific operation to summarize (None for all)
            min_samples: Minimum samples required to include in summary

        Returns:
            Dictionary containing performance statistics

        Example:
            >>> tracker = PerformanceTracker()
            >>> summary = tracker.get_performance_summary()
            >>> isinstance(summary, dict)
            True
        """
        summary = {}

        operations = {operation_name: self.operation_timings[operation_name]} if operation_name and operation_name in self.operation_timings else self.operation_timings

        for op_name, timings in operations.items():
            if len(timings) < min_samples:
                continue

            # Calculate percentiles
            sorted_timings = sorted(timings)
            count = len(sorted_timings)

            def percentile(p: float, *, sorted_vals=sorted_timings, n=count) -> float:
                """Calculate percentile value.

                Args:
                    p: Percentile to calculate (0.0 to 1.0)
                    sorted_vals: Sorted list of values
                    n: Number of values

                Returns:
                    float: Calculated percentile value
                """
                k = (n - 1) * p
                f = int(k)
                c = k - f
                if f + 1 < n:
                    return sorted_vals[f] * (1 - c) + sorted_vals[f + 1] * c
                return sorted_vals[f]

            summary[op_name] = {
                "count": count,
                "avg_duration_ms": statistics.mean(timings) * 1000,
                "min_duration_ms": min(timings) * 1000,
                "max_duration_ms": max(timings) * 1000,
                "p50_duration_ms": percentile(0.5) * 1000,
                "p95_duration_ms": percentile(0.95) * 1000,
                "p99_duration_ms": percentile(0.99) * 1000,
                "threshold_ms": self.performance_thresholds.get(op_name, float("inf")) * 1000,
                "threshold_violations": sum(1 for t in timings if t > self.performance_thresholds.get(op_name, float("inf"))),
                "violation_rate": sum(1 for t in timings if t > self.performance_thresholds.get(op_name, float("inf"))) / count,
            }

        return summary

    def get_operation_stats(self, operation_name: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific operation.

        Args:
            operation_name: Name of the operation

        Returns:
            Statistics dictionary or None if no data
        """
        if operation_name not in self.operation_timings:
            return None

        timings = self.operation_timings[operation_name]
        if not timings:
            return None

        return {
            "operation": operation_name,
            "sample_count": len(timings),
            "avg_duration_ms": statistics.mean(timings) * 1000,
            "min_duration_ms": min(timings) * 1000,
            "max_duration_ms": max(timings) * 1000,
            "total_time_ms": sum(timings) * 1000,
            "threshold_ms": self.performance_thresholds.get(operation_name, float("inf")) * 1000,
        }

    def clear_stats(self, operation_name: Optional[str] = None) -> None:
        """Clear performance statistics.

        Args:
            operation_name: Specific operation to clear (None for all)
        """
        if operation_name:
            if operation_name in self.operation_timings:
                self.operation_timings[operation_name].clear()
        else:
            self.operation_timings.clear()

    def set_threshold(self, operation_name: str, threshold_seconds: float) -> None:
        """Set or update performance threshold for an operation.

        Args:
            operation_name: Name of the operation
            threshold_seconds: Threshold in seconds
        """
        self.performance_thresholds[operation_name] = threshold_seconds

    def check_performance_degradation(self, operation_name: str, baseline_multiplier: float = 2.0) -> Dict[str, Any]:
        """Check if performance has degraded compared to baseline.

        Args:
            operation_name: Name of the operation to check
            baseline_multiplier: Multiplier for degradation detection

        Returns:
            Dictionary with degradation analysis
        """
        if operation_name not in self.operation_timings:
            return {"degraded": False, "reason": "no_data"}

        timings = self.operation_timings[operation_name]
        if len(timings) < 10:
            return {"degraded": False, "reason": "insufficient_samples"}

        # Compare recent timings to overall average
        # Convert deque to list for slicing operations
        timings_list = list(timings)
        recent_count = min(10, len(timings_list))
        recent_timings = timings_list[-recent_count:]
        historical_timings = timings_list[:-recent_count] if len(timings_list) > recent_count else timings_list

        if not historical_timings:
            return {"degraded": False, "reason": "insufficient_historical_data"}

        recent_avg = statistics.mean(recent_timings)
        historical_avg = statistics.mean(historical_timings)

        degraded = recent_avg > (historical_avg * baseline_multiplier)

        return {
            "degraded": degraded,
            "recent_avg_ms": recent_avg * 1000,
            "historical_avg_ms": historical_avg * 1000,
            "multiplier": recent_avg / historical_avg if historical_avg > 0 else 0,
            "threshold_multiplier": baseline_multiplier,
        }


# Global performance tracker instance
_performance_tracker: Optional[PerformanceTracker] = None


def get_performance_tracker() -> PerformanceTracker:
    """Get or create the global performance tracker instance.

    Returns:
        Global PerformanceTracker instance
    """
    global _performance_tracker  # pylint: disable=global-statement
    if _performance_tracker is None:
        _performance_tracker = PerformanceTracker()
    return _performance_tracker
