# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_token_name_active_uniqueness_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for migration f3a8c2d94e17 (scope token name uniqueness to active tokens).

Tests verify:
- Migration module structure (import, functions, revision chain)
- Functional execution on SQLite: after upgrade, a revoked (is_active = 0) token no
  longer blocks its name, while duplicate ACTIVE names are still rejected
- Idempotency and missing-table guards in upgrade() and downgrade()
"""

# Standard
import importlib
import inspect as pyinspect

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.f3a8c2d94e17_scope_token_name_uniqueness_to_active_"
REVISION = "f3a8c2d94e17"  # pragma: allowlist secret
DOWN_REVISION = "d21698ae4a19"  # pragma: allowlist secret


class TestActiveUniquenessModuleStructure:
    """Test migration f3a8c2d94e17 module structure."""

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


def _create_pre_upgrade_table(conn):
    """Create email_api_tokens in the pre-upgrade state (all-rows uniqueness)."""
    conn.execute(sa.text("""
            CREATE TABLE email_api_tokens (
                id VARCHAR(36) PRIMARY KEY,
                user_email VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                team_id VARCHAR(36),
                jti VARCHAR(36) NOT NULL,
                token_hash VARCHAR(255) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_email_api_tokens_user_name_team UNIQUE (user_email, name, team_id)
            )
            """))
    conn.execute(sa.text("""
            CREATE UNIQUE INDEX uq_email_api_tokens_user_name_global
            ON email_api_tokens (user_email, name)
            WHERE team_id IS NULL
            """))


def _insert_token(conn, token_id, user_email, name, team_id=None, is_active=1):
    """Insert a minimal email_api_tokens row."""
    conn.execute(
        sa.text("INSERT INTO email_api_tokens (id, user_email, name, team_id, jti, token_hash, is_active) " "VALUES (:id, :user_email, :name, :team_id, :jti, :token_hash, :is_active)"),
        {"id": token_id, "user_email": user_email, "name": name, "team_id": team_id, "jti": f"jti-{token_id}", "token_hash": f"hash-{token_id}", "is_active": is_active},
    )


def _run_migration(conn, func_name):
    """Run the migration's upgrade() or downgrade() against the given connection."""
    ctx = MigrationContext.configure(conn, opts={"as_sql": False})
    with Operations.context(ctx):
        module = importlib.import_module(MODULE_NAME)
        getattr(module, func_name)()


def _get_table_names(conn):
    """Return a set of table names in the current database."""
    inspector = sa.inspect(conn)
    return set(inspector.get_table_names())


class TestUpgradeFunctional:
    """Functional tests for upgrade() on SQLite."""

    def test_revoked_token_name_reusable_after_upgrade(self):
        """A revoked token's name can be reused; the pre-upgrade schema rejected it."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_pre_upgrade_table(conn)
                _insert_token(conn, "t1", "user@example.com", "my-token", is_active=0)  # revoked
                conn.commit()

                # Pre-upgrade: the revoked row still blocks the name (the bug)
                with pytest.raises(sa.exc.IntegrityError):
                    _insert_token(conn, "t2", "user@example.com", "my-token")
                conn.rollback()

                _run_migration(conn, "upgrade")

                # Post-upgrade: the name is reusable
                _insert_token(conn, "t2", "user@example.com", "my-token")
                conn.commit()
        finally:
            engine.dispose()

    def test_duplicate_active_names_still_rejected_after_upgrade(self):
        """Active tokens still cannot share a name in the same scope."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_pre_upgrade_table(conn)
                conn.commit()

                _run_migration(conn, "upgrade")

                # Global scope (team_id IS NULL)
                _insert_token(conn, "t1", "user@example.com", "my-token")
                conn.commit()
                with pytest.raises(sa.exc.IntegrityError):
                    _insert_token(conn, "t2", "user@example.com", "my-token")
                conn.rollback()

                # Team scope
                _insert_token(conn, "t3", "user@example.com", "team-token", team_id="team-1")
                conn.commit()
                with pytest.raises(sa.exc.IntegrityError):
                    _insert_token(conn, "t4", "user@example.com", "team-token", team_id="team-1")
                conn.rollback()

                # Same name in a different team scope is allowed
                _insert_token(conn, "t5", "user@example.com", "team-token", team_id="team-2")
                conn.commit()
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent(self):
        """Running upgrade twice does not raise."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_pre_upgrade_table(conn)
                conn.commit()

                _run_migration(conn, "upgrade")
                _run_migration(conn, "upgrade")  # Should not raise

                assert "email_api_tokens" in _get_table_names(conn)
        finally:
            engine.dispose()

    def test_upgrade_skips_when_table_missing(self):
        """Test upgrade is a no-op when email_api_tokens table doesn't exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _run_migration(conn, "upgrade")  # Should not raise
                assert "email_api_tokens" not in _get_table_names(conn)
        finally:
            engine.dispose()


class TestDowngradeFunctional:
    """Functional tests for downgrade() on SQLite."""

    def test_downgrade_restores_all_rows_uniqueness(self):
        """After downgrade, a revoked token blocks its name again (pre-fix behavior)."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_pre_upgrade_table(conn)
                conn.commit()

                _run_migration(conn, "upgrade")
                _run_migration(conn, "downgrade")

                _insert_token(conn, "t1", "user@example.com", "my-token", is_active=0)
                conn.commit()
                with pytest.raises(sa.exc.IntegrityError):
                    _insert_token(conn, "t2", "user@example.com", "my-token")
                conn.rollback()
        finally:
            engine.dispose()

    def test_downgrade_skips_when_table_missing(self):
        """Test downgrade is a no-op when email_api_tokens table doesn't exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _run_migration(conn, "downgrade")  # Should not raise
                assert "email_api_tokens" not in _get_table_names(conn)
        finally:
            engine.dispose()
