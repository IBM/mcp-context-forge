# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_tool_validation_policy_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the tool validation policy Alembic migration.
"""

# Standard
import importlib

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.e5c2a7b91f4d_add_tool_validation_policy"
REVISION = "e5c2a7b91f4d"  # pragma: allowlist secret
DOWN_REVISION = "d3f6a9b1c5e8"  # pragma: allowlist secret
COLUMNS = {
    "gateways": {"tool_validation_policy"},
    "tools": {"tool_validation_policy", "validation_refusal"},
}


def _create_tables(conn: sa.engine.Connection, tables=tuple(COLUMNS)) -> None:
    """Create minimal pre-migration tables."""
    for table in tables:
        conn.execute(sa.text(f"CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL)"))


def _column_names(conn: sa.engine.Connection, table: str) -> set[str]:
    """Return the current column names of a table."""
    return {column["name"] for column in sa.inspect(conn).get_columns(table)}


def _run(conn: sa.engine.Connection, function_name: str) -> None:
    """Run a migration function against the connection."""
    module = importlib.import_module(MODULE_NAME)
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, function_name)()


def test_revision_chain():
    """The migration follows the previous head."""
    module = importlib.import_module(MODULE_NAME)
    assert module.revision == REVISION
    assert module.down_revision == DOWN_REVISION


def test_upgrade_adds_nullable_columns_and_is_idempotent():
    """upgrade() adds each column once and keeps existing rows."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _create_tables(conn)
        conn.execute(sa.text("INSERT INTO gateways (id, name) VALUES ('gw-1', 'one')"))
        conn.execute(sa.text("INSERT INTO tools (id, name) VALUES ('tool-1', 'one')"))

        _run(conn, "upgrade")
        _run(conn, "upgrade")

        for table, columns in COLUMNS.items():
            assert columns <= _column_names(conn, table)
            for column in columns:
                assert conn.execute(sa.text(f"SELECT {column} FROM {table}")).scalar() is None
        assert "validation_refusal" not in _column_names(conn, "gateways")


def test_upgrade_adds_only_the_missing_column():
    """A table that already has one of the columns gains only the other."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _create_tables(conn, tables=("tools",))
        conn.execute(sa.text("ALTER TABLE tools ADD COLUMN tool_validation_policy TEXT"))
        _run(conn, "upgrade")
        assert COLUMNS["tools"] <= _column_names(conn, "tools")


def test_downgrade_drops_columns_and_is_idempotent():
    """downgrade() removes every column and tolerates a second run."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _create_tables(conn)
        _run(conn, "upgrade")

        _run(conn, "downgrade")
        _run(conn, "downgrade")

        for table, columns in COLUMNS.items():
            assert not columns & _column_names(conn, table)


@pytest.mark.parametrize("present", ["gateways", "tools"])
def test_upgrade_handles_one_table_missing(present):
    """upgrade() alters the table that exists and skips the one that does not."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _create_tables(conn, tables=(present,))
        _run(conn, "upgrade")
        assert COLUMNS[present] <= _column_names(conn, present)
        assert {present} == set(sa.inspect(conn).get_table_names())
