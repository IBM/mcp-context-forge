# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/metrics_query_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Metrics Query Service for combined raw + rollup queries.
This service provides unified metrics queries that combine recent raw metrics
with historical hourly rollups for complete historical coverage.
"""

# Standard
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Type

# Third-Party
from sqlalchemy import and_, case, func, literal, select, union_all
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import (
    A2AAgentMetric,
    A2AAgentMetricsDaily,
    A2AAgentMetricsHourly,
    PromptMetric,
    PromptMetricsDaily,
    PromptMetricsHourly,
    ResourceMetric,
    ResourceMetricsDaily,
    ResourceMetricsHourly,
    ServerMetric,
    ServerMetricsDaily,
    ServerMetricsHourly,
    ToolMetric,
    ToolMetricsDaily,
    ToolMetricsHourly,
)

logger = logging.getLogger(__name__)


@dataclass
class AggregatedMetrics:
    """Aggregated metrics result combining raw and rollup data."""

    total_executions: int
    successful_executions: int
    failed_executions: int
    failure_rate: float
    min_response_time: Optional[float]
    max_response_time: Optional[float]
    avg_response_time: Optional[float]
    last_execution_time: Optional[datetime]
    # Source breakdown for debugging
    raw_count: int = 0
    rollup_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for API response.

        Returns:
            Dict[str, Any]: Dictionary representation of the metrics.
        """
        return {
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "failure_rate": self.failure_rate,
            "min_response_time": self.min_response_time,
            "max_response_time": self.max_response_time,
            "avg_response_time": self.avg_response_time,
            "last_execution_time": self.last_execution_time,
        }


@dataclass
class TopPerformerResult:
    """Result object for top performer queries, compatible with build_top_performers."""

    id: str
    name: str
    execution_count: int
    avg_response_time: Optional[float]
    success_rate: Optional[float]
    last_execution: Optional[datetime]


# Mapping of metric types to their raw and hourly models
# Format: (RawModel, HourlyModel, entity_id_column, preserved_name_column)
METRIC_MODELS = {
    "tool": (ToolMetric, ToolMetricsHourly, "tool_id", "tool_name"),
    "resource": (ResourceMetric, ResourceMetricsHourly, "resource_id", "resource_name"),
    "prompt": (PromptMetric, PromptMetricsHourly, "prompt_id", "prompt_name"),
    "server": (ServerMetric, ServerMetricsHourly, "server_id", "server_name"),
    "a2a_agent": (A2AAgentMetric, A2AAgentMetricsHourly, "a2a_agent_id", "agent_name"),
}

# Mapping of metric types to their daily rollup models
# Format: (DailyModel, entity_id_column, preserved_name_column)
DAILY_MODELS = {
    "tool": (ToolMetricsDaily, "tool_id", "tool_name"),
    "resource": (ResourceMetricsDaily, "resource_id", "resource_name"),
    "prompt": (PromptMetricsDaily, "prompt_id", "prompt_name"),
    "server": (ServerMetricsDaily, "server_id", "server_name"),
    "a2a_agent": (A2AAgentMetricsDaily, "a2a_agent_id", "agent_name"),
}


def get_current_hour_start() -> datetime:
    """Get the start of the current hour (UTC).

    Returns:
        datetime: Start of current hour, aligned to hour boundary.
    """
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def _merge_min(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Merge two optional minimum values, returning the smaller one.

    Args:
        a: First optional float value.
        b: Second optional float value.

    Returns:
        The smaller of the two values, or the non-None value if one is None.
    """
    if a is not None and b is not None:
        return min(a, b)
    return a if a is not None else b


def _merge_max(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Merge two optional maximum values, returning the larger one.

    Args:
        a: First optional float value.
        b: Second optional float value.

    Returns:
        The larger of the two values, or the non-None value if one is None.
    """
    if a is not None and b is not None:
        return max(a, b)
    return a if a is not None else b


def _merge_weighted_avg(avg1: Optional[float], count1: int, avg2: Optional[float], count2: int) -> Optional[float]:
    """Merge two weighted averages.

    Args:
        avg1: First average value (or None).
        count1: Count for first average.
        avg2: Second average value (or None).
        count2: Count for second average.

    Returns:
        Weighted average of the two, or None if both are None.
    """
    total = count1 + count2
    if total == 0:
        return None
    if count1 > 0 and count2 > 0 and avg1 is not None and avg2 is not None:
        return (avg1 * count1 + avg2 * count2) / total
    if avg1 is not None and count1 > 0:
        return avg1
    if avg2 is not None and count2 > 0:
        return avg2
    return None


def _merge_last_time(a: Optional[datetime], b: Optional[datetime]) -> Optional[datetime]:
    """Merge two optional timestamps, returning the most recent one.

    Args:
        a: First optional datetime value.
        b: Second optional datetime value.

    Returns:
        The more recent of the two timestamps, or the non-None value if one is None.
    """
    if a is not None and b is not None:
        return max(a, b)
    return a if a is not None else b


def get_retention_cutoff() -> datetime:
    """Get the cutoff datetime for raw metrics retention, aligned to hour boundary.

    This considers both the configured retention period AND the delete_raw_after_rollup
    setting to ensure we query rollups for any period where raw data may have been deleted.

    The cutoff is aligned to the start of the hour to prevent double-counting:
    - Raw data uses: timestamp >= cutoff (data from cutoff hour onward)
    - Rollups use: hour_start < cutoff (rollups before cutoff hour)

    Returns:
        datetime: The cutoff point (hour-aligned) - data older than this comes from rollups.
    """
    retention_days = getattr(settings, "metrics_retention_days", 7)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)

    # If raw data is deleted after rollup, use the more recent cutoff
    # to ensure rollups cover any deleted raw data
    delete_raw_enabled = getattr(settings, "metrics_delete_raw_after_rollup", False)
    if delete_raw_enabled:
        delete_raw_hours = getattr(settings, "metrics_delete_raw_after_rollup_hours", 1)
        delete_cutoff = now - timedelta(hours=delete_raw_hours)
        cutoff = max(cutoff, delete_cutoff)

    # Align to hour boundary (round down) to prevent double-counting at the boundary
    # Raw query uses >= cutoff, rollup query uses < cutoff, so no overlap
    return cutoff.replace(minute=0, second=0, microsecond=0)


def get_daily_retention_cutoff() -> datetime:
    """Get the cutoff datetime for daily rollup usage, aligned to day boundary.

    Data older than this cutoff is read from the daily rollup tables; more recent
    data is read from hourly rollups (and raw for the latest hours). The cutoff is
    day-aligned (UTC midnight) so the daily/hourly partition has no overlap and
    no gap, as long as the daily rollup pass keeps every completed day populated.

    Returns:
        datetime: The cutoff (day-aligned) - daily rollups use day_start < cutoff.
    """
    cutoff_days = getattr(settings, "metrics_daily_rollup_cutoff_days", 90)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=cutoff_days)
    return cutoff.replace(hour=0, minute=0, second=0, microsecond=0)


def get_current_hour_aggregation(
    db: Session,
    metric_type: str,
    entity_id: Optional[str] = None,
) -> Optional[AggregatedMetrics]:
    """Aggregate raw metrics for the current incomplete hour only.

    This function queries raw metrics from the start of the current hour
    to now, providing real-time visibility into metrics that haven't been
    rolled up yet.

    Args:
        db: Database session.
        metric_type: Type of metric ('tool', 'resource', 'prompt', 'server', 'a2a_agent').
        entity_id: Optional entity ID to filter by.

    Returns:
        AggregatedMetrics for the current hour, or None if no data exists.

    Raises:
        ValueError: If metric_type is not recognized.
    """
    if metric_type not in METRIC_MODELS:
        raise ValueError(f"Unknown metric type: {metric_type}")

    raw_model, _, id_col, _ = METRIC_MODELS[metric_type]
    current_hour_start = get_current_hour_start()

    # Query current hour raw metrics
    filters = [raw_model.timestamp >= current_hour_start]
    if entity_id is not None:
        filters.append(getattr(raw_model, id_col) == entity_id)

    # pylint: disable=not-callable
    result = db.execute(
        select(
            func.count(raw_model.id).label("total"),
            func.sum(case((raw_model.is_success.is_(True), 1), else_=0)).label("successful"),
            func.sum(case((raw_model.is_success.is_(False), 1), else_=0)).label("failed"),
            func.min(raw_model.response_time).label("min_rt"),
            func.max(raw_model.response_time).label("max_rt"),
            func.avg(raw_model.response_time).label("avg_rt"),
            func.max(raw_model.timestamp).label("last_time"),
        ).where(and_(*filters))
    ).one()

    total = result.total or 0
    if total == 0:
        return None

    successful = result.successful or 0
    failed = result.failed or 0

    return AggregatedMetrics(
        total_executions=total,
        successful_executions=successful,
        failed_executions=failed,
        failure_rate=failed / total if total > 0 else 0.0,
        min_response_time=result.min_rt,
        max_response_time=result.max_rt,
        avg_response_time=result.avg_rt,
        last_execution_time=result.last_time,
        raw_count=total,
        rollup_count=0,
    )


def aggregate_metrics_combined(
    db: Session,
    metric_type: str,
    entity_id: Optional[str] = None,
) -> AggregatedMetrics:
    """Aggregate metrics combining four data sources for complete coverage.

    This function queries:
    1. Daily rollup table (for data older than the daily cutoff) - when enabled
    2. Hourly rollup table (for the mid-term range)
    3. Raw metrics table (for completed hours within retention period)
    4. Current hour raw metrics (for the incomplete current hour)

    Partition (no overlap, no gap) when daily rollups are enabled:
    - daily: day_start < daily_cutoff
    - hourly: daily_cutoff <= hour_start < retention_cutoff
    - raw completed hours: retention_cutoff <= timestamp < current_hour_start
    - current hour: timestamp >= current_hour_start

    When daily rollups are disabled, falls back to the three-source behaviour.

    Args:
        db: Database session
        metric_type: Type of metric ('tool', 'resource', 'prompt', 'server', 'a2a_agent')
        entity_id: Optional entity ID to filter by (e.g., specific tool_id)

    Returns:
        AggregatedMetrics: Combined metrics from all sources

    Raises:
        ValueError: If metric_type is not recognized.
    """
    if metric_type not in METRIC_MODELS:
        raise ValueError(f"Unknown metric type: {metric_type}")

    raw_model, hourly_model, id_col, _ = METRIC_MODELS[metric_type]
    cutoff = get_retention_cutoff()
    current_hour_start = get_current_hour_start()

    daily_enabled = getattr(settings, "metrics_daily_rollup_enabled", True)
    daily_models = DAILY_MODELS.get(metric_type)
    use_daily = daily_enabled and daily_models is not None
    daily_cutoff = get_daily_retention_cutoff() if use_daily else None

    daily_total = daily_successful = daily_failed = 0
    daily_min_rt = daily_max_rt = daily_avg_rt = daily_last_time = None

    if use_daily:
        daily_model, _, _ = daily_models
        daily_filters = [daily_model.day_start < daily_cutoff]
        if entity_id is not None:
            daily_filters.append(getattr(daily_model, id_col) == entity_id)

        # pylint: disable=not-callable
        daily_result = db.execute(
            select(
                func.sum(daily_model.total_count).label("total"),
                func.sum(daily_model.success_count).label("successful"),
                func.sum(daily_model.failure_count).label("failed"),
                func.min(daily_model.min_response_time).label("min_rt"),
                func.max(daily_model.max_response_time).label("max_rt"),
                (func.sum(daily_model.avg_response_time * daily_model.total_count) / func.nullif(func.sum(daily_model.total_count), 0)).label("avg_rt"),
                func.max(daily_model.day_start).label("last_time"),
            ).where(and_(*daily_filters))
        ).one()

        daily_total = daily_result.total or 0
        daily_successful = daily_result.successful or 0
        daily_failed = daily_result.failed or 0
        daily_min_rt = daily_result.min_rt
        daily_max_rt = daily_result.max_rt
        daily_avg_rt = daily_result.avg_rt
        daily_last_time = daily_result.last_time

    # Query: Hourly rollup data for the mid-term range.
    # When daily rollups are enabled, hourly covers [daily_cutoff, cutoff) only,
    # so older data is read from the daily tables instead of scanning months of
    # hourly rows. When disabled, hourly covers everything older than cutoff.
    rollup_filters = [hourly_model.hour_start < cutoff]
    if daily_cutoff is not None:
        rollup_filters.append(hourly_model.hour_start >= daily_cutoff)
    if entity_id is not None:
        rollup_filters.append(getattr(hourly_model, id_col) == entity_id)

    # pylint: disable=not-callable
    rollup_result = db.execute(
        select(
            func.sum(hourly_model.total_count).label("total"),
            func.sum(hourly_model.success_count).label("successful"),
            func.sum(hourly_model.failure_count).label("failed"),
            func.min(hourly_model.min_response_time).label("min_rt"),
            func.max(hourly_model.max_response_time).label("max_rt"),
            # Weighted average: sum(avg * count) / sum(count)
            (func.sum(hourly_model.avg_response_time * hourly_model.total_count) / func.nullif(func.sum(hourly_model.total_count), 0)).label("avg_rt"),
            func.max(hourly_model.hour_start).label("last_time"),
        ).where(and_(*rollup_filters))
    ).one()

    rollup_total = rollup_result.total or 0
    rollup_successful = rollup_result.successful or 0
    rollup_failed = rollup_result.failed or 0
    rollup_min_rt = rollup_result.min_rt
    rollup_max_rt = rollup_result.max_rt
    rollup_avg_rt = rollup_result.avg_rt
    rollup_last_time = rollup_result.last_time

    # Query 2: Raw metrics for completed hours (cutoff <= timestamp < current_hour_start)
    # This covers the gap between rollup data and the current incomplete hour
    raw_filters = [
        raw_model.timestamp >= cutoff,
        raw_model.timestamp < current_hour_start,
    ]
    if entity_id is not None:
        raw_filters.append(getattr(raw_model, id_col) == entity_id)

    raw_result = db.execute(
        select(
            func.count(raw_model.id).label("total"),
            func.sum(case((raw_model.is_success.is_(True), 1), else_=0)).label("successful"),
            func.sum(case((raw_model.is_success.is_(False), 1), else_=0)).label("failed"),
            func.min(raw_model.response_time).label("min_rt"),
            func.max(raw_model.response_time).label("max_rt"),
            func.avg(raw_model.response_time).label("avg_rt"),
            func.max(raw_model.timestamp).label("last_time"),
        ).where(and_(*raw_filters))
    ).one()

    raw_total = raw_result.total or 0
    raw_successful = raw_result.successful or 0
    raw_failed = raw_result.failed or 0
    raw_min_rt = raw_result.min_rt
    raw_max_rt = raw_result.max_rt
    raw_avg_rt = raw_result.avg_rt
    raw_last_time = raw_result.last_time

    # Query 3: Current hour raw metrics (timestamp >= current_hour_start)
    # This provides immediate visibility into metrics that haven't been rolled up yet
    current_filters = [raw_model.timestamp >= current_hour_start]
    if entity_id is not None:
        current_filters.append(getattr(raw_model, id_col) == entity_id)

    current_result = db.execute(
        select(
            func.count(raw_model.id).label("total"),
            func.sum(case((raw_model.is_success.is_(True), 1), else_=0)).label("successful"),
            func.sum(case((raw_model.is_success.is_(False), 1), else_=0)).label("failed"),
            func.min(raw_model.response_time).label("min_rt"),
            func.max(raw_model.response_time).label("max_rt"),
            func.avg(raw_model.response_time).label("avg_rt"),
            func.max(raw_model.timestamp).label("last_time"),
        ).where(and_(*current_filters))
    ).one()

    current_total = current_result.total or 0
    current_successful = current_result.successful or 0
    current_failed = current_result.failed or 0
    current_min_rt = current_result.min_rt
    current_max_rt = current_result.max_rt
    current_avg_rt = current_result.avg_rt
    current_last_time = current_result.last_time

    # Merge all sources
    total = daily_total + rollup_total + raw_total + current_total
    successful = daily_successful + rollup_successful + raw_successful + current_successful
    failed = daily_failed + rollup_failed + raw_failed + current_failed
    failure_rate = failed / total if total > 0 else 0.0

    # Min/max across all sources
    min_rt = _merge_min(_merge_min(_merge_min(daily_min_rt, rollup_min_rt), raw_min_rt), current_min_rt)
    max_rt = _merge_max(_merge_max(_merge_max(daily_max_rt, rollup_max_rt), raw_max_rt), current_max_rt)

    # Weighted average across all sources
    daily_rollup_avg = _merge_weighted_avg(daily_avg_rt, daily_total, rollup_avg_rt, rollup_total)
    daily_rollup_total = daily_total + rollup_total
    mid_avg = _merge_weighted_avg(daily_rollup_avg, daily_rollup_total, raw_avg_rt, raw_total)
    avg_rt = _merge_weighted_avg(mid_avg, daily_rollup_total + raw_total, current_avg_rt, current_total)

    # Last execution time (most recent from any source)
    last_time = _merge_last_time(
        _merge_last_time(_merge_last_time(daily_last_time, rollup_last_time), raw_last_time),
        current_last_time,
    )

    return AggregatedMetrics(
        total_executions=total,
        successful_executions=successful,
        failed_executions=failed,
        failure_rate=failure_rate,
        min_response_time=min_rt,
        max_response_time=max_rt,
        avg_response_time=avg_rt,
        last_execution_time=last_time,
        raw_count=raw_total + current_total,
        rollup_count=daily_total + rollup_total,
    )


def get_top_entities_combined(
    db: Session,
    metric_type: str,
    entity_model: Type,
    limit: int = 10,
    order_by: str = "execution_count",
    name_column: str = "name",
    include_deleted: bool = False,
) -> List[Dict[str, Any]]:
    """Get top entities by metric counts, combining four data sources.

    This function queries:
    1. Daily rollup table (for data older than the daily cutoff) - when enabled
    2. Hourly rollup table (for the mid-term range)
    3. Raw metrics table (for completed hours within retention period)
    4. Current hour raw metrics (for the incomplete current hour)

    When daily rollups are disabled, falls back to the three-source behaviour.

    Args:
        db: Database session
        metric_type: Type of metric ('tool', 'resource', 'prompt', 'server', 'a2a_agent')
        entity_model: SQLAlchemy model for the entity (Tool, Resource, etc.)
        limit: Maximum number of results
        order_by: Field to order by ('execution_count', 'avg_response_time', 'failure_rate')
        name_column: Name of the column to use as entity name (default: 'name')
        include_deleted: Whether to include deleted entities from rollups

    Returns:
        List of entity metrics dictionaries

    Raises:
        ValueError: If metric_type is not recognized.
    """
    if metric_type not in METRIC_MODELS:
        raise ValueError(f"Unknown metric type: {metric_type}")

    raw_model, hourly_model, id_col, preserved_name_col = METRIC_MODELS[metric_type]
    cutoff = get_retention_cutoff()
    current_hour_start = get_current_hour_start()

    daily_enabled = getattr(settings, "metrics_daily_rollup_enabled", True)
    daily_models = DAILY_MODELS.get(metric_type)
    use_daily = daily_enabled and daily_models is not None
    daily_cutoff = get_daily_retention_cutoff() if use_daily else None
    daily_model = daily_models[0] if use_daily else None

    # Get all entity IDs with their combined metrics from four sources
    # This query includes both existing entities and deleted entities (via rollup name preservation)

    # Subquery 0: Daily rollup metrics aggregated by entity (data older than daily cutoff)
    # Daily tables carry the same preserved_name, so deleted entities stay distinct
    # exactly as they do on the hourly side.
    # pylint: disable=not-callable
    daily_subq = None
    if use_daily:
        daily_subq = (
            select(
                getattr(daily_model, id_col).label("entity_id"),
                getattr(daily_model, preserved_name_col).label("preserved_name"),
                func.sum(daily_model.total_count).label("total"),
                func.sum(daily_model.success_count).label("successful"),
                func.sum(daily_model.failure_count).label("failed"),
                (func.sum(daily_model.avg_response_time * daily_model.total_count) / func.nullif(func.sum(daily_model.total_count), 0)).label("avg_rt"),
                func.max(daily_model.day_start).label("last_time"),
            )
            .where(daily_model.day_start < daily_cutoff)
            .group_by(getattr(daily_model, id_col), getattr(daily_model, preserved_name_col))
            .subquery()
        )

    # Subquery 1: Hourly rollup metrics aggregated by entity (mid-term range)
    # When daily rollups are enabled, hourly covers [daily_cutoff, cutoff) only.
    # Group by BOTH entity_id AND preserved_name to keep deleted entities separate
    # (when entity is deleted, entity_id becomes NULL, but preserved_name keeps them distinct)
    rollup_filters = [hourly_model.hour_start < cutoff]
    if daily_cutoff is not None:
        rollup_filters.append(hourly_model.hour_start >= daily_cutoff)
    rollup_subq = (
        select(
            getattr(hourly_model, id_col).label("entity_id"),
            getattr(hourly_model, preserved_name_col).label("preserved_name"),
            func.sum(hourly_model.total_count).label("total"),
            func.sum(hourly_model.success_count).label("successful"),
            func.sum(hourly_model.failure_count).label("failed"),
            # Weighted average for rollups: sum(avg * count) / sum(count)
            (func.sum(hourly_model.avg_response_time * hourly_model.total_count) / func.nullif(func.sum(hourly_model.total_count), 0)).label("avg_rt"),
            func.max(hourly_model.hour_start).label("last_time"),
        )
        .where(and_(*rollup_filters))
        .group_by(getattr(hourly_model, id_col), getattr(hourly_model, preserved_name_col))
        .subquery()
    )

    # Subquery 2: Raw metrics for completed hours (cutoff <= timestamp < current_hour_start)
    raw_subq = (
        select(
            getattr(raw_model, id_col).label("entity_id"),
            func.count(raw_model.id).label("total"),
            func.sum(case((raw_model.is_success.is_(True), 1), else_=0)).label("successful"),
            func.sum(case((raw_model.is_success.is_(False), 1), else_=0)).label("failed"),
            func.avg(raw_model.response_time).label("avg_rt"),
            func.max(raw_model.timestamp).label("last_time"),
        )
        .where(and_(raw_model.timestamp >= cutoff, raw_model.timestamp < current_hour_start))
        .group_by(getattr(raw_model, id_col))
        .subquery()
    )

    # Subquery 3: Current hour raw metrics (timestamp >= current_hour_start)
    current_subq = (
        select(
            getattr(raw_model, id_col).label("entity_id"),
            func.count(raw_model.id).label("total"),
            func.sum(case((raw_model.is_success.is_(True), 1), else_=0)).label("successful"),
            func.sum(case((raw_model.is_success.is_(False), 1), else_=0)).label("failed"),
            func.avg(raw_model.response_time).label("avg_rt"),
            func.max(raw_model.timestamp).label("last_time"),
        )
        .where(raw_model.timestamp >= current_hour_start)
        .group_by(getattr(raw_model, id_col))
        .subquery()
    )

    # Get the name column from entity model
    entity_name_col = getattr(entity_model, name_column)

    # Compute combined totals from all sources (daily optional)
    daily_total_expr = func.coalesce(daily_subq.c.total, 0) if daily_subq is not None else literal(0)
    daily_successful_expr = func.coalesce(daily_subq.c.successful, 0) if daily_subq is not None else literal(0)
    daily_failed_expr = func.coalesce(daily_subq.c.failed, 0) if daily_subq is not None else literal(0)

    total_count_expr = daily_total_expr + func.coalesce(rollup_subq.c.total, 0) + func.coalesce(raw_subq.c.total, 0) + func.coalesce(current_subq.c.total, 0)
    successful_expr = daily_successful_expr + func.coalesce(rollup_subq.c.successful, 0) + func.coalesce(raw_subq.c.successful, 0) + func.coalesce(current_subq.c.successful, 0)
    failed_expr = daily_failed_expr + func.coalesce(rollup_subq.c.failed, 0) + func.coalesce(raw_subq.c.failed, 0) + func.coalesce(current_subq.c.failed, 0)

    # Weighted average across all sources
    # Formula: sum(avg_i * count_i) / sum(count_i)
    daily_avg_term = func.coalesce(daily_subq.c.avg_rt * func.coalesce(daily_subq.c.total, 0), 0) if daily_subq is not None else literal(0)
    weighted_avg_expr = (
        daily_avg_term
        + func.coalesce(rollup_subq.c.avg_rt * func.coalesce(rollup_subq.c.total, 0), 0)
        + func.coalesce(raw_subq.c.avg_rt * func.coalesce(raw_subq.c.total, 0), 0)
        + func.coalesce(current_subq.c.avg_rt * func.coalesce(current_subq.c.total, 0), 0)
    ) / func.nullif(total_count_expr, 0)

    # Last execution time (most recent from any source) using GREATEST-like logic
    # SQLAlchemy doesn't have a portable GREATEST, so we use COALESCE with preference order
    # pylint: disable-next=assignment-from-no-return
    daily_last_term = daily_subq.c.last_time if daily_subq is not None else None
    if daily_last_term is not None:
        last_time_expr = func.coalesce(current_subq.c.last_time, raw_subq.c.last_time, rollup_subq.c.last_time, daily_last_term)
    else:
        last_time_expr = func.coalesce(current_subq.c.last_time, raw_subq.c.last_time, rollup_subq.c.last_time)

    # Query: Existing entities with combined metrics from all sources
    existing_entities_query = (
        select(
            entity_model.id.label("id"),
            func.coalesce(entity_name_col, rollup_subq.c.preserved_name).label("name"),
            total_count_expr.label("execution_count"),
            successful_expr.label("successful"),
            failed_expr.label("failed"),
            weighted_avg_expr.label("avg_response_time"),
            last_time_expr.label("last_execution"),
            literal(False).label("is_deleted"),
        )
        .outerjoin(rollup_subq, entity_model.id == rollup_subq.c.entity_id)
        .outerjoin(raw_subq, entity_model.id == raw_subq.c.entity_id)
        .outerjoin(current_subq, entity_model.id == current_subq.c.entity_id)
        .where(
            # Only include entities that have metrics in any source
            (rollup_subq.c.total.isnot(None)) | (raw_subq.c.total.isnot(None)) | (current_subq.c.total.isnot(None))
            | ((daily_subq.c.total.isnot(None)) if daily_subq is not None else False)
        )
    )

    if use_daily and daily_subq is not None:
        existing_entities_query = existing_entities_query.outerjoin(daily_subq, entity_model.id == daily_subq.c.entity_id)

    if include_deleted:
        # Query for deleted entities (exist in rollup/daily but not in entity table).
        # rollup_subq and daily_subq share the same column shape (entity_id, preserved_name,
        # total, successful, failed, avg_rt, last_time). Union them and re-aggregate
        # by (entity_id, preserved_name). This avoids a cross join between the two sources and
        # keeps deleted entities with NULL entity_id (SET NULL on delete) distinct via name.
        deleted_source = rollup_subq
        if daily_subq is not None:
            _cols = ("entity_id", "preserved_name", "total", "successful", "failed", "avg_rt", "last_time")
            deleted_source = union_all(
                select(*[getattr(rollup_subq.c, c).label(c) for c in _cols]),
                select(*[getattr(daily_subq.c, c).label(c) for c in _cols]),
            ).subquery()

        existing_ids_select = select(entity_model.id)
        deleted_entities_query = (
            select(
                deleted_source.c.entity_id.label("id"),
                deleted_source.c.preserved_name.label("name"),
                func.sum(deleted_source.c.total).label("execution_count"),
                func.sum(deleted_source.c.successful).label("successful"),
                func.sum(deleted_source.c.failed).label("failed"),
                (func.sum(deleted_source.c.avg_rt * func.coalesce(deleted_source.c.total, 0)) / func.nullif(func.sum(deleted_source.c.total), 0)).label("avg_response_time"),
                func.max(deleted_source.c.last_time).label("last_execution"),
                literal(True).label("is_deleted"),
            )
            .where(
                # Include entities with NULL id (deleted via SET NULL) OR entities not in entity table
                (deleted_source.c.entity_id.is_(None))
                | (deleted_source.c.entity_id.notin_(existing_ids_select))
            )
            .group_by(deleted_source.c.entity_id, deleted_source.c.preserved_name)
        )

        # Combine existing and deleted entities
        combined_query = union_all(existing_entities_query, deleted_entities_query).subquery()
    else:
        combined_query = existing_entities_query.subquery()

    # Apply ordering and limit to the combined results
    if order_by == "avg_response_time":
        final_query = select(combined_query).order_by(combined_query.c.avg_response_time.desc().nullslast())
    elif order_by == "failure_rate":
        # Order by failure rate (failed / total)
        final_query = select(combined_query).order_by((combined_query.c.failed * 1.0 / func.nullif(combined_query.c.execution_count, 0)).desc().nullslast())
    else:  # default: execution_count
        final_query = select(combined_query).order_by(combined_query.c.execution_count.desc())

    final_query = final_query.limit(limit)

    results = []
    for row in db.execute(final_query).fetchall():
        total = row.execution_count or 0
        successful = row.successful or 0
        failed = row.failed or 0
        success_rate = (successful / total * 100) if total > 0 else None
        result_dict = {
            "id": row.id,
            "name": row.name,
            "execution_count": total,
            "successful_executions": successful,
            "failed_executions": failed,
            "failure_rate": failed / total if total > 0 else 0.0,
            "success_rate": success_rate,
            "avg_response_time": row.avg_response_time,
            "last_execution": row.last_execution,
        }
        # Mark deleted entities so UI can optionally style them differently
        if row.is_deleted:
            result_dict["is_deleted"] = True
        results.append(result_dict)

    return results


def get_top_performers_combined(
    db: Session,
    metric_type: str,
    entity_model: Type,
    limit: int = 10,
    name_column: str = "name",
    include_deleted: bool = False,
) -> List[TopPerformerResult]:
    """Get top performers combining raw and rollup data.

    This function wraps get_top_entities_combined and returns TopPerformerResult
    objects that are compatible with build_top_performers().

    Args:
        db: Database session
        metric_type: Type of metric ('tool', 'resource', 'prompt', 'server', 'a2a_agent')
        entity_model: SQLAlchemy model for the entity (Tool, Resource, etc.)
        limit: Maximum number of results
        name_column: Name of the column to use as entity name (default: 'name')
        include_deleted: Whether to include deleted entities from rollups

    Returns:
        List[TopPerformerResult]: List of top performer results
    """
    raw_results = get_top_entities_combined(
        db=db,
        metric_type=metric_type,
        entity_model=entity_model,
        limit=limit,
        order_by="execution_count",
        name_column=name_column,
        include_deleted=include_deleted,
    )

    return [
        TopPerformerResult(
            id=r["id"],
            name=r["name"],
            execution_count=r["execution_count"],
            avg_response_time=r["avg_response_time"],
            success_rate=r["success_rate"],
            last_execution=r["last_execution"],
        )
        for r in raw_results
    ]
