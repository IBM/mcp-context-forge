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
- _generate_unique_prefix helper function
"""

import pytest
import json
from unittest.mock import MagicMock, patch
from sqlalchemy import text, and_, func, create_engine
from sqlalchemy.sql.elements import BooleanClauseList
from typing import Any

from mcpgateway.utils.sqlalchemy_modifier import (
    _ensure_list,
    json_contains_expr,
    json_contains_tag_expr,
    _generate_unique_prefix,
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
        assert isinstance(expr, BooleanClauseList)


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
    assert isinstance(expr, BooleanClauseList)
    assert "EXISTS" in str(expr)


def test_json_contains_expr_sqlite_single_value(mock_session: Any):
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn()
    expr = json_contains_expr(mock_session, col, ["a"], match_any=False)
    assert isinstance(expr, type(text("EXISTS (SELECT 1)")))
    assert "EXISTS" in str(expr)


# --- Tests for _generate_unique_prefix ---


def test_generate_unique_prefix_basic():
    """Test that unique prefixes are generated with counter suffix."""
    prefix1 = _generate_unique_prefix("tools.tags")
    prefix2 = _generate_unique_prefix("tools.tags")
    # Should start with sanitized column name
    assert prefix1.startswith("tools_tags_")
    assert prefix2.startswith("tools_tags_")
    # Each call should get a unique counter
    assert prefix1 != prefix2


def test_generate_unique_prefix_prevents_collision():
    """Test that different columns that sanitize to same string get unique prefixes."""
    # These would collide with simple sanitization: a_b.c -> a_b_c, a.b_c -> a_b_c
    prefix1 = _generate_unique_prefix("a_b.c")
    prefix2 = _generate_unique_prefix("a.b_c")
    # Both start with a_b_c_ but have different counter suffixes
    assert prefix1.startswith("a_b_c_")
    assert prefix2.startswith("a_b_c_")
    assert prefix1 != prefix2


# --- Tests for json_contains_tag_expr ---


def test_json_contains_tag_expr_empty_values(mock_session: Any):
    """Test that empty values raise ValueError."""
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn()
    with pytest.raises(ValueError):
        json_contains_tag_expr(mock_session, col, [])


def test_json_contains_tag_expr_sqlite_match_any(mock_session: Any):
    """Test SQLite tag filtering with match_any=True."""
    import re
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn(name="tags", table_name="tools")
    expr = json_contains_tag_expr(mock_session, col, ["api", "data"], match_any=True)
    expr_str = str(expr)
    assert "EXISTS" in expr_str
    assert "json_each" in expr_str
    # Check for pattern with unique counter: tools_tags_<counter>_p0, tools_tags_<counter>_p1
    assert re.search(r"tools_tags_\d+_p0", expr_str)
    assert re.search(r"tools_tags_\d+_p1", expr_str)


def test_json_contains_tag_expr_sqlite_match_all(mock_session: Any):
    """Test SQLite tag filtering with match_any=False (match all)."""
    import re
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn(name="tags", table_name="resources")
    expr = json_contains_tag_expr(mock_session, col, ["api", "data"], match_any=False)
    expr_str = str(expr)
    assert "EXISTS" in expr_str
    # match_all returns and_() of multiple EXISTS clauses
    assert re.search(r"resources_tags_\d+_p0", expr_str)
    assert re.search(r"resources_tags_\d+_p1", expr_str)


def test_json_contains_tag_expr_sqlite_single_tag(mock_session: Any):
    """Test SQLite tag filtering with a single tag value."""
    import re
    mock_session.get_bind().dialect.name = "sqlite"
    col = DummyColumn(name="tags", table_name="prompts")
    expr = json_contains_tag_expr(mock_session, col, ["single"], match_any=True)
    expr_str = str(expr)
    assert re.search(r"prompts_tags_\d+_p0", expr_str)
    # Should not have IN clause for single value
    assert "IN" not in expr_str


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

    # Verify all values are present (order doesn't matter due to unique counters)
    values = set(compiled.params.values())
    assert values == {"tag1", "tag2", "cat1", "cat2"}


def test_json_contains_tag_expr_same_column_no_collision(mock_session: Any):
    """Test that filtering the same column twice doesn't cause collision."""
    mock_session.get_bind().dialect.name = "sqlite"

    col = DummyColumn(name="tags", table_name="tools")

    # Filter same column twice (edge case)
    expr1 = json_contains_tag_expr(mock_session, col, ["tag1"], match_any=True)
    expr2 = json_contains_tag_expr(mock_session, col, ["tag2"], match_any=True)

    combined = and_(expr1, expr2)
    engine = create_engine("sqlite:///:memory:")
    compiled = combined.compile(engine)

    # Both params should be present with unique names
    assert len(compiled.params) == 2
    assert set(compiled.params.values()) == {"tag1", "tag2"}


# --- Tests for template functions ---


def test_sqlite_tag_any_template_uses_provided_prefix():
    """Test that _sqlite_tag_any_template uses the provided prefix."""
    tmpl = _sqlite_tag_any_template("resources.tags", "my_prefix", 2)
    tmpl_str = str(tmpl)
    assert "my_prefix_p0" in tmpl_str
    assert "my_prefix_p1" in tmpl_str


def test_sqlite_tag_all_template_uses_provided_prefix():
    """Test that _sqlite_tag_all_template uses the provided prefix."""
    tmpl = _sqlite_tag_all_template("prompts.tags", "custom_prefix", 3)
    tmpl_str = str(tmpl)
    assert "custom_prefix_p0" in tmpl_str
    assert "custom_prefix_p1" in tmpl_str
    assert "custom_prefix_p2" in tmpl_str


def test_sqlite_tag_any_template_single_value():
    """Test _sqlite_tag_any_template with single value uses equality, not IN."""
    tmpl = _sqlite_tag_any_template("tools.tags", "prefix", 1)
    tmpl_str = str(tmpl)
    assert "prefix_p0" in tmpl_str
    # Single value should use = not IN
    assert "IN" not in tmpl_str


# --- Tests for dict-format tags and PostgreSQL compilation ---


def test_sqlite_tag_template_handles_dict_format():
    """Test that SQLite template SQL supports dict-format tags with 'id' field extraction."""
    # The template should include json_extract for object types
    tmpl = _sqlite_tag_any_template("tools.tags", "prefix", 1)
    tmpl_str = str(tmpl)
    # Should handle both string values and object.id
    assert "json_extract(value, '$.id')" in tmpl_str
    assert "CASE WHEN type = 'object'" in tmpl_str


def test_json_contains_tag_expr_postgresql_compiles(mock_session: Any):
    """Test that PostgreSQL json_contains_tag_expr compiles valid SQL.

    The generated SQL uses:
    - CAST(col AS JSONB) @> for string tag matching
    - EXISTS (SELECT 1 FROM jsonb_array_elements(...) AS elem WHERE elem.value ->> 'id' = ...)
      for dict-format tag matching

    Uses table_valued() for idiomatic SQLAlchemy handling of table-valued functions,
    which produces explicit 'elem.value' column references.
    """
    from sqlalchemy import Column, JSON, MetaData, Table
    from sqlalchemy.dialects import postgresql

    mock_session.get_bind().dialect.name = "postgresql"

    # Create a real column for testing
    metadata = MetaData()
    test_table = Table('tools', metadata, Column('tags', JSON))
    col = test_table.c.tags

    expr = json_contains_tag_expr(mock_session, col, ["api", "data"], match_any=True)

    # Compile with PostgreSQL dialect
    compiled = expr.compile(dialect=postgresql.dialect())
    sql_str = str(compiled)

    # Verify key SQL components are present
    assert "CAST(tools.tags AS JSONB)" in sql_str
    assert "jsonb_array_elements" in sql_str
    assert "@>" in sql_str  # JSONB containment operator for string match
    assert "->> 'id'" in sql_str  # JSON text extraction for dict match

    # Verify the EXISTS subquery structure uses table_valued pattern:
    # Should have "FROM jsonb_array_elements(...) AS elem" with "elem.value ->>"
    import re
    # Pattern: jsonb_array_elements followed by alias
    assert re.search(r"jsonb_array_elements.*AS elem", sql_str), \
        f"Expected 'jsonb_array_elements(...) AS elem' pattern, got: {sql_str}"
    # Pattern: explicit column reference elem.value ->> 'id'
    assert re.search(r"\(elem\.value ->> 'id'\)", sql_str), \
        f"Expected '(elem.value ->> 'id')' pattern for dict tag extraction, got: {sql_str}"


def test_json_contains_tag_expr_postgresql_match_all(mock_session: Any):
    """Test PostgreSQL json_contains_tag_expr with match_any=False."""
    from sqlalchemy import Column, JSON, MetaData, Table
    from sqlalchemy.dialects import postgresql

    mock_session.get_bind().dialect.name = "postgresql"

    metadata = MetaData()
    test_table = Table('resources', metadata, Column('tags', JSON))
    col = test_table.c.tags

    expr = json_contains_tag_expr(mock_session, col, ["tag1", "tag2"], match_any=False)

    # Compile with PostgreSQL dialect
    compiled = expr.compile(dialect=postgresql.dialect())
    sql_str = str(compiled)

    # match_all should use AND between conditions
    assert "AND" in sql_str
    assert "jsonb_array_elements" in sql_str


def test_json_contains_tag_expr_unsupported_dialect(mock_session: Any):
    """Test that unsupported dialects raise RuntimeError."""
    mock_session.get_bind().dialect.name = "oracle"
    col = DummyColumn()
    with pytest.raises(RuntimeError, match="Unsupported dialect"):
        json_contains_tag_expr(mock_session, col, ["tag"])
