# -*- coding: utf-8 -*-
"""Location: ./tests/helpers/observability.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Test synchronization for the background SQL-instrumentation span writer.

``instrument_sqlalchemy()`` (mcpgateway/instrumentation/sqlalchemy.py) starts a
single, process-wide background thread that dequeues and writes query spans
asynchronously, decoupled from the request that produced them. A test that
disposes its own SQLite engine (``engine.dispose()``) while a span for that
engine is still queued races the writer thread: the write can land after
disposal, when the connection pool no longer has a live connection to the
test's (often in-memory) database, raising
``sqlite3.OperationalError: no such table: observability_traces``.

Call ``drain_span_writer_queue()`` after the test body and before
``engine.dispose()`` in any fixture that enables observability + SQL
instrumentation on its own SQLite engine.
"""

# Standard
import time

# First-Party
from mcpgateway.instrumentation import sqlalchemy as sql_instrumentation


def drain_span_writer_queue(timeout: float = 5.0) -> None:
    """Block until the background span writer has processed all queued spans.

    Args:
        timeout: Maximum seconds to wait before giving up.

    Raises:
        AssertionError: If the queue is still non-empty after ``timeout`` seconds.
    """
    deadline = time.monotonic() + timeout
    pending_queue = sql_instrumentation._span_queue  # pylint: disable=protected-access
    while pending_queue.unfinished_tasks > 0:
        if time.monotonic() > deadline:
            raise AssertionError(f"Span writer queue did not drain within {timeout}s ({pending_queue.unfinished_tasks} span(s) still pending)")
        time.sleep(0.05)
