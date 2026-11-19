# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_gateway_refresh_mode_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the per-gateway refresh_mode Alembic migration (issue #7017).
"""

# Standard
import importlib

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.b8d4e1f0c2a3_add_gateway_refresh_mode"
REVISION = "b8d4e1f0c2a3"  # pragma: allowlist secret
DOWN_REVISION = "a7c3e9d1b5f2"  # pragma: allowlist secret


def _column_names(conn: sa.engine.Connection, table: str) -> set[str]:
    """Return the current column names for a table."""
    return {column["name"] for column in sa.inspect(conn).get_columns(table)}


def _run(conn: sa.engine.Connection, function_name: str) -> None:
    """Run a migration function against the connection."""
    module = importlib.import_module(MODULE_NAME)
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, function_name)()


def _create_pre_migration_tables(conn: sa.engine.Connection) -> None:
    """Create a minimal pre-migration gateways table."""
    conn.execute(sa.text("CREATE TABLE gateways (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, refresh_interval_seconds INTEGER)"))


def test_revision_chain():
    """The migration follows the previous head."""
    module = importlib.import_module(MODULE_NAME)
    assert module.revision == REVISION
    assert module.down_revision == DOWN_REVISION


def test_upgrade_adds_column_and_is_idempotent():
    """upgrade() adds refresh_mode once and leaves existing rows intact."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _create_pre_migration_tables(conn)
        conn.execute(sa.text("INSERT INTO gateways (id, name, refresh_interval_seconds) VALUES ('g1', 'alpha', 300)"))

        _run(conn, "upgrade")
        _run(conn, "upgrade")

        assert "refresh_mode" in _column_names(conn, "gateways")
        assert conn.execute(sa.text("SELECT refresh_mode FROM gateways WHERE id = 'g1'")).scalar() is None


def test_downgrade_drops_column_and_is_idempotent():
    """downgrade() removes refresh_mode and tolerates a second run."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _create_pre_migration_tables(conn)
        _run(conn, "upgrade")

        _run(conn, "downgrade")
        _run(conn, "downgrade")

        assert "refresh_mode" not in _column_names(conn, "gateways")
        assert "refresh_interval_seconds" in _column_names(conn, "gateways")


def test_upgrade_is_a_no_op_without_gateways_table():
    """upgrade() does nothing when the gateways table is absent."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _run(conn, "upgrade")
        assert "gateways" not in sa.inspect(conn).get_table_names()
