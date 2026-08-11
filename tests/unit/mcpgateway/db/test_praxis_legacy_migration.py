"""Partial-schema idempotence tests for the Task 21 migration."""

from collections.abc import Iterator
import importlib
import os
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from mcpgateway.db import Base

PARENT_MODULE = "mcpgateway.alembic.versions.f5a6b7c8d9e0_add_praxis_bundle_persistence"
TELEMETRY_MODULE = "mcpgateway.alembic.versions.a6b7c8d9e0f1_extend_praxis_legacy_telemetry"
STATE = "praxis_legacy_telemetry_state"
CONSUMERS = "praxis_legacy_consumers"
STATE_CHECK = "ck_praxis_legacy_telemetry_state_shadow_diff_count"
RETENTION_CHECK = "ck_praxis_legacy_consumers_retention_state"
IDENTITY_UNIQUE = "uq_praxis_legacy_consumers_identity_path"

DATABASE_PARAMS = [pytest.param("sqlite", id="sqlite")]
if postgres_url := os.getenv("MCPGATEWAY_TEST_POSTGRES_URL"):
    DATABASE_PARAMS.append(pytest.param(postgres_url, id="postgresql"))


@pytest.fixture(params=DATABASE_PARAMS)
def migration_engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'partial-migration.db'}" if request.param == "sqlite" else request.param)
    yield engine
    if request.param != "sqlite":
        with engine.connect() as connection:
            if STATE in sa.inspect(connection).get_table_names():
                _run(connection, TELEMETRY_MODULE, "downgrade")
                _run(connection, PARENT_MODULE, "downgrade")
            connection.execute(sa.text("DROP TABLE IF EXISTS task21_sentinel"))
            connection.execute(sa.text("DROP TABLE IF EXISTS servers CASCADE"))
            connection.commit()
    engine.dispose()


def _run(connection: Connection, module_name: str, operation: str) -> None:
    module = importlib.import_module(module_name)
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(module, operation)()


def _create_parent_schema(connection: Connection) -> None:
    connection.execute(sa.text("CREATE TABLE servers (id VARCHAR(36) PRIMARY KEY)"))
    connection.execute(sa.text("CREATE TABLE task21_sentinel (value TEXT NOT NULL)"))
    connection.execute(sa.text("INSERT INTO task21_sentinel VALUES ('preserved')"))
    _run(connection, PARENT_MODULE, "upgrade")
    connection.execute(
        sa.text(
            "INSERT INTO praxis_legacy_telemetry_state "
            "(id, cas_epoch, updated_at) VALUES (1, 7, CURRENT_TIMESTAMP)"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO praxis_legacy_consumers "
            "(id, declared_identity, declared_version, observability_class, first_seen_at, last_seen_at, active, revoked_at, retain_until) "
            "VALUES ('consumer-a', 'legacy-a', '1.0', 'unobservable', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, TRUE, NULL, NULL)"
        )
    )


def _add_partial_columns(connection: Connection, *, all_columns: bool) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        with Operations(context).batch_alter_table(STATE) as batch:
            batch.add_column(sa.Column("shadow_diff_count", sa.Integer(), nullable=False, server_default="0"))
            if all_columns:
                batch.add_column(sa.Column("private_state_present", sa.Boolean(), nullable=False, server_default=sa.false()))
                batch.add_column(sa.Column("task20_e2e_passed", sa.Boolean(), nullable=False, server_default=sa.false()))
                batch.add_column(sa.Column("launcher_fleet_compatible", sa.Boolean(), nullable=False, server_default=sa.false()))
        with Operations(context).batch_alter_table(CONSUMERS) as batch:
            batch.add_column(sa.Column("consumer_path", sa.String(64), nullable=False, server_default="control_plane_grpc"))
            batch.add_column(sa.Column("retention_state", sa.String(32), nullable=False, server_default="active"))
            if all_columns:
                batch.add_column(sa.Column("authenticated_identity", sa.String(255), nullable=True))
                batch.add_column(sa.Column("observed", sa.Boolean(), nullable=False, server_default=sa.false()))
                batch.add_column(sa.Column("attested", sa.Boolean(), nullable=False, server_default=sa.false()))
                batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
                batch.create_unique_constraint(IDENTITY_UNIQUE, ["declared_identity", "consumer_path"])


def _assert_model_parity(connection: Connection) -> None:
    inspector = sa.inspect(connection)
    for table_name in (STATE, CONSUMERS):
        expected = Base.metadata.tables[table_name]
        actual_columns = {column["name"]: (str(column["type"].compile(dialect=connection.dialect)), column["nullable"]) for column in inspector.get_columns(table_name)}
        expected_columns = {column.name: (str(column.type.compile(dialect=connection.dialect)), column.nullable) for column in expected.c}
        assert actual_columns == expected_columns
        assert {constraint["name"] for constraint in inspector.get_check_constraints(table_name)} == {
            constraint.name for constraint in expected.constraints if isinstance(constraint, sa.CheckConstraint)
        }
        assert {(constraint["name"], tuple(constraint["column_names"])) for constraint in inspector.get_unique_constraints(table_name)} == {
            (constraint.name, tuple(column.name for column in constraint.columns))
            for constraint in expected.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        }


def test_upgrade_reconciles_columns_and_constraints_independently(migration_engine: Engine) -> None:
    with migration_engine.connect() as connection:
        _create_parent_schema(connection)
        _add_partial_columns(connection, all_columns=False)

        _run(connection, TELEMETRY_MODULE, "upgrade")
        _run(connection, TELEMETRY_MODULE, "upgrade")

        inspector = sa.inspect(connection)
        assert {constraint["name"] for constraint in inspector.get_check_constraints(STATE)} >= {STATE_CHECK}
        assert {constraint["name"] for constraint in inspector.get_check_constraints(CONSUMERS)} >= {RETENTION_CHECK}
        assert {constraint["name"] for constraint in inspector.get_unique_constraints(CONSUMERS)} >= {IDENTITY_UNIQUE}
        assert connection.execute(sa.text("SELECT cas_epoch FROM praxis_legacy_telemetry_state WHERE id = 1")).scalar_one() == 7
        assert connection.execute(sa.text("SELECT declared_identity FROM praxis_legacy_consumers WHERE id = 'consumer-a'")).scalar_one() == "legacy-a"
        assert connection.execute(sa.text("SELECT value FROM task21_sentinel")).scalar_one() == "preserved"


def test_downgrade_tolerates_independently_missing_checks(migration_engine: Engine) -> None:
    with migration_engine.connect() as connection:
        _create_parent_schema(connection)
        _add_partial_columns(connection, all_columns=True)

        _run(connection, TELEMETRY_MODULE, "downgrade")
        _run(connection, TELEMETRY_MODULE, "downgrade")

        inspector = sa.inspect(connection)
        assert {column["name"] for column in inspector.get_columns(STATE)} == {
            "id",
            "coverage_started_at",
            "inventory_attested_at",
            "inventory_attested_by",
            "inventory_attestation_hash",
            "cas_epoch",
            "updated_at",
        }
        assert "consumer_path" not in {column["name"] for column in inspector.get_columns(CONSUMERS)}
        assert connection.execute(sa.text("SELECT cas_epoch FROM praxis_legacy_telemetry_state WHERE id = 1")).scalar_one() == 7
        assert connection.execute(sa.text("SELECT value FROM task21_sentinel")).scalar_one() == "preserved"


def test_upgrade_downgrade_upgrade_matches_model_and_preserves_data(migration_engine: Engine) -> None:
    with migration_engine.connect() as connection:
        _create_parent_schema(connection)

        _run(connection, TELEMETRY_MODULE, "upgrade")
        _run(connection, TELEMETRY_MODULE, "upgrade")
        _assert_model_parity(connection)

        _run(connection, TELEMETRY_MODULE, "downgrade")
        assert connection.execute(sa.text("SELECT cas_epoch FROM praxis_legacy_telemetry_state WHERE id = 1")).scalar_one() == 7
        assert connection.execute(sa.text("SELECT declared_identity FROM praxis_legacy_consumers WHERE id = 'consumer-a'")).scalar_one() == "legacy-a"
        assert connection.execute(sa.text("SELECT value FROM task21_sentinel")).scalar_one() == "preserved"

        _run(connection, TELEMETRY_MODULE, "upgrade")
        _assert_model_parity(connection)
