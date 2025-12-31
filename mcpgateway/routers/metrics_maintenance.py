# -*- coding: utf-8 -*-
"""Metrics Maintenance Router.

This router provides admin endpoints for metrics cleanup and rollup operations.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import logging
from typing import Dict, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.verify_credentials import require_admin_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/metrics",
    tags=["Metrics Maintenance"],
    dependencies=[Depends(require_admin_auth)],
)


class CleanupRequest(BaseModel):
    """Request model for manual cleanup."""

    retention_days: Optional[int] = Field(None, ge=0, le=365, description="Override retention period in days (0 = delete all)")
    include_rollup: bool = Field(True, description="Also clean up old rollup data")
    table_type: Optional[str] = Field(None, description="Clean specific table: tool, resource, prompt, server, a2a_agent")


class RollupRequest(BaseModel):
    """Request model for manual rollup."""

    hours_back: int = Field(24, ge=1, le=8760, description="How many hours back to process (max 365 days)")
    force_reprocess: bool = Field(
        False,
        description="Deprecated: rollup now always re-aggregates hours with raw data to include late-arriving metrics. This parameter is kept for API compatibility but has no effect.",
    )


class CleanupResultResponse(BaseModel):
    """Response model for cleanup result."""

    table_name: str
    deleted_count: int
    remaining_count: int
    cutoff_date: str
    duration_seconds: float
    error: Optional[str] = None


class CleanupSummaryResponse(BaseModel):
    """Response model for cleanup summary."""

    total_deleted: int
    tables: Dict[str, CleanupResultResponse]
    duration_seconds: float
    started_at: str
    completed_at: str


class RollupResultResponse(BaseModel):
    """Response model for rollup result."""

    table_name: str
    hours_processed: int
    records_aggregated: int
    rollups_created: int
    rollups_updated: int
    raw_deleted: int
    duration_seconds: float
    error: Optional[str] = None


class RollupSummaryResponse(BaseModel):
    """Response model for rollup summary."""

    total_hours_processed: int
    total_records_aggregated: int
    total_rollups_created: int
    total_rollups_updated: int
    tables: Dict[str, RollupResultResponse]
    duration_seconds: float
    started_at: str
    completed_at: str


class MetricsStatsResponse(BaseModel):
    """Response model for metrics stats."""

    cleanup: Dict
    rollup: Dict
    table_sizes: Dict[str, int]


@router.post("/cleanup", response_model=CleanupSummaryResponse)
async def trigger_cleanup(request: CleanupRequest = CleanupRequest()):
    """Trigger manual cleanup of old metrics data.

    This endpoint allows administrators to manually trigger cleanup of old
    metrics data. By default, it uses the configured retention period, but
    this can be overridden.

    Args:
        request: Cleanup request parameters

    Returns:
        CleanupSummaryResponse: Summary of the cleanup operation

    Raises:
        HTTPException: If metrics cleanup is disabled (400).
    """
    if not settings.metrics_cleanup_enabled:
        raise HTTPException(status_code=400, detail="Metrics cleanup is disabled")

    # First-Party
    from mcpgateway.services.metrics_cleanup_service import get_metrics_cleanup_service

    service = get_metrics_cleanup_service()

    if request.table_type:
        # Clean specific table
        # Standard
        from datetime import datetime, timezone

        started_at = datetime.now(timezone.utc)
        try:
            result = await service.cleanup_table(
                table_type=request.table_type,
                retention_days=request.retention_days,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        completed_at = datetime.now(timezone.utc)
        return CleanupSummaryResponse(
            total_deleted=result.deleted_count,
            tables={
                result.table_name: CleanupResultResponse(
                    table_name=result.table_name,
                    deleted_count=result.deleted_count,
                    remaining_count=result.remaining_count,
                    cutoff_date=result.cutoff_date.isoformat(),
                    duration_seconds=result.duration_seconds,
                    error=result.error,
                )
            },
            duration_seconds=result.duration_seconds,
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat(),
        )

    # Clean all tables
    summary = await service.cleanup_all(
        retention_days=request.retention_days,
        include_rollup=request.include_rollup,
    )

    return CleanupSummaryResponse(
        total_deleted=summary.total_deleted,
        tables={
            name: CleanupResultResponse(
                table_name=result.table_name,
                deleted_count=result.deleted_count,
                remaining_count=result.remaining_count,
                cutoff_date=result.cutoff_date.isoformat(),
                duration_seconds=result.duration_seconds,
                error=result.error,
            )
            for name, result in summary.tables.items()
        },
        duration_seconds=summary.duration_seconds,
        started_at=summary.started_at.isoformat(),
        completed_at=summary.completed_at.isoformat(),
    )


@router.post("/rollup", response_model=RollupSummaryResponse)
async def trigger_rollup(request: RollupRequest = RollupRequest()):
    """Trigger manual rollup of raw metrics into hourly summaries.

    This endpoint allows administrators to manually trigger rollup of raw
    metrics into hourly summary tables for efficient historical queries.

    Args:
        request: Rollup request parameters

    Returns:
        RollupSummaryResponse: Summary of the rollup operation

    Raises:
        HTTPException: If metrics rollup is disabled (400).
    """
    if not settings.metrics_rollup_enabled:
        raise HTTPException(status_code=400, detail="Metrics rollup is disabled")

    # First-Party
    from mcpgateway.services.metrics_rollup_service import get_metrics_rollup_service

    service = get_metrics_rollup_service()

    summary = await service.rollup_all(
        hours_back=request.hours_back,
        force_reprocess=request.force_reprocess,
    )

    return RollupSummaryResponse(
        total_hours_processed=summary.total_hours_processed,
        total_records_aggregated=summary.total_records_aggregated,
        total_rollups_created=summary.total_rollups_created,
        total_rollups_updated=summary.total_rollups_updated,
        tables={
            name: RollupResultResponse(
                table_name=result.table_name,
                hours_processed=result.hours_processed,
                records_aggregated=result.records_aggregated,
                rollups_created=result.rollups_created,
                rollups_updated=result.rollups_updated,
                raw_deleted=result.raw_deleted,
                duration_seconds=result.duration_seconds,
                error=result.error,
            )
            for name, result in summary.tables.items()
        },
        duration_seconds=summary.duration_seconds,
        started_at=summary.started_at.isoformat(),
        completed_at=summary.completed_at.isoformat(),
    )


@router.get("/stats", response_model=MetricsStatsResponse)
async def get_metrics_stats():
    """Get statistics about metrics cleanup and rollup services.

    Returns:
        MetricsStatsResponse: Statistics including service status and table sizes
    """
    cleanup_stats = {"enabled": False}
    rollup_stats = {"enabled": False}
    table_sizes = {}

    if settings.metrics_cleanup_enabled:
        # First-Party
        from mcpgateway.services.metrics_cleanup_service import get_metrics_cleanup_service

        cleanup_service = get_metrics_cleanup_service()
        cleanup_stats = cleanup_service.get_stats()
        table_sizes = await cleanup_service.get_table_sizes()

    if settings.metrics_rollup_enabled:
        # First-Party
        from mcpgateway.services.metrics_rollup_service import get_metrics_rollup_service

        rollup_service = get_metrics_rollup_service()
        rollup_stats = rollup_service.get_stats()

    return MetricsStatsResponse(
        cleanup=cleanup_stats,
        rollup=rollup_stats,
        table_sizes=table_sizes,
    )


@router.get("/config")
async def get_metrics_config():
    """Get current metrics maintenance configuration.

    Returns information about cleanup and rollup configuration settings.

    Returns:
        dict: Current configuration settings
    """
    return {
        "cleanup": {
            "enabled": settings.metrics_cleanup_enabled,
            "retention_days": settings.metrics_retention_days,
            "interval_hours": settings.metrics_cleanup_interval_hours,
            "batch_size": settings.metrics_cleanup_batch_size,
        },
        "rollup": {
            "enabled": settings.metrics_rollup_enabled,
            "interval_hours": settings.metrics_rollup_interval_hours,
            "retention_days": settings.metrics_rollup_retention_days,
            "late_data_hours": settings.metrics_rollup_late_data_hours,
            "delete_raw_after_rollup": settings.metrics_delete_raw_after_rollup,
            "delete_raw_after_rollup_hours": settings.metrics_delete_raw_after_rollup_hours,
        },
    }
