# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_a2a_agent_cards_kind_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the a2a_agent_cards.kind Alembic migration.
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

MODULE_NAME = "mcpgateway.alembic.versions.7a3a6305ddb6_add_kind_to_a2a_agent_cards"
REVISION = "7a3a6305ddb6"  # pragma: allowlist secret
DOWN_REVISION = "f6b8d3e1a5c2"  # pragma: allowlist secret
ALEMBIC_INI = Path(__file__).resolve().parents[4] / "mcpgateway" / "alembic.ini"


def _create_cards_table(conn: sa.engine.Connection) -> None:
    """Create the pre-migration a2a_agent_cards table with one public row."""
    conn.execute(sa.text("CREATE TABLE a2a_agent_cards (id VARCHAR(36) PRIMARY KEY, a2a_agent_id VARCHAR(36) NOT NULL, version INTEGER NOT NULL)"))
    conn.execute(sa.text("INSERT INTO a2a_agent_cards (id, a2a_agent_id, version) VALUES ('c1', 'agent-1', 1)"))


def _run(conn: sa.engine.Connection, function_name: str) -> None:
    """Run a migration function against the connection."""
    module = importlib.import_module(MODULE_NAME)
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, function_name)()


def _columns(conn: sa.engine.Connection) -> set[str]:
    """Return the current column names."""
    return {column["name"] for column in sa.inspect(conn).get_columns("a2a_agent_cards")}


def test_alembic_has_a_single_head():
    """The migration follows the previous head and leaves one head."""
    module = importlib.import_module(MODULE_NAME)
    assert (module.revision, module.down_revision) == (REVISION, DOWN_REVISION)
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    assert len(script.get_heads()) == 1


def test_upgrade_backfills_public_and_is_idempotent():
    """Existing rows become public, and a second run changes nothing."""
    with sa.create_engine("sqlite://").begin() as conn:
        _create_cards_table(conn)
        _run(conn, "upgrade")
        _run(conn, "upgrade")
        assert "kind" in _columns(conn)
        assert conn.execute(sa.text("SELECT kind FROM a2a_agent_cards WHERE id = 'c1'")).scalar() == "public"


def test_upgrade_skips_a_missing_table():
    """The upgrade does nothing when the table does not exist."""
    with sa.create_engine("sqlite://").begin() as conn:
        _run(conn, "upgrade")
        assert not sa.inspect(conn).get_table_names()


def test_downgrade_deletes_extended_rows_and_drops_column():
    """The downgrade keeps public rows and removes every extended row, so the old read route cannot return one."""
    with sa.create_engine("sqlite://").begin() as conn:
        _create_cards_table(conn)
        _run(conn, "upgrade")
        conn.execute(sa.text("INSERT INTO a2a_agent_cards (id, a2a_agent_id, version, kind) VALUES ('c2', 'agent-1', 3, 'extended')"))

        _run(conn, "downgrade")

        assert "kind" not in _columns(conn)
        assert [row[0] for row in conn.execute(sa.text("SELECT id FROM a2a_agent_cards"))] == ["c1"]


def test_downgrade_is_idempotent_and_skips_a_missing_table():
    """A second downgrade and a downgrade without the table both do nothing."""
    with sa.create_engine("sqlite://").begin() as conn:
        _run(conn, "downgrade")
        _create_cards_table(conn)
        _run(conn, "upgrade")
        _run(conn, "downgrade")
        _run(conn, "downgrade")
        assert "kind" not in _columns(conn)
