# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_translate_jsonpath_filters_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the jq-to-CEL jsonpath_filter translation migration.
"""

# Standard
import importlib
import logging
from unittest.mock import patch

# Third-Party
import pytest
from sqlalchemy import create_engine, text

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.cel_runner import CelEvaluationError, check_expression, evaluate_value

MIGRATION_MODULE = "mcpgateway.alembic.versions.f2c3d4e5a6b7_translate_jsonpath_filters_to_cel"

TRANSLATED = [
    (".", "[response]"),
    (".a", "[response.a]"),
    (".data.items", "[response.data.items]"),
    (".[0]", "[response[0]]"),
    (".a[2].b", "[response.a[2].b]"),
    (".[].a", "response.map(x, x.a)"),
    (".items[].name", "response.items.map(x, x.name)"),
    (".data.items[].id", "response.data.items.map(x, x.id)"),
    (".items[]", "response.items"),
    (".[]", "response"),
    (" .a ", "[response.a]"),
]

LEFT_ALONE = ["$.main", "$ENV", "select(.a)", ".a | .b", ".[].a[].b", '.["a-b"]', ".a?", "user@example.com", "response.a", ".null", ".true", ".false", ".in", ".a.null", ".items[].in"]

# One response, and what jq produced for each translated filter on it.
RESPONSE = {"a": {"b": "ab"}, "data": {"items": [{"id": 1}, {"id": 2}]}, "items": [{"name": "x"}, {"name": "y"}]}
LIST_RESPONSE = [{"a": 10}, {"a": 20}, {"a": 30}]
EVALUATED = [
    ("[response]", RESPONSE, [RESPONSE]),
    ("[response.a]", RESPONSE, [{"b": "ab"}]),
    ("[response.data.items]", RESPONSE, [[{"id": 1}, {"id": 2}]]),
    ("[response[0]]", LIST_RESPONSE, [{"a": 10}]),
    ("[response.a[2].b]", {"a": [0, 1, {"b": "deep"}]}, ["deep"]),
    ("response.map(x, x.a)", LIST_RESPONSE, [10, 20, 30]),
    ("response.items.map(x, x.name)", RESPONSE, ["x", "y"]),
    ("response.data.items.map(x, x.id)", RESPONSE, [1, 2]),
    ("response.items", RESPONSE, [{"name": "x"}, {"name": "y"}]),
    ("response", LIST_RESPONSE, LIST_RESPONSE),
]


@pytest.fixture
def migration():
    """Load the migration module."""
    return importlib.import_module(MIGRATION_MODULE)


@pytest.fixture
def inprocess(monkeypatch):
    """Evaluate filters in the test process so these tests need no sandbox."""
    monkeypatch.setattr(settings, "cel_execution", "inprocess")


@pytest.mark.parametrize("jq,cel", TRANSLATED)
def test_jq_to_cel(migration, jq, cel):
    """Each simple jq shape has one CEL equivalent."""
    assert migration.jq_to_cel(jq) == cel


@pytest.mark.parametrize("cel", sorted({cel for _jq, cel in TRANSLATED}))
def test_every_translation_compiles(cel):
    """What the upgrade writes is accepted by the same check a new filter must pass."""
    assert check_expression(cel, {"response"}) is None


@pytest.mark.parametrize("cel,response,expected", EVALUATED)
def test_every_translation_keeps_the_jq_result(inprocess, cel, response, expected):
    """A translated filter returns what jq returned, including jq's list wrapping."""
    assert evaluate_value(cel, {"response": response}) == expected


def test_each_on_an_object_response_fails_loudly(inprocess):
    """jq walked an object's values for ``.[]``; CEL ``map`` walks its keys, so the call errors instead of answering differently."""
    with pytest.raises(CelEvaluationError):
        evaluate_value("response.map(x, x.a)", {"response": {"k": {"a": 1}}})


def test_missing_field_fails_loudly(inprocess):
    """jq answered ``[null]`` for a missing field; the translated filter reports an error."""
    with pytest.raises(CelEvaluationError):
        evaluate_value("[response.missing]", {"response": {"a": 1}})


@pytest.mark.parametrize("jq", LEFT_ALONE)
def test_jq_to_cel_refuses_anything_else(migration, jq):
    """A filter outside the simple shapes, or through a CEL keyword, is not guessed at."""
    assert migration.jq_to_cel(jq) is None


@pytest.mark.parametrize("jq,cel", [(jq.strip(), cel) for jq, cel in TRANSLATED])
def test_cel_to_jq_reverses_the_translation(migration, jq, cel):
    """Downgrade restores the original jq for every translated shape, iteration included."""
    assert migration.cel_to_jq(cel) == jq


@pytest.mark.parametrize("cel", ["response.items.filter(x, x.a)", "response.map(i, i.a)", '{"n": response.a}', "response.a + 1", ".a", "[response.a, 1]"])
def test_cel_to_jq_refuses_hand_written_cel(migration, cel):
    """A CEL expression that was not produced by the upgrade has no jq form."""
    assert migration.cel_to_jq(cel) is None


@pytest.fixture
def connection():
    """Create a minimal tools table."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tools (id TEXT PRIMARY KEY, name TEXT, jsonpath_filter TEXT)"))
        rows = [("t1", ".a"), ("t2", ".data.items[].id"), ("t3", ""), ("t4", None), ("t5", "$.main"), ("t6", "response.items.filter(x, x.a)"), ("t7", "select(.a)")]
        for tool_id, stored in rows:
            conn.execute(text("INSERT INTO tools VALUES (:id, :name, :f)"), {"id": tool_id, "name": f"tool-{tool_id}", "f": stored})
    with engine.begin() as conn:
        yield conn
    engine.dispose()


def _filters(connection):
    """Read every stored filter keyed by tool id."""
    return dict(connection.execute(text("SELECT id, jsonpath_filter FROM tools ORDER BY id")).all())


def test_upgrade_translates_simple_filters_and_warns_about_the_rest(migration, connection, caplog):
    """Simple jq paths become CEL, the rest stay as stored and are named in a warning."""
    with patch.object(migration.op, "get_bind", return_value=connection), caplog.at_level(logging.WARNING, logger=MIGRATION_MODULE):
        migration.upgrade()

    assert _filters(connection) == {"t1": "[response.a]", "t2": "response.data.items.map(x, x.id)", "t3": "", "t4": None, "t5": "$.main", "t6": "response.items.filter(x, x.a)", "t7": "select(.a)"}
    warned = [record.getMessage() for record in caplog.records]
    assert any("'tool-t5'" in message and "(id t5)" in message and "$.main" in message and "CEL" in message for message in warned)
    assert any("t7" in message and "select(.a)" in message for message in warned)
    assert not any("t6" in message for message in warned)


def test_upgrade_is_idempotent(migration, connection):
    """Running the upgrade twice changes nothing the second time."""
    with patch.object(migration.op, "get_bind", return_value=connection):
        migration.upgrade()
        first = _filters(connection)
        migration.upgrade()
    assert _filters(connection) == first


def test_downgrade_restores_the_translated_filters(migration, connection, caplog):
    """Downgrade reverses the upgrade and leaves CEL that has no jq form, with a warning."""
    with patch.object(migration.op, "get_bind", return_value=connection), caplog.at_level(logging.WARNING, logger=MIGRATION_MODULE):
        migration.upgrade()
        caplog.clear()
        migration.downgrade()

    filters = _filters(connection)
    assert filters["t1"] == ".a"
    assert filters["t2"] == ".data.items[].id"
    assert filters["t5"] == "$.main"
    assert filters["t6"] == "response.items.filter(x, x.a)"
    assert filters["t7"] == "select(.a)"
    assert any("t6" in record.getMessage() and "jq" in record.getMessage() for record in caplog.records)


def test_missing_tools_table_is_safe(migration):
    """A fresh database without a tools table is skipped."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection, patch.object(migration.op, "get_bind", return_value=connection):
        migration.upgrade()
        migration.downgrade()
    engine.dispose()
