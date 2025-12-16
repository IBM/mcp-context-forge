# -*- coding: utf-8 -*-
"""Database query counter for detecting N+1 patterns.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

This module provides utilities for counting and analyzing SQL queries,
useful for detecting N+1 query patterns and optimizing database access.

Examples:
    >>> from tests.helpers.query_counter import count_queries
    >>> from mcpgateway.db import engine
    >>> with count_queries(engine) as counter:  # doctest: +SKIP
    ...     # perform database operations
    ...     pass  # doctest: +SKIP
    >>> print(f"Executed {counter.count} queries")  # doctest: +SKIP
"""

from contextlib import contextmanager
import threading
import time
from typing import Any, Dict, Generator, List, Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine


class QueryCounter:
    """Thread-safe SQL query counter using SQLAlchemy events.

    Attributes:
        count: Number of queries executed
        queries: List of query details (statement, parameters, duration, etc.)
    """

    def __init__(self) -> None:
        """Initialize the query counter."""
        self.count: int = 0
        self.queries: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._start_times: Dict[int, float] = {}

    def _before_execute(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        """Record query start time.

        Args:
            conn: Database connection
            cursor: Database cursor
            statement: SQL statement
            parameters: Query parameters
            context: Execution context
            executemany: Whether this is a bulk operation
        """
        conn_id = id(conn)
        self._start_times[conn_id] = time.perf_counter()

    def _after_execute(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        """Record query completion and duration.

        Args:
            conn: Database connection
            cursor: Database cursor
            statement: SQL statement
            parameters: Query parameters
            context: Execution context
            executemany: Whether this is a bulk operation
        """
        conn_id = id(conn)
        start_time = self._start_times.pop(conn_id, time.perf_counter())
        duration_ms = (time.perf_counter() - start_time) * 1000

        with self._lock:
            self.count += 1
            self.queries.append(
                {
                    "index": self.count,
                    "statement": statement,
                    "parameters": parameters,
                    "executemany": executemany,
                    "duration_ms": duration_ms,
                }
            )

    def reset(self) -> None:
        """Reset the counter and clear query history."""
        with self._lock:
            self.count = 0
            self.queries = []
            self._start_times = {}

    @property
    def total_duration_ms(self) -> float:
        """Total duration of all queries in milliseconds."""
        return sum(q.get("duration_ms", 0) for q in self.queries)

    def get_slow_queries(self, threshold_ms: float = 10.0) -> List[Dict[str, Any]]:
        """Get queries slower than the threshold.

        Args:
            threshold_ms: Minimum duration to consider slow (default: 10ms)

        Returns:
            List of slow query details
        """
        return [q for q in self.queries if q.get("duration_ms", 0) > threshold_ms]

    def get_query_types(self) -> Dict[str, int]:
        """Get count of each query type (SELECT, INSERT, UPDATE, DELETE).

        Returns:
            Dictionary mapping query type to count
        """
        types: Dict[str, int] = {}
        for q in self.queries:
            stmt = q.get("statement", "").strip().upper()
            query_type = stmt.split()[0] if stmt else "UNKNOWN"
            types[query_type] = types.get(query_type, 0) + 1
        return types

    def print_summary(self, show_queries: bool = True, max_queries: int = 50) -> None:
        """Print a summary of executed queries.

        Args:
            show_queries: Whether to print individual queries
            max_queries: Maximum number of queries to print
        """
        print(f"\n{'=' * 70}")
        print(f"QUERY SUMMARY: {self.count} queries, {self.total_duration_ms:.2f}ms total")
        print(f"{'=' * 70}")

        types = self.get_query_types()
        print(f"Query types: {types}")

        slow = self.get_slow_queries()
        if slow:
            print(f"Slow queries (>10ms): {len(slow)}")

        if show_queries:
            print(f"\n{'─' * 70}")
            for i, q in enumerate(self.queries[:max_queries]):
                duration = q.get("duration_ms", 0)
                marker = "⚠️ " if duration > 10 else "   "
                stmt = q["statement"][:80].replace("\n", " ")
                print(f"{marker}{i + 1:3}. [{duration:6.2f}ms] {stmt}...")

            if len(self.queries) > max_queries:
                print(f"\n... and {len(self.queries) - max_queries} more queries")

        print(f"{'=' * 70}\n")


@contextmanager
def count_queries(
    engine: Engine,
    print_queries: bool = False,
    print_summary: bool = False,
) -> Generator[QueryCounter, None, None]:
    """Context manager to count SQL queries executed within a block.

    Args:
        engine: SQLAlchemy engine to monitor
        print_queries: If True, print each query as it's executed
        print_summary: If True, print summary after the block completes

    Yields:
        QueryCounter instance with query statistics

    Examples:
        >>> from sqlalchemy import create_engine
        >>> engine = create_engine("sqlite:///:memory:")
        >>> with count_queries(engine) as counter:  # doctest: +SKIP
        ...     # Your database code here
        ...     pass
        >>> assert counter.count >= 0  # doctest: +SKIP
    """
    counter = QueryCounter()

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        counter._before_execute(conn, cursor, statement, parameters, context, executemany)

    def after_execute(conn, cursor, statement, parameters, context, executemany):
        counter._after_execute(conn, cursor, statement, parameters, context, executemany)
        if print_queries:
            q = counter.queries[-1]
            print(f"[Query #{q['index']}] [{q['duration_ms']:.2f}ms] {statement[:100]}...")

    event.listen(engine, "before_cursor_execute", before_execute)
    event.listen(engine, "after_cursor_execute", after_execute)

    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", before_execute)
        event.remove(engine, "after_cursor_execute", after_execute)

        if print_summary:
            counter.print_summary()


@contextmanager
def assert_max_queries(
    engine: Engine,
    max_count: int,
    message: Optional[str] = None,
) -> Generator[QueryCounter, None, None]:
    """Context manager that asserts the query count stays within a limit.

    Args:
        engine: SQLAlchemy engine to monitor
        max_count: Maximum allowed query count
        message: Custom error message

    Yields:
        QueryCounter instance

    Raises:
        AssertionError: If query count exceeds max_count

    Examples:
        >>> from sqlalchemy import create_engine
        >>> engine = create_engine("sqlite:///:memory:")
        >>> with assert_max_queries(engine, 10):  # doctest: +SKIP
        ...     # Database operations that should use <= 10 queries
        ...     pass
    """
    with count_queries(engine) as counter:
        yield counter

    if counter.count > max_count:
        query_list = "\n".join(f"  {q['index']:3}. [{q['duration_ms']:6.2f}ms] {q['statement'][:80]}..." for q in counter.queries)
        default_msg = f"Expected at most {max_count} queries, got {counter.count}"
        raise AssertionError(f"{message or default_msg}\n\nQueries executed:\n{query_list}")


def detect_n_plus_one(
    counter: QueryCounter,
    threshold: int = 5,
) -> List[str]:
    """Analyze queries to detect potential N+1 patterns.

    Looks for repeated similar queries that might indicate N+1 access patterns.

    Args:
        counter: QueryCounter with recorded queries
        threshold: Minimum repetitions to flag as potential N+1

    Returns:
        List of warning messages for potential N+1 patterns
    """
    warnings = []

    # Normalize queries to detect patterns (remove specific IDs/values)
    import re

    patterns: Dict[str, int] = {}

    for q in counter.queries:
        stmt = q.get("statement", "")
        # Normalize: replace specific values with placeholders
        normalized = re.sub(r"'[^']*'", "'?'", stmt)
        normalized = re.sub(r"\b\d+\b", "?", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        patterns[normalized] = patterns.get(normalized, 0) + 1

    for pattern, count in patterns.items():
        if count >= threshold:
            warnings.append(f"Potential N+1: Query pattern repeated {count} times:\n  {pattern[:100]}...")

    return warnings
