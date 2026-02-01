# -*- coding: utf-8 -*-
"""Tests for psycopg3 optimization helpers."""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, List

# Third-Party
import pytest

# First-Party
from mcpgateway.utils import psycopg3_optimizations as psy


class DummyResult:
    def __init__(self, rows: List[Any]):
        self._rows = rows

    def fetchall(self):
        return self._rows


class DummyDB:
    def __init__(self, rows: List[Any]):
        self.rows = rows
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return DummyResult(self.rows)


def test_format_value_for_copy():
    assert psy._format_value_for_copy(None) == "\\N"
    assert psy._format_value_for_copy(True) == "t"
    assert psy._format_value_for_copy(False) == "f"

    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert psy._format_value_for_copy(now) == now.isoformat()

    text = "line1\tline2\nline3\\line4\r"
    assert psy._format_value_for_copy(text) == "line1\\tline2\\nline3\\\\line4\\r"
    assert psy._format_value_for_copy(123) == "123"


def test_bulk_insert_with_copy_fallback(monkeypatch):
    monkeypatch.setattr(psy, "_is_psycopg3", False)
    db = DummyDB(rows=[(1,)])

    count = psy.bulk_insert_with_copy(db, "my_table", ["id", "name"], [(1, "a"), (2, "b")])

    assert count == 2
    assert len(db.calls) == 1
    sql, data = db.calls[0]
    assert "INSERT INTO my_table" in str(sql)
    assert data == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]


def test_bulk_insert_with_copy_empty(monkeypatch):
    monkeypatch.setattr(psy, "_is_psycopg3", False)
    db = DummyDB(rows=[])

    count = psy.bulk_insert_with_copy(db, "my_table", ["id"], [])
    assert count == 0
    assert db.calls == []


def test_execute_pipelined_fallback(monkeypatch):
    monkeypatch.setattr(psy, "_is_psycopg3", False)
    db = DummyDB(rows=[("ok",)])

    results = psy.execute_pipelined(db, [("select 1", {"id": 1}), ("select 2", {"id": 2})])

    assert results == [[("ok",)], [("ok",)]]
    assert len(db.calls) == 2


def test_execute_pipelined_exception_fallback(monkeypatch):
    monkeypatch.setattr(psy, "_is_psycopg3", True)

    class FailingDB(DummyDB):
        def connection(self):
            raise RuntimeError("no raw connection")

    db = FailingDB(rows=[("fallback",)])
    results = psy.execute_pipelined(db, [("select 1", {}), ("select 2", {})])

    assert results == [[("fallback",)], [("fallback",)]]
    assert len(db.calls) == 2


def test_bulk_insert_metrics(monkeypatch):
    captured = {}

    def fake_bulk_insert(db, table_name, columns, rows, schema=None):
        captured["columns"] = list(columns)
        captured["rows"] = rows
        return 3

    monkeypatch.setattr(psy, "bulk_insert_with_copy", fake_bulk_insert)

    count = psy.bulk_insert_metrics(
        db=None,
        table_name="metrics",
        metrics=[
            {"tool_id": "t1", "value": 1},
            {"tool_id": "t2", "value": 2},
            {"tool_id": "t3", "value": 3},
        ],
    )

    assert count == 3
    assert captured["columns"] == ["tool_id", "value"]
    assert captured["rows"] == [["t1", 1], ["t2", 2], ["t3", 3]]


def test_get_raw_connection(monkeypatch):
    monkeypatch.setattr(psy, "_is_psycopg3", False)
    assert psy.get_raw_connection(db=None) is None

    monkeypatch.setattr(psy, "_is_psycopg3", True)

    class ConnDB:
        def connection(self):
            raise RuntimeError("boom")

    assert psy.get_raw_connection(ConnDB()) is None


def test_bulk_insert_with_copy_psycopg3_success(monkeypatch):
    monkeypatch.setattr(psy, "_is_psycopg3", True)

    class DummyCopy:
        def __init__(self):
            self.writes = []

        def write(self, data):
            self.writes.append(data)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyCursor:
        def __init__(self):
            self.copy_calls = []
            self.copy_obj = DummyCopy()

        def copy(self, cmd):
            self.copy_calls.append(cmd)
            return self.copy_obj

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyRawConn:
        def __init__(self):
            self.cursor_obj = DummyCursor()

        def cursor(self):
            return self.cursor_obj

    raw_conn = DummyRawConn()

    class DummyDB:
        def connection(self):
            return SimpleNamespace(connection=SimpleNamespace(dbapi_connection=raw_conn))

    db = DummyDB()
    count = psy.bulk_insert_with_copy(db, "items", ["id", "name"], [(1, "a"), (2, "b")])

    assert count == 2
    assert raw_conn.cursor_obj.copy_calls


def test_execute_pipelined_psycopg3_success(monkeypatch):
    monkeypatch.setattr(psy, "_is_psycopg3", True)

    class DummyCursor:
        def __init__(self, rows, raise_on_fetch=False):
            self._rows = rows
            self._raise_on_fetch = raise_on_fetch

        def fetchall(self):
            if self._raise_on_fetch:
                raise RuntimeError("fetch failed")
            return self._rows

    class DummyRawConn:
        def __init__(self):
            self.executed = []
            self._call_count = 0

        def pipeline(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            self.executed.append((sql, params))
            self._call_count += 1
            if self._call_count == 2:
                return DummyCursor([], raise_on_fetch=True)
            return DummyCursor([("ok",)])

    raw_conn = DummyRawConn()

    class DummyDB:
        def connection(self):
            return SimpleNamespace(connection=SimpleNamespace(dbapi_connection=raw_conn))

    db = DummyDB()
    results = psy.execute_pipelined(db, [("select 1", {"id": 1}), ("select 2", {"id": 2})])

    assert results == [[("ok",)], []]


def test_execute_pipelined_empty_queries(monkeypatch):
    monkeypatch.setattr(psy, "_is_psycopg3", True)
    assert psy.execute_pipelined(db=None, queries=[]) == []


def test_get_raw_connection_psycopg3_success(monkeypatch):
    monkeypatch.setattr(psy, "_is_psycopg3", True)
    raw_conn = object()

    class DummyDB:
        def connection(self):
            return SimpleNamespace(connection=SimpleNamespace(dbapi_connection=raw_conn))

    assert psy.get_raw_connection(DummyDB()) is raw_conn
