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
import queue
import threading
import time
from typing import Any, Optional

# Third-Party
from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

# Thread-local storage for tracking queries in progress
# Use a thread-local object so each thread has its own mapping. This
# prevents cross-thread mutation of a single dict which could lead to
# race conditions when the span writer (background thread) and request
# threads interact with tracked queries.
_query_tracking = threading.local()

# Thread-local flag to prevent recursive instrumentation
_instrumentation_context = threading.local()

# Background queue for deferred span writes to avoid database locks


class InstrumentationQueue:
    """Configurable queue wrapper that tracks dropped/total counts.

    This provides a simple drop-rate metric and a bounded queue used by
    the background span writer.

    Examples:
        >>> queue = InstrumentationQueue(maxsize=100)
        >>> queue.put({"span": "data"})
        True
        >>> queue.drop_rate  # Check drop rate
        0.0
        >>> queue.stats  # Get all metrics
        {'total': 1, 'dropped': 0, 'drop_rate': 0.0, 'maxsize': 100}
    """

    def __init__(self, maxsize: Optional[int] = None) -> None:
        # Import settings lazily to avoid import cycles during module
        # initialization in tests or tooling.
        try:
            from mcpgateway.config import settings

            cfg_size = getattr(settings, "instrumentation_queue_size", None)
        except Exception:
            cfg_size = None

        self._maxsize = maxsize if maxsize is not None else (cfg_size or 1000)
        self._queue: queue.Queue = queue.Queue(maxsize=self._maxsize)
        self._dropped_count = 0
        self._total_count = 0
        self._lock = threading.Lock()

    def put(self, span: dict) -> bool:
        """Non-blocking put that returns success status.

        Returns True if span was enqueued, False if queue was full.
        Updates total and dropped counters for metrics tracking.
        """
        try:
            self._queue.put_nowait(span)
            with self._lock:
                self._total_count += 1
            return True
        except queue.Full:
            with self._lock:
                self._total_count += 1
                self._dropped_count += 1
            return False

    def put_nowait(self, span: dict) -> None:
        """Non-blocking put that mirrors Queue.put_nowait semantics.

        Raises ``queue.Full`` when the queue is full. Counters are still
        updated to track totals and drops for metrics.
        """
        with self._lock:
            self._total_count += 1
        try:
            self._queue.put_nowait(span)
        except queue.Full:
            with self._lock:
                self._dropped_count += 1
            raise

    def get(self, timeout: Optional[float] = None):
        return self._queue.get(timeout=timeout)

    def task_done(self) -> None:
        self._queue.task_done()

    @property
    def drop_rate(self) -> float:
        """Calculate the drop rate (dropped/total).

        Returns:
            float: Drop rate between 0.0 and 1.0, or 0.0 if no spans processed yet.
        """
        with self._lock:
            if self._total_count == 0:
                return 0.0
            return float(self._dropped_count) / float(self._total_count)

    @property
    def stats(self) -> dict:
        """Get all queue statistics in a single call.

        Returns:
            dict: Dictionary containing total, dropped, drop_rate, and maxsize.

        Examples:
            >>> queue = InstrumentationQueue(maxsize=100)
            >>> queue.put({"span": "data"})
            True
            >>> queue.stats
            {'total': 1, 'dropped': 0, 'drop_rate': 0.0, 'maxsize': 100}
        """
        with self._lock:
            if self._total_count == 0:
                drop_rate = 0.0
            else:
                drop_rate = float(self._dropped_count) / float(self._total_count)
            
            return {
                "total": self._total_count,
                "dropped": self._dropped_count,
                "drop_rate": drop_rate,
                "maxsize": self._maxsize,
            }


_span_queue: InstrumentationQueue = InstrumentationQueue()
_span_writer_thread: Optional[threading.Thread] = None
_shutdown_event = threading.Event()


def _write_span_to_db(span_data: dict) -> None:
    """Write a single span to the database.

    Args:
        span_data: Dictionary containing span information
    """
    # Set recursion guard so DB operations performed while persisting
    # observability spans are not re-instrumented by SQLAlchemy hooks.
    setattr(_instrumentation_context, "inside_span_creation", True)
    try:
        # Import here to avoid circular imports
        # First-Party
        # pylint: disable=import-outside-toplevel
        from mcpgateway.db import ObservabilitySpan, SessionLocal
        from mcpgateway.services.observability_service import ObservabilityService

        # pylint: enable=import-outside-toplevel

        service = ObservabilityService()
        db = SessionLocal()
        try:
            span_id = service.start_span(
                db=db,
                trace_id=span_data["trace_id"],
                name=span_data["name"],
                kind=span_data["kind"],
                resource_type=span_data["resource_type"],
                resource_name=span_data["resource_name"],
                attributes=span_data["start_attributes"],
            )

            # End span with measured duration in attributes
            service.end_span(
                db=db,
                span_id=span_id,
                status=span_data["status"],
                attributes=span_data["end_attributes"],
            )

            # Update the span duration to match what we actually measured
            span = db.query(ObservabilitySpan).filter_by(span_id=span_id).first()
            if span:
                span.duration_ms = span_data["duration_ms"]
                db.commit()

            logger.debug(f"Created span for {span_data['resource_name']} query: " f"{span_data['duration_ms']:.2f}ms, {span_data.get('row_count')} rows")

        finally:
            db.close()  # Commit already done above

    except Exception as e:  # pylint: disable=broad-except
        # Don't fail if span creation fails
        logger.warning(f"Failed to write query span: {e}")
    finally:
        # Clear recursion guard even if errors occurred
        try:
            setattr(_instrumentation_context, "inside_span_creation", False)
        except Exception:
            pass


def _span_writer_worker() -> None:
    """Background worker thread that writes spans to the database.

    This runs in a separate thread to avoid blocking the main request thread
    and to prevent database lock contention.
    """
    logger.info("Span writer worker started")

    while not _shutdown_event.is_set():
        try:
            # Wait for span data with timeout to allow checking shutdown
            try:
                span_data = _span_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # Write the span to the database
            _write_span_to_db(span_data)
            _span_queue.task_done()

        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Error in span writer worker: {e}")
            # Continue processing even if one span fails

    logger.info("Span writer worker stopped")


def instrument_sqlalchemy(engine: Engine) -> None:
    """Instrument a SQLAlchemy engine to capture query spans.

    Args:
        engine: SQLAlchemy engine to instrument

    Examples:
        >>> from sqlalchemy import create_engine  # doctest: +SKIP
        >>> engine = create_engine("sqlite:///./mcp.db")  # doctest: +SKIP
        >>> instrument_sqlalchemy(engine)  # doctest: +SKIP
    """
    global _span_writer_thread  # pylint: disable=global-statement

    # Register event listeners
    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine, "after_cursor_execute", _after_cursor_execute)

    # Start background span writer thread if not already running
    if _span_writer_thread is None or not _span_writer_thread.is_alive():
        _span_writer_thread = threading.Thread(target=_span_writer_worker, name="SpanWriterThread", daemon=True)
        _span_writer_thread.start()
        logger.info("Started background span writer thread")

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
    if not hasattr(_query_tracking, "map"):
        _query_tracking.map = {}
    _query_tracking.map[conn_id] = {
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
    tracking = None
    if hasattr(_query_tracking, "map"):
        tracking = _query_tracking.map.pop(conn_id, None)

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
    except Exception:  # pylint: disable=broad-except  # nosec B110 - row_count is optional metadata
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

    This function enqueues span data to be written by a background thread,
    avoiding database lock contention.

    Args:
        trace_id: Parent trace ID
        statement: SQL statement
        duration_ms: Query duration in milliseconds
        row_count: Number of rows affected/returned
        executemany: Whether this is a bulk execution
    """
    try:
        # Extract query type (SELECT, INSERT, UPDATE, DELETE, etc.)
        query_type = statement.strip().split()[0].upper() if statement else "UNKNOWN"

        # Truncate long queries for span name
        span_name = f"db.query.{query_type.lower()}"

        # Prepare span data
        span_data = {
            "trace_id": trace_id,
            "name": span_name,
            "kind": "client",
            "resource_type": "database",
            "resource_name": query_type,
            "duration_ms": duration_ms,
            "status": "ok",
            "start_attributes": {
                "db.statement": statement[:500],  # Truncate long queries
                "db.operation": query_type,
                "db.executemany": executemany,
                "db.duration_measured_ms": duration_ms,  # Store actual measured duration
            },
            "end_attributes": {
                "db.row_count": row_count,
            },
            "row_count": row_count,
        }

        # Enqueue for background processing using non-blocking semantics.
        # Support both the custom InstrumentationQueue (which exposes
        # `put` returning bool and `put_nowait`) and plain `queue.Queue`
        # instances (which expose `put_nowait`). Prefer non-blocking
        # `put_nowait` when available to avoid blocking the producer.
        try:
            if hasattr(_span_queue, "put_nowait"):
                try:
                    _span_queue.put_nowait(span_data)
                    logger.debug(f"Enqueued span for {query_type} query: {duration_ms:.2f}ms")
                except queue.Full:
                    logger.warning("Span queue is full, dropping span data")
            else:
                # Fallback: call `put` and interpret boolean return when
                # provided by a custom implementation. If `put` returns
                # None, treat it as success (best-effort).
                put_fn = getattr(_span_queue, "put", None)
                if put_fn is None:
                    logger.warning("No queue put available, dropping span data")
                else:
                    try:
                        res = put_fn(span_data)
                        if res is True:
                            logger.debug(f"Enqueued span for {query_type} query: {duration_ms:.2f}ms")
                        elif res is False:
                            logger.warning("Span queue is full, dropping span data")
                        else:
                            # treat None/other as success
                            logger.debug(f"Enqueued span for {query_type} query: {duration_ms:.2f}ms")
                    except Exception as e:  # pragma: no cover - defensive
                        logger.warning(f"Failed to enqueue span data: {e}")
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"Failed to enqueue span data: {e}")

    except Exception as e:  # pylint: disable=broad-except
        # Don't fail the query if span creation fails
        logger.debug(f"Failed to enqueue query span: {e}")


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
