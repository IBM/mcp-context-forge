# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_server_instructions_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the servers.instructions Alembic migration.
"""

# Standard
import importlib

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.d3f6a9b1c5e8_add_instructions_to_servers"
REVISION = "d3f6a9b1c5e8"  # pragma: allowlist secret
DOWN_REVISION = "a4b8c1d9e2f7"  # pragma: allowlist secret


def _create_server_table(conn: sa.engine.Connection) -> None:
    """Create a minimal pre-migration servers table."""
    conn.execute(sa.text("CREATE TABLE servers (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL)"))


def _column_names(conn: sa.engine.Connection) -> set[str]:
    """Return the current server column names."""
    return {column["name"] for column in sa.inspect(conn).get_columns("servers")}


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


def test_upgrade_adds_nullable_column_and_is_idempotent():
    """upgrade() adds the column once and keeps existing rows."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _create_server_table(conn)
        conn.execute(sa.text("INSERT INTO servers (id, name) VALUES ('srv-1', 'one')"))

        _run(conn, "upgrade")
        _run(conn, "upgrade")

        assert "instructions" in _column_names(conn)
        assert conn.execute(sa.text("SELECT instructions FROM servers")).scalar() is None


def test_downgrade_drops_column_and_is_idempotent():
    """downgrade() removes the column and tolerates a second run."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _create_server_table(conn)
        _run(conn, "upgrade")

        _run(conn, "downgrade")
        _run(conn, "downgrade")

        assert "instructions" not in _column_names(conn)


def test_upgrade_skips_missing_table():
    """upgrade() does nothing when the servers table does not exist."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _run(conn, "upgrade")
        assert "servers" not in sa.inspect(conn).get_table_names()
