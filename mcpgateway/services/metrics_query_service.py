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
from sqlalchemy import and_, case, func, literal, select, union_all
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


def aggregate_metrics_combined(
    db: Session,
    metric_type: str,
    entity_id: Optional[str] = None,
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

    raw_model, hourly_model, id_col, _ = METRIC_MODELS[metric_type]
    cutoff = get_retention_cutoff()

    # Query 1: Recent raw metrics (within retention period)
    raw_filters = [raw_model.timestamp >= cutoff]
    if entity_id is not None:
        raw_filters.append(getattr(raw_model, id_col) == entity_id)

    # pylint: disable=not-callable
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

    # Compute weighted average: sum(avg * count) / sum(count)
    # This ensures each hour's average is weighted by how many executions occurred
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
    name_column: str = "name",
    include_deleted: bool = False,
) -> List[Dict[str, Any]]:
    """Get top entities by metric counts, combining raw and rollup data.

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

    # Get all entity IDs with their combined metrics
    # This query includes both existing entities and deleted entities (via rollup name preservation)

    # Subquery for raw metrics aggregated by entity
    # pylint: disable=not-callable
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

    # Subquery for rollup metrics aggregated by entity (includes preserved name for deleted entities)
    # Group by BOTH entity_id AND preserved_name to keep deleted entities separate
    # (when entity is deleted, entity_id becomes NULL, but preserved_name keeps them distinct)
    # Use weighted average: sum(avg * count) / sum(count)
    rollup_subq = (
        select(
            getattr(hourly_model, id_col).label("entity_id"),
            getattr(hourly_model, preserved_name_col).label("preserved_name"),
            func.sum(hourly_model.total_count).label("total"),
            func.sum(hourly_model.success_count).label("successful"),
            func.sum(hourly_model.failure_count).label("failed"),
            # Weighted average for rollups
            (func.sum(hourly_model.avg_response_time * hourly_model.total_count) / func.nullif(func.sum(hourly_model.total_count), 0)).label("avg_rt"),
            func.max(hourly_model.hour_start).label("last_time"),
        )
        .where(hourly_model.hour_start < cutoff)
        .group_by(getattr(hourly_model, id_col), getattr(hourly_model, preserved_name_col))
        .subquery()
    )

    # Get the name column from entity model
    entity_name_col = getattr(entity_model, name_column)

    # Query 1: Existing entities with combined metrics
    # Uses entity table name, falls back to rollup preserved name if entity has no name (shouldn't happen)
    existing_entities_query = (
        select(
            entity_model.id.label("id"),
            func.coalesce(entity_name_col, rollup_subq.c.preserved_name).label("name"),
            (func.coalesce(raw_subq.c.total, 0) + func.coalesce(rollup_subq.c.total, 0)).label("execution_count"),
            (func.coalesce(raw_subq.c.successful, 0) + func.coalesce(rollup_subq.c.successful, 0)).label("successful"),
            (func.coalesce(raw_subq.c.failed, 0) + func.coalesce(rollup_subq.c.failed, 0)).label("failed"),
            (
                (func.coalesce(raw_subq.c.avg_rt * func.coalesce(raw_subq.c.total, 0), 0) + func.coalesce(rollup_subq.c.avg_rt * func.coalesce(rollup_subq.c.total, 0), 0))
                / func.nullif(func.coalesce(raw_subq.c.total, 0) + func.coalesce(rollup_subq.c.total, 0), 0)
            ).label("avg_response_time"),
            func.coalesce(raw_subq.c.last_time, rollup_subq.c.last_time).label("last_execution"),
            literal(False).label("is_deleted"),
        )
        .outerjoin(raw_subq, entity_model.id == raw_subq.c.entity_id)
        .outerjoin(rollup_subq, entity_model.id == rollup_subq.c.entity_id)
        .where(
            # Only include entities that have metrics in either source
            (raw_subq.c.total.isnot(None))
            | (rollup_subq.c.total.isnot(None))
        )
    )

    if include_deleted:
        # Query 2: Deleted entities (exist in rollup but not in entity table)
        # Handle NULL properly: entity_id IS NULL (deleted via SET NULL) OR entity_id not in existing entities
        # Note: NOT IN with NULL never returns true, so we need explicit IS NULL check
        existing_ids_subq = select(entity_model.id).subquery()
        deleted_entities_query = select(
            rollup_subq.c.entity_id.label("id"),
            rollup_subq.c.preserved_name.label("name"),
            rollup_subq.c.total.label("execution_count"),
            rollup_subq.c.successful.label("successful"),
            rollup_subq.c.failed.label("failed"),
            rollup_subq.c.avg_rt.label("avg_response_time"),
            rollup_subq.c.last_time.label("last_execution"),
            literal(True).label("is_deleted"),
        ).where(
            # Include entities with NULL id (deleted via SET NULL) OR entities not in entity table
            (rollup_subq.c.entity_id.is_(None))
            | (rollup_subq.c.entity_id.notin_(existing_ids_subq))
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
