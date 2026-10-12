# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_audit_resource_id_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify audit resource ID nullability migration and aggregate audit persistence.
"""

# Standard
from collections.abc import Iterator
from datetime import datetime, timezone
import importlib
from importlib.resources import files
from io import StringIO
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

# Third-Party
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import AuditTrail
from mcpgateway.services import audit_trail_service
from mcpgateway.utils.correlation_id import get_correlation_id

MODULE_NAME = "mcpgateway.alembic.versions.4a7d9e2c6b18_allow_nullable_audit_resource_id"
REVISION = "4a7d9e2c6b18"  # pragma: allowlist secret
DOWN_REVISION = "c7e91a2b4d60"  # pragma: allowlist secret
ACTOR = "audit-migration@example.com"
TEAM_ID = "00000000000040008000000000000001"


@pytest.fixture(name="migration")
def audit_resource_id_migration() -> ModuleType:
    """Load the audit resource ID migration."""
    return importlib.import_module(MODULE_NAME)


@pytest.fixture(name="engine")
def audit_migration_engine(tmp_path: Path) -> Iterator[Engine]:
    """Provide an isolated SQLite database with independent connections."""
    test_engine = sa.create_engine(f"sqlite:///{tmp_path / 'audit-migration.db'}")
    try:
        yield test_engine
    finally:
        test_engine.dispose()


def _alembic_config(connection: Connection | None = None) -> Config:
    """Configure repository migrations for an optional isolated connection.

    Args:
        connection: The isolated connection used by migration commands.

    Returns:
        The Alembic configuration for repository migrations.
    """
    config = Config()
    config.set_main_option("script_location", str(files("mcpgateway").joinpath("alembic")))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def _create_audit_table(connection: Connection, *, nullable: bool = False) -> sa.Table:
    """Create the audit table with the selected resource ID nullability.

    Args:
        connection: The isolated database connection.
        nullable: Whether resource IDs accept NULL.

    Returns:
        The isolated audit table definition.
    """
    table = AuditTrail.__table__.to_metadata(sa.MetaData())
    table.c.resource_id.nullable = nullable
    table.append_constraint(sa.CheckConstraint("action <> ''", name="ck_audit_action_nonempty"))
    table.create(connection)
    connection.execute(
        table.insert(),
        {
            "id": "historical-audit",
            "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "action": "create_tool",
            "resource_type": "tool",
            "resource_id": "historical-tool",
            "resource_name": "Historical tool",
            "user_id": ACTOR,
            "user_email": ACTOR,
            "team_id": TEAM_ID,
            "success": True,
            "context": {"details": {"count": 1}},
        },
    )
    return table


def _schema_snapshot(connection: Connection) -> dict:
    """Capture reflected audit schema definitions for preservation checks.

    Args:
        connection: The isolated database connection.

    Returns:
        Audit columns, indexes, and constraints.
    """
    inspector = sa.inspect(connection)
    return {
        "columns": {column["name"]: {**column, "type": str(column["type"])} for column in inspector.get_columns("audit_trails")},
        "indexes": sorted(inspector.get_indexes("audit_trails"), key=lambda index: index["name"]),
        "primary_key": inspector.get_pk_constraint("audit_trails"),
        "unique_constraints": inspector.get_unique_constraints("audit_trails"),
        "check_constraints": inspector.get_check_constraints("audit_trails"),
        "foreign_keys": inspector.get_foreign_keys("audit_trails"),
    }


def _audit_rows(connection: Connection) -> list[dict]:
    """Capture every persisted audit value in deterministic order.

    Args:
        connection: The isolated database connection.

    Returns:
        Audit rows ordered by ID.
    """
    return [dict(row) for row in connection.execute(sa.text("SELECT * FROM audit_trails ORDER BY id")).mappings()]


def test_revision_extends_single_repository_head(migration: ModuleType) -> None:
    """The migration extends the verified parent and leaves exactly one head."""
    assert migration.revision == REVISION
    assert migration.down_revision == DOWN_REVISION
    assert migration.branch_labels is None
    assert migration.depends_on is None
    assert ScriptDirectory.from_config(_alembic_config()).get_heads() == [REVISION]


def test_upgrade_preserves_historical_rows_indexes_and_other_schema(engine: Engine, migration: ModuleType) -> None:
    """Alembic changes only resource ID nullability and preserves historical data."""
    with engine.begin() as connection:
        _create_audit_table(connection)
        expected_schema = _schema_snapshot(connection)
        expected_rows = _audit_rows(connection)
        config = _alembic_config(connection)
        command.stamp(config, DOWN_REVISION)

        command.upgrade(config, REVISION)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()

        expected_schema["columns"]["resource_id"]["nullable"] = True
        assert _schema_snapshot(connection) == expected_schema
        assert _audit_rows(connection) == expected_rows
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


def test_migrated_table_persists_bulk_team_audit_in_independent_session(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aggregate team audits persist with NULL resource IDs after the request session rolls back."""
    with engine.begin() as connection:
        _create_audit_table(connection)
        config = _alembic_config(connection)
        command.stamp(config, DOWN_REVISION)
        command.upgrade(config, REVISION)

    initial_correlation_id = get_correlation_id()
    monkeypatch.setattr(audit_trail_service.settings, "audit_trail_enabled", True)
    monkeypatch.setattr(audit_trail_service, "get_or_generate_correlation_id", lambda: "migration-audit-correlation")
    session_factory = sessionmaker(bind=engine)
    with session_factory() as request_db, patch.object(audit_trail_service, "SessionLocal", wraps=session_factory) as audit_sessions:
        request_db.add(AuditTrail(id="uncommitted-request-audit", action="request_action", resource_type="tool", resource_id="uncommitted-tool", user_id=ACTOR, success=False))
        entry = audit_trail_service.AuditTrailService().log_action(
            action="bulk_create_tools",
            resource_type="tool",
            resource_id=None,
            user_id=ACTOR,
            team_id=TEAM_ID,
            details={"count": 2, "import_batch_id": "migration-batch"},
        )
        assert entry is not None
        audit_sessions.assert_called_once_with()
        request_db.rollback()

    with session_factory() as fresh:
        assert fresh.get(AuditTrail, "uncommitted-request-audit") is None
        row = fresh.execute(sa.select(AuditTrail).where(AuditTrail.action == "bulk_create_tools")).scalar_one()
        assert row.resource_id is None
        assert row.team_id == TEAM_ID
        assert row.correlation_id == "migration-audit-correlation"
        assert row.context["details"] == {"count": 2, "import_batch_id": "migration-batch"}
        assert fresh.get(AuditTrail, "historical-audit").resource_id == "historical-tool"
    assert get_correlation_id() == initial_correlation_id


@pytest.mark.parametrize("operation", ["upgrade", "downgrade"])
def test_missing_table_is_repeatable_noop(engine: Engine, migration: ModuleType, operation: str) -> None:
    """Migration operations preserve databases without an audit table."""
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, operation)()
            getattr(migration, operation)()
        assert sa.inspect(connection).get_table_names() == []


@pytest.mark.parametrize("operation", ["upgrade", "downgrade"])
def test_missing_resource_column_is_repeatable_noop(engine: Engine, migration: ModuleType, operation: str) -> None:
    """Migration operations preserve audit tables without a resource ID column."""
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE audit_trails (id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO audit_trails (id) VALUES ('historical-audit')"))
        expected_schema = _schema_snapshot(connection)
        expected_rows = _audit_rows(connection)
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, operation)()
            getattr(migration, operation)()
        assert _schema_snapshot(connection) == expected_schema
        assert _audit_rows(connection) == expected_rows


def test_already_nullable_upgrade_preserves_null_rows(engine: Engine, migration: ModuleType) -> None:
    """An already-nullable audit table bypasses batch alteration and preserves aggregate rows."""
    with engine.begin() as connection:
        table = _create_audit_table(connection, nullable=True)
        connection.execute(
            table.insert(), {"id": "aggregate-audit", "action": "bulk_create_tools", "resource_type": "tool", "resource_id": None, "user_id": ACTOR, "team_id": TEAM_ID, "success": True}
        )
        expected_schema = _schema_snapshot(connection)
        expected_rows = _audit_rows(connection)
        with Operations.context(MigrationContext.configure(connection)), patch.object(migration.op, "batch_alter_table", wraps=migration.op.batch_alter_table) as batch:
            migration.upgrade()
            migration.upgrade()
            batch.assert_not_called()
        assert _schema_snapshot(connection) == expected_schema
        assert _audit_rows(connection) == expected_rows


def test_compatible_downgrade_restores_not_null_without_data_loss(engine: Engine, migration: ModuleType) -> None:
    """Downgrade restores NOT NULL while preserving historical rows, indexes, and other schema definitions."""
    with engine.begin() as connection:
        table = _create_audit_table(connection, nullable=True)
        expected_schema = _schema_snapshot(connection)
        expected_rows = _audit_rows(connection)
        config = _alembic_config(connection)
        command.stamp(config, REVISION)

        command.downgrade(config, DOWN_REVISION)
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        expected_schema["columns"]["resource_id"]["nullable"] = False
        assert _schema_snapshot(connection) == expected_schema
        assert _audit_rows(connection) == expected_rows
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == DOWN_REVISION
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(table.insert(), {"id": "rejected-aggregate", "action": "bulk_create_tools", "resource_type": "tool", "resource_id": None, "user_id": ACTOR, "success": True})
        assert _audit_rows(connection) == expected_rows


def test_null_rows_reject_downgrade_before_any_schema_or_revision_change(engine: Engine, migration: ModuleType) -> None:
    """Downgrade rejects NULL resource IDs before batch alteration and preserves all rows and revision state."""
    with engine.begin() as connection:
        table = _create_audit_table(connection, nullable=True)
        connection.execute(
            table.insert(), {"id": "aggregate-audit", "action": "bulk_create_tools", "resource_type": "tool", "resource_id": None, "user_id": ACTOR, "team_id": TEAM_ID, "success": True}
        )
        config = _alembic_config(connection)
        command.stamp(config, REVISION)
        expected_schema = _schema_snapshot(connection)
        expected_rows = _audit_rows(connection)

        with patch.object(migration.op, "batch_alter_table", wraps=migration.op.batch_alter_table) as batch:
            with pytest.raises(RuntimeError, match=r"Cannot restore NOT NULL on audit_trails\.resource_id while NULL resource IDs exist"):
                command.downgrade(config, DOWN_REVISION)
            batch.assert_not_called()

        assert _schema_snapshot(connection) == expected_schema
        assert _audit_rows(connection) == expected_rows
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION
        assert set(sa.inspect(connection).get_table_names()) == {"audit_trails", "alembic_version"}


@pytest.mark.parametrize(
    "operation, nullable, sql",
    [("upgrade", False, "ALTER TABLE audit_trails ALTER COLUMN resource_id DROP NOT NULL;"), ("downgrade", True, "ALTER TABLE audit_trails ALTER COLUMN resource_id SET NOT NULL;")],
)
def test_postgresql_uses_in_place_alter_contract(migration: ModuleType, operation: str, nullable: bool, sql: str) -> None:
    """PostgreSQL batch operations emit only the corresponding in-place nullability ALTER statement."""
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context), patch.object(migration.sa, "inspect") as inspector, patch.object(migration.op, "get_bind") as bind:
        inspector.return_value.has_table.return_value = True
        inspector.return_value.get_columns.return_value = [{"name": "resource_id", "nullable": nullable, "type": sa.String(255)}]
        bind.return_value.execute.return_value.first.return_value = None
        getattr(migration, operation)()
    assert output.getvalue().strip() == sql
