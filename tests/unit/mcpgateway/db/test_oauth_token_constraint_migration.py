# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_oauth_token_constraint_migration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Darren Halden

Unit tests for migration 6b65e7b0c0ad.
"""

# Standard
import importlib
import inspect as pyinspect

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.6b65e7b0c0ad_drop_stale_oauth_token_unique_constraint"
REVISION = "6b65e7b0c0ad"  # pragma: allowlist secret
DOWN_REVISION = "0a089912b5f0"  # pragma: allowlist secret


def _run_migration(conn: sa.Connection, direction: str) -> None:
    ctx = MigrationContext.configure(conn, opts={"as_sql": False})
    with Operations.context(ctx):
        module = importlib.import_module(MODULE_NAME)
        getattr(module, direction)()


def _unique_constraints(conn: sa.Connection) -> list[dict[str, object]]:
    return sa.inspect(conn).get_unique_constraints("oauth_tokens")


def _create_oauth_tokens_table(conn: sa.Connection, *, stale_constraint: bool) -> None:
    stale_constraint_sql = ", CONSTRAINT unique_gateway_user UNIQUE (gateway_id, user_id)" if stale_constraint else ""
    conn.execute(sa.text(f"""
        CREATE TABLE oauth_tokens (
            id VARCHAR(36) PRIMARY KEY,
            gateway_id VARCHAR(36) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            app_user_email VARCHAR(255) NOT NULL,
            access_token TEXT NOT NULL
            {stale_constraint_sql}
        )
        """))
    conn.execute(sa.text("CREATE UNIQUE INDEX idx_oauth_gateway_user ON oauth_tokens (gateway_id, app_user_email)"))


def _insert_oauth_token(conn: sa.Connection, token_id: str, app_user_email: str, provider_user_id: str = "provider-sub") -> None:
    conn.execute(
        sa.text("""
            INSERT INTO oauth_tokens (id, gateway_id, user_id, app_user_email, access_token)
            VALUES (:id, 'gateway-1', :provider_user_id, :app_user_email, :access_token)
            """),
        {
            "id": token_id,
            "provider_user_id": provider_user_id,
            "app_user_email": app_user_email,
            "access_token": f"token-{token_id}",
        },
    )


class TestOAuthTokenConstraintMigrationStructure:
    """Validate migration module metadata and API."""

    def test_migration_module_imports(self):
        module = importlib.import_module(MODULE_NAME)
        assert module is not None

    def test_migration_revision_id(self):
        module = importlib.import_module(MODULE_NAME)
        assert module.revision == REVISION

    def test_migration_down_revision(self):
        module = importlib.import_module(MODULE_NAME)
        assert module.down_revision == DOWN_REVISION

    def test_migration_functions_have_no_parameters(self):
        module = importlib.import_module(MODULE_NAME)
        assert len(pyinspect.signature(module.upgrade).parameters) == 0
        assert len(pyinspect.signature(module.downgrade).parameters) == 0


class TestOAuthTokenConstraintMigrationUpgrade:
    """Functional upgrade tests on SQLite."""

    def test_upgrade_drops_stale_provider_user_constraint(self):
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_oauth_tokens_table(conn, stale_constraint=True)
                conn.commit()

                assert any(constraint["name"] == "unique_gateway_user" for constraint in _unique_constraints(conn))
                _insert_oauth_token(conn, "1", "alice@example.com")
                with pytest.raises(sa.exc.IntegrityError):
                    _insert_oauth_token(conn, "2", "bob@example.com")
                conn.rollback()

                _run_migration(conn, "upgrade")
                assert all(constraint["name"] != "unique_gateway_user" for constraint in _unique_constraints(conn))

                _insert_oauth_token(conn, "1", "alice@example.com")
                _insert_oauth_token(conn, "2", "bob@example.com")
                with pytest.raises(sa.exc.IntegrityError):
                    _insert_oauth_token(conn, "3", "alice@example.com", provider_user_id="other-provider-sub")
        finally:
            engine.dispose()

    def test_upgrade_skips_when_table_missing(self):
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _run_migration(conn, "upgrade")
                assert "oauth_tokens" not in sa.inspect(conn).get_table_names()
        finally:
            engine.dispose()

    def test_upgrade_skips_when_constraint_already_missing(self):
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_oauth_tokens_table(conn, stale_constraint=False)
                conn.commit()
                _run_migration(conn, "upgrade")
                _insert_oauth_token(conn, "1", "alice@example.com")
                _insert_oauth_token(conn, "2", "bob@example.com")
        finally:
            engine.dispose()


class TestOAuthTokenConstraintMigrationDowngrade:
    """Functional downgrade tests on SQLite."""

    def test_downgrade_restores_legacy_provider_user_constraint(self):
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_oauth_tokens_table(conn, stale_constraint=False)
                conn.commit()

                _run_migration(conn, "downgrade")
                assert any(constraint["name"] == "unique_gateway_user" for constraint in _unique_constraints(conn))

                _insert_oauth_token(conn, "1", "alice@example.com")
                with pytest.raises(sa.exc.IntegrityError):
                    _insert_oauth_token(conn, "2", "bob@example.com")
        finally:
            engine.dispose()
