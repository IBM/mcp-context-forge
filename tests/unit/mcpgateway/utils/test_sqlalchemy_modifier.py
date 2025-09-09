# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_sqlalchemy_modifier.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

Comprehensive test suite for sqlalchemy_modiier.
This suite provides complete test coverage for:
- _ensure_list
- json_contains_expr
"""

import uuid
import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Table, Column, MetaData, JSON
from sqlalchemy.sql.elements import ClauseElement

# adjust import path to where your helper actually lives
from mcpgateway.utils.sqlalchemy_modifier import _ensure_list, json_contains_expr


def test__ensure_list_none_returns_empty():
    assert _ensure_list(None) == []


def test__ensure_list_string_returns_list():
    assert _ensure_list("foo") == ["foo"]


def test__ensure_list_iterable_returns_list():
    assert _ensure_list(["a", "b"]) == ["a", "b"]
    assert _ensure_list(("x", "y")) == ["x", "y"]


def make_session_with_dialect(name: str):
    """Helper to produce a session-like MagicMock with a bind whose dialect.name is set."""
    session = MagicMock()
    bind = MagicMock()
    bind.dialect = MagicMock()
    bind.dialect.name = name
    session.get_bind.return_value = bind
    return session


def make_column(table_name="tools", col_name="tags"):
    """Create a real SQLAlchemy Column element attached to a simple table. Useful for .contains()."""
    md = MetaData()
    tbl = Table(table_name, md, Column(col_name, JSON))
    return tbl.c[col_name]


def test_json_contains_expr_raises_on_empty_values():
    session = make_session_with_dialect("sqlite")
    col = make_column()
    with pytest.raises(ValueError):
        json_contains_expr(session, col, [])


def test_json_contains_expr_mysql_any_and_all():
    session = make_session_with_dialect("mysql")
    col = make_column()

    # any-of: expects json_overlaps or fallback
    expr_any = json_contains_expr(session, col, ["a", "b"], match_any=True)
    assert isinstance(expr_any, ClauseElement)
    # string representation should contain the function name
    assert "json_overlaps" in str(expr_any).lower() or "json_contains" in str(expr_any).lower()

    # all-of: json_contains([...]) == 1 expected
    expr_all = json_contains_expr(session, col, ["a", "b"], match_any=False)
    assert isinstance(expr_all, ClauseElement)
    assert "json_contains" in str(expr_all).lower()


def test_json_contains_expr_postgresql_any_and_all():
    session = make_session_with_dialect("postgresql")
    col = make_column(table_name="servers")

    # any-of: returns an OR of col.contains([...]) expressions (ClauseElement)
    expr_any = json_contains_expr(session, col, ["x", "y"], match_any=True)
    assert isinstance(expr_any, ClauseElement)

    # all-of: returns col.contains(list) (ClauseElement)
    expr_all = json_contains_expr(session, col, ["x", "y"], match_any=False)
    assert isinstance(expr_all, ClauseElement)


def test_json_contains_expr_sqlite_any_of_binds_params_correctly():
    session = make_session_with_dialect("sqlite")
    col = make_column(table_name="tools", col_name="tags")

    values = ["test1", "test2"]
    expr = json_contains_expr(session, col, values, match_any=True)

    # Should be a ClauseElement (text() based)
    assert isinstance(expr, ClauseElement)
    sql_text = str(expr).lower()
    assert "json_each" in sql_text  # uses json_each in SQLite branch
    # compiled params should include our two values
    compiled_params = expr.compile().params
    assert set(compiled_params.values()) == set(values)


def test_json_contains_expr_sqlite_all_of_and_combination():
    session = make_session_with_dialect("sqlite")
    col = make_column(table_name="tools", col_name="tags")

    values = ["one"]
    expr_single = json_contains_expr(session, col, values, match_any=False)
    assert isinstance(expr_single, ClauseElement)
    assert "json_each" in str(expr_single).lower()
    # params contain the single value
    assert list(expr_single.compile().params.values())[0] == "one"

    # multi-value AND (all-of)
    values_multi = ["a", "b"]
    expr_multi = json_contains_expr(session, col, values_multi, match_any=False)
    assert isinstance(expr_multi, ClauseElement)
    # ensure compiled params contain both
    assert set(expr_multi.compile().params.values()) == set(values_multi)


def test_json_contains_expr_unsupported_dialect_raises():
    session = make_session_with_dialect("oracle")
    col = make_column()
    with pytest.raises(RuntimeError):
        json_contains_expr(session, col, ["x"])
