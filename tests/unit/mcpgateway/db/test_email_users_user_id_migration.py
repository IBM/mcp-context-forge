# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_email_users_user_id_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the migration that adds the user_id column to email_users.
"""

# Standard
import importlib
import inspect as pyinspect

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

REVISION = "bf2998718ea1"  # pragma: allowlist secret
DOWN_REVISION = "12d4a0c7789c"  # pragma: allowlist secret
MODULE_NAME = f"mcpgateway.alembic.versions.{REVISION}_add_user_id_to_email_users"
TABLE_NAME = "email_users"
COLUMN_NAME = "user_id"
INDEX_NAME = "ix_email_users_user_id"

SEED_ROWS = [
    ("user-uuid-1", "alice@example.com", "hash-a"),
    ("user-uuid-2", "bob@example.com", "hash-b"),
    ("user-uuid-3", "carol@example.com", "hash-c"),
]


def _make_engine():
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
    """Create a minimal pre-migration email_users table with three rows."""
    conn.execute(
        sa.text(
            """
            CREATE TABLE email_users (
                id VARCHAR(36) PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                password_hash VARCHAR(255) NOT NULL
            )
            """
        )
    )
    conn.execute(
        sa.text("INSERT INTO email_users (id, email, password_hash) VALUES (:id, :email, :password_hash)"),
        [{"id": row_id, "email": email, "password_hash": password_hash} for row_id, email, password_hash in SEED_ROWS],
    )
    conn.commit()


def _table_names(conn) -> set[str]:
    """Return reflected table names."""
    return set(sa.inspect(conn).get_table_names())


def _column_names(conn) -> set[str]:
    """Return reflected column names for email_users."""
    return {column["name"] for column in sa.inspect(conn).get_columns(TABLE_NAME)}


def _indexes(conn) -> list[dict]:
    """Return reflected index descriptions for email_users."""
    return list(sa.inspect(conn).get_indexes(TABLE_NAME))


def _rows(conn) -> list[tuple]:
    """Return all email_users rows ordered by id."""
    return list(conn.execute(sa.text("SELECT id, email, user_id FROM email_users ORDER BY id")))


class TestEmailUsersUserIdMigrationStructure:
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

    def test_migration_functions_have_no_parameters(self):
        """upgrade() and downgrade() remain standard Alembic entrypoints."""
        module = importlib.import_module(MODULE_NAME)
        assert len(pyinspect.signature(module.upgrade).parameters) == 0
        assert len(pyinspect.signature(module.downgrade).parameters) == 0


class TestEmailUsersUserIdMigrationSqlite:
    """Functional SQLite coverage for the user_id column migration."""

    def test_upgrade_adds_user_id_column(self):
        """upgrade() adds the nullable user_id column to email_users."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                assert COLUMN_NAME not in _column_names(conn)

                _run_upgrade(conn)

                columns = {column["name"]: column for column in sa.inspect(conn).get_columns(TABLE_NAME)}
                assert COLUMN_NAME in columns
                assert columns[COLUMN_NAME]["nullable"] is True
        finally:
            engine.dispose()

    def test_upgrade_backfills_user_id_with_email(self):
        """upgrade() sets user_id equal to email on every existing row."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                _run_upgrade(conn)

                rows = _rows(conn)
                assert len(rows) == len(SEED_ROWS)
                for _row_id, email, user_id in rows:
                    assert user_id == email
        finally:
            engine.dispose()

    def test_upgrade_creates_non_unique_index(self):
        """upgrade() creates a non-unique index ix_email_users_user_id on user_id."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                _run_upgrade(conn)

                indexes = {index["name"]: index for index in _indexes(conn)}
                assert INDEX_NAME in indexes
                assert indexes[INDEX_NAME]["column_names"] == [COLUMN_NAME]
                assert not indexes[INDEX_NAME]["unique"]
        finally:
            engine.dispose()

    def test_downgrade_removes_column_and_index(self):
        """downgrade() drops both the index and the user_id column."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                _run_upgrade(conn)

                _run_downgrade(conn)

                assert COLUMN_NAME not in _column_names(conn)
                assert INDEX_NAME not in {index["name"] for index in _indexes(conn)}
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent(self):
        """A second upgrade run raises no error and changes no row."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                _run_upgrade(conn)
                before = _rows(conn)

                # Diverge one row: a re-run must not overwrite a non-NULL user_id.
                conn.execute(sa.text("UPDATE email_users SET user_id = 'canonical-uuid-1' WHERE email = 'alice@example.com'"))
                conn.commit()

                _run_upgrade(conn)

                after = _rows(conn)
                assert len(after) == len(before)
                for (_id_before, email_before, _uid_before), (_id_after, email_after, uid_after) in zip(before, after):
                    assert email_after == email_before
                user_ids = {email: user_id for _row_id, email, user_id in after}
                assert user_ids["alice@example.com"] == "canonical-uuid-1"
                assert user_ids["bob@example.com"] == "bob@example.com"
                assert user_ids["carol@example.com"] == "carol@example.com"
        finally:
            engine.dispose()

    def test_upgrade_skips_when_email_users_missing(self):
        """upgrade() exits cleanly when email_users does not exist."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _run_upgrade(conn)
                assert TABLE_NAME not in _table_names(conn)
        finally:
            engine.dispose()

    def test_downgrade_skips_when_email_users_missing(self):
        """downgrade() exits cleanly when email_users does not exist."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _run_downgrade(conn)
                assert TABLE_NAME not in _table_names(conn)
        finally:
            engine.dispose()
