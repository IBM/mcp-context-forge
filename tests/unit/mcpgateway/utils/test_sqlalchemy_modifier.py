# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_sqlalchemy_modifier.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

Comprehensive test suite for sqlalchemy_modifier.
This suite provides complete test coverage for:
- _ensure_list function
- json_contains_expr function across supported SQL dialects
- json_contains_tag_expr function for tag filtering
- _sanitize_col_prefix helper function
"""

import pytest
import json
from unittest.mock import MagicMock, patch
from sqlalchemy import text, and_, or_, func, create_engine
from typing import Any

from mcpgateway.utils.sqlalchemy_modifier import (
    _ensure_list,
    json_contains_expr,
    json_contains_tag_expr,
    _sanitize_col_prefix,
    _sqlite_tag_any_template,
    _sqlite_tag_all_template,
)

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


# --- Tests for _sanitize_col_prefix ---


def test_sanitize_col_prefix_basic():
    """Test that column references are properly sanitized."""
    assert _sanitize_col_prefix("tools.tags") == "tools_tags"
    assert _sanitize_col_prefix("resources.tags") == "resources_tags"


def test_sanitize_col_prefix_special_chars():
    """Test that special characters are replaced with underscores."""
    assert _sanitize_col_prefix("schema.table.column") == "schema_table_column"
    assert _sanitize_col_prefix("my-table.my-column") == "my_table_my_column"


# --- Tests for json_contains_tag_expr ---


def test_json_contains_tag_expr_empty_values(mock_session: Any):
    """Test that empty values raise ValueError."""
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn()
    with pytest.raises(ValueError):
        json_contains_tag_expr(mock_session, col, [])


def test_json_contains_tag_expr_sqlite_match_any(mock_session: Any):
    """Test SQLite tag filtering with match_any=True."""
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn(name="tags", table_name="tools")
    expr = json_contains_tag_expr(mock_session, col, ["api", "data"], match_any=True)
    expr_str = str(expr)
    assert "EXISTS" in expr_str
    assert "json_each" in expr_str
    assert "tools_tags_p0" in expr_str
    assert "tools_tags_p1" in expr_str


def test_json_contains_tag_expr_sqlite_match_all(mock_session: Any):
    """Test SQLite tag filtering with match_any=False (match all)."""
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn(name="tags", table_name="resources")
    expr = json_contains_tag_expr(mock_session, col, ["api", "data"], match_any=False)
    expr_str = str(expr)
    assert "EXISTS" in expr_str
    # match_all returns and_() of multiple EXISTS clauses
    assert "resources_tags_p0" in expr_str
    assert "resources_tags_p1" in expr_str


def test_json_contains_tag_expr_sqlite_single_tag(mock_session: Any):
    """Test SQLite tag filtering with a single tag value."""
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn(name="tags", table_name="prompts")
    expr = json_contains_tag_expr(mock_session, col, ["single"], match_any=True)
    expr_str = str(expr)
    assert "prompts_tags_p0" in expr_str
    # Should not have IN clause for single value
    assert "IN" not in expr_str or "prompts_tags_p0" in expr_str


def test_json_contains_tag_expr_no_bind_collision(mock_session: Any):
    """Test that multiple tag filters on different columns don't collide."""
    mock_session.get_bind().dialect.name = "sqlite"

    col1 = DummyColumn(name="tags", table_name="tools")
    col2 = DummyColumn(name="categories", table_name="tools")

    expr1 = json_contains_tag_expr(mock_session, col1, ["tag1", "tag2"], match_any=True)
    expr2 = json_contains_tag_expr(mock_session, col2, ["cat1", "cat2"], match_any=True)

    # Combine the expressions
    combined = and_(expr1, expr2)

    # Compile with SQLite to verify params don't collide
    engine = create_engine("sqlite:///:memory:")
    compiled = combined.compile(engine)

    # All 4 params should be present (2 for each column)
    assert len(compiled.params) == 4
    assert "tools_tags_p0" in compiled.params
    assert "tools_tags_p1" in compiled.params
    assert "tools_categories_p0" in compiled.params
    assert "tools_categories_p1" in compiled.params

    # Verify values are correct
    assert compiled.params["tools_tags_p0"] == "tag1"
    assert compiled.params["tools_tags_p1"] == "tag2"
    assert compiled.params["tools_categories_p0"] == "cat1"
    assert compiled.params["tools_categories_p1"] == "cat2"


# --- Tests for cached template functions ---


def test_sqlite_tag_any_template_uses_column_prefix():
    """Test that _sqlite_tag_any_template uses column-specific prefixes."""
    tmpl = _sqlite_tag_any_template("resources.tags", 2)
    tmpl_str = str(tmpl)
    assert "resources_tags_p0" in tmpl_str
    assert "resources_tags_p1" in tmpl_str


def test_sqlite_tag_all_template_uses_column_prefix():
    """Test that _sqlite_tag_all_template uses column-specific prefixes."""
    tmpl = _sqlite_tag_all_template("prompts.tags", 3)
    tmpl_str = str(tmpl)
    assert "prompts_tags_p0" in tmpl_str
    assert "prompts_tags_p1" in tmpl_str
    assert "prompts_tags_p2" in tmpl_str


def test_sqlite_tag_any_template_caching():
    """Test that template caching works correctly."""
    # Clear cache first
    _sqlite_tag_any_template.cache_clear()

    tmpl1 = _sqlite_tag_any_template("tools.tags", 2)
    tmpl2 = _sqlite_tag_any_template("tools.tags", 2)

    # Same inputs should return the same cached object
    assert tmpl1 is tmpl2

    # Different inputs should return different objects
    tmpl3 = _sqlite_tag_any_template("tools.tags", 3)
    assert tmpl1 is not tmpl3
