#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/migration/test_token_revocation_jti_length.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Migration tests for the token revocation JTI width.
"""

# Standard
import importlib.util
import os
from pathlib import Path
import uuid

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine

MIGRATION_PATH = Path(__file__).resolve().parents[2] / "mcpgateway" / "alembic" / "versions" / "b7c9d1e3f5a7_widen_token_revocation_jti.py"
POSTGRES_URL = os.environ.get("MIGRATION_TEST_POSTGRES_URL")
REVOKER_EMAIL = "revoker@example.com"
EXISTING_JTI = "existing-jti"
KEYCLOAK_JTI = "onrtac:12345678-1234-1234-1234-123456789012"
MAXIMUM_JTI = "j" * 255

_SPEC = importlib.util.spec_from_file_location("token_revocation_jti_migration", MIGRATION_PATH)
assert _SPEC is not None and _SPEC.loader is not None
MIGRATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MIGRATION)


def _run_migration(connection: sa.Connection, direction: str) -> None:
    """Run one migration function against a test connection.

    Args:
        connection: The isolated database connection.
        direction: Either ``upgrade`` or ``downgrade``.
    """
    with Operations.context(MigrationContext.configure(connection)):
        getattr(MIGRATION, direction)()


def _create_previous_schema(connection: sa.Connection) -> None:
    """Create the previous revocation schema and one existing row.

    Args:
        connection: The isolated database connection.
    """
    metadata = sa.MetaData()
    users = sa.Table(
        "email_users",
        metadata,
        sa.Column("email", sa.String(255), primary_key=True),
    )
    sa.Table(
        "token_revocations",
        metadata,
        sa.Column("jti", sa.String(36), primary_key=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_by", sa.String(255), sa.ForeignKey("email_users.email"), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=True),
        sa.Index("idx_token_revocations_expiry_cleanup", "token_expiry"),
        sa.Index("idx_token_revocations_revoked_at", "revoked_at"),
    )
    metadata.create_all(connection)
    connection.execute(users.insert().values(email=REVOKER_EMAIL))
    connection.execute(
        sa.text("INSERT INTO token_revocations " "(jti, revoked_at, revoked_by, reason) " "VALUES (:jti, CURRENT_TIMESTAMP, :revoked_by, :reason)"),
        {"jti": EXISTING_JTI, "revoked_by": REVOKER_EMAIL, "reason": "logout"},
    )


def _jti_length(connection: sa.Connection) -> int | None:
    """Return the reflected JTI length.

    Args:
        connection: The isolated database connection.

    Returns:
        The declared length, or None for an unbounded string type.
    """
    column = next(column for column in sa.inspect(connection).get_columns("token_revocations") if column["name"] == "jti")
    return getattr(column["type"], "length", None)


def _insert_jti(connection: sa.Connection, jti: str) -> None:
    """Insert one revocation row.

    Args:
        connection: The isolated database connection.
        jti: The token ID to store.
    """
    connection.execute(
        sa.text("INSERT INTO token_revocations " "(jti, revoked_at, revoked_by, reason) " "VALUES (:jti, CURRENT_TIMESTAMP, :revoked_by, :reason)"),
        {"jti": jti, "revoked_by": REVOKER_EMAIL, "reason": "logout"},
    )


def _stored_jtis(connection: sa.Connection) -> list[str]:
    """Return all stored token IDs in deterministic order.

    Args:
        connection: The isolated database connection.

    Returns:
        The stored token IDs.
    """
    return list(connection.execute(sa.text("SELECT jti FROM token_revocations ORDER BY jti")).scalars())


@pytest.fixture(params=[pytest.param("sqlite", id="sqlite"), pytest.param("postgresql", id="postgresql", marks=pytest.mark.postgresql)])
def migration_connection(request: pytest.FixtureRequest, tmp_path: Path):
    """Yield an isolated connection with the previous schema.

    Args:
        request: The pytest fixture request.
        tmp_path: The temporary directory for SQLite.

    Yields:
        A connection to an isolated migration database.
    """
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path / 'token-revocations.db'}")
        connection = engine.connect()
        try:
            _create_previous_schema(connection)
            connection.commit()
            yield connection
        finally:
            connection.close()
            engine.dispose()
        return

    if not POSTGRES_URL:
        pytest.skip("MIGRATION_TEST_POSTGRES_URL is not set")

    url = POSTGRES_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)

    engine = create_engine(url)
    schema = f"token_revocation_jti_{uuid.uuid4().hex}"
    try:
        with engine.begin() as admin_connection:
            admin_connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))

        connection = engine.connect()
        try:
            connection.execute(sa.text(f'SET search_path TO "{schema}"'))
            _create_previous_schema(connection)
            connection.commit()
            yield connection
        finally:
            connection.close()
    finally:
        with engine.begin() as admin_connection:
            admin_connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def test_upgrade_widens_jti_and_preserves_schema_and_data(migration_connection: sa.Connection) -> None:
    """Upgrade preserves existing data, constraints, and indexes."""
    inspector = sa.inspect(migration_connection)
    indexes_before = {index["name"] for index in inspector.get_indexes("token_revocations")}
    foreign_keys_before = inspector.get_foreign_keys("token_revocations")

    _run_migration(migration_connection, "upgrade")

    assert _jti_length(migration_connection) == 255
    assert EXISTING_JTI in _stored_jtis(migration_connection)
    _insert_jti(migration_connection, KEYCLOAK_JTI)
    _insert_jti(migration_connection, MAXIMUM_JTI)
    assert _stored_jtis(migration_connection) == sorted([EXISTING_JTI, KEYCLOAK_JTI, MAXIMUM_JTI])

    inspector = sa.inspect(migration_connection)
    assert {index["name"] for index in inspector.get_indexes("token_revocations")} == indexes_before
    assert inspector.get_foreign_keys("token_revocations") == foreign_keys_before
    assert inspector.get_pk_constraint("token_revocations")["constrained_columns"] == ["jti"]


def test_upgrade_is_idempotent(migration_connection: sa.Connection) -> None:
    """A second upgrade leaves the widened schema and data unchanged."""
    _run_migration(migration_connection, "upgrade")
    _run_migration(migration_connection, "upgrade")

    assert _jti_length(migration_connection) == 255
    assert _stored_jtis(migration_connection) == [EXISTING_JTI]


def test_downgrade_rejects_long_jtis_without_schema_or_data_loss(migration_connection: sa.Connection) -> None:
    """Downgrade fails before changing schema or data when a long JTI exists."""
    _run_migration(migration_connection, "upgrade")
    _insert_jti(migration_connection, KEYCLOAK_JTI)
    migration_connection.commit()
    rows_before = _stored_jtis(migration_connection)

    with pytest.raises(RuntimeError, match="exceeds 36 characters"):
        _run_migration(migration_connection, "downgrade")

    assert _jti_length(migration_connection) == 255
    assert _stored_jtis(migration_connection) == rows_before


def test_downgrade_is_safe_and_idempotent_after_long_jtis_are_removed(migration_connection: sa.Connection) -> None:
    """Downgrade and re-upgrade succeed after all long JTIs are removed."""
    _run_migration(migration_connection, "upgrade")
    _insert_jti(migration_connection, KEYCLOAK_JTI)
    _insert_jti(migration_connection, MAXIMUM_JTI)
    migration_connection.execute(sa.text("DELETE FROM token_revocations WHERE jti <> :jti"), {"jti": EXISTING_JTI})
    migration_connection.commit()

    _run_migration(migration_connection, "downgrade")
    assert _jti_length(migration_connection) == 36
    assert _stored_jtis(migration_connection) == [EXISTING_JTI]

    _run_migration(migration_connection, "downgrade")
    assert _jti_length(migration_connection) == 36
    assert _stored_jtis(migration_connection) == [EXISTING_JTI]

    _run_migration(migration_connection, "upgrade")
    assert _jti_length(migration_connection) == 255
    assert _stored_jtis(migration_connection) == [EXISTING_JTI]


def test_missing_table_is_a_noop(tmp_path: Path) -> None:
    """Upgrade and downgrade skip databases without the revocation table."""
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    try:
        with engine.connect() as connection:
            _run_migration(connection, "upgrade")
            _run_migration(connection, "downgrade")
            assert "token_revocations" not in sa.inspect(connection).get_table_names()
    finally:
        engine.dispose()
