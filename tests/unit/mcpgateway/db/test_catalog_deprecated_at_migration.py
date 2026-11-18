# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_catalog_deprecated_at_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the catalog deprecation Alembic migration (issue #7014).
"""

# Standard
import importlib

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.f8c4a19e2b70_add_catalog_deprecated_at"
REVISION = "f8c4a19e2b70"  # pragma: allowlist secret
DOWN_REVISION = "7ac83e50bd12"  # pragma: allowlist secret


def _column_names(conn: sa.engine.Connection, table: str) -> set[str]:
    """Return the current column names for a table."""
    return {column["name"] for column in sa.inspect(conn).get_columns(table)}


def _run(conn: sa.engine.Connection, function_name: str) -> None:
    """Run a migration function against the connection."""
    module = importlib.import_module(MODULE_NAME)
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, function_name)()


def _create_pre_migration_tables(conn: sa.engine.Connection) -> None:
    """Create minimal pre-migration tools, resources, and prompts tables."""
    conn.execute(sa.text("CREATE TABLE tools (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, deprecated BOOLEAN NOT NULL DEFAULT 0)"))
    conn.execute(sa.text("CREATE TABLE resources (id VARCHAR(36) PRIMARY KEY, uri VARCHAR(767) NOT NULL)"))
    conn.execute(sa.text("CREATE TABLE prompts (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL)"))


def test_revision_chain():
    """The migration follows the previous head."""
    module = importlib.import_module(MODULE_NAME)
    assert module.revision == REVISION
    assert module.down_revision == DOWN_REVISION


def test_upgrade_adds_columns_and_is_idempotent():
    """upgrade() adds the new columns once and leaves existing rows intact."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _create_pre_migration_tables(conn)
        conn.execute(sa.text("INSERT INTO tools (id, name, deprecated) VALUES ('t1', 'alpha', 0)"))
        conn.execute(sa.text("INSERT INTO resources (id, uri) VALUES ('r1', 'res://alpha')"))
        conn.execute(sa.text("INSERT INTO prompts (id, name) VALUES ('p1', 'alpha')"))

        _run(conn, "upgrade")
        _run(conn, "upgrade")

        assert "deprecated_at" in _column_names(conn, "tools")
        assert {"deprecated", "deprecated_at"} <= _column_names(conn, "resources")
        assert {"deprecated", "deprecated_at"} <= _column_names(conn, "prompts")
        assert conn.execute(sa.text("SELECT deprecated_at FROM tools WHERE id = 't1'")).scalar() is None
        assert conn.execute(sa.text("SELECT deprecated, deprecated_at FROM resources WHERE id = 'r1'")).first() == (0, None)
        assert conn.execute(sa.text("SELECT deprecated, deprecated_at FROM prompts WHERE id = 'p1'")).first() == (0, None)


def test_downgrade_drops_columns_and_is_idempotent():
    """downgrade() removes the new columns and tolerates a second run."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _create_pre_migration_tables(conn)
        _run(conn, "upgrade")

        _run(conn, "downgrade")
        _run(conn, "downgrade")

        assert "deprecated_at" not in _column_names(conn, "tools")
        assert "deprecated" in _column_names(conn, "tools")
        assert "deprecated" not in _column_names(conn, "resources")
        assert "deprecated_at" not in _column_names(conn, "resources")
        assert "deprecated" not in _column_names(conn, "prompts")
        assert "deprecated_at" not in _column_names(conn, "prompts")


def test_upgrade_skips_missing_tables():
    """upgrade() does nothing when the catalog tables do not exist."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _run(conn, "upgrade")
        tables = set(sa.inspect(conn).get_table_names())
        assert "tools" not in tables
        assert "resources" not in tables
        assert "prompts" not in tables
