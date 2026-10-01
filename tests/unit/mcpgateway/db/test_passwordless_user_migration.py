# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_passwordless_user_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for passwordless SSO-only EmailUser migration.
"""

# Standard
import importlib
import inspect as pyinspect

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.5e211ec89cad_allow_nullable_email_user_password_hash"
REVISION = "5e211ec89cad"  # pragma: allowlist secret
DOWN_REVISION = "12d4a0c7789c"  # pragma: allowlist secret


def _migration_context(conn):
    """Create an Alembic migration context for a test connection."""
    return MigrationContext.configure(conn, opts={"as_sql": False})


def _create_email_users_table(conn) -> None:
    """Create the pre-migration email_users shape needed by this revision."""
    conn.execute(
        sa.text(
            """
            CREATE TABLE email_users (
                email VARCHAR(255) PRIMARY KEY,
                password_hash VARCHAR(255) NOT NULL,
                password_hash_type VARCHAR(20) NOT NULL DEFAULT 'argon2id'
            )
            """
        )
    )


def _create_migration_metadata_table(conn) -> None:
    """Create the migration_metadata table used by older migrations."""
    conn.execute(
        sa.text(
            """
            CREATE TABLE migration_metadata (
                revision VARCHAR(64) NOT NULL,
                key VARCHAR(128) NOT NULL,
                value TEXT,
                created_at DATETIME,
                PRIMARY KEY (revision, key)
            )
            """
        )
    )


def _column_nullable(conn, column_name: str) -> bool:
    """Return reflected nullability for an email_users column."""
    columns = {column["name"]: column for column in sa.inspect(conn).get_columns("email_users")}
    return bool(columns[column_name]["nullable"])


def _row(conn, email: str):
    """Fetch a compact email_users row by email."""
    return conn.execute(
        sa.text("SELECT password_hash, password_hash_type FROM email_users WHERE email = :email"),
        {"email": email},
    ).one()


def _metadata_count(conn) -> int:
    """Return passwordless metadata row count for this migration."""
    return int(
        conn.execute(
            sa.text("SELECT COUNT(*) FROM migration_metadata WHERE revision = :revision"),
            {"revision": REVISION},
        ).scalar()
        or 0
    )


@pytest.fixture
def migration():
    """Load migration module."""
    return importlib.import_module(MODULE_NAME)


def test_migration_module_structure(migration):
    """Migration metadata and entry points are valid."""
    assert migration.revision == REVISION
    assert migration.down_revision == DOWN_REVISION
    assert callable(migration.upgrade)
    assert callable(migration.downgrade)
    assert len(pyinspect.signature(migration.upgrade).parameters) == 0
    assert len(pyinspect.signature(migration.downgrade).parameters) == 0


def test_upgrade_and_downgrade_normalize_passwordless_rows(migration):
    """Downgrade normalizes passwordless rows and upgrade restores only those rows."""
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        with engine.connect() as conn:
            _create_email_users_table(conn)
            _create_migration_metadata_table(conn)
            conn.execute(
                sa.text("INSERT INTO email_users (email, password_hash, password_hash_type) VALUES (:email, :password_hash, :password_hash_type)"),
                {"email": "local@example.com", "password_hash": "local-hash", "password_hash_type": "argon2id"},
            )
            conn.execute(
                sa.text("INSERT INTO email_users (email, password_hash, password_hash_type) VALUES (:email, :password_hash, :password_hash_type)"),
                {"email": "disabled@example.com", "password_hash": "!disabled", "password_hash_type": "argon2id"},
            )

            with Operations.context(_migration_context(conn)):
                migration.upgrade()
                migration.upgrade()

            assert _column_nullable(conn, "password_hash") is True

            conn.execute(
                sa.text("INSERT INTO email_users (email, password_hash, password_hash_type) VALUES (:email, :password_hash, :password_hash_type)"),
                {"email": "null@example.com", "password_hash": None, "password_hash_type": "none"},
            )
            conn.execute(
                sa.text("INSERT INTO email_users (email, password_hash, password_hash_type) VALUES (:email, :password_hash, :password_hash_type)"),
                {"email": "marker@example.com", "password_hash": "valid-looking-hash", "password_hash_type": "none"},
            )

            with Operations.context(_migration_context(conn)):
                migration.downgrade()
                migration.downgrade()

            assert _column_nullable(conn, "password_hash") is False
            assert _row(conn, "local@example.com") == ("local-hash", "argon2id")
            assert _row(conn, "disabled@example.com") == ("!disabled", "argon2id")
            assert _row(conn, "null@example.com") == ("!disabled", "argon2id")
            assert _row(conn, "marker@example.com") == ("valid-looking-hash", "argon2id")
            assert _metadata_count(conn) == 3

            with Operations.context(_migration_context(conn)):
                migration.upgrade()
                migration.upgrade()

            assert _column_nullable(conn, "password_hash") is True
            assert _row(conn, "local@example.com") == ("local-hash", "argon2id")
            assert _row(conn, "disabled@example.com") == ("!disabled", "argon2id")
            assert _row(conn, "null@example.com") == (None, "none")
            assert _row(conn, "marker@example.com") == ("valid-looking-hash", "none")
            assert _metadata_count(conn) == 0
    finally:
        engine.dispose()


def test_upgrade_preserves_password_changes_made_while_downgraded(migration):
    """Re-upgrade does not re-mark rows whose password changed while downgraded."""
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        with engine.connect() as conn:
            _create_email_users_table(conn)
            _create_migration_metadata_table(conn)

            with Operations.context(_migration_context(conn)):
                migration.upgrade()

            conn.execute(
                sa.text("INSERT INTO email_users (email, password_hash, password_hash_type) VALUES (:email, :password_hash, :password_hash_type)"),
                {"email": "null-changed@example.com", "password_hash": None, "password_hash_type": "none"},
            )
            conn.execute(
                sa.text("INSERT INTO email_users (email, password_hash, password_hash_type) VALUES (:email, :password_hash, :password_hash_type)"),
                {"email": "marker-changed@example.com", "password_hash": "old-marker-hash", "password_hash_type": "none"},
            )

            with Operations.context(_migration_context(conn)):
                migration.downgrade()

            assert _row(conn, "null-changed@example.com") == ("!disabled", "argon2id")
            assert _row(conn, "marker-changed@example.com") == ("old-marker-hash", "argon2id")
            assert _metadata_count(conn) == 3

            conn.execute(
                sa.text("UPDATE email_users SET password_hash = :password_hash, password_hash_type = :password_hash_type WHERE email = :email"),
                {"email": "null-changed@example.com", "password_hash": "new-null-local-hash", "password_hash_type": "argon2id"},
            )
            conn.execute(
                sa.text("UPDATE email_users SET password_hash = :password_hash, password_hash_type = :password_hash_type WHERE email = :email"),
                {"email": "marker-changed@example.com", "password_hash": "new-marker-local-hash", "password_hash_type": "argon2id"},
            )

            with Operations.context(_migration_context(conn)):
                migration.upgrade()

            assert _row(conn, "null-changed@example.com") == ("new-null-local-hash", "argon2id")
            assert _row(conn, "marker-changed@example.com") == ("new-marker-local-hash", "argon2id")
            assert _metadata_count(conn) == 0
    finally:
        engine.dispose()


def test_upgrade_and_downgrade_skip_when_email_users_missing(migration):
    """Fresh databases without email_users are skipped."""
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        with engine.connect() as conn:
            with Operations.context(_migration_context(conn)):
                migration.upgrade()
                migration.downgrade()

            assert "email_users" not in sa.inspect(conn).get_table_names()
    finally:
        engine.dispose()
