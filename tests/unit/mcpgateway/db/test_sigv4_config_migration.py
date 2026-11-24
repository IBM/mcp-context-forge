# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_sigv4_config_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify the sigv4_config migration upgrade and its downgrade reset of sigv4 tools.
"""

# Standard
from collections.abc import Iterator
import importlib
from pathlib import Path
from types import ModuleType

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

MODULE_NAME = "mcpgateway.alembic.versions.f6b8d3e1a5c2_add_sigv4_config_to_tools"


@pytest.fixture(name="migration")
def sigv4_migration() -> ModuleType:
    """Load the sigv4_config migration."""
    return importlib.import_module(MODULE_NAME)


@pytest.fixture(name="engine")
def sigv4_engine(tmp_path: Path) -> Iterator[Engine]:
    """Provide an isolated SQLite database."""
    test_engine = sa.create_engine(f"sqlite:///{tmp_path / 'sigv4-migration.db'}")
    try:
        yield test_engine
    finally:
        test_engine.dispose()


def _create_tools_table(engine: Engine) -> sa.Table:
    """Create a minimal tools table without the sigv4_config column.

    Args:
        engine: Database engine.

    Returns:
        The tools table definition.
    """
    metadata = sa.MetaData()
    tools = sa.Table(
        "tools",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("auth_type", sa.String, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(tools),
            [
                {"id": "signed", "auth_type": "sigv4", "enabled": True},
                {"id": "bearer", "auth_type": "bearer", "enabled": True},
                {"id": "plain", "auth_type": None, "enabled": True},
            ],
        )
    return tools


def _run(engine: Engine, step) -> None:
    """Run a migration step on one connection.

    Args:
        engine: Database engine.
        step: Callable that performs the upgrade or downgrade.
    """
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            step()


def _rows(engine: Engine) -> dict:
    """Read the auth type and enabled flag of each tool.

    Args:
        engine: Database engine.

    Returns:
        Mapping of tool ID to the auth type and enabled flag.
    """
    with engine.connect() as connection:
        return {row.id: (row.auth_type, bool(row.enabled)) for row in connection.execute(sa.text("SELECT id, auth_type, enabled FROM tools"))}


def test_downgrade_disables_and_resets_only_sigv4_tools(engine: Engine, migration: ModuleType) -> None:
    """The downgrade leaves no tool that older code cannot invoke."""
    _create_tools_table(engine)
    _run(engine, migration.upgrade)
    assert "sigv4_config" in {column["name"] for column in sa.inspect(engine).get_columns("tools")}

    _run(engine, migration.downgrade)

    assert "sigv4_config" not in {column["name"] for column in sa.inspect(engine).get_columns("tools")}
    assert _rows(engine) == {"signed": (None, False), "bearer": ("bearer", True), "plain": (None, True)}


def test_upgrade_is_repeatable_after_a_downgrade(engine: Engine, migration: ModuleType) -> None:
    """A roundtrip of upgrade, downgrade and upgrade ends with the column present."""
    _create_tools_table(engine)

    _run(engine, migration.upgrade)
    _run(engine, migration.upgrade)
    _run(engine, migration.downgrade)
    _run(engine, migration.upgrade)

    assert "sigv4_config" in {column["name"] for column in sa.inspect(engine).get_columns("tools")}


def test_downgrade_without_the_column_changes_no_row(engine: Engine, migration: ModuleType) -> None:
    """A downgrade on a database without the column is a no-op."""
    _create_tools_table(engine)

    _run(engine, migration.downgrade)

    assert _rows(engine)["signed"] == ("sigv4", True)
