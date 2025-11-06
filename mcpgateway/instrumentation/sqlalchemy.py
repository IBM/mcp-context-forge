# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/instrumentation/sqlalchemy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Automatic instrumentation for SQLAlchemy database queries.

This module instruments SQLAlchemy to automatically capture database
queries as observability spans, providing visibility into database
performance.

Examples:
    >>> from mcpgateway.instrumentation import instrument_sqlalchemy  # doctest: +SKIP
    >>> instrument_sqlalchemy(engine)  # doctest: +SKIP
"""

# Standard
import logging
import threading
import time
from typing import Any, Optional

# Third-Party
from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

# Thread-local storage for tracking queries in progress
_query_tracking = {}

# Thread-local flag to prevent recursive instrumentation
_instrumentation_context = threading.local()


def instrument_sqlalchemy(engine: Engine) -> None:
    """Instrument a SQLAlchemy engine to capture query spans.

    Args:
        engine: SQLAlchemy engine to instrument

    Examples:
        >>> from sqlalchemy import create_engine  # doctest: +SKIP
        >>> engine = create_engine("sqlite:///./mcp.db")  # doctest: +SKIP
        >>> instrument_sqlalchemy(engine)  # doctest: +SKIP
    """
    # Register event listeners
    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine, "after_cursor_execute", _after_cursor_execute)
    logger.info("SQLAlchemy instrumentation enabled")


def _before_cursor_execute(
    conn: Connection,
    _cursor: Any,
    statement: str,
    parameters: Any,
    _context: Any,
    executemany: bool,
) -> None:
    """Event handler called before SQL query execution.

    Args:
        conn: Database connection
        _cursor: Database cursor (required by SQLAlchemy event API)
        statement: SQL statement
        parameters: Query parameters
        _context: Execution context (required by SQLAlchemy event API)
        executemany: Whether this is a bulk execution
    """
    # Store start time for this query
    conn_id = id(conn)
    _query_tracking[conn_id] = {
        "start_time": time.time(),
        "statement": statement,
        "parameters": parameters,
        "executemany": executemany,
    }


def _after_cursor_execute(
    conn: Connection,
    cursor: Any,
    statement: str,
    _parameters: Any,
    _context: Any,
    executemany: bool,
) -> None:
    """Event handler called after SQL query execution.

    Args:
        conn: Database connection
        cursor: Database cursor
        statement: SQL statement
        _parameters: Query parameters (required by SQLAlchemy event API)
        _context: Execution context (required by SQLAlchemy event API)
        executemany: Whether this is a bulk execution
    """
    conn_id = id(conn)
    tracking = _query_tracking.pop(conn_id, None)

    if not tracking:
        return

    # Skip instrumentation if we're already inside span creation (prevent recursion)
    if getattr(_instrumentation_context, "inside_span_creation", False):
        return

    # Skip instrumentation for observability tables to prevent recursion and lock issues
    statement_upper = statement.upper()
    if any(table in statement_upper for table in ["OBSERVABILITY_TRACES", "OBSERVABILITY_SPANS", "OBSERVABILITY_EVENTS", "OBSERVABILITY_METRICS"]):
        logger.debug(f"Skipping instrumentation for observability table query: {statement[:100]}...")
        return

    # Calculate query duration
    duration_ms = (time.time() - tracking["start_time"]) * 1000

    # Get row count if available
    row_count = None
    try:
        if hasattr(cursor, "rowcount") and cursor.rowcount >= 0:
            row_count = cursor.rowcount
    except Exception:  # pylint: disable=broad-except
        pass

    # Try to get trace context from connection info
    trace_id = None
    if hasattr(conn, "info") and "trace_id" in conn.info:
        trace_id = conn.info["trace_id"]

    # If we have a trace_id, create a span
    if trace_id:
        _create_query_span(
            trace_id=trace_id,
            statement=statement,
            duration_ms=duration_ms,
            row_count=row_count,
            executemany=executemany,
        )
    else:
        # Log for debugging but don't fail
        logger.debug(f"Query executed without trace context: {statement[:100]}... ({duration_ms:.2f}ms)")


def _create_query_span(
    trace_id: str,
    statement: str,
    duration_ms: float,
    row_count: Optional[int],
    executemany: bool,
) -> None:
    """Create an observability span for a database query.

    Args:
        trace_id: Parent trace ID
        statement: SQL statement
        duration_ms: Query duration in milliseconds
        row_count: Number of rows affected/returned
        executemany: Whether this is a bulk execution
    """
    # Set flag to prevent recursive instrumentation
    _instrumentation_context.inside_span_creation = True
    try:
        # Import here to avoid circular imports
        # First-Party
        # pylint: disable=import-outside-toplevel
        from mcpgateway.db import ObservabilitySpan, SessionLocal
        from mcpgateway.services.observability_service import ObservabilityService

        # pylint: enable=import-outside-toplevel
        # Extract query type (SELECT, INSERT, UPDATE, DELETE, etc.)
        query_type = statement.strip().split()[0].upper() if statement else "UNKNOWN"

        # Truncate long queries for span name
        span_name = f"db.query.{query_type.lower()}"

        # Create span
        service = ObservabilityService()
        db = SessionLocal()
        try:
            span_id = service.start_span(
                db=db,
                trace_id=trace_id,
                name=span_name,
                kind="client",
                resource_type="database",
                resource_name=query_type,
                attributes={
                    "db.statement": statement[:500],  # Truncate long queries
                    "db.operation": query_type,
                    "db.executemany": executemany,
                    "db.duration_measured_ms": duration_ms,  # Store actual measured duration
                },
            )

            # End span with measured duration in attributes
            service.end_span(
                db=db,
                span_id=span_id,
                status="ok",
                attributes={
                    "db.row_count": row_count,
                },
            )

            # Update the span duration to match what we actually measured
            span = db.query(ObservabilitySpan).filter_by(span_id=span_id).first()
            if span:
                span.duration_ms = duration_ms
                db.commit()

            logger.debug(f"Created span for {query_type} query: {duration_ms:.2f}ms, {row_count} rows")

        finally:
            db.close()

    except Exception as e:  # pylint: disable=broad-except
        # Don't fail the query if span creation fails
        logger.warning(f"Failed to create query span: {e}")
    finally:
        # Always clear the flag
        _instrumentation_context.inside_span_creation = False


def attach_trace_to_session(session: Any, trace_id: str) -> None:
    """Attach a trace ID to a database session.

    This allows the instrumentation to correlate queries with traces.

    Args:
        session: SQLAlchemy session
        trace_id: Trace ID to attach

    Examples:
        >>> from mcpgateway.db import SessionLocal  # doctest: +SKIP
        >>> db = SessionLocal()  # doctest: +SKIP
        >>> attach_trace_to_session(db, trace_id)  # doctest: +SKIP
    """
    if hasattr(session, "bind") and session.bind:
        # Get a connection and attach trace_id to its info dict
        connection = session.connection()
        if hasattr(connection, "info"):
            connection.info["trace_id"] = trace_id
