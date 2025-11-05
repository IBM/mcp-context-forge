# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/observability_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Observability Service Implementation.
This module provides OpenTelemetry-style observability for MCP Gateway,
capturing traces, spans, events, and metrics for all operations.

It includes:
- Trace creation and management
- Span tracking with hierarchical nesting
- Event logging within spans
- Metrics collection and storage
- Query and filtering capabilities
- Integration with FastAPI middleware

Examples:
    >>> from mcpgateway.services.observability_service import ObservabilityService  # doctest: +SKIP
    >>> service = ObservabilityService()  # doctest: +SKIP
    >>> trace_id = service.start_trace(db, "GET /tools", http_method="GET", http_url="/tools")  # doctest: +SKIP
    >>> span_id = service.start_span(db, trace_id, "database_query", resource_type="database")  # doctest: +SKIP
    >>> service.end_span(db, span_id, status="ok")  # doctest: +SKIP
    >>> service.end_trace(db, trace_id, status="ok", http_status_code=200)  # doctest: +SKIP
"""

# Standard
from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import traceback
from typing import Any, Dict, List, Optional
import uuid

# Third-Party
from sqlalchemy import desc
from sqlalchemy.orm import joinedload, Session

# First-Party
from mcpgateway.db import ObservabilityEvent, ObservabilityMetric, ObservabilitySpan, ObservabilityTrace

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Return current UTC time with timezone.

    Returns:
        datetime: Current time in UTC with timezone info
    """
    return datetime.now(timezone.utc)


def ensure_timezone_aware(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware (UTC).

    SQLite returns naive datetimes even when stored with timezone info.
    This helper ensures consistency for datetime arithmetic.

    Args:
        dt: Datetime that may be naive or aware

    Returns:
        Timezone-aware datetime in UTC
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class ObservabilityService:
    """Service for managing observability traces, spans, events, and metrics.

    This service provides comprehensive observability capabilities similar to
    OpenTelemetry, allowing tracking of request flows through the system.

    Examples:
        >>> service = ObservabilityService()  # doctest: +SKIP
        >>> trace_id = service.start_trace(db, "POST /tools/invoke")  # doctest: +SKIP
        >>> span_id = service.start_span(db, trace_id, "tool_execution")  # doctest: +SKIP
        >>> service.end_span(db, span_id, status="ok")  # doctest: +SKIP
        >>> service.end_trace(db, trace_id, status="ok")  # doctest: +SKIP
    """

    # ==============================
    # Trace Management
    # ==============================

    def start_trace(
        self,
        db: Session,
        name: str,
        http_method: Optional[str] = None,
        http_url: Optional[str] = None,
        user_email: Optional[str] = None,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        resource_attributes: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start a new trace.

        Args:
            db: Database session
            name: Trace name (e.g., "POST /tools/invoke")
            http_method: HTTP method (GET, POST, etc.)
            http_url: Full request URL
            user_email: Authenticated user email
            user_agent: Client user agent string
            ip_address: Client IP address
            attributes: Additional trace attributes
            resource_attributes: Resource attributes (service name, version, etc.)

        Returns:
            Trace ID (UUID string)

        Examples:
            >>> trace_id = service.start_trace(  # doctest: +SKIP
            ...     db,
            ...     "POST /tools/invoke",
            ...     http_method="POST",
            ...     http_url="https://api.example.com/tools/invoke",
            ...     user_email="user@example.com"
            ... )
        """
        trace_id = str(uuid.uuid4())
        trace = ObservabilityTrace(
            trace_id=trace_id,
            name=name,
            start_time=utc_now(),
            status="unset",
            http_method=http_method,
            http_url=http_url,
            user_email=user_email,
            user_agent=user_agent,
            ip_address=ip_address,
            attributes=attributes or {},
            resource_attributes=resource_attributes or {},
            created_at=utc_now(),
        )
        db.add(trace)
        db.commit()
        logger.debug(f"Started trace {trace_id}: {name}")
        return trace_id

    def end_trace(
        self,
        db: Session,
        trace_id: str,
        status: str = "ok",
        status_message: Optional[str] = None,
        http_status_code: Optional[int] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """End a trace.

        Args:
            db: Database session
            trace_id: Trace ID to end
            status: Trace status (ok, error)
            status_message: Optional status message
            http_status_code: HTTP response status code
            attributes: Additional attributes to merge

        Examples:
            >>> service.end_trace(  # doctest: +SKIP
            ...     db,
            ...     trace_id,
            ...     status="ok",
            ...     http_status_code=200
            ... )
        """
        trace = db.query(ObservabilityTrace).filter_by(trace_id=trace_id).first()
        if not trace:
            logger.warning(f"Trace {trace_id} not found")
            return

        end_time = utc_now()
        duration_ms = (end_time - ensure_timezone_aware(trace.start_time)).total_seconds() * 1000

        trace.end_time = end_time
        trace.duration_ms = duration_ms
        trace.status = status
        trace.status_message = status_message
        if http_status_code is not None:
            trace.http_status_code = http_status_code
        if attributes:
            trace.attributes = {**(trace.attributes or {}), **attributes}

        db.commit()
        logger.debug(f"Ended trace {trace_id}: {status} ({duration_ms:.2f}ms)")

    def get_trace(self, db: Session, trace_id: str, include_spans: bool = False) -> Optional[ObservabilityTrace]:
        """Get a trace by ID.

        Args:
            db: Database session
            trace_id: Trace ID
            include_spans: Whether to load spans eagerly

        Returns:
            Trace object or None if not found

        Examples:
            >>> trace = service.get_trace(db, trace_id, include_spans=True)  # doctest: +SKIP
            >>> if trace:  # doctest: +SKIP
            ...     print(f"Trace: {trace.name}, Spans: {len(trace.spans)}")  # doctest: +SKIP
        """
        query = db.query(ObservabilityTrace).filter_by(trace_id=trace_id)
        if include_spans:
            query = query.options(joinedload(ObservabilityTrace.spans))
        return query.first()

    # ==============================
    # Span Management
    # ==============================

    def start_span(
        self,
        db: Session,
        trace_id: str,
        name: str,
        parent_span_id: Optional[str] = None,
        kind: str = "internal",
        resource_name: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start a new span within a trace.

        Args:
            db: Database session
            trace_id: Parent trace ID
            name: Span name (e.g., "database_query", "tool_invocation")
            parent_span_id: Parent span ID (for nested spans)
            kind: Span kind (internal, server, client, producer, consumer)
            resource_name: Resource name being operated on
            resource_type: Resource type (tool, resource, prompt, etc.)
            resource_id: Resource ID
            attributes: Additional span attributes

        Returns:
            Span ID (UUID string)

        Examples:
            >>> span_id = service.start_span(  # doctest: +SKIP
            ...     db,
            ...     trace_id,
            ...     "tool_invocation",
            ...     resource_type="tool",
            ...     resource_name="get_weather"
            ... )
        """
        span_id = str(uuid.uuid4())
        span = ObservabilitySpan(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            name=name,
            kind=kind,
            start_time=utc_now(),
            status="unset",
            resource_name=resource_name,
            resource_type=resource_type,
            resource_id=resource_id,
            attributes=attributes or {},
            created_at=utc_now(),
        )
        db.add(span)
        db.commit()
        logger.debug(f"Started span {span_id}: {name} (trace={trace_id})")
        return span_id

    def end_span(
        self,
        db: Session,
        span_id: str,
        status: str = "ok",
        status_message: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """End a span.

        Args:
            db: Database session
            span_id: Span ID to end
            status: Span status (ok, error)
            status_message: Optional status message
            attributes: Additional attributes to merge

        Examples:
            >>> service.end_span(db, span_id, status="ok")  # doctest: +SKIP
        """
        span = db.query(ObservabilitySpan).filter_by(span_id=span_id).first()
        if not span:
            logger.warning(f"Span {span_id} not found")
            return

        end_time = utc_now()
        duration_ms = (end_time - ensure_timezone_aware(span.start_time)).total_seconds() * 1000

        span.end_time = end_time
        span.duration_ms = duration_ms
        span.status = status
        span.status_message = status_message
        if attributes:
            span.attributes = {**(span.attributes or {}), **attributes}

        db.commit()
        logger.debug(f"Ended span {span_id}: {status} ({duration_ms:.2f}ms)")

    @contextmanager
    def trace_span(
        self,
        db: Session,
        trace_id: str,
        name: str,
        parent_span_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_name: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """Context manager for automatic span lifecycle management.

        Args:
            db: Database session
            trace_id: Parent trace ID
            name: Span name
            parent_span_id: Parent span ID (optional)
            resource_type: Resource type
            resource_name: Resource name
            attributes: Additional attributes

        Yields:
            Span ID

        Raises:
            Exception: Re-raises any exception after logging it in the span

        Examples:
            >>> with service.trace_span(db, trace_id, "database_query") as span_id:  # doctest: +SKIP
            ...     results = db.query(Tool).all()  # doctest: +SKIP
        """
        span_id = self.start_span(db, trace_id, name, parent_span_id, resource_type=resource_type, resource_name=resource_name, attributes=attributes)
        try:
            yield span_id
            self.end_span(db, span_id, status="ok")
        except Exception as e:
            self.end_span(db, span_id, status="error", status_message=str(e))
            self.add_event(db, span_id, "exception", severity="error", message=str(e), exception_type=type(e).__name__, exception_message=str(e), exception_stacktrace=traceback.format_exc())
            raise

    # ==============================
    # Event Management
    # ==============================

    def add_event(
        self,
        db: Session,
        span_id: str,
        name: str,
        severity: Optional[str] = None,
        message: Optional[str] = None,
        exception_type: Optional[str] = None,
        exception_message: Optional[str] = None,
        exception_stacktrace: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Add an event to a span.

        Args:
            db: Database session
            span_id: Parent span ID
            name: Event name
            severity: Log severity (debug, info, warning, error, critical)
            message: Event message
            exception_type: Exception class name
            exception_message: Exception message
            exception_stacktrace: Exception stacktrace
            attributes: Additional event attributes

        Returns:
            Event ID

        Examples:
            >>> event_id = service.add_event(  # doctest: +SKIP
            ...     db,  # doctest: +SKIP
            ...     span_id,  # doctest: +SKIP
            ...     "database_connection_error",  # doctest: +SKIP
            ...     severity="error",  # doctest: +SKIP
            ...     message="Failed to connect to database"  # doctest: +SKIP
            ... )  # doctest: +SKIP
        """
        event = ObservabilityEvent(
            span_id=span_id,
            name=name,
            timestamp=utc_now(),
            severity=severity,
            message=message,
            exception_type=exception_type,
            exception_message=exception_message,
            exception_stacktrace=exception_stacktrace,
            attributes=attributes or {},
            created_at=utc_now(),
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        logger.debug(f"Added event to span {span_id}: {name}")
        return event.id

    # ==============================
    # Metric Management
    # ==============================

    def record_metric(
        self,
        db: Session,
        name: str,
        value: float,
        metric_type: str = "gauge",
        unit: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Record a metric.

        Args:
            db: Database session
            name: Metric name (e.g., "http.request.duration")
            value: Metric value
            metric_type: Metric type (counter, gauge, histogram)
            unit: Metric unit (ms, count, bytes, etc.)
            resource_type: Resource type
            resource_id: Resource ID
            trace_id: Associated trace ID
            attributes: Additional metric attributes/labels

        Returns:
            Metric ID

        Examples:
            >>> metric_id = service.record_metric(  # doctest: +SKIP
            ...     db,  # doctest: +SKIP
            ...     "http.request.duration",  # doctest: +SKIP
            ...     123.45,  # doctest: +SKIP
            ...     metric_type="histogram",  # doctest: +SKIP
            ...     unit="ms",  # doctest: +SKIP
            ...     trace_id=trace_id  # doctest: +SKIP
            ... )  # doctest: +SKIP
        """
        metric = ObservabilityMetric(
            name=name,
            value=value,
            metric_type=metric_type,
            timestamp=utc_now(),
            unit=unit,
            resource_type=resource_type,
            resource_id=resource_id,
            trace_id=trace_id,
            attributes=attributes or {},
            created_at=utc_now(),
        )
        db.add(metric)
        db.commit()
        db.refresh(metric)
        logger.debug(f"Recorded metric: {name} = {value} {unit or ''}")
        return metric.id

    # ==============================
    # Query Methods
    # ==============================

    def query_traces(
        self,
        db: Session,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        status: Optional[str] = None,
        http_status_code: Optional[int] = None,
        user_email: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ObservabilityTrace]:
        """Query traces with filters.

        Args:
            db: Database session
            start_time: Filter traces after this time
            end_time: Filter traces before this time
            status: Filter by status
            http_status_code: Filter by HTTP status code
            user_email: Filter by user email
            limit: Maximum results
            offset: Result offset

        Returns:
            List of traces

        Examples:
            >>> traces = service.query_traces(  # doctest: +SKIP
            ...     db,
            ...     status="error",
            ...     limit=50
            ... )
        """
        query = db.query(ObservabilityTrace)

        if start_time:
            query = query.filter(ObservabilityTrace.start_time >= start_time)
        if end_time:
            query = query.filter(ObservabilityTrace.start_time <= end_time)
        if status:
            query = query.filter(ObservabilityTrace.status == status)
        if http_status_code:
            query = query.filter(ObservabilityTrace.http_status_code == http_status_code)
        if user_email:
            query = query.filter(ObservabilityTrace.user_email == user_email)

        query = query.order_by(desc(ObservabilityTrace.start_time))
        query = query.limit(limit).offset(offset)

        return query.all()

    def query_spans(
        self,
        db: Session,
        trace_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ObservabilitySpan]:
        """Query spans with filters.

        Args:
            db: Database session
            trace_id: Filter by trace ID
            resource_type: Filter by resource type
            resource_name: Filter by resource name
            start_time: Filter spans after this time
            end_time: Filter spans before this time
            limit: Maximum results
            offset: Result offset

        Returns:
            List of spans

        Examples:
            >>> spans = service.query_spans(  # doctest: +SKIP
            ...     db,
            ...     trace_id=trace_id,
            ...     resource_type="tool"
            ... )
        """
        query = db.query(ObservabilitySpan)

        if trace_id:
            query = query.filter(ObservabilitySpan.trace_id == trace_id)
        if resource_type:
            query = query.filter(ObservabilitySpan.resource_type == resource_type)
        if resource_name:
            query = query.filter(ObservabilitySpan.resource_name == resource_name)
        if start_time:
            query = query.filter(ObservabilitySpan.start_time >= start_time)
        if end_time:
            query = query.filter(ObservabilitySpan.start_time <= end_time)

        query = query.order_by(desc(ObservabilitySpan.start_time))
        query = query.limit(limit).offset(offset)

        return query.all()

    def get_trace_with_spans(self, db: Session, trace_id: str) -> Optional[ObservabilityTrace]:
        """Get a complete trace with all spans and events.

        Args:
            db: Database session
            trace_id: Trace ID

        Returns:
            Trace with spans and events loaded

        Examples:
            >>> trace = service.get_trace_with_spans(db, trace_id)  # doctest: +SKIP
            >>> if trace:  # doctest: +SKIP
            ...     for span in trace.spans:  # doctest: +SKIP
            ...         print(f"Span: {span.name}, Events: {len(span.events)}")  # doctest: +SKIP
        """
        return db.query(ObservabilityTrace).filter_by(trace_id=trace_id).options(joinedload(ObservabilityTrace.spans).joinedload(ObservabilitySpan.events)).first()

    def delete_old_traces(self, db: Session, before_time: datetime) -> int:
        """Delete traces older than a given time.

        Args:
            db: Database session
            before_time: Delete traces before this time

        Returns:
            Number of traces deleted

        Examples:
            >>> from datetime import timedelta  # doctest: +SKIP
            >>> cutoff = utc_now() - timedelta(days=30)  # doctest: +SKIP
            >>> deleted = service.delete_old_traces(db, cutoff)  # doctest: +SKIP
            >>> print(f"Deleted {deleted} old traces")  # doctest: +SKIP
        """
        deleted = db.query(ObservabilityTrace).filter(ObservabilityTrace.start_time < before_time).delete()
        db.commit()
        logger.info(f"Deleted {deleted} traces older than {before_time}")
        return deleted
