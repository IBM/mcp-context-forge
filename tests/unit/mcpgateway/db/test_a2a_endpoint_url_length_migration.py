# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_a2a_endpoint_url_length_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the a2a_agents.endpoint_url widening migration (#7606).
"""

# Standard
import importlib
from pathlib import Path

# Third-Party
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.c3d4e5f6a7b8_widen_a2a_agent_endpoint_url"
REVISION = "c3d4e5f6a7b8"  # pragma: allowlist secret
DOWN_REVISION = "b7e291a4c630"  # pragma: allowlist secret
ALEMBIC_INI = Path(__file__).resolve().parents[4] / "mcpgateway" / "alembic.ini"
OLD_URL = "https://example.com/" + "a" * (767 - len("https://example.com/"))


def _create_agents_table(conn: sa.engine.Connection) -> None:
    """Create the pre-migration a2a_agents table with one row holding a 767 character URL."""
    conn.execute(sa.text("CREATE TABLE a2a_agents (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, slug VARCHAR(255) NOT NULL, endpoint_url VARCHAR(767) NOT NULL)"))
    conn.execute(sa.text("INSERT INTO a2a_agents (id, name, slug, endpoint_url) VALUES ('a1', 'agent', 'agent', :url)"), {"url": OLD_URL})


def _run(conn: sa.engine.Connection, function_name: str) -> None:
    """Run a migration function against the connection."""
    module = importlib.import_module(MODULE_NAME)
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, function_name)()


def _endpoint_url_length(conn: sa.engine.Connection) -> int:
    """Return the endpoint_url column length."""
    for column in sa.inspect(conn).get_columns("a2a_agents"):
        if column["name"] == "endpoint_url":
            return column["type"].length
    raise AssertionError("endpoint_url column is missing")


def test_alembic_has_a_single_head():
    """The migration follows the previous head and leaves one head."""
    module = importlib.import_module(MODULE_NAME)
    assert (module.revision, module.down_revision) == (REVISION, DOWN_REVISION)
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    assert len(script.get_heads()) == 1


def test_upgrade_widens_the_column_and_keeps_existing_agents():
    """An existing table with agents gets a 2048 character column and keeps its rows."""
    with sa.create_engine("sqlite://").begin() as conn:
        _create_agents_table(conn)
        _run(conn, "upgrade")
        _run(conn, "upgrade")

        assert _endpoint_url_length(conn) == 2048
        assert conn.execute(sa.text("SELECT endpoint_url FROM a2a_agents WHERE id = 'a1'")).scalar() == OLD_URL


def test_upgrade_skips_a_missing_table():
    """The upgrade does nothing when the table does not exist."""
    with sa.create_engine("sqlite://").begin() as conn:
        _run(conn, "upgrade")
        assert not sa.inspect(conn).get_table_names()


def test_downgrade_restores_the_old_length_and_is_idempotent():
    """The downgrade returns the column to 767 characters and a second run changes nothing."""
    with sa.create_engine("sqlite://").begin() as conn:
        _create_agents_table(conn)
        _run(conn, "upgrade")

        _run(conn, "downgrade")
        _run(conn, "downgrade")

        assert _endpoint_url_length(conn) == 767
        assert conn.execute(sa.text("SELECT endpoint_url FROM a2a_agents WHERE id = 'a1'")).scalar() == OLD_URL
