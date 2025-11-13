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
    min_duration_ms: Optional[float] = Query(None, ge=0, description="Minimum duration in milliseconds"),
    max_duration_ms: Optional[float] = Query(None, ge=0, description="Maximum duration in milliseconds"),
    status: Optional[str] = Query(None, description="Filter by status (ok, error)"),
    http_status_code: Optional[int] = Query(None, description="Filter by HTTP status code"),
    http_method: Optional[str] = Query(None, description="Filter by HTTP method (GET, POST, etc.)"),
    user_email: Optional[str] = Query(None, description="Filter by user email"),
    attribute_search: Optional[str] = Query(None, description="Free-text search within trace attributes"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Result offset"),
    db: Session = Depends(get_db),
):
    """List traces with optional filtering.

    Query traces with various filters including time range, duration, status, HTTP method,
    HTTP status code, user email, and attribute search. Results are paginated.

    Note: For structured attribute filtering (key-value pairs with AND logic),
    use a JSON request body via POST endpoint or the Python SDK.

    Args:
        start_time: Filter traces after this time
        end_time: Filter traces before this time
        min_duration_ms: Minimum duration in milliseconds
        max_duration_ms: Maximum duration in milliseconds
        status: Filter by status (ok, error)
        http_status_code: Filter by HTTP status code
        http_method: Filter by HTTP method (GET, POST, etc.)
        user_email: Filter by user email
        attribute_search: Free-text search across all trace attributes
        limit: Maximum results
        offset: Result offset
        db: Database session

    Returns:
        List[ObservabilityTraceRead]: List of traces matching filters

    Examples:
        >>> import mcpgateway.routers.observability as obs
        >>> class FakeTrace:
        ...     def __init__(self, trace_id='t1'):
        ...         self.trace_id = trace_id
        ...         self.name = 'n'
        ...         self.start_time = None
        ...         self.end_time = None
        ...         self.duration_ms = 100
        ...         self.status = 'ok'
        ...         self.http_method = 'GET'
        ...         self.http_url = '/'
        ...         self.http_status_code = 200
        ...         self.user_email = 'u'
        >>> class FakeService:
        ...     def query_traces(self, **kwargs):
        ...         return [FakeTrace('t1')]
        >>> obs.ObservabilityService = FakeService
        >>> obs.list_traces(db=None)[0].trace_id
        't1'
    """
    service = ObservabilityService()
    traces = service.query_traces(
        db=db,
        start_time=start_time,
        end_time=end_time,
        min_duration_ms=min_duration_ms,
        max_duration_ms=max_duration_ms,
        status=status,
        http_status_code=http_status_code,
        http_method=http_method,
        user_email=user_email,
        attribute_search=attribute_search,
        limit=limit,
        offset=offset,
    )
    return traces


@router.post("/traces/query", response_model=List[ObservabilityTraceRead])
def query_traces_advanced(
    # Third-Party
    request_body: dict,
    db: Session = Depends(get_db),
):
    """Advanced trace querying with attribute filtering.

    POST endpoint that accepts a JSON body with complex filtering criteria,
    including structured attribute filters with AND logic.

    Request Body:
        {
            "start_time": "2025-01-01T00:00:00Z",  # Optional datetime
            "end_time": "2025-01-02T00:00:00Z",    # Optional datetime
            "min_duration_ms": 100.0,               # Optional float
            "max_duration_ms": 5000.0,              # Optional float
            "status": "error",                      # Optional string
            "http_status_code": 500,                # Optional int
            "http_method": "POST",                  # Optional string
            "user_email": "user@example.com",       # Optional string
            "attribute_filters": {                  # Optional dict (AND logic)
                "http.route": "/api/tools",
                "service.name": "mcp-gateway"
            },
            "attribute_search": "error",            # Optional string (OR logic)
            "limit": 100,                           # Optional int
            "offset": 0                             # Optional int
        }

    Args:
        request_body: JSON request body with filter criteria
        db: Database session

    Returns:
        List[ObservabilityTraceRead]: List of traces matching filters

    Raises:
        HTTPException: 400 error if request body is invalid

    Examples:
        >>> from fastapi import HTTPException
        >>> try:
        ...     query_traces_advanced({"start_time": "not-a-date"}, db=None)
        ... except HTTPException as e:
        ...     (e.status_code, "Invalid request body" in str(e.detail))
        (400, True)

        >>> import mcpgateway.routers.observability as obs
        >>> class FakeTrace:
        ...     def __init__(self):
        ...         self.trace_id = 'tx'
        ...         self.name = 'n'

        >>> class FakeService2:
        ...     def query_traces(self, **kwargs):
        ...         return [FakeTrace()]
        >>> obs.ObservabilityService = FakeService2
        >>> obs.query_traces_advanced({}, db=None)[0].trace_id
        'tx'
    """
    # Third-Party
    from pydantic import ValidationError

    try:
        # Extract filters from request body
        service = ObservabilityService()

        # Parse datetime strings if provided
        start_time = request_body.get("start_time")
        if start_time and isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))

        end_time = request_body.get("end_time")
        if end_time and isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time.replace("Z", "+00:00"))

        traces = service.query_traces(
            db=db,
            start_time=start_time,
            end_time=end_time,
            min_duration_ms=request_body.get("min_duration_ms"),
            max_duration_ms=request_body.get("max_duration_ms"),
            status=request_body.get("status"),
            status_in=request_body.get("status_in"),
            status_not_in=request_body.get("status_not_in"),
            http_status_code=request_body.get("http_status_code"),
            http_status_code_in=request_body.get("http_status_code_in"),
            http_method=request_body.get("http_method"),
            http_method_in=request_body.get("http_method_in"),
            user_email=request_body.get("user_email"),
            user_email_in=request_body.get("user_email_in"),
            attribute_filters=request_body.get("attribute_filters"),
            attribute_filters_or=request_body.get("attribute_filters_or"),
            attribute_search=request_body.get("attribute_search"),
            name_contains=request_body.get("name_contains"),
            order_by=request_body.get("order_by", "start_time_desc"),
            limit=request_body.get("limit", 100),
            offset=request_body.get("offset", 0),
        )
        return traces
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid request body: {e}")


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

    Examples:
        >>> import mcpgateway.routers.observability as obs
        >>> class FakeService:
        ...     def get_trace_with_spans(self, db, trace_id):
        ...         return None
        >>> obs.ObservabilityService = FakeService
        >>> try:
        ...     obs.get_trace('missing', db=None)
        ... except obs.HTTPException as e:
        ...     e.status_code
        404
        >>> class FakeService2:
        ...     def get_trace_with_spans(self, db, trace_id):
        ...         return {'trace_id': trace_id}
        >>> obs.ObservabilityService = FakeService2
        >>> obs.get_trace('found', db=None)['trace_id']
        'found'
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

    Examples:
        >>> import mcpgateway.routers.observability as obs
        >>> class FakeSpan:
        ...     def __init__(self):
        ...         self.span_id = 's1'
        ...         self.trace_id = 't1'
        ...         self.name = 'op'
        >>> class FakeService:
        ...     def query_spans(self, **kwargs):
        ...         return [FakeSpan()]
        >>> obs.ObservabilityService = FakeService
        >>> obs.list_spans(db=None)[0].span_id
        's1'
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

    Examples:
        >>> import mcpgateway.routers.observability as obs
        >>> class FakeService:
        ...     def delete_old_traces(self, db, cutoff):
        ...         return 5
        >>> obs.ObservabilityService = FakeService
        >>> res = obs.cleanup_old_traces(days=7, db=None)
        >>> res['deleted']
        5
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


@router.post("/traces/export")
def export_traces(
    request_body: dict,
    format: str = Query("json", description="Export format (json, csv, ndjson)"),
    db: Session = Depends(get_db),
):
    """Export traces in various formats.

    POST endpoint that accepts filter criteria (same as /traces/query) and exports
    matching traces in the specified format.

    Supported formats:
    - json: Standard JSON array
    - csv: Comma-separated values
    - ndjson: Newline-delimited JSON (streaming)

    Args:
        request_body: JSON request body with filter criteria (same as /traces/query)
        format: Export format (json, csv, ndjson)
        db: Database session

    Returns:
        StreamingResponse or JSONResponse with exported data

    Raises:
        HTTPException: 400 error if format is invalid or export fails

    Examples:
        >>> from fastapi import HTTPException
        >>> try:
        ...     export_traces({}, format="xml", db=None)
        ... except HTTPException as e:
        ...     (e.status_code, "format must be one of" in str(e.detail))
        (400, True)
        >>> import mcpgateway.routers.observability as obs
        >>> from datetime import datetime
        >>> class FakeTrace:
        ...     def __init__(self):
        ...         self.trace_id = 'tx'
        ...         self.name = 'name'
        ...         self.start_time = datetime(2025,1,1)
        ...         self.end_time = None
        ...         self.duration_ms = 100
        ...         self.status = 'ok'
        ...         self.http_method = 'GET'
        ...         self.http_url = '/'
        ...         self.http_status_code = 200
        ...         self.user_email = 'u'
        >>> class FakeService:
        ...     def query_traces(self, **kwargs):
        ...         return [FakeTrace()]
        >>> obs.ObservabilityService = FakeService
        >>> out = obs.export_traces({}, format='json', db=None)
        >>> out[0]['trace_id']
        'tx'
        >>> resp = obs.export_traces({}, format='csv', db=None)
        >>> hasattr(resp, 'media_type') and 'csv' in resp.media_type
        True
        >>> resp2 = obs.export_traces({}, format='ndjson', db=None)
        >>> type(resp2).__name__
        'StreamingResponse'
    """
    # Standard
    import csv
    import io

    # Third-Party
    from starlette.responses import Response, StreamingResponse

    # Validate format
    if format not in ["json", "csv", "ndjson"]:
        raise HTTPException(status_code=400, detail="format must be one of: json, csv, ndjson")

    try:
        service = ObservabilityService()

        # Parse datetime strings
        start_time = request_body.get("start_time")
        if start_time and isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))

        end_time = request_body.get("end_time")
        if end_time and isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time.replace("Z", "+00:00"))

        # Query traces
        traces = service.query_traces(
            db=db,
            start_time=start_time,
            end_time=end_time,
            min_duration_ms=request_body.get("min_duration_ms"),
            max_duration_ms=request_body.get("max_duration_ms"),
            status=request_body.get("status"),
            status_in=request_body.get("status_in"),
            http_status_code=request_body.get("http_status_code"),
            http_method=request_body.get("http_method"),
            user_email=request_body.get("user_email"),
            order_by=request_body.get("order_by", "start_time_desc"),
            limit=request_body.get("limit", 1000),  # Higher limit for export
            offset=request_body.get("offset", 0),
        )

        if format == "json":
            # Standard JSON response
            return [
                {
                    "trace_id": t.trace_id,
                    "name": t.name,
                    "start_time": t.start_time.isoformat() if t.start_time else None,
                    "end_time": t.end_time.isoformat() if t.end_time else None,
                    "duration_ms": t.duration_ms,
                    "status": t.status,
                    "http_method": t.http_method,
                    "http_url": t.http_url,
                    "http_status_code": t.http_status_code,
                    "user_email": t.user_email,
                }
                for t in traces
            ]

        elif format == "csv":
            # CSV export
            output = io.StringIO()
            writer = csv.writer(output)

            # Write header
            writer.writerow(["trace_id", "name", "start_time", "duration_ms", "status", "http_method", "http_status_code", "user_email"])

            # Write data
            for t in traces:
                writer.writerow(
                    [t.trace_id, t.name, t.start_time.isoformat() if t.start_time else "", t.duration_ms or "", t.status, t.http_method or "", t.http_status_code or "", t.user_email or ""]
                )

            output.seek(0)
            return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=traces.csv"})

        elif format == "ndjson":
            # Newline-delimited JSON (streaming)
            def generate():
                """Yield newline-delimited JSON strings for each trace.

                This nested generator is used to stream NDJSON responses.

                Yields:
                    str: A JSON-encoded line (with trailing newline) for a trace.
                """
                for t in traces:
                    # Standard
                    import json

                    yield json.dumps(
                        {
                            "trace_id": t.trace_id,
                            "name": t.name,
                            "start_time": t.start_time.isoformat() if t.start_time else None,
                            "duration_ms": t.duration_ms,
                            "status": t.status,
                            "http_method": t.http_method,
                            "http_status_code": t.http_status_code,
                            "user_email": t.user_email,
                        }
                    ) + "\n"

            return StreamingResponse(generate(), media_type="application/x-ndjson", headers={"Content-Disposition": "attachment; filename=traces.ndjson"})

    except (ValueError, Exception) as e:
        raise HTTPException(status_code=400, detail=f"Export failed: {e}")


@router.get("/analytics/query-performance")
def get_query_performance(hours: int = Query(24, ge=1, le=168, description="Time window in hours"), db: Session = Depends(get_db)):
    """Get query performance analytics.

    Returns performance metrics about trace queries including:
    - Average, min, max, p50, p95, p99 durations
    - Query volume over time
    - Error rate trends

    Args:
        hours: Time window in hours
        db: Database session

    Returns:
        dict: Performance analytics

    Examples:
        >>> import mcpgateway.routers.observability as obs
        >>> class EmptyDB:
        ...     def query(self, *a, **k):
        ...         return self
        ...     def filter(self, *a, **k):
        ...         return self
        ...     def all(self):
        ...         return []
        >>> obs.get_query_performance(hours=1, db=EmptyDB())['total_traces']
        0

        >>> class SmallDB:
        ...     def query(self, *a, **k):
        ...         return self
        ...     def filter(self, *a, **k):
        ...         return self
        ...     def all(self):
        ...         return [(10,), (20,), (30,), (40,)]
        >>> res = obs.get_query_performance(hours=1, db=SmallDB())
        >>> res['total_traces']
        4

    """

    # Third-Party

    # First-Party
    from mcpgateway.db import ObservabilityTrace

    ObservabilityService()
    cutoff_time = datetime.now() - timedelta(hours=hours)

    # Get duration percentiles using SQL
    traces_with_duration = db.query(ObservabilityTrace.duration_ms).filter(ObservabilityTrace.start_time >= cutoff_time, ObservabilityTrace.duration_ms.isnot(None)).all()

    durations = sorted([t[0] for t in traces_with_duration if t[0] is not None])

    if not durations:
        return {
            "time_window_hours": hours,
            "total_traces": 0,
            "percentiles": {},
            "avg_duration_ms": 0,
            "min_duration_ms": 0,
            "max_duration_ms": 0,
        }

    def percentile(data, p):
        n = len(data)
        if n == 0:
            return 0
        k = (n - 1) * p
        f = int(k)
        c = k - f
        if f + 1 < n:
            return data[f] + (c * (data[f + 1] - data[f]))
        return data[f]

    return {
        "time_window_hours": hours,
        "total_traces": len(durations),
        "percentiles": {
            "p50": round(percentile(durations, 0.50), 2),
            "p75": round(percentile(durations, 0.75), 2),
            "p90": round(percentile(durations, 0.90), 2),
            "p95": round(percentile(durations, 0.95), 2),
            "p99": round(percentile(durations, 0.99), 2),
        },
        "avg_duration_ms": round(sum(durations) / len(durations), 2),
        "min_duration_ms": round(durations[0], 2),
        "max_duration_ms": round(durations[-1], 2),
    }
