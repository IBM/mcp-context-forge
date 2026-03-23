# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_token_uniqueness_migration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for migration d9e0f1a2b3c4 (change token uniqueness to per-team).

Tests verify:
- Migration module structure (import, functions, revision chain)
- Orphaned temp table cleanup guard in upgrade() and downgrade()
- Functional execution with and without orphaned temp tables on SQLite
"""

# Standard
import importlib
import inspect as pyinspect

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.d9e0f1a2b3c4_change_token_uniqueness_to_per_team"
REVISION = "d9e0f1a2b3c4"
DOWN_REVISION = "b2d9c6e4f1a7"


class TestTokenUniquenessModuleStructure:
    """Test migration d9e0f1a2b3c4 module structure."""

    def test_migration_module_imports(self):
        """Test that migration module can be imported."""
        module = importlib.import_module(MODULE_NAME)
        assert module is not None

    def test_migration_has_upgrade_function(self):
        """Test that migration has a callable upgrade() function."""
        module = importlib.import_module(MODULE_NAME)
        assert hasattr(module, "upgrade")
        assert callable(module.upgrade)

    def test_migration_has_downgrade_function(self):
        """Test that migration has a callable downgrade() function."""
        module = importlib.import_module(MODULE_NAME)
        assert hasattr(module, "downgrade")
        assert callable(module.downgrade)

    def test_migration_revision_id(self):
        """Test migration has the correct revision ID."""
        module = importlib.import_module(MODULE_NAME)
        assert module.revision == REVISION

    def test_migration_down_revision(self):
        """Test migration has the correct down_revision."""
        module = importlib.import_module(MODULE_NAME)
        assert module.down_revision == DOWN_REVISION

    def test_migration_functions_have_no_parameters(self):
        """Test that upgrade() and downgrade() accept no parameters."""
        module = importlib.import_module(MODULE_NAME)
        assert len(pyinspect.signature(module.upgrade).parameters) == 0
        assert len(pyinspect.signature(module.downgrade).parameters) == 0


class TestOrphanedTempTableGuard:
    """Test that the orphaned temp table cleanup guard is present in source."""

    def test_upgrade_contains_temp_table_guard(self):
        """Test upgrade() checks for and drops orphaned _alembic_tmp_email_api_tokens."""
        module = importlib.import_module(MODULE_NAME)
        source = pyinspect.getsource(module.upgrade)
        assert "_alembic_tmp_email_api_tokens" in source
        assert 'op.drop_table("_alembic_tmp_email_api_tokens")' in source

    def test_downgrade_contains_temp_table_guard(self):
        """Test downgrade() checks for and drops orphaned _alembic_tmp_email_api_tokens."""
        module = importlib.import_module(MODULE_NAME)
        source = pyinspect.getsource(module.downgrade)
        assert "_alembic_tmp_email_api_tokens" in source
        assert 'op.drop_table("_alembic_tmp_email_api_tokens")' in source

    def test_temp_table_guard_before_batch_alter(self):
        """Test guard appears before batch_alter_table in both functions."""
        module = importlib.import_module(MODULE_NAME)

        for func in (module.upgrade, module.downgrade):
            source = pyinspect.getsource(func)
            guard_pos = source.index('op.drop_table("_alembic_tmp_email_api_tokens")')
            batch_pos = source.index("op.batch_alter_table")
            assert guard_pos < batch_pos, f"Guard must appear before batch_alter_table in {func.__name__}()"

    def test_uses_batch_alter_table_for_sqlite_compat(self):
        """Test that migration uses batch_alter_table (required for SQLite)."""
        module = importlib.import_module(MODULE_NAME)
        upgrade_source = pyinspect.getsource(module.upgrade)
        downgrade_source = pyinspect.getsource(module.downgrade)
        assert "batch_alter_table" in upgrade_source
        assert "batch_alter_table" in downgrade_source


def _create_email_api_tokens_table(conn):
    """Create the email_api_tokens table with the old global uniqueness constraint."""
    conn.execute(
        sa.text(
            """
            CREATE TABLE email_api_tokens (
                id VARCHAR(36) PRIMARY KEY,
                user_email VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                team_id VARCHAR(36),
                hashed_key VARCHAR(255) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_email, name)
            )
            """
        )
    )


def _create_orphaned_temp_table(conn):
    """Create the orphaned _alembic_tmp_email_api_tokens table (simulates failed migration)."""
    conn.execute(
        sa.text(
            """
            CREATE TABLE _alembic_tmp_email_api_tokens (
                id VARCHAR(36) PRIMARY KEY,
                user_email VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                team_id VARCHAR(36),
                hashed_key VARCHAR(255) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )


def _get_table_names(conn):
    """Return a set of table names in the current database."""
    inspector = sa.inspect(conn)
    return set(inspector.get_table_names())


class TestUpgradeFunctional:
    """Functional tests for upgrade() on SQLite."""

    def test_upgrade_with_orphaned_temp_table(self):
        """Test upgrade succeeds when orphaned _alembic_tmp_email_api_tokens exists."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_email_api_tokens_table(conn)
                _create_orphaned_temp_table(conn)
                conn.commit()

                # Verify orphaned table exists
                assert "_alembic_tmp_email_api_tokens" in _get_table_names(conn)

                # Run migration upgrade
                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                # Orphaned table should be gone
                assert "_alembic_tmp_email_api_tokens" not in _get_table_names(conn)
                # Main table should still exist
                assert "email_api_tokens" in _get_table_names(conn)
        finally:
            engine.dispose()

    def test_upgrade_without_orphaned_temp_table(self):
        """Test upgrade succeeds normally without an orphaned temp table."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_email_api_tokens_table(conn)
                conn.commit()

                # Verify no orphaned table
                assert "_alembic_tmp_email_api_tokens" not in _get_table_names(conn)

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                assert "email_api_tokens" in _get_table_names(conn)
        finally:
            engine.dispose()

    def test_upgrade_skips_when_table_missing(self):
        """Test upgrade is a no-op when email_api_tokens table doesn't exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()  # Should not raise

                assert "email_api_tokens" not in _get_table_names(conn)
        finally:
            engine.dispose()


class TestDowngradeFunctional:
    """Functional tests for downgrade() on SQLite."""

    def _create_upgraded_table(self, conn):
        """Create email_api_tokens with the per-team constraint (post-upgrade state)."""
        conn.execute(
            sa.text(
                """
                CREATE TABLE email_api_tokens (
                    id VARCHAR(36) PRIMARY KEY,
                    user_email VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    team_id VARCHAR(36),
                    hashed_key VARCHAR(255) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_email_api_tokens_user_name_team UNIQUE (user_email, name, team_id)
                )
                """
            )
        )
        conn.execute(
            sa.text(
                """
                CREATE UNIQUE INDEX uq_email_api_tokens_user_name_global
                ON email_api_tokens (user_email, name)
                WHERE team_id IS NULL
                """
            )
        )

    def test_downgrade_with_orphaned_temp_table(self):
        """Test downgrade succeeds when orphaned _alembic_tmp_email_api_tokens exists."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                self._create_upgraded_table(conn)
                _create_orphaned_temp_table(conn)
                conn.commit()

                assert "_alembic_tmp_email_api_tokens" in _get_table_names(conn)

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.downgrade()

                assert "_alembic_tmp_email_api_tokens" not in _get_table_names(conn)
                assert "email_api_tokens" in _get_table_names(conn)
        finally:
            engine.dispose()

    def test_downgrade_without_orphaned_temp_table(self):
        """Test downgrade succeeds normally without an orphaned temp table."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                self._create_upgraded_table(conn)
                conn.commit()

                assert "_alembic_tmp_email_api_tokens" not in _get_table_names(conn)

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.downgrade()

                assert "email_api_tokens" in _get_table_names(conn)
        finally:
            engine.dispose()

    def test_downgrade_skips_when_table_missing(self):
        """Test downgrade is a no-op when email_api_tokens table doesn't exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.downgrade()  # Should not raise

                assert "email_api_tokens" not in _get_table_names(conn)
        finally:
            engine.dispose()
