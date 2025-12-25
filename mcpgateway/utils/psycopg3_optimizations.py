# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/psycopg3_optimizations.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

psycopg3-specific optimizations for database operations.

This module provides optimized database operations leveraging psycopg3's
advanced features:
- COPY protocol for bulk inserts (5-10x faster than INSERT)
- Pipeline mode for batch queries (reduced round-trips)
- Prepared statement hints

These optimizations are PostgreSQL-specific and gracefully fall back to
standard SQLAlchemy operations for other databases.

Examples:
    >>> from mcpgateway.utils.psycopg3_optimizations import is_psycopg3_backend
    >>> isinstance(is_psycopg3_backend(), bool)
    True
"""

# Standard
from datetime import datetime
import io
import logging
from typing import Any, Iterable, List, Optional, Sequence, Tuple, TypeVar

# Third-Party
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Check if we're using psycopg3 backend
_is_psycopg3: Optional[bool] = None


def is_psycopg3_backend() -> bool:
    """Check if the current database backend is PostgreSQL with psycopg3.

    Returns:
        True if using PostgreSQL with psycopg3 driver, False otherwise.

    Examples:
        >>> isinstance(is_psycopg3_backend(), bool)
        True
    """
    global _is_psycopg3
    if _is_psycopg3 is None:
        try:
            # First-Party
            from mcpgateway.db import backend, driver

            _is_psycopg3 = backend == "postgresql" and driver in ("psycopg", "default", "")
        except ImportError:
            _is_psycopg3 = False
    return _is_psycopg3


def _format_value_for_copy(value: Any) -> str:
    """Format a Python value for PostgreSQL COPY TEXT format.

    Args:
        value: The value to format.

    Returns:
        String representation suitable for COPY TEXT format.
    """
    if value is None:
        return "\\N"  # NULL representation in COPY
    if isinstance(value, bool):
        return "t" if value else "f"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        # Escape special characters for COPY TEXT format
        return value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    return str(value)


def bulk_insert_with_copy(
    db: Session,
    table_name: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    schema: Optional[str] = None,
) -> int:
    """Bulk insert rows using PostgreSQL COPY protocol.

    This is significantly faster than individual INSERT statements or even
    bulk_insert_mappings for large datasets. The COPY protocol streams data
    directly to PostgreSQL with minimal overhead.

    Args:
        db: SQLAlchemy session.
        table_name: Name of the target table.
        columns: Sequence of column names to insert.
        rows: Iterable of row tuples matching column order.
        schema: Optional schema name (defaults to search_path).

    Returns:
        Number of rows inserted.

    Note:
        Falls back to executemany for non-PostgreSQL databases.
    """
    if not is_psycopg3_backend():
        # Fallback to standard INSERT for non-PostgreSQL
        return _bulk_insert_fallback(db, table_name, columns, rows, schema)

    try:
        # Get raw psycopg connection from SQLAlchemy
        raw_conn = db.connection().connection.dbapi_connection

        # Build the qualified table name
        qualified_table = f"{schema}.{table_name}" if schema else table_name
        columns_str = ", ".join(columns)

        # Create a file-like object with COPY data
        buffer = io.StringIO()
        row_count = 0

        for row in rows:
            line = "\t".join(_format_value_for_copy(v) for v in row)
            buffer.write(line + "\n")
            row_count += 1

        if row_count == 0:
            return 0

        buffer.seek(0)

        # Use psycopg3's COPY FROM
        with raw_conn.cursor() as cur:
            with cur.copy(f"COPY {qualified_table} ({columns_str}) FROM STDIN") as copy:
                while data := buffer.read(8192):
                    copy.write(data)

        logger.debug("COPY inserted %d rows into %s", row_count, qualified_table)
        return row_count

    except Exception as e:
        logger.warning("COPY failed, falling back to INSERT: %s", e)
        return _bulk_insert_fallback(db, table_name, columns, rows, schema)


def _bulk_insert_fallback(
    db: Session,
    table_name: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    schema: Optional[str] = None,
) -> int:
    """Fallback bulk insert using executemany.

    Args:
        db: SQLAlchemy session.
        table_name: Name of the target table.
        columns: Sequence of column names to insert.
        rows: Iterable of row tuples matching column order.
        schema: Optional schema name.

    Returns:
        Number of rows inserted.
    """
    qualified_table = f"{schema}.{table_name}" if schema else table_name
    columns_str = ", ".join(columns)
    placeholders = ", ".join(f":{col}" for col in columns)

    sql = text(f"INSERT INTO {qualified_table} ({columns_str}) VALUES ({placeholders})")  # nosec B608 - table/columns from SQLAlchemy models, not user input

    row_list = list(rows)
    if not row_list:
        return 0

    # Convert rows to list of dicts
    data = [dict(zip(columns, row)) for row in row_list]
    db.execute(sql, data)

    return len(row_list)


T = TypeVar("T")


def execute_pipelined(
    db: Session,
    queries: Sequence[Tuple[str, dict]],
) -> List[List[Any]]:
    """Execute multiple queries in pipeline mode for reduced round-trips.

    Pipeline mode allows sending multiple queries without waiting for
    individual responses, significantly reducing latency for independent
    queries.

    Args:
        db: SQLAlchemy session.
        queries: Sequence of (sql_string, params_dict) tuples.

    Returns:
        List of result lists, one per query.

    Note:
        Falls back to sequential execution for non-PostgreSQL databases.
    """
    if not queries:
        return []

    if not is_psycopg3_backend():
        # Fallback to sequential execution
        return [list(db.execute(text(sql), params).fetchall()) for sql, params in queries]

    try:
        raw_conn = db.connection().connection.dbapi_connection

        results = []
        with raw_conn.pipeline():
            cursors = []
            for sql, params in queries:
                cur = raw_conn.execute(sql, params)
                cursors.append(cur)

            for cur in cursors:
                try:
                    results.append(list(cur.fetchall()))
                except Exception:
                    results.append([])

        logger.debug("Pipelined %d queries", len(queries))
        return results

    except Exception as e:
        logger.warning("Pipeline mode failed, falling back to sequential: %s", e)
        return [list(db.execute(text(sql), params).fetchall()) for sql, params in queries]


def bulk_insert_metrics(
    db: Session,
    table_name: str,
    metrics: Sequence[dict],
    columns: Optional[Sequence[str]] = None,
) -> int:
    """Optimized bulk insert for metric records.

    Uses COPY protocol on PostgreSQL for maximum performance when
    writing metrics data.

    Args:
        db: SQLAlchemy session.
        table_name: Name of the metrics table.
        metrics: Sequence of metric dictionaries.
        columns: Optional explicit column list. If not provided,
                 uses keys from first metric dict.

    Returns:
        Number of rows inserted.

    Examples:
        >>> # Example usage (would need actual DB connection):
        >>> # bulk_insert_metrics(db, "tool_metrics", [
        >>> #     {"tool_id": "abc", "timestamp": datetime.now(), "response_time": 0.5, "is_success": True}
        >>> # ])
    """
    if not metrics:
        return 0

    # Determine columns from first metric if not provided
    if columns is None:
        columns = list(metrics[0].keys())

    # Convert dicts to ordered tuples
    rows = [[m.get(col) for col in columns] for m in metrics]

    return bulk_insert_with_copy(db, table_name, columns, rows)


def get_raw_connection(db: Session) -> Any:
    """Get the raw psycopg3 connection from a SQLAlchemy session.

    Args:
        db: SQLAlchemy session.

    Returns:
        The underlying psycopg3 connection, or None if not using psycopg3.
    """
    if not is_psycopg3_backend():
        return None

    try:
        return db.connection().connection.dbapi_connection
    except Exception:
        return None
