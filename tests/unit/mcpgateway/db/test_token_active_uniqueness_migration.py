# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_token_active_uniqueness_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for issue #5931: revoked API tokens must not block name reuse.

Tests verify:
- Migration a7b8c9d0e1f2 module structure (import, functions, revision chain)
- Functional upgrade/downgrade execution on SQLite
- Model-level partial unique indexes on EmailApiToken scope uniqueness to
  active tokens only (revoked token names can be reused, active ones cannot)
"""

# Standard
import importlib
import inspect as pyinspect

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

# First-Party
from mcpgateway.db import EmailApiToken

MODULE_NAME = "mcpgateway.alembic.versions.a7b8c9d0e1f2_scope_token_name_uniqueness_to_active"
REVISION = "a7b8c9d0e1f2"  # pragma: allowlist secret
DOWN_REVISION = "d21698ae4a19"  # pragma: allowlist secret


class TestTokenActiveUniquenessModuleStructure:
    """Test migration a7b8c9d0e1f2 module structure."""

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


def _create_old_email_api_tokens_table(conn):
    """Create email_api_tokens with the pre-migration all-rows uniqueness rules."""
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


def _insert_token(conn, name, user_email="user@example.com", team_id=None, is_active=1, token_id=None):
    """Insert a minimal email_api_tokens row."""
    conn.execute(
        sa.text("INSERT INTO email_api_tokens (id, user_email, name, team_id, jti, token_hash, is_active) VALUES (:id, :email, :name, :team_id, :jti, :hash, :active)"),
        {
            "id": token_id or f"id-{name}-{team_id}-{is_active}-{user_email}",
            "email": user_email,
            "name": name,
            "team_id": team_id,
            "jti": f"jti-{name}-{team_id}-{is_active}-{user_email}",
            "hash": "x",
            "active": is_active,
        },
    )


def _get_index_names(conn):
    """Return index names on email_api_tokens."""
    return {idx["name"] for idx in sa.inspect(conn).get_indexes("email_api_tokens")}


def _get_constraint_names(conn):
    """Return unique constraint names on email_api_tokens."""
    return {c["name"] for c in sa.inspect(conn).get_unique_constraints("email_api_tokens")}


class TestUpgradeFunctional:
    """Functional tests for upgrade() on SQLite."""

    def test_upgrade_replaces_all_rows_constraint_with_active_scoped_indexes(self):
        """After upgrade, uniqueness is enforced by active-only partial indexes."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_old_email_api_tokens_table(conn)
                conn.commit()

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                assert "uq_email_api_tokens_user_name_team" not in _get_constraint_names(conn)
                indexes = _get_index_names(conn)
                assert "uq_email_api_tokens_user_name_team" in indexes
                assert "uq_email_api_tokens_user_name_global" in indexes
        finally:
            engine.dispose()

    def test_upgrade_allows_name_reuse_after_revocation(self):
        """Regression test for #5931: a revoked token's name can be reused."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_old_email_api_tokens_table(conn)
                _insert_token(conn, "my-token", is_active=1)
                conn.execute(sa.text("UPDATE email_api_tokens SET is_active = 0 WHERE name = 'my-token'"))
                conn.commit()

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                # Global scope: same name after revocation must succeed
                _insert_token(conn, "my-token", is_active=1, token_id="id-new-global")
                # Team scope: same name after revocation must succeed
                _insert_token(conn, "team-token", team_id="team-1", is_active=0, token_id="id-old-team")
                _insert_token(conn, "team-token", team_id="team-1", is_active=1, token_id="id-new-team")
                conn.commit()
        finally:
            engine.dispose()

    def test_upgrade_still_blocks_duplicate_active_names(self):
        """After upgrade, two ACTIVE tokens with the same name in one scope conflict."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_old_email_api_tokens_table(conn)
                conn.commit()

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                _insert_token(conn, "dup", is_active=1, token_id="id-a")
                with pytest.raises(sa.exc.IntegrityError):
                    with conn.begin_nested():
                        _insert_token(conn, "dup", is_active=1, token_id="id-b")

                _insert_token(conn, "dup-team", team_id="team-1", is_active=1, token_id="id-c")
                with pytest.raises(sa.exc.IntegrityError):
                    with conn.begin_nested():
                        _insert_token(conn, "dup-team", team_id="team-1", is_active=1, token_id="id-d")

                # Same name in a different team scope is still allowed
                _insert_token(conn, "dup-team", team_id="team-2", is_active=1, token_id="id-e")
                conn.commit()
        finally:
            engine.dispose()

    def test_upgrade_cleans_up_orphaned_temp_table(self):
        """Upgrade drops a leftover _alembic_tmp_email_api_tokens table."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_old_email_api_tokens_table(conn)
                conn.execute(sa.text("CREATE TABLE _alembic_tmp_email_api_tokens (id VARCHAR(36) PRIMARY KEY)"))
                conn.commit()

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                assert "_alembic_tmp_email_api_tokens" not in set(sa.inspect(conn).get_table_names())
                assert "email_api_tokens" in set(sa.inspect(conn).get_table_names())
        finally:
            engine.dispose()

    def test_upgrade_skips_when_table_missing(self):
        """Upgrade is a no-op when email_api_tokens table doesn't exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()  # Should not raise

                assert "email_api_tokens" not in set(sa.inspect(conn).get_table_names())
        finally:
            engine.dispose()


class TestDowngradeFunctional:
    """Functional tests for downgrade() on SQLite."""

    def test_downgrade_restores_all_rows_uniqueness(self):
        """Downgrade restores the all-rows constraint and global partial index."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_old_email_api_tokens_table(conn)
                conn.commit()

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()
                    module.downgrade()

                assert "uq_email_api_tokens_user_name_team" in _get_constraint_names(conn)
                assert "uq_email_api_tokens_user_name_global" in _get_index_names(conn)

                # Restored all-rows rule: revoked token name can no longer be reused
                _insert_token(conn, "restored", is_active=0, token_id="id-old")
                with pytest.raises(sa.exc.IntegrityError):
                    with conn.begin_nested():
                        _insert_token(conn, "restored", is_active=1, token_id="id-new")
        finally:
            engine.dispose()

    def test_downgrade_skips_when_table_missing(self):
        """Downgrade is a no-op when email_api_tokens table doesn't exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.downgrade()  # Should not raise

                assert "email_api_tokens" not in set(sa.inspect(conn).get_table_names())
        finally:
            engine.dispose()


class TestEmailApiTokenModelIndexes:
    """Model-level tests: fresh databases (db.py __table_args__) get active-scoped uniqueness."""

    def _create_table(self, engine):
        """Create only the email_api_tokens table from the model metadata."""
        EmailApiToken.__table__.create(engine, checkfirst=True)

    def test_model_defines_active_scoped_partial_indexes(self):
        """Model exposes partial unique indexes filtered on is_active, no all-rows constraint."""
        constraint_names = {c.name for c in EmailApiToken.__table__.constraints if isinstance(c, sa.UniqueConstraint)}
        assert "uq_email_api_tokens_user_name_team" not in constraint_names

        index_by_name = {idx.name: idx for idx in EmailApiToken.__table__.indexes}
        team_idx = index_by_name["uq_email_api_tokens_user_name_team"]
        global_idx = index_by_name["uq_email_api_tokens_user_name_global"]

        assert team_idx.unique
        assert [c.name for c in team_idx.columns] == ["user_email", "name", "team_id"]
        assert global_idx.unique
        assert [c.name for c in global_idx.columns] == ["user_email", "name"]

        # The is_active filter must be part of both dialect WHERE clauses
        for idx in (team_idx, global_idx):
            pg_where = str(idx.dialect_options["postgresql"]["where"])
            sqlite_where = str(idx.dialect_options["sqlite"]["where"])
            assert "is_active" in pg_where
            assert "is_active" in sqlite_where

    def test_fresh_db_allows_name_reuse_after_revocation(self):
        """On a fresh SQLite DB, a revoked token's name can be reused (#5931)."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            self._create_table(engine)
            with engine.begin() as conn:
                conn.execute(
                    EmailApiToken.__table__.insert().values(user_email="user@example.com", name="my-token", team_id=None, token_hash="h1", is_active=False),
                )
                # Reusing the revoked token's name must succeed
                conn.execute(
                    EmailApiToken.__table__.insert().values(user_email="user@example.com", name="my-token", team_id=None, token_hash="h2", is_active=True),
                )
        finally:
            engine.dispose()

    def test_fresh_db_blocks_duplicate_active_names(self):
        """On a fresh SQLite DB, two ACTIVE tokens with the same name in one scope conflict."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            self._create_table(engine)
            with engine.begin() as conn:
                conn.execute(
                    EmailApiToken.__table__.insert().values(user_email="user@example.com", name="my-token", team_id=None, token_hash="h1", is_active=True),
                )
                with pytest.raises(sa.exc.IntegrityError):
                    with conn.begin_nested():
                        conn.execute(
                            EmailApiToken.__table__.insert().values(user_email="user@example.com", name="my-token", team_id=None, token_hash="h2", is_active=True),
                        )
        finally:
            engine.dispose()
