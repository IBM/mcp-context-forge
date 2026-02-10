# -*- coding: utf-8 -*-
"""Tests for DB query logging middleware."""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import orjson
import pytest
from starlette.responses import Response

# First-Party
from mcpgateway.middleware import db_query_logging as dql


class DummySettings:
    def __init__(self, **kwargs):
        self.db_query_log_enabled = kwargs.get("db_query_log_enabled", True)
        self.db_query_log_min_queries = kwargs.get("db_query_log_min_queries", 0)
        self.db_query_log_detect_n1 = kwargs.get("db_query_log_detect_n1", True)
        self.db_query_log_n1_threshold = kwargs.get("db_query_log_n1_threshold", 2)
        self.db_query_log_format = kwargs.get("db_query_log_format", "json")
        self.db_query_log_file = kwargs.get("db_query_log_file", "/tmp/db-queries.log")
        self.db_query_log_json_file = kwargs.get("db_query_log_json_file", "/tmp/db-queries.jsonl")
        self.db_query_log_include_params = kwargs.get("db_query_log_include_params", True)
        self.correlation_id_header = kwargs.get("correlation_id_header", "x-correlation-id")


def test_normalize_query_replaces_literals():
    sql = "SELECT * FROM tools WHERE id=123 AND name='bob' AND id IN (1,2,3)"
    normalized = dql._normalize_query(sql)
    assert "?" in normalized
    assert "IN (?)" in normalized
    assert "'?'" in normalized


def test_extract_table_name():
    assert dql._extract_table_name("select * from tools") == "tools"
    assert dql._extract_table_name("UPDATE resources SET name='x'") == "resources"
    assert dql._extract_table_name("INSERT INTO metrics (id) VALUES (1)") == "metrics"


def test_detect_n1_patterns():
    queries = [
        {"sql": "select * from tools where id=1"},
        {"sql": "select * from tools where id=2"},
        {"sql": "select * from resources where id=1"},
    ]
    issues = dql._detect_n1_patterns(queries, threshold=2)
    assert len(issues) == 1
    assert issues[0]["count"] == 2
    assert issues[0]["table"] == "tools"


def test_format_text_log_and_json_log():
    request_data = {"method": "GET", "path": "/tools", "timestamp": "2025-01-01T00:00:00Z"}
    queries = [
        {"sql": "select * from tools", "duration_ms": 1.2},
        {"sql": "select * from tools", "duration_ms": 2.3},
    ]
    issues = dql._detect_n1_patterns(queries, threshold=2)

    text = dql._format_text_log(request_data, queries, issues)
    assert "POTENTIAL N+1" in text
    assert "GET /tools" in text

    json_text = dql._format_json_log(request_data, queries, issues)
    payload = orjson.loads(json_text)
    assert payload["query_count"] == 2
    assert payload["n1_issues"]


def test_should_exclude_query():
    assert dql._should_exclude_query("select * from observability_traces") is True
    assert dql._should_exclude_query("select * from tools") is False


def test_before_and_after_cursor_execute_records_query(monkeypatch: pytest.MonkeyPatch):
    ctx = {"queries": []}
    token = dql._request_context.set(ctx)

    try:
        conn = SimpleNamespace(info={})
        dql._before_cursor_execute(conn, None, "select * from tools", None, None, False)
        assert "_query_start_time" in conn.info

        monkeypatch.setattr(dql, "get_settings", lambda: DummySettings(db_query_log_include_params=True))
        dql._after_cursor_execute(conn, None, "select * from tools", [1, 2], None, False)

        assert len(ctx["queries"]) == 1
        assert ctx["queries"][0]["param_count"] == 2
    finally:
        dql._request_context.reset(token)


def test_after_cursor_execute_skips_excluded(monkeypatch: pytest.MonkeyPatch):
    ctx = {"queries": []}
    token = dql._request_context.set(ctx)

    try:
        conn = SimpleNamespace(info={"_query_start_time": 0})
        monkeypatch.setattr(dql, "get_settings", lambda: DummySettings())
        dql._after_cursor_execute(conn, None, "select * from observability_traces", None, None, False)
        assert ctx["queries"] == []
    finally:
        dql._request_context.reset(token)


def test_instrument_engine_for_logging_idempotent(monkeypatch: pytest.MonkeyPatch):
    engine = MagicMock()
    monkeypatch.setattr(dql, "_instrumented_engines", set())
    listen_calls = []

    def fake_listen(*args, **kwargs):
        listen_calls.append(args)

    monkeypatch.setattr(dql.event, "listen", fake_listen)

    dql.instrument_engine_for_logging(engine)
    dql.instrument_engine_for_logging(engine)

    assert len(listen_calls) == 2  # before/after registered once


@pytest.mark.asyncio
async def test_middleware_dispatch_disabled(monkeypatch: pytest.MonkeyPatch):
    middleware = dql.DBQueryLoggingMiddleware(app=None)
    request = MagicMock()
    request.method = "GET"
    request.url.path = "/tools"
    request.headers = {}
    request.state = SimpleNamespace()

    monkeypatch.setattr(dql, "get_settings", lambda: DummySettings(db_query_log_enabled=False))
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_dispatch_skips_path(monkeypatch: pytest.MonkeyPatch):
    middleware = dql.DBQueryLoggingMiddleware(app=None)
    request = MagicMock()
    request.method = "GET"
    request.url.path = "/health"
    request.headers = {}
    request.state = SimpleNamespace()

    monkeypatch.setattr(dql, "get_settings", lambda: DummySettings(db_query_log_enabled=True))
    monkeypatch.setattr(dql, "should_skip_db_query_logging", lambda path: True)
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_dispatch_writes_logs(monkeypatch: pytest.MonkeyPatch):
    middleware = dql.DBQueryLoggingMiddleware(app=None)
    request = MagicMock()
    request.method = "GET"
    request.url.path = "/tools"
    request.headers = {"x-correlation-id": "cid"}
    request.state = SimpleNamespace(username="tester")

    monkeypatch.setattr(dql, "get_settings", lambda: DummySettings(db_query_log_enabled=True))
    monkeypatch.setattr(dql, "should_skip_db_query_logging", lambda path: False)
    monkeypatch.setattr(dql, "_write_logs", lambda *args, **kwargs: None)

    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once()


def test_setup_query_logging(monkeypatch: pytest.MonkeyPatch):
    app = MagicMock()
    engine = MagicMock()

    monkeypatch.setattr(dql, "get_settings", lambda: DummySettings(db_query_log_enabled=False))
    dql.setup_query_logging(app, engine)
    app.add_middleware.assert_not_called()

    monkeypatch.setattr(dql, "get_settings", lambda: DummySettings(db_query_log_enabled=True))
    monkeypatch.setattr(dql, "instrument_engine_for_logging", MagicMock())
    dql.setup_query_logging(app, engine)
    app.add_middleware.assert_called_once()
