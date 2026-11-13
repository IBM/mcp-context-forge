# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_oauth_state_binding_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the oauth_states.browser_binding_hash Alembic migration.
"""

# Standard
import importlib

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.7ac83e50bd12_add_browser_binding_hash"
REVISION = "7ac83e50bd12"  # pragma: allowlist secret
DOWN_REVISION = "4a7d9e2c6b18"  # pragma: allowlist secret


def _create_state_table(conn: sa.engine.Connection) -> None:
    """Create a minimal pre-migration oauth_states table."""
    conn.execute(sa.text("CREATE TABLE oauth_states (id VARCHAR(36) PRIMARY KEY, state VARCHAR(500) NOT NULL)"))


def _column_names(conn: sa.engine.Connection) -> set[str]:
    """Return the current state column names."""
    return {column["name"] for column in sa.inspect(conn).get_columns("oauth_states")}


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
        _create_state_table(conn)
        conn.execute(sa.text("INSERT INTO oauth_states (id, state) VALUES ('state-1', 'opaque-state')"))

        _run(conn, "upgrade")
        _run(conn, "upgrade")

        column = next(column for column in sa.inspect(conn).get_columns("oauth_states") if column["name"] == "browser_binding_hash")
        assert column["nullable"]
        assert column["type"].length == 64
        assert conn.execute(sa.text("SELECT state FROM oauth_states")).scalar() == "opaque-state"
        assert conn.execute(sa.text("SELECT browser_binding_hash FROM oauth_states")).scalar() is None


def test_downgrade_drops_column_and_is_idempotent():
    """downgrade() removes the column and tolerates a second run."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _create_state_table(conn)
        _run(conn, "upgrade")

        _run(conn, "downgrade")
        _run(conn, "downgrade")

        assert "browser_binding_hash" not in _column_names(conn)


def test_upgrade_skips_missing_table():
    """upgrade() does nothing when the oauth_states table does not exist."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _run(conn, "upgrade")
        assert "oauth_states" not in sa.inspect(conn).get_table_names()


def test_downgrade_skips_missing_table():
    """downgrade() tolerates a database without OAuth state storage."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _run(conn, "downgrade")
        assert "oauth_states" not in sa.inspect(conn).get_table_names()


def test_upgrade_preserves_fresh_model_schema():
    """upgrade() accepts binding columns created from the current ORM model."""
    # First-Party
    from mcpgateway.db import OAuthState

    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        OAuthState.__table__.create(conn)
        _run(conn, "upgrade")
        column = next(column for column in sa.inspect(conn).get_columns("oauth_states") if column["name"] == "browser_binding_hash")
        assert column["nullable"]
        assert column["type"].length == 64
