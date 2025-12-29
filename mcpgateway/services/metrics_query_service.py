# -*- coding: utf-8 -*-
"""Metrics Query Service for combined raw + rollup queries.

This service provides unified metrics queries that combine recent raw metrics
with historical hourly rollups for complete historical coverage.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Type

# Third-Party
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import (
    A2AAgentMetric,
    A2AAgentMetricsHourly,
    PromptMetric,
    PromptMetricsHourly,
    ResourceMetric,
    ResourceMetricsHourly,
    ServerMetric,
    ServerMetricsHourly,
    ToolMetric,
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


# Mapping of metric types to their raw and hourly models
METRIC_MODELS = {
    "tool": (ToolMetric, ToolMetricsHourly, "tool_id"),
    "resource": (ResourceMetric, ResourceMetricsHourly, "resource_id"),
    "prompt": (PromptMetric, PromptMetricsHourly, "prompt_id"),
    "server": (ServerMetric, ServerMetricsHourly, "server_id"),
    "a2a_agent": (A2AAgentMetric, A2AAgentMetricsHourly, "a2a_agent_id"),
}


def get_retention_cutoff() -> datetime:
    """Get the cutoff datetime for raw metrics retention.

    Returns:
        datetime: The cutoff point - data older than this should come from rollups.
    """
    retention_days = getattr(settings, "metrics_retention_days", 30)
    return datetime.now(timezone.utc) - timedelta(days=retention_days)


def aggregate_metrics_combined(
    db: Session,
    metric_type: str,
    entity_id: Optional[int] = None,
) -> AggregatedMetrics:
    """Aggregate metrics combining raw recent data with historical rollups.

    This function queries both the raw metrics table (for recent data within
    retention period) and the hourly rollup table (for older historical data),
    then merges the results for complete historical coverage.

    Args:
        db: Database session
        metric_type: Type of metric ('tool', 'resource', 'prompt', 'server', 'a2a_agent')
        entity_id: Optional entity ID to filter by (e.g., specific tool_id)

    Returns:
        AggregatedMetrics: Combined metrics from raw + rollup tables

    Raises:
        ValueError: If metric_type is not recognized.
    """
    if metric_type not in METRIC_MODELS:
        raise ValueError(f"Unknown metric type: {metric_type}")

    raw_model, hourly_model, id_col = METRIC_MODELS[metric_type]
    cutoff = get_retention_cutoff()

    # Query 1: Recent raw metrics (within retention period)
    raw_filters = [raw_model.timestamp >= cutoff]
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

    # Query 2: Historical rollup data (older than retention period)
    rollup_filters = [hourly_model.hour_start < cutoff]
    if entity_id is not None:
        rollup_filters.append(getattr(hourly_model, id_col) == entity_id)

    rollup_result = db.execute(
        select(
            func.sum(hourly_model.total_count).label("total"),
            func.sum(hourly_model.success_count).label("successful"),
            func.sum(hourly_model.failure_count).label("failed"),
            func.min(hourly_model.min_response_time).label("min_rt"),
            func.max(hourly_model.max_response_time).label("max_rt"),
            # For avg, we need weighted average: sum(avg * count) / sum(count)
            # Simplified: just use the overall average from rollups
            func.avg(hourly_model.avg_response_time).label("avg_rt"),
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

    # Merge results
    total = raw_total + rollup_total
    successful = raw_successful + rollup_successful
    failed = raw_failed + rollup_failed
    failure_rate = failed / total if total > 0 else 0.0

    # Min/max across both sources
    min_rt = None
    if raw_min_rt is not None and rollup_min_rt is not None:
        min_rt = min(raw_min_rt, rollup_min_rt)
    elif raw_min_rt is not None:
        min_rt = raw_min_rt
    elif rollup_min_rt is not None:
        min_rt = rollup_min_rt

    max_rt = None
    if raw_max_rt is not None and rollup_max_rt is not None:
        max_rt = max(raw_max_rt, rollup_max_rt)
    elif raw_max_rt is not None:
        max_rt = raw_max_rt
    elif rollup_max_rt is not None:
        max_rt = rollup_max_rt

    # Weighted average for avg_rt
    avg_rt = None
    if raw_total > 0 and rollup_total > 0 and raw_avg_rt is not None and rollup_avg_rt is not None:
        avg_rt = (raw_avg_rt * raw_total + rollup_avg_rt * rollup_total) / total
    elif raw_avg_rt is not None:
        avg_rt = raw_avg_rt
    elif rollup_avg_rt is not None:
        avg_rt = rollup_avg_rt

    # Last execution time (most recent)
    last_time = raw_last_time
    if last_time is None:
        last_time = rollup_last_time

    return AggregatedMetrics(
        total_executions=total,
        successful_executions=successful,
        failed_executions=failed,
        failure_rate=failure_rate,
        min_response_time=min_rt,
        max_response_time=max_rt,
        avg_response_time=avg_rt,
        last_execution_time=last_time,
        raw_count=raw_total,
        rollup_count=rollup_total,
    )


def get_top_entities_combined(
    db: Session,
    metric_type: str,
    entity_model: Type,
    limit: int = 10,
    order_by: str = "execution_count",
) -> List[Dict[str, Any]]:
    """Get top entities by metric counts, combining raw and rollup data.

    Args:
        db: Database session
        metric_type: Type of metric ('tool', 'resource', 'prompt', 'server', 'a2a_agent')
        entity_model: SQLAlchemy model for the entity (Tool, Resource, etc.)
        limit: Maximum number of results
        order_by: Field to order by ('execution_count', 'avg_response_time', 'failure_rate')

    Returns:
        List of entity metrics dictionaries

    Raises:
        ValueError: If metric_type is not recognized.
    """
    if metric_type not in METRIC_MODELS:
        raise ValueError(f"Unknown metric type: {metric_type}")

    raw_model, hourly_model, id_col = METRIC_MODELS[metric_type]
    cutoff = get_retention_cutoff()

    # Get all entity IDs with their combined metrics
    # This is a more complex query that unions raw + rollup data

    # Subquery for raw metrics aggregated by entity
    raw_subq = (
        select(
            getattr(raw_model, id_col).label("entity_id"),
            func.count(raw_model.id).label("total"),
            func.sum(case((raw_model.is_success.is_(True), 1), else_=0)).label("successful"),
            func.sum(case((raw_model.is_success.is_(False), 1), else_=0)).label("failed"),
            func.avg(raw_model.response_time).label("avg_rt"),
            func.max(raw_model.timestamp).label("last_time"),
        )
        .where(raw_model.timestamp >= cutoff)
        .group_by(getattr(raw_model, id_col))
        .subquery()
    )

    # Subquery for rollup metrics aggregated by entity
    rollup_subq = (
        select(
            getattr(hourly_model, id_col).label("entity_id"),
            func.sum(hourly_model.total_count).label("total"),
            func.sum(hourly_model.success_count).label("successful"),
            func.sum(hourly_model.failure_count).label("failed"),
            func.avg(hourly_model.avg_response_time).label("avg_rt"),
            func.max(hourly_model.hour_start).label("last_time"),
        )
        .where(hourly_model.hour_start < cutoff)
        .group_by(getattr(hourly_model, id_col))
        .subquery()
    )

    # Join entity with both subqueries and combine
    # Using COALESCE to handle cases where only one source has data
    query = (
        select(
            entity_model.id,
            entity_model.name,
            (func.coalesce(raw_subq.c.total, 0) + func.coalesce(rollup_subq.c.total, 0)).label("execution_count"),
            (func.coalesce(raw_subq.c.successful, 0) + func.coalesce(rollup_subq.c.successful, 0)).label("successful"),
            (func.coalesce(raw_subq.c.failed, 0) + func.coalesce(rollup_subq.c.failed, 0)).label("failed"),
            func.coalesce(raw_subq.c.avg_rt, rollup_subq.c.avg_rt).label("avg_response_time"),
            func.coalesce(raw_subq.c.last_time, rollup_subq.c.last_time).label("last_execution"),
        )
        .outerjoin(raw_subq, entity_model.id == raw_subq.c.entity_id)
        .outerjoin(rollup_subq, entity_model.id == rollup_subq.c.entity_id)
        .where(
            # Only include entities that have metrics in either source
            (raw_subq.c.total.isnot(None))
            | (rollup_subq.c.total.isnot(None))
        )
    )

    # Order by the specified field
    if order_by == "avg_response_time":
        query = query.order_by(func.coalesce(raw_subq.c.avg_rt, rollup_subq.c.avg_rt).desc())
    elif order_by == "failure_rate":
        # Order by failure rate (failed / total)
        total_expr = func.coalesce(raw_subq.c.total, 0) + func.coalesce(rollup_subq.c.total, 0)
        failed_expr = func.coalesce(raw_subq.c.failed, 0) + func.coalesce(rollup_subq.c.failed, 0)
        query = query.order_by((failed_expr * 1.0 / func.nullif(total_expr, 0)).desc().nullslast())
    else:  # default: execution_count
        query = query.order_by((func.coalesce(raw_subq.c.total, 0) + func.coalesce(rollup_subq.c.total, 0)).desc())

    query = query.limit(limit)

    results = []
    for row in db.execute(query).fetchall():
        total = row.execution_count or 0
        failed = row.failed or 0
        results.append(
            {
                "id": row.id,
                "name": row.name,
                "execution_count": total,
                "successful_executions": row.successful or 0,
                "failed_executions": failed,
                "failure_rate": failed / total if total > 0 else 0.0,
                "avg_response_time": row.avg_response_time,
                "last_execution": row.last_execution,
            }
        )

    return results
