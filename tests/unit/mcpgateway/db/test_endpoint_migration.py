# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_endpoint_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify the tool endpoint migration upgrade and its downgrade reset of delegating tools.
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

MODULE_NAME = "mcpgateway.alembic.versions.c4e8a1d7b392_add_endpoint_to_tools"


@pytest.fixture(name="migration")
def endpoint_migration() -> ModuleType:
    """Load the endpoint migration."""
    return importlib.import_module(MODULE_NAME)


@pytest.fixture(name="engine")
def endpoint_engine(tmp_path: Path) -> Iterator[Engine]:
    """Provide an isolated SQLite database."""
    test_engine = sa.create_engine(f"sqlite:///{tmp_path / 'endpoint-migration.db'}")
    try:
        yield test_engine
    finally:
        test_engine.dispose()


def _create_tools_table(engine: Engine) -> None:
    """Create a minimal tools table without the endpoint column.

    Args:
        engine: Database engine.
    """
    metadata = sa.MetaData()
    sa.Table(
        "tools",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("auth_type", sa.String, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO tools (id, auth_type, enabled) VALUES (:id, :auth_type, :enabled)"),
            [
                {"id": "inheriting", "auth_type": "inherit", "enabled": True},
                {"id": "bearer", "auth_type": "bearer", "enabled": True},
                {"id": "endpoint", "auth_type": None, "enabled": True},
                {"id": "plain", "auth_type": None, "enabled": True},
            ],
        )


def _run(engine: Engine, step) -> None:
    """Run a migration step on one connection.

    Args:
        engine: Database engine.
        step: Callable that performs the upgrade or downgrade.
    """
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            step()


def _columns(engine: Engine) -> set:
    """Read the column names of the tools table.

    Args:
        engine: Database engine.

    Returns:
        Set of column names.
    """
    return {column["name"] for column in sa.inspect(engine).get_columns("tools")}


def _rows(engine: Engine) -> dict:
    """Read the auth type and enabled flag of each tool.

    Args:
        engine: Database engine.

    Returns:
        Mapping of tool ID to the auth type and enabled flag.
    """
    with engine.connect() as connection:
        return {row.id: (row.auth_type, bool(row.enabled)) for row in connection.execute(sa.text("SELECT id, auth_type, enabled FROM tools"))}


def test_upgrade_adds_a_nullable_endpoint_column(engine: Engine, migration: ModuleType) -> None:
    """Existing tools keep a NULL endpoint after the upgrade."""
    _create_tools_table(engine)

    _run(engine, migration.upgrade)

    assert "endpoint" in _columns(engine)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM tools WHERE endpoint IS NOT NULL")).scalar() == 0


def test_downgrade_disables_and_resets_only_delegating_tools(engine: Engine, migration: ModuleType) -> None:
    """The downgrade leaves no tool that older code cannot invoke."""
    _create_tools_table(engine)
    _run(engine, migration.upgrade)
    with engine.begin() as connection:
        connection.execute(sa.text("UPDATE tools SET endpoint = '/v1/items' WHERE id = 'endpoint'"))

    _run(engine, migration.downgrade)

    assert "endpoint" not in _columns(engine)
    assert _rows(engine) == {"inheriting": (None, False), "bearer": ("bearer", True), "endpoint": (None, False), "plain": (None, True)}


def test_upgrade_is_repeatable_after_a_downgrade(engine: Engine, migration: ModuleType) -> None:
    """A roundtrip of upgrade, downgrade and upgrade ends with the column present."""
    _create_tools_table(engine)

    _run(engine, migration.upgrade)
    _run(engine, migration.upgrade)
    _run(engine, migration.downgrade)
    _run(engine, migration.upgrade)

    assert "endpoint" in _columns(engine)


def test_downgrade_without_the_column_changes_no_row(engine: Engine, migration: ModuleType) -> None:
    """A downgrade on a database without the column is a no-op."""
    _create_tools_table(engine)

    _run(engine, migration.downgrade)

    assert _rows(engine)["inheriting"] == ("inherit", True)


def test_migration_is_a_no_op_without_a_tools_table(engine: Engine, migration: ModuleType) -> None:
    """Both directions skip a database that has no tools table."""
    _run(engine, migration.upgrade)
    _run(engine, migration.downgrade)

    assert not sa.inspect(engine).has_table("tools")
