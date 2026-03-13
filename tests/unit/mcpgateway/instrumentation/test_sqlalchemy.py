# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/instrumentation/test_sqlalchemy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for sqlalchemy instrumentation.
"""
import pytest
import threading
import queue
import time
from unittest.mock import MagicMock, patch

import mcpgateway.instrumentation.sqlalchemy as sa


@pytest.fixture(autouse=True)
def reset_globals():
    # Reset thread-local storage by clearing the map attribute if it exists
    if hasattr(sa._query_tracking, "map"):
        sa._query_tracking.map.clear()
    sa._instrumentation_context = threading.local()
    # Reset to a fresh InstrumentationQueue with small maxsize for testing
    sa._span_queue = sa.InstrumentationQueue(maxsize=2)
    sa._shutdown_event.clear()
    sa._span_writer_thread = None
    yield
    # Clean up after test
    if hasattr(sa._query_tracking, "map"):
        sa._query_tracking.map.clear()


def test_before_cursor_execute_stores_tracking():
    conn = MagicMock()
    sa._before_cursor_execute(conn, None, "SELECT * FROM test", {"id": 1}, None, False)
    conn_id = id(conn)
    assert hasattr(sa._query_tracking, "map")
    assert conn_id in sa._query_tracking.map
    tracking = sa._query_tracking.map[conn_id]
    assert tracking["statement"] == "SELECT * FROM test"
    assert "start_time" in tracking


def test_after_cursor_execute_no_tracking():
    conn = MagicMock()
    sa._after_cursor_execute(conn, None, "SELECT * FROM test", None, None, False)
    # Should not raise or enqueue anything
    assert sa._span_queue._queue.empty()


def test_after_cursor_execute_inside_span_creation_skips():
    conn = MagicMock()
    conn_id = id(conn)
    if not hasattr(sa._query_tracking, "map"):
        sa._query_tracking.map = {}
    sa._query_tracking.map[conn_id] = {"start_time": time.time(), "statement": "SELECT 1", "parameters": None, "executemany": False}
    sa._instrumentation_context.inside_span_creation = True
    sa._after_cursor_execute(conn, MagicMock(), "SELECT 1", None, None, False)
    assert sa._span_queue._queue.empty()


def test_after_cursor_execute_observability_table_skips(caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    sa.logger.setLevel(logging.DEBUG)
    sa.logger.propagate = True
    conn = MagicMock()
    conn_id = id(conn)
    if not hasattr(sa._query_tracking, "map"):
        sa._query_tracking.map = {}
    sa._query_tracking.map[conn_id] = {"start_time": time.time(), "statement": "SELECT * FROM observability_spans", "parameters": None, "executemany": False}
    sa._after_cursor_execute(conn, MagicMock(), "SELECT * FROM observability_spans", None, None, False)
    assert "Skipping instrumentation" in caplog.text


def test_after_cursor_execute_with_trace_id_calls_create_query_span():
    conn = MagicMock()
    conn.info = {"trace_id": "abc123"}
    conn_id = id(conn)
    if not hasattr(sa._query_tracking, "map"):
        sa._query_tracking.map = {}
    sa._query_tracking.map[conn_id] = {"start_time": time.time(), "statement": "SELECT * FROM users", "parameters": None, "executemany": False}
    with patch.object(sa, "_create_query_span") as mock_create:
        sa._after_cursor_execute(conn, MagicMock(rowcount=5), "SELECT * FROM users", None, None, False)
        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        assert kwargs["trace_id"] == "abc123"


def test_after_cursor_execute_without_trace_id_logs_debug(caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    sa.logger.setLevel(logging.DEBUG)
    sa.logger.propagate = True
    conn = MagicMock()
    conn.info = {}
    conn_id = id(conn)
    if not hasattr(sa._query_tracking, "map"):
        sa._query_tracking.map = {}
    sa._query_tracking.map[conn_id] = {"start_time": time.time(), "statement": "SELECT * FROM users", "parameters": None, "executemany": False}
    sa._after_cursor_execute(conn, MagicMock(rowcount=5), "SELECT * FROM users", None, None, False)
    assert "Query executed without trace context" in caplog.text


def test_create_query_span_enqueues_successfully(caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    sa.logger.setLevel(logging.DEBUG)
    sa.logger.propagate = True
    sa._create_query_span("trace123", "SELECT * FROM test", 10.0, 5, False)
    assert not sa._span_queue._queue.empty()
    assert "Enqueued span" in caplog.text


def test_create_query_span_queue_full_warns(caplog):
    # Create a new queue with maxsize=1 and fill it
    sa._span_queue = sa.InstrumentationQueue(maxsize=1)
    sa._span_queue._queue.put({"dummy": "data"})
    sa._create_query_span("trace123", "SELECT * FROM test", 10.0, 5, False)
    assert "Span queue is full" in caplog.text


def test_create_query_span_exception_does_not_raise(caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    sa.logger.setLevel(logging.DEBUG)
    sa.logger.propagate = True
    with patch("mcpgateway.instrumentation.sqlalchemy._span_queue.put_nowait", side_effect=Exception("fail")):
        sa._create_query_span("trace123", "SELECT * FROM test", 10.0, 5, False)
    assert "Failed to enqueue query span" in caplog.text


def test_write_span_to_db_success():
    span_data = {
        "trace_id": "t1",
        "name": "db.query.select",
        "kind": "client",
        "resource_type": "database",
        "resource_name": "SELECT",
        "start_attributes": {},
        "end_attributes": {},
        "status": "ok",
        "duration_ms": 10.0,
        "row_count": 1,
    }
    mock_service = MagicMock()
    mock_db = MagicMock()
    mock_span = MagicMock()
    mock_db.query().filter_by().first.return_value = mock_span
    with patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service), \
         patch("mcpgateway.db.SessionLocal", return_value=mock_db), \
         patch("mcpgateway.db.ObservabilitySpan", MagicMock()):
        sa._write_span_to_db(span_data)
    mock_service.start_span.assert_called_once()
    mock_service.end_span.assert_called_once()
    mock_db.commit.assert_called_once()


def test_write_span_to_db_when_span_row_missing():
    span_data = {
        "trace_id": "t1",
        "name": "db.query.select",
        "kind": "client",
        "resource_type": "database",
        "resource_name": "SELECT",
        "start_attributes": {},
        "end_attributes": {},
        "status": "ok",
        "duration_ms": 10.0,
        "row_count": 1,
    }
    mock_service = MagicMock()
    mock_db = MagicMock()
    mock_db.query().filter_by().first.return_value = None
    with patch("mcpgateway.services.observability_service.ObservabilityService", return_value=mock_service), patch("mcpgateway.db.SessionLocal", return_value=mock_db), patch("mcpgateway.db.ObservabilitySpan", MagicMock()):
        sa._write_span_to_db(span_data)

    mock_service.start_span.assert_called_once()
    mock_service.end_span.assert_called_once()
    mock_db.commit.assert_not_called()


def test_write_span_to_db_exception_logs_warning(caplog):
    with patch("mcpgateway.services.observability_service.ObservabilityService", side_effect=Exception("fail")):
        sa._write_span_to_db({})
    assert "Failed to write query span" in caplog.text


def test_span_writer_worker_processes_queue(monkeypatch):
    span_data = {"trace_id": "t1", "name": "db.query.select", "kind": "client", "resource_type": "database", "resource_name": "SELECT", "start_attributes": {}, "end_attributes": {}, "status": "ok", "duration_ms": 10.0}
    sa._span_queue.put(span_data)
    mock_write = MagicMock()
    monkeypatch.setattr(sa, "_write_span_to_db", mock_write)
    thread = threading.Thread(target=lambda: (time.sleep(0.1), sa._shutdown_event.set()))
    thread.start()
    sa._span_writer_worker()
    mock_write.assert_called_once()


def test_span_writer_worker_logs_error_on_write_failure(monkeypatch, caplog):
    sa._span_queue.put({"trace_id": "t1"})

    def _boom(_span):
        raise RuntimeError("write failed")

    monkeypatch.setattr(sa, "_write_span_to_db", _boom)

    stopper = threading.Thread(target=lambda: (time.sleep(0.1), sa._shutdown_event.set()))
    stopper.start()
    sa._span_writer_worker()

    assert "Error in span writer worker" in caplog.text


def test_instrument_sqlalchemy_starts_thread_and_registers_events():
    engine = MagicMock()
    with patch("mcpgateway.instrumentation.sqlalchemy.event.listen") as mock_listen, \
         patch("mcpgateway.instrumentation.sqlalchemy.threading.Thread") as mock_thread:
        mock_thread.return_value = MagicMock(is_alive=lambda: False)
        sa.instrument_sqlalchemy(engine)
        assert mock_listen.call_count == 2
        mock_thread.assert_called_once()


def test_instrument_sqlalchemy_does_not_restart_alive_thread():
    engine = MagicMock()
    alive_thread = MagicMock()
    alive_thread.is_alive.return_value = True
    sa._span_writer_thread = alive_thread

    with patch("mcpgateway.instrumentation.sqlalchemy.event.listen") as mock_listen, patch("mcpgateway.instrumentation.sqlalchemy.threading.Thread") as mock_thread:
        sa.instrument_sqlalchemy(engine)

    assert mock_listen.call_count == 2
    mock_thread.assert_not_called()


def test_attach_trace_to_session_sets_trace_id():
    session = MagicMock()
    connection = MagicMock()
    connection.info = {}
    session.bind = True
    session.connection.return_value = connection
    sa.attach_trace_to_session(session, "trace123")
    assert connection.info["trace_id"] == "trace123"


def test_after_cursor_execute_handles_rowcount_exception_and_no_trace():
    conn = MagicMock()
    conn.info = {}
    conn_id = id(conn)
    if not hasattr(sa._query_tracking, "map"):
        sa._query_tracking.map = {}
    sa._query_tracking.map[conn_id] = {"start_time": time.time(), "statement": "SELECT * FROM users", "parameters": None, "executemany": False}

    class Cursor:
        @property
        def rowcount(self):
            raise RuntimeError("no rowcount")

    sa._after_cursor_execute(conn, Cursor(), "SELECT * FROM users", None, None, False)
    assert sa._span_queue._queue.empty()


def test_after_cursor_execute_negative_rowcount_skips_assignment():
    conn = MagicMock()
    conn.info = {}
    conn_id = id(conn)
    if not hasattr(sa._query_tracking, "map"):
        sa._query_tracking.map = {}
    sa._query_tracking.map[conn_id] = {"start_time": time.time(), "statement": "SELECT * FROM users", "parameters": None, "executemany": False}

    cursor = MagicMock()
    cursor.rowcount = -1

    sa._after_cursor_execute(conn, cursor, "SELECT * FROM users", None, None, False)
    assert sa._span_queue._queue.empty()


def test_attach_trace_to_session_no_bind_noop():
    session = MagicMock()
    session.bind = None
    sa.attach_trace_to_session(session, "trace123")
    session.connection.assert_not_called()




def test_instrumentation_queue_init_with_settings_exception():
    """Test InstrumentationQueue initialization when settings access fails."""
    # Mock getattr to raise exception when accessing instrumentation_queue_size
    original_getattr = getattr

    def mock_getattr(obj, name, default=None):
        if name == "instrumentation_queue_size":
            raise Exception("settings error")
        return original_getattr(obj, name, default) if default is not None else original_getattr(obj, name)

    with patch("builtins.getattr", side_effect=mock_getattr):
        queue = sa.InstrumentationQueue()
        # Should fall back to default 1000
        assert queue._maxsize == 1000


def test_attach_trace_to_session_connection_without_info():
    session = MagicMock()
    session.bind = True
    session.connection.return_value = object()
    sa.attach_trace_to_session(session, "trace123")
