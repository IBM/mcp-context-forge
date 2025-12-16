# -*- coding: utf-8 -*-
"""Database query logging middleware for N+1 detection.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

This middleware logs all database queries per request to help identify
N+1 query patterns and other performance issues.

Enable with:
    DB_QUERY_LOG_ENABLED=true

Output files:
    - logs/db-queries.log (human-readable text)
    - logs/db-queries.jsonl (JSON Lines for tooling)
"""

# Standard
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.config import get_settings

logger = logging.getLogger(__name__)

# Context variable to track queries per request
_request_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("db_query_request_context", default=None)

# Lock for thread-safe file writing
_file_lock = threading.Lock()

# Track if we've already instrumented the engine
_instrumented_engines: set = set()


def _normalize_query(sql: str) -> str:
    """Normalize a SQL query for pattern detection.

    Replaces specific values with placeholders to identify similar queries.

    Args:
        sql: The SQL query string

    Returns:
        Normalized query string
    """
    # Replace quoted strings
    normalized = re.sub(r"'[^']*'", "'?'", sql)
    # Replace numbers
    normalized = re.sub(r"\b\d+\b", "?", normalized)
    # Replace IN clauses with multiple values
    normalized = re.sub(r"IN\s*\([^)]+\)", "IN (?)", normalized, flags=re.IGNORECASE)
    # Normalize whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _extract_table_name(sql: str) -> Optional[str]:
    """Extract the main table name from a SQL query.

    Args:
        sql: The SQL query string

    Returns:
        Table name or None
    """
    # Match FROM table or INTO table or UPDATE table
    match = re.search(r"(?:FROM|INTO|UPDATE)\s+[\"']?(\w+)[\"']?", sql, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def _detect_n1_patterns(queries: List[Dict[str, Any]], threshold: int = 3) -> List[Dict[str, Any]]:
    """Detect potential N+1 query patterns.

    Args:
        queries: List of query dictionaries with 'sql' key
        threshold: Minimum repetitions to flag as N+1

    Returns:
        List of detected N+1 patterns with details
    """
    patterns: Dict[str, List[int]] = {}

    for idx, q in enumerate(queries):
        normalized = _normalize_query(q.get("sql", ""))
        if normalized not in patterns:
            patterns[normalized] = []
        patterns[normalized].append(idx)

    n1_issues = []
    for pattern, indices in patterns.items():
        if len(indices) >= threshold:
            table = _extract_table_name(pattern)
            n1_issues.append(
                {
                    "pattern": pattern[:200],  # Truncate long patterns
                    "count": len(indices),
                    "table": table,
                    "query_indices": indices,
                }
            )

    return sorted(n1_issues, key=lambda x: x["count"], reverse=True)


def _format_text_log(request_data: Dict[str, Any], queries: List[Dict[str, Any]], n1_issues: List[Dict[str, Any]]) -> str:
    """Format request and queries as human-readable text.

    Args:
        request_data: Request metadata
        queries: List of executed queries
        n1_issues: Detected N+1 patterns

    Returns:
        Formatted text string
    """
    lines = []
    separator = "=" * 80

    # Header
    lines.append(separator)
    timestamp = request_data.get("timestamp", datetime.now(timezone.utc).isoformat())
    method = request_data.get("method", "?")
    path = request_data.get("path", "?")
    lines.append(f"[{timestamp}] {method} {path}")

    # Metadata line
    meta_parts = []
    if request_data.get("user"):
        meta_parts.append(f"User: {request_data['user']}")
    if request_data.get("correlation_id"):
        meta_parts.append(f"Correlation-ID: {request_data['correlation_id']}")
    meta_parts.append(f"Queries: {len(queries)}")
    total_ms = sum(q.get("duration_ms", 0) for q in queries)
    meta_parts.append(f"Total: {total_ms:.1f}ms")
    lines.append(" | ".join(meta_parts))
    lines.append(separator)

    # N+1 warnings at top if detected
    if n1_issues:
        lines.append("")
        lines.append("⚠️  POTENTIAL N+1 QUERIES DETECTED:")
        for issue in n1_issues:
            table_info = f" on '{issue['table']}'" if issue.get("table") else ""
            lines.append(f"   • {issue['count']}x similar queries{table_info}")
            lines.append(f"     Pattern: {issue['pattern'][:100]}...")
        lines.append("")

    # Query list
    for idx, q in enumerate(queries, 1):
        duration = q.get("duration_ms", 0)
        sql = q.get("sql", "")

        # Check if this query is part of an N+1 pattern
        n1_marker = ""
        for issue in n1_issues:
            if idx - 1 in issue.get("query_indices", []):
                n1_marker = "  ← N+1"
                break

        # Truncate long queries
        if len(sql) > 200:
            sql = sql[:200] + "..."

        lines.append(f"  {idx:3}. [{duration:6.1f}ms] {sql}{n1_marker}")

    # Footer
    lines.append("-" * 80)
    if n1_issues:
        lines.append(f"⚠️  {len(n1_issues)} potential N+1 pattern(s) detected - see docs/docs/development/db-performance.md")
    lines.append(f"Total: {len(queries)} queries, {total_ms:.1f}ms")
    lines.append(separator)
    lines.append("")

    return "\n".join(lines)


def _format_json_log(request_data: Dict[str, Any], queries: List[Dict[str, Any]], n1_issues: List[Dict[str, Any]]) -> str:
    """Format request and queries as JSON.

    Args:
        request_data: Request metadata
        queries: List of executed queries
        n1_issues: Detected N+1 patterns

    Returns:
        JSON string (single line)
    """
    total_ms = sum(q.get("duration_ms", 0) for q in queries)

    log_entry = {
        "timestamp": request_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "method": request_data.get("method"),
        "path": request_data.get("path"),
        "user": request_data.get("user"),
        "correlation_id": request_data.get("correlation_id"),
        "status_code": request_data.get("status_code"),
        "query_count": len(queries),
        "total_query_ms": round(total_ms, 2),
        "request_duration_ms": request_data.get("request_duration_ms"),
        "n1_issues": n1_issues if n1_issues else None,
        "queries": [
            {
                "sql": q.get("sql", "")[:500],  # Truncate long queries
                "duration_ms": round(q.get("duration_ms", 0), 2),
                "table": _extract_table_name(q.get("sql", "")),
            }
            for q in queries
        ],
    }

    return json.dumps(log_entry, default=str)


def _write_logs(request_data: Dict[str, Any], queries: List[Dict[str, Any]]) -> None:
    """Write query logs to file(s).

    Args:
        request_data: Request metadata
        queries: List of executed queries
    """
    settings = get_settings()

    # Skip if no queries or below threshold
    if not queries or len(queries) < settings.db_query_log_min_queries:
        return

    # Detect N+1 patterns
    n1_issues = []
    if settings.db_query_log_detect_n1:
        n1_issues = _detect_n1_patterns(queries, settings.db_query_log_n1_threshold)

    log_format = settings.db_query_log_format.lower()

    with _file_lock:
        # Write text log
        if log_format in ("text", "both"):
            text_path = Path(settings.db_query_log_file)
            text_path.parent.mkdir(parents=True, exist_ok=True)
            with open(text_path, "a", encoding="utf-8") as f:
                f.write(_format_text_log(request_data, queries, n1_issues))

        # Write JSON log
        if log_format in ("json", "both"):
            json_path = Path(settings.db_query_log_json_file)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(json_path, "a", encoding="utf-8") as f:
                f.write(_format_json_log(request_data, queries, n1_issues) + "\n")


def _before_cursor_execute(conn: Any, _cursor: Any, _statement: str, _parameters: Any, _context: Any, _executemany: bool) -> None:
    """SQLAlchemy event handler called before query execution.

    Args:
        conn: Database connection
        _cursor: Database cursor (unused, required by SQLAlchemy event signature)
        _statement: SQL statement to execute (unused, required by SQLAlchemy event signature)
        _parameters: Query parameters (unused, required by SQLAlchemy event signature)
        _context: Execution context (unused, required by SQLAlchemy event signature)
        _executemany: Whether this is an executemany call (unused, required by SQLAlchemy event signature)
    """
    ctx = _request_context.get()
    if ctx is None:
        return

    # Store start time on the connection
    conn.info["_query_start_time"] = time.perf_counter()


# Tables to exclude from query logging (internal/observability tables)
_EXCLUDED_TABLES = {
    "observability_traces",
    "observability_spans",
    "observability_events",
    "observability_metrics",
    "structured_log_entries",
    "audit_logs",
    "security_events",
}


def _should_exclude_query(statement: str) -> bool:
    """Check if a query should be excluded from logging.

    Args:
        statement: SQL statement

    Returns:
        True if the query should be excluded
    """
    statement_upper = statement.upper()
    for table in _EXCLUDED_TABLES:
        if table.upper() in statement_upper:
            return True
    return False


def _after_cursor_execute(conn: Any, _cursor: Any, statement: str, parameters: Any, _context: Any, executemany: bool) -> None:
    """SQLAlchemy event handler called after query execution.

    Args:
        conn: Database connection
        _cursor: Database cursor (unused, required by SQLAlchemy event signature)
        statement: SQL statement that was executed
        parameters: Query parameters
        _context: Execution context (unused, required by SQLAlchemy event signature)
        executemany: Whether this was an executemany call
    """
    ctx = _request_context.get()
    if ctx is None:
        return

    # Skip internal observability queries
    if _should_exclude_query(statement):
        conn.info.pop("_query_start_time", None)  # Clean up
        return

    # Calculate duration
    start_time = conn.info.pop("_query_start_time", None)
    duration_ms = (time.perf_counter() - start_time) * 1000 if start_time else 0

    # Get settings for parameter inclusion
    settings = get_settings()

    query_info = {
        "sql": statement,
        "duration_ms": duration_ms,
        "executemany": executemany,
    }

    if settings.db_query_log_include_params and parameters:
        # Sanitize parameters - don't include actual values by default
        query_info["param_count"] = len(parameters) if isinstance(parameters, (list, tuple, dict)) else 1

    ctx["queries"].append(query_info)


def instrument_engine_for_logging(engine: Engine) -> None:
    """Instrument a SQLAlchemy engine for query logging.

    Args:
        engine: SQLAlchemy engine to instrument
    """
    engine_id = id(engine)
    if engine_id in _instrumented_engines:
        return

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine, "after_cursor_execute", _after_cursor_execute)
    _instrumented_engines.add(engine_id)
    logger.info("Database query logging instrumentation enabled")


class DBQueryLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log database queries per request.

    This middleware:
    1. Creates a request context to collect queries
    2. Captures request metadata (method, path, user, correlation ID)
    3. After the request, writes all queries to log file(s)
    4. Detects and flags potential N+1 query patterns
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request and log database queries.

        Args:
            request: The incoming request
            call_next: Next middleware/handler

        Returns:
            Response from the handler
        """
        settings = get_settings()

        if not settings.db_query_log_enabled:
            return await call_next(request)

        # Skip static files and health checks
        path = request.url.path
        if path.startswith("/static") or path in ("/health", "/healthz", "/ready"):
            return await call_next(request)

        # Create request context
        ctx: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": request.method,
            "path": path,
            "user": None,
            "correlation_id": request.headers.get(settings.correlation_id_header),
            "queries": [],
        }

        # Try to get user from request state (set by auth middleware)
        if hasattr(request.state, "user"):
            ctx["user"] = getattr(request.state.user, "username", str(request.state.user))
        elif hasattr(request.state, "username"):
            ctx["user"] = request.state.username

        # Set context for SQLAlchemy event handlers
        token = _request_context.set(ctx)

        try:
            start_time = time.perf_counter()
            response = await call_next(request)
            request_duration = (time.perf_counter() - start_time) * 1000

            ctx["status_code"] = response.status_code
            ctx["request_duration_ms"] = round(request_duration, 2)

            return response
        finally:
            # Write logs
            try:
                _write_logs(ctx, ctx["queries"])
            except Exception as e:
                logger.warning(f"Failed to write query log: {e}")

            # Reset context
            _request_context.reset(token)


def setup_query_logging(app: Any, engine: Engine) -> None:
    """Set up database query logging for an application.

    Args:
        app: FastAPI application
        engine: SQLAlchemy engine
    """
    settings = get_settings()

    if not settings.db_query_log_enabled:
        return

    # Instrument the engine
    instrument_engine_for_logging(engine)

    # Add middleware
    app.add_middleware(DBQueryLoggingMiddleware)

    logger.info(f"Database query logging enabled: " f"format={settings.db_query_log_format}, " f"text_file={settings.db_query_log_file}, " f"json_file={settings.db_query_log_json_file}")
