# -*- coding: utf-8 -*-
"""Location: ./tests/migration/test_revoked_by_nullable.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Migration tests for the TokenRevocation.revoked_by FK relaxation
(issue #5901).

The migration makes ``token_revocations.revoked_by`` nullable and drops
the foreign key to ``email_users.email`` so trust-mode principals (no
local user row) can write revocation rows. SQLite coverage runs hermetic
against an in-memory pre-migration schema. The PostgreSQL cycle runs when
``MIGRATION_TEST_POSTGRES_URL`` points at a scratch database; it is
skipped otherwise.
"""

# Standard
import importlib
import os

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

REVISION = "f7a8b9c0d1e2"  # pragma: allowlist secret
DOWN_REVISION = "e5f6a7b8c9d0"  # pragma: allowlist secret
MODULE_NAME = f"mcpgateway.alembic.versions.{REVISION}_relax_revoked_by_fk"
TABLE_NAME = "token_revocations"
FK_NAME = "token_revocations_revoked_by_fkey"

POSTGRES_URL = os.environ.get("MIGRATION_TEST_POSTGRES_URL")


def _make_sqlite_engine():
    """Return an in-memory SQLite engine that reuses one connection."""
    return sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def _migration_context(conn):
    """Create an Alembic migration context for a live connection."""
    return MigrationContext.configure(conn, opts={"as_sql": False})


def _run_upgrade(conn) -> None:
    """Execute the migration upgrade on a connection."""
    ctx = _migration_context(conn)
    with Operations.context(ctx):
        module = importlib.import_module(MODULE_NAME)
        module.upgrade()


def _run_downgrade(conn) -> None:
    """Execute the migration downgrade on a connection."""
    ctx = _migration_context(conn)
    with Operations.context(ctx):
        module = importlib.import_module(MODULE_NAME)
        module.downgrade()


def _create_pre_migration_schema(conn) -> None:
    """Create the pre-migration schema: revoked_by NOT NULL with the FK."""
    conn.execute(
        sa.text(
            """
            CREATE TABLE email_users (
                id VARCHAR(36) PRIMARY KEY,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL
            )
            """
        )
    )
    conn.execute(
        sa.text(
            f"""
            CREATE TABLE {TABLE_NAME} (
                jti VARCHAR(36) PRIMARY KEY,
                revoked_at DATETIME NOT NULL,
                revoked_by VARCHAR(255) NOT NULL,
                reason VARCHAR(255),
                token_expiry DATETIME,
                last_activity DATETIME,
                CONSTRAINT {FK_NAME} FOREIGN KEY(revoked_by) REFERENCES email_users (email)
            )
            """
        )
    )
    conn.execute(sa.text("INSERT INTO email_users (id, email, password_hash) VALUES ('u-1', 'admin@example.com', 'hash')"))
    conn.execute(
        sa.text(f"INSERT INTO {TABLE_NAME} (jti, revoked_at, revoked_by, reason) VALUES ('jti-existing', '2026-01-01 00:00:00', 'admin@example.com', 'logout')"),
    )
    conn.commit()


def _fk_names(conn) -> list:
    """Return foreign key names constraining token_revocations."""
    return [fk.get("name") for fk in sa.inspect(conn).get_foreign_keys(TABLE_NAME)]


def _revoked_by_column(conn) -> dict:
    """Return the reflected revoked_by column description."""
    columns = {column["name"]: column for column in sa.inspect(conn).get_columns(TABLE_NAME)}
    return columns["revoked_by"]


def _revoked_by_values(conn) -> list:
    """Return all (jti, revoked_by) rows ordered by jti."""
    return list(conn.execute(sa.text(f"SELECT jti, revoked_by FROM {TABLE_NAME} ORDER BY jti")))


def _assert_relaxed(conn) -> None:
    """Assert the post-upgrade shape: nullable column, no FK, rows intact."""
    assert _revoked_by_column(conn)["nullable"] is True
    assert FK_NAME not in _fk_names(conn)
    assert ("jti-existing", "admin@example.com") in _revoked_by_values(conn)
    # Trust-mode shape: no user row backs the revoker identity.
    conn.execute(sa.text(f"INSERT INTO {TABLE_NAME} (jti, revoked_at, revoked_by, reason) VALUES ('jti-trust', '2026-01-02 00:00:00', 'trust-subject-0001', 'logout')"))
    # Sentinel shape: a NULL revoked_by is now legal.
    conn.execute(sa.text(f"INSERT INTO {TABLE_NAME} (jti, revoked_at, revoked_by, reason) VALUES ('jti-null', '2026-01-03 00:00:00', NULL, 'idle_timeout')"))
    conn.commit()


def _assert_restored(conn) -> None:
    """Assert the post-downgrade shape: NOT NULL column, FK restored."""
    assert _revoked_by_column(conn)["nullable"] is False
    assert FK_NAME in _fk_names(conn)


class TestRevokedByMigrationStructure:
    """Verify migration metadata and importability."""

    def test_migration_module_imports(self):
        """Migration module imports successfully."""
        assert importlib.import_module(MODULE_NAME) is not None

    def test_migration_revision_id(self):
        """Revision identifier matches expected value."""
        module = importlib.import_module(MODULE_NAME)
        assert module.revision == REVISION

    def test_migration_down_revision(self):
        """down_revision points to the recorded head."""
        module = importlib.import_module(MODULE_NAME)
        assert module.down_revision == DOWN_REVISION


class TestRevokedByMigrationSqlite:
    """Functional SQLite coverage: up/down/up cycle."""

    def test_upgrade_relaxes_fk_and_nullable(self):
        """upgrade() drops the FK and makes revoked_by nullable."""
        engine = _make_sqlite_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                assert _revoked_by_column(conn)["nullable"] is False
                assert FK_NAME in _fk_names(conn)

                _run_upgrade(conn)

                _assert_relaxed(conn)
        finally:
            engine.dispose()

    def test_downgrade_restores_fk_and_not_null(self):
        """downgrade() restores the FK and the NOT NULL constraint."""
        engine = _make_sqlite_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                _run_upgrade(conn)

                # Downgrade needs FK-valid, non-NULL rows: remove the rows
                # that only the relaxed schema allows.
                conn.execute(sa.text(f"DELETE FROM {TABLE_NAME} WHERE jti IN ('jti-trust', 'jti-null')"))
                conn.commit()

                _run_downgrade(conn)

                _assert_restored(conn)
                assert ("jti-existing", "admin@example.com") in _revoked_by_values(conn)
        finally:
            engine.dispose()

    def test_up_down_up_cycle_is_clean(self):
        """up -> down -> up completes without error and keeps data."""
        engine = _make_sqlite_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                _run_upgrade(conn)
                conn.execute(sa.text(f"DELETE FROM {TABLE_NAME} WHERE jti IN ('jti-trust', 'jti-null')"))
                conn.commit()
                _run_downgrade(conn)
                _assert_restored(conn)

                _run_upgrade(conn)

                _assert_relaxed(conn)
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent(self):
        """A second upgrade run raises no error."""
        engine = _make_sqlite_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                _run_upgrade(conn)

                _run_upgrade(conn)

                _assert_relaxed(conn)
        finally:
            engine.dispose()

    def test_upgrade_skips_when_table_missing(self):
        """upgrade() exits cleanly when token_revocations does not exist."""
        engine = _make_sqlite_engine()
        try:
            with engine.connect() as conn:
                _run_upgrade(conn)
                assert TABLE_NAME not in set(sa.inspect(conn).get_table_names())
        finally:
            engine.dispose()

    def test_downgrade_skips_when_table_missing(self):
        """downgrade() exits cleanly when token_revocations does not exist."""
        engine = _make_sqlite_engine()
        try:
            with engine.connect() as conn:
                _run_downgrade(conn)
                assert TABLE_NAME not in set(sa.inspect(conn).get_table_names())
        finally:
            engine.dispose()


@pytest.mark.skipif(not POSTGRES_URL, reason="MIGRATION_TEST_POSTGRES_URL not set; PostgreSQL cycle runs in CI or local compose")
class TestRevokedByMigrationPostgres:
    """Functional PostgreSQL coverage: up/down/up cycle."""

    def test_up_down_up_cycle_is_clean(self):
        """up -> down -> up completes against a scratch PostgreSQL database."""
        engine = sa.create_engine(POSTGRES_URL)
        try:
            with engine.connect() as conn:
                conn.execute(sa.text(f"DROP TABLE IF EXISTS {TABLE_NAME}"))
                conn.execute(sa.text("DROP TABLE IF EXISTS email_users"))
                conn.commit()

                _create_pre_migration_schema(conn)
                _run_upgrade(conn)
                _assert_relaxed(conn)

                conn.execute(sa.text(f"DELETE FROM {TABLE_NAME} WHERE jti IN ('jti-trust', 'jti-null')"))
                conn.commit()
                _run_downgrade(conn)
                _assert_restored(conn)

                _run_upgrade(conn)
                _assert_relaxed(conn)
        finally:
            with engine.connect() as conn:
                conn.execute(sa.text(f"DROP TABLE IF EXISTS {TABLE_NAME}"))
                conn.execute(sa.text("DROP TABLE IF EXISTS email_users"))
                conn.commit()
            engine.dispose()
