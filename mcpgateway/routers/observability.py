# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/observability.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Observability API Router.
Provides REST endpoints for querying traces, spans, events, and metrics.
"""

# Standard
from datetime import datetime, timedelta
from typing import List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import SessionLocal
from mcpgateway.schemas import (
    ObservabilitySpanRead,
    ObservabilityTraceRead,
    ObservabilityTraceWithSpans,
)
from mcpgateway.services.observability_service import ObservabilityService

router = APIRouter(prefix="/observability", tags=["Observability"])


def get_db():
    """Database session dependency.

    Yields:
        Session: SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/traces", response_model=List[ObservabilityTraceRead])
def list_traces(
    start_time: Optional[datetime] = Query(None, description="Filter traces after this time"),
    end_time: Optional[datetime] = Query(None, description="Filter traces before this time"),
    status: Optional[str] = Query(None, description="Filter by status (ok, error)"),
    http_status_code: Optional[int] = Query(None, description="Filter by HTTP status code"),
    user_email: Optional[str] = Query(None, description="Filter by user email"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Result offset"),
    db: Session = Depends(get_db),
):
    """List traces with optional filtering.

    Query traces with various filters including time range, status, HTTP status code,
    and user email. Results are paginated.

    Args:
        start_time: Filter traces after this time
        end_time: Filter traces before this time
        status: Filter by status (ok, error)
        http_status_code: Filter by HTTP status code
        user_email: Filter by user email
        limit: Maximum results
        offset: Result offset
        db: Database session

    Returns:
        List[ObservabilityTraceRead]: List of traces matching filters
    """
    service = ObservabilityService()
    traces = service.query_traces(
        db=db,
        start_time=start_time,
        end_time=end_time,
        status=status,
        http_status_code=http_status_code,
        user_email=user_email,
        limit=limit,
        offset=offset,
    )
    return traces


@router.get("/traces/{trace_id}", response_model=ObservabilityTraceWithSpans)
def get_trace(trace_id: str, db: Session = Depends(get_db)):
    """Get a trace by ID with all its spans and events.

    Returns a complete trace with all nested spans and their events,
    providing a full view of the request flow.

    Args:
        trace_id: UUID of the trace to retrieve
        db: Database session

    Returns:
        ObservabilityTraceWithSpans: Complete trace with all spans and events

    Raises:
        HTTPException: 404 if trace not found
    """
    service = ObservabilityService()
    trace = service.get_trace_with_spans(db, trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.get("/spans", response_model=List[ObservabilitySpanRead])
def list_spans(
    trace_id: Optional[str] = Query(None, description="Filter by trace ID"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    resource_name: Optional[str] = Query(None, description="Filter by resource name"),
    start_time: Optional[datetime] = Query(None, description="Filter spans after this time"),
    end_time: Optional[datetime] = Query(None, description="Filter spans before this time"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Result offset"),
    db: Session = Depends(get_db),
):
    """List spans with optional filtering.

    Query spans by trace ID, resource type, resource name, or time range.
    Useful for analyzing specific operations or resource performance.

    Args:
        trace_id: Filter by trace ID
        resource_type: Filter by resource type
        resource_name: Filter by resource name
        start_time: Filter spans after this time
        end_time: Filter spans before this time
        limit: Maximum results
        offset: Result offset
        db: Database session

    Returns:
        List[ObservabilitySpanRead]: List of spans matching filters
    """
    service = ObservabilityService()
    spans = service.query_spans(
        db=db,
        trace_id=trace_id,
        resource_type=resource_type,
        resource_name=resource_name,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    return spans


@router.delete("/traces/cleanup")
def cleanup_old_traces(
    days: int = Query(7, ge=1, description="Delete traces older than this many days"),
    db: Session = Depends(get_db),
):
    """Delete traces older than a specified number of days.

    Cleans up old trace data to manage storage. Cascading deletes will
    also remove associated spans, events, and metrics.

    Args:
        days: Delete traces older than this many days
        db: Database session

    Returns:
        dict: Number of deleted traces and cutoff time
    """
    service = ObservabilityService()
    cutoff_time = datetime.now() - timedelta(days=days)
    deleted = service.delete_old_traces(db, cutoff_time)
    return {"deleted": deleted, "cutoff_time": cutoff_time}


@router.get("/stats")
def get_stats(
    hours: int = Query(24, ge=1, le=168, description="Time window in hours"),
    db: Session = Depends(get_db),
):
    """Get observability statistics.

    Returns summary statistics including:
    - Total traces in time window
    - Success/error counts
    - Average response time
    - Top slowest endpoints

    Args:
        hours: Time window in hours
        db: Database session

    Returns:
        dict: Statistics including counts, error rate, and slowest endpoints
    """
    # Third-Party
    from sqlalchemy import func

    # First-Party
    from mcpgateway.db import ObservabilityTrace

    ObservabilityService()
    cutoff_time = datetime.now() - timedelta(hours=hours)

    # Get basic counts
    total_traces = db.query(func.count(ObservabilityTrace.trace_id)).filter(ObservabilityTrace.start_time >= cutoff_time).scalar()

    success_count = db.query(func.count(ObservabilityTrace.trace_id)).filter(ObservabilityTrace.start_time >= cutoff_time, ObservabilityTrace.status == "ok").scalar()

    error_count = db.query(func.count(ObservabilityTrace.trace_id)).filter(ObservabilityTrace.start_time >= cutoff_time, ObservabilityTrace.status == "error").scalar()

    avg_duration = db.query(func.avg(ObservabilityTrace.duration_ms)).filter(ObservabilityTrace.start_time >= cutoff_time, ObservabilityTrace.duration_ms.isnot(None)).scalar() or 0

    # Get slowest endpoints
    slowest = (
        db.query(ObservabilityTrace.name, func.avg(ObservabilityTrace.duration_ms).label("avg_duration"), func.count(ObservabilityTrace.trace_id).label("count"))
        .filter(ObservabilityTrace.start_time >= cutoff_time, ObservabilityTrace.duration_ms.isnot(None))
        .group_by(ObservabilityTrace.name)
        .order_by(func.avg(ObservabilityTrace.duration_ms).desc())
        .limit(10)
        .all()
    )

    return {
        "time_window_hours": hours,
        "total_traces": total_traces,
        "success_count": success_count,
        "error_count": error_count,
        "error_rate": (error_count / total_traces * 100) if total_traces > 0 else 0,
        "avg_duration_ms": round(avg_duration, 2),
        "slowest_endpoints": [{"name": row[0], "avg_duration_ms": round(row[1], 2), "count": row[2]} for row in slowest],
    }
