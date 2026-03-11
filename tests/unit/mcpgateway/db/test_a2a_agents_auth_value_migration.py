# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_a2a_agents_auth_value_migration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for migration a3c38b6c2437 (fix a2a_agents auth_value JSON -> TEXT).

Tests verify:
- Migration module structure (import, functions, revision chain)
- Guard behaviour when table or column is absent
- Functional execution on SQLite (no-op dialect path)
- Data preservation: existing auth_value strings survive upgrade/downgrade cycle
"""

# Standard
import importlib
import inspect as pyinspect
import os

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.a3c38b6c2437_fix_a2a_agents_auth_value"
REVISION = "a3c38b6c2437"
DOWN_REVISION = "e1f2a3b4c5d6"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_a2a_agents_table(conn, auth_value_type: str = "TEXT") -> None:
    """Create a minimal a2a_agents table with the given auth_value column type."""
    conn.execute(
        sa.text(
            f"""
            CREATE TABLE a2a_agents (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                auth_type VARCHAR(20),
                auth_value {auth_value_type}
            )
            """
        )
    )


def _create_a2a_agents_table_no_auth_value(conn) -> None:
    """Create a minimal a2a_agents table without auth_value column."""
    conn.execute(
        sa.text(
            """
            CREATE TABLE a2a_agents (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL
            )
            """
        )
    )


def _get_table_names(conn) -> set:
    return set(sa.inspect(conn).get_table_names())


def _get_column_names(conn, table_name: str) -> set:
    return {col["name"] for col in sa.inspect(conn).get_columns(table_name)}


def _migration_context(conn):
    return MigrationContext.configure(conn, opts={"as_sql": False})


# ---------------------------------------------------------------------------
# Module structure
# ---------------------------------------------------------------------------


class TestMigrationModuleStructure:
    """Test a3c38b6c2437 module structure."""

    def test_migration_module_imports(self):
        """Migration module can be imported."""
        module = importlib.import_module(MODULE_NAME)
        assert module is not None

    def test_migration_has_upgrade_function(self):
        """Migration exposes a callable upgrade()."""
        module = importlib.import_module(MODULE_NAME)
        assert hasattr(module, "upgrade")
        assert callable(module.upgrade)

    def test_migration_has_downgrade_function(self):
        """Migration exposes a callable downgrade()."""
        module = importlib.import_module(MODULE_NAME)
        assert hasattr(module, "downgrade")
        assert callable(module.downgrade)

    def test_migration_revision_id(self):
        """Migration has the correct revision ID."""
        module = importlib.import_module(MODULE_NAME)
        assert module.revision == REVISION

    def test_migration_down_revision(self):
        """Migration has the correct down_revision."""
        module = importlib.import_module(MODULE_NAME)
        assert module.down_revision == DOWN_REVISION

    def test_migration_functions_have_no_parameters(self):
        """upgrade() and downgrade() accept no parameters."""
        module = importlib.import_module(MODULE_NAME)
        assert len(pyinspect.signature(module.upgrade).parameters) == 0
        assert len(pyinspect.signature(module.downgrade).parameters) == 0


# ---------------------------------------------------------------------------
# Guard: missing table / missing column
# ---------------------------------------------------------------------------


class TestUpgradeGuards:
    """Test that upgrade() exits early when preconditions are not met."""

    def test_upgrade_skips_when_table_missing(self):
        """upgrade() is a no-op when a2a_agents does not exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()  # Must not raise
                assert "a2a_agents" not in _get_table_names(conn)
        finally:
            engine.dispose()

    def test_upgrade_skips_when_column_missing(self):
        """upgrade() is a no-op when auth_value column does not exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_a2a_agents_table_no_auth_value(conn)
                conn.commit()
                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()  # Must not raise
                assert "a2a_agents" in _get_table_names(conn)
                assert "auth_value" not in _get_column_names(conn, "a2a_agents")
        finally:
            engine.dispose()


class TestDowngradeGuards:
    """Test that downgrade() exits early when preconditions are not met."""

    def test_downgrade_skips_when_table_missing(self):
        """downgrade() is a no-op when a2a_agents does not exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.downgrade()  # Must not raise
                assert "a2a_agents" not in _get_table_names(conn)
        finally:
            engine.dispose()

    def test_downgrade_skips_when_column_missing(self):
        """downgrade() is a no-op when auth_value column does not exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_a2a_agents_table_no_auth_value(conn)
                conn.commit()
                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.downgrade()  # Must not raise
                assert "a2a_agents" in _get_table_names(conn)
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# Functional: SQLite (no-op dialect path)
# ---------------------------------------------------------------------------


class TestUpgradeFunctional:
    """Functional tests for upgrade() on SQLite."""

    def test_upgrade_is_noop_on_sqlite(self):
        """upgrade() leaves the table intact on SQLite (dialect is not postgresql)."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_a2a_agents_table(conn, auth_value_type="TEXT")
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES ('1', 'agent', 'my-token')"))
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                assert "a2a_agents" in _get_table_names(conn)
                assert "auth_value" in _get_column_names(conn, "a2a_agents")
                row = conn.execute(sa.text("SELECT auth_value FROM a2a_agents WHERE id='1'")).fetchone()
                assert row[0] == "my-token"
        finally:
            engine.dispose()

    def test_upgrade_preserves_null_auth_value(self):
        """upgrade() does not corrupt NULL auth_value rows on SQLite."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_a2a_agents_table(conn, auth_value_type="TEXT")
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES ('1', 'agent', NULL)"))
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                row = conn.execute(sa.text("SELECT auth_value FROM a2a_agents WHERE id='1'")).fetchone()
                assert row[0] is None
        finally:
            engine.dispose()


class TestDowngradeFunctional:
    """Functional tests for downgrade() on SQLite."""

    def test_downgrade_is_noop_on_sqlite(self):
        """downgrade() leaves the table intact on SQLite (dialect is not postgresql)."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_a2a_agents_table(conn, auth_value_type="TEXT")
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES ('1', 'agent', 'bearer-abc')"))
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.downgrade()

                assert "a2a_agents" in _get_table_names(conn)
                row = conn.execute(sa.text("SELECT auth_value FROM a2a_agents WHERE id='1'")).fetchone()
                assert row[0] == "bearer-abc"
        finally:
            engine.dispose()

    def test_downgrade_skips_when_column_is_not_text(self):
        """downgrade() skips when auth_value is not TEXT (already reverted or different type)."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_a2a_agents_table(conn, auth_value_type="INTEGER")
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.downgrade()  # Must not raise

                assert "a2a_agents" in _get_table_names(conn)
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# PostgreSQL functional tests (skipped when TEST_POSTGRES_URL is unset)
# ---------------------------------------------------------------------------

_PG_URL = os.environ.get("TEST_POSTGRES_URL")
_pg_skip = pytest.mark.skipif(not _PG_URL, reason="TEST_POSTGRES_URL not set")


def _pg_engine():
    return sa.create_engine(_PG_URL)


def _setup_pg_table(conn, auth_value_type: str = "JSON") -> None:
    """Create a fresh a2a_agents table on PostgreSQL with the given auth_value type."""
    conn.execute(sa.text("DROP TABLE IF EXISTS a2a_agents CASCADE"))
    conn.execute(
        sa.text(
            f"""
            CREATE TABLE a2a_agents (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                auth_type VARCHAR(20),
                auth_value {auth_value_type}
            )
            """
        )
    )
    conn.commit()


def _drop_pg_table(conn) -> None:
    conn.execute(sa.text("DROP TABLE IF EXISTS a2a_agents CASCADE"))
    conn.commit()


def _pg_auth_value_sql_type(conn) -> str:
    """Return the SQL data_type of auth_value from information_schema."""
    row = conn.execute(sa.text("SELECT data_type FROM information_schema.columns" " WHERE table_name = 'a2a_agents' AND column_name = 'auth_value'")).fetchone()
    return row[0] if row else None


@_pg_skip
class TestPostgreSQLUpgrade:
    """Functional tests for upgrade() on PostgreSQL (requires TEST_POSTGRES_URL)."""

    def test_upgrade_changes_json_column_to_text(self):
        """upgrade() alters auth_value from JSON to TEXT on PostgreSQL."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "JSON")
                assert _pg_auth_value_sql_type(conn) == "json"

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).upgrade()
                conn.commit()

                assert _pg_auth_value_sql_type(conn) == "text"
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()

    def test_upgrade_is_noop_when_column_already_text(self):
        """upgrade() skips without error when auth_value is already TEXT."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "TEXT")
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES ('1', 'agent', 'my-token')"))
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).upgrade()

                row = conn.execute(sa.text("SELECT auth_value FROM a2a_agents WHERE id='1'")).fetchone()
                assert row[0] == "my-token"
                assert _pg_auth_value_sql_type(conn) == "text"
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()

    def test_upgrade_nullifies_empty_json_string(self):
        """upgrade() sets auth_value to NULL when stored value is an empty JSON string ("")."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "JSON")
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES ('1', 'agent', '\"\"')"))
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).upgrade()
                conn.commit()

                row = conn.execute(sa.text("SELECT auth_value FROM a2a_agents WHERE id='1'")).fetchone()
                assert row[0] is None
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()

    def test_upgrade_nullifies_json_null(self):
        """upgrade() sets auth_value to NULL when stored value is JSON null."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "JSON")
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES ('1', 'agent', 'null')"))
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).upgrade()
                conn.commit()

                row = conn.execute(sa.text("SELECT auth_value FROM a2a_agents WHERE id='1'")).fetchone()
                assert row[0] is None
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()

    def test_upgrade_strips_surrounding_json_quotes_from_token(self):
        """upgrade() extracts the plain string from a JSON-encoded token (strips surrounding quotes)."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "JSON")
                # In PostgreSQL, inserting a JSON string value: stored as "my-token" (with quotes in JSON)
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES ('1', 'agent', '\"my-token\"')"))
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).upgrade()
                conn.commit()

                # After upgrade with auth_value#>>'{}', the plain text value is returned
                row = conn.execute(sa.text("SELECT auth_value FROM a2a_agents WHERE id='1'")).fetchone()
                assert row[0] == "my-token"
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()

    def test_upgrade_preserves_null_auth_value(self):
        """upgrade() leaves NULL auth_value rows as NULL on PostgreSQL."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "JSON")
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES ('1', 'agent', NULL)"))
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).upgrade()
                conn.commit()

                row = conn.execute(sa.text("SELECT auth_value FROM a2a_agents WHERE id='1'")).fetchone()
                assert row[0] is None
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()

    def test_upgrade_skips_when_table_missing(self):
        """upgrade() is a no-op when a2a_agents does not exist on PostgreSQL."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _drop_pg_table(conn)

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).upgrade()  # Must not raise

                assert "a2a_agents" not in _get_table_names(conn)
        finally:
            engine.dispose()


@_pg_skip
class TestPostgreSQLDowngrade:
    """Functional tests for downgrade() on PostgreSQL (requires TEST_POSTGRES_URL)."""

    def test_downgrade_changes_text_column_to_json(self):
        """downgrade() alters auth_value from TEXT to JSON on PostgreSQL."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "TEXT")
                assert _pg_auth_value_sql_type(conn) == "text"

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).downgrade()
                conn.commit()

                assert _pg_auth_value_sql_type(conn) == "json"
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()

    def test_downgrade_is_noop_when_column_already_json(self):
        """downgrade() skips without error when auth_value is already JSON."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "JSON")
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).downgrade()  # type is not sa.Text, should skip

                assert _pg_auth_value_sql_type(conn) == "json"
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()

    def test_downgrade_wraps_plain_text_token_in_json(self):
        """downgrade() converts a plain text token to a JSON-encoded string value."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "TEXT")
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES ('1', 'agent', 'my-token')"))
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).downgrade()
                conn.commit()

                assert _pg_auth_value_sql_type(conn) == "json"
                # The value should be accessible as text and contain the token
                row = conn.execute(sa.text("SELECT auth_value::text FROM a2a_agents WHERE id='1'")).fetchone()
                assert "my-token" in row[0]
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()

    def test_downgrade_preserves_null_auth_value(self):
        """downgrade() leaves NULL auth_value rows as NULL on PostgreSQL."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "TEXT")
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES ('1', 'agent', NULL)"))
                conn.commit()

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).downgrade()
                conn.commit()

                row = conn.execute(sa.text("SELECT auth_value FROM a2a_agents WHERE id='1'")).fetchone()
                assert row[0] is None
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()

    def test_downgrade_skips_when_table_missing(self):
        """downgrade() is a no-op when a2a_agents does not exist on PostgreSQL."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _drop_pg_table(conn)

                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    importlib.import_module(MODULE_NAME).downgrade()  # Must not raise

                assert "a2a_agents" not in _get_table_names(conn)
        finally:
            engine.dispose()


@_pg_skip
class TestPostgreSQLRoundtrip:
    """Round-trip upgrade/downgrade tests on PostgreSQL (requires TEST_POSTGRES_URL)."""

    def test_upgrade_then_downgrade_preserves_token_data(self):
        """Full upgrade→downgrade cycle preserves token values and NULL rows."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "JSON")
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES " "('1', 'agent1', '\"bearer-abc\"'), " "('2', 'agent2', '\"api-key-xyz\"'), " "('3', 'agent3', NULL)"))
                conn.commit()

                module = importlib.import_module(MODULE_NAME)

                # --- upgrade ---
                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module.upgrade()
                conn.commit()

                assert _pg_auth_value_sql_type(conn) == "text"
                rows = {r[0]: r[1] for r in conn.execute(sa.text("SELECT id, auth_value FROM a2a_agents")).fetchall()}
                assert rows["1"] == "bearer-abc"
                assert rows["2"] == "api-key-xyz"
                assert rows["3"] is None

                # --- downgrade ---
                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module.downgrade()
                conn.commit()

                assert _pg_auth_value_sql_type(conn) == "json"
                rows_down = {r[0]: r[1] for r in conn.execute(sa.text("SELECT id, auth_value FROM a2a_agents")).fetchall()}
                assert rows_down["3"] is None  # NULL survives the round-trip
                # Tokens are now JSON-encoded strings; verify token text is present
                assert rows_down["1"] is not None
                assert rows_down["2"] is not None
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()

    def test_multiple_upgrades_are_idempotent(self):
        """Running upgrade() twice does not raise or corrupt data."""
        engine = _pg_engine()
        try:
            with engine.connect() as conn:
                _setup_pg_table(conn, "JSON")
                conn.execute(sa.text("INSERT INTO a2a_agents (id, name, auth_value) VALUES ('1', 'agent', '\"token\"')"))
                conn.commit()

                module = importlib.import_module(MODULE_NAME)

                # First upgrade
                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module.upgrade()
                conn.commit()

                # Second upgrade (column is already TEXT, should be a no-op)
                ctx = _migration_context(conn)
                with Operations.context(ctx):
                    module.upgrade()

                assert _pg_auth_value_sql_type(conn) == "text"
                row = conn.execute(sa.text("SELECT auth_value FROM a2a_agents WHERE id='1'")).fetchone()
                assert row[0] == "token"
        finally:
            with engine.connect() as conn:
                _drop_pg_table(conn)
            engine.dispose()
