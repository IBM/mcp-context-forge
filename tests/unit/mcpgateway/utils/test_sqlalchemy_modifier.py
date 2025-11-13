# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_sqlalchemy_modifier.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

Comprehensive test suite for sqlalchemy_modiier.
This suite provides complete test coverage for:
- _ensure_list function
- json_contains_expr function across supported SQL dialects
"""

import pytest
import json
from unittest.mock import MagicMock, patch
from sqlalchemy import text, and_, or_, func
from typing import Any

from mcpgateway.utils.sqlalchemy_modifier import _ensure_list, json_contains_expr

class DummyColumn:
    def __init__(self, name: str = "col", table_name: str = "tbl"):
        self.name = name
        self.table = MagicMock(name=table_name)
        self.table.name = table_name

    def contains(self, value: Any) -> str:
        return f"contains({value})"

@pytest.fixture
def mock_session() -> Any:
    session = MagicMock()
    bind = MagicMock()
    session.get_bind.return_value = bind
    return session

def test_ensure_list_none():
    assert _ensure_list(None) == []

def test_ensure_list_string():
    assert _ensure_list("abc") == ["abc"]

def test_ensure_list_iterable():
    assert _ensure_list(["a", "b"]) == ["a", "b"]
    assert _ensure_list(("x", "y")) == ["x", "y"]

def test_json_contains_expr_empty_values(mock_session: Any):
    mock_session.get_bind().dialect.name = "mysql"
    with pytest.raises(ValueError):
        json_contains_expr(mock_session, DummyColumn(), [])

def test_json_contains_expr_unsupported_dialect(mock_session: Any):
    mock_session.get_bind().dialect.name = "oracle"
    with pytest.raises(RuntimeError):
        json_contains_expr(mock_session, DummyColumn(), ["a"])

def test_json_contains_expr_mysql_match_any(mock_session: Any):
    mock_session.get_bind().dialect.name = "mysql"
    col = DummyColumn()
    with patch("mcpgateway.utils.sqlalchemy_modifier.func.json_overlaps", return_value=1):
        expr = json_contains_expr(mock_session, col, ["a", "b"], match_any=True)
        assert expr == 1 == 1 or expr == (func.json_overlaps(col, json.dumps(["a", "b"])) == 1)

def test_json_contains_expr_mysql_match_all(mock_session: Any):
    mock_session.get_bind().dialect.name = "mysql"
    col = DummyColumn()
    with patch("mcpgateway.utils.sqlalchemy_modifier.func.json_contains", return_value=1):
        expr = json_contains_expr(mock_session, col, ["a", "b"], match_any=False)
        assert expr == 1 == 1 or expr == (func.json_contains(col, json.dumps(["a", "b"])) == 1)

def test_json_contains_expr_mysql_fallback(mock_session: Any):
    mock_session.get_bind().dialect.name = "mysql"
    col = DummyColumn()
    with patch("mcpgateway.utils.sqlalchemy_modifier.func.json_overlaps", side_effect=Exception("fail")):
        expr = json_contains_expr(mock_session, col, ["a", "b"], match_any=True)
        assert isinstance(expr, type(or_()))

def test_json_contains_expr_postgresql_match_any(mock_session: Any):
    mock_session.get_bind().dialect.name = "postgresql"
    col = DummyColumn()
    with patch("mcpgateway.utils.sqlalchemy_modifier.or_", return_value=MagicMock()) as mock_or:
        with patch.object(col, "contains", return_value=MagicMock()):
            expr = json_contains_expr(mock_session, col, ["a", "b"], match_any=True)
            mock_or.assert_called()
            assert expr is not None

def test_json_contains_expr_postgresql_match_all(mock_session: Any):
    mock_session.get_bind().dialect.name = "postgresql"
    col = DummyColumn()
    with patch.object(col, "contains", return_value=MagicMock()):
        expr = json_contains_expr(mock_session, col, ["a", "b"], match_any=False)
        assert expr is not None

def test_json_contains_expr_sqlite_match_any(mock_session: Any):
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn()
    expr = json_contains_expr(mock_session, col, ["a", "b"], match_any=True)
    assert isinstance(expr, type(text("EXISTS (SELECT 1)")))
    assert "EXISTS" in str(expr)

def test_json_contains_expr_sqlite_match_all(mock_session: Any):
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn()
    expr = json_contains_expr(mock_session, col, ["a", "b"], match_any=False)
    assert isinstance(expr, type(and_()))
    assert "EXISTS" in str(expr)

def test_json_contains_expr_sqlite_single_value(mock_session: Any):
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn()
    expr = json_contains_expr(mock_session, col, ["a"], match_any=False)
    assert isinstance(expr, type(text("EXISTS (SELECT 1)")))
    assert "EXISTS" in str(expr)
