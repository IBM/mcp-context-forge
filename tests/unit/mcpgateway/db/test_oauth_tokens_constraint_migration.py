# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_oauth_tokens_constraint_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for migration 7ab59991e017 (fix oauth_tokens unique constraint).
"""

# Standard
import importlib
import inspect as pyinspect
from types import SimpleNamespace
from unittest.mock import patch

# Third-Party
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

MODULE_NAME = "mcpgateway.alembic.versions.7ab59991e017_fix_oauth_tokens_unique_constraint"
REVISION = "7ab59991e017"  # pragma: allowlist secret
DOWN_REVISION = "d21698ae4a19"  # pragma: allowlist secret
TABLE_NAME = "oauth_tokens"
OLD_CONSTRAINT = "unique_gateway_user"
NEW_CONSTRAINT = "uq_oauth_gateway_user"
LOOKUP_INDEX = "idx_oauth_gateway_user"


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
    """Create oauth_tokens in the buggy pre-fix state.

    State modeled here:
    - old uniqueness still enforced on (gateway_id, user_id)
    - new app_user_email lookup index already exists and must remain
    """
    conn.execute(sa.text("CREATE TABLE gateways (id VARCHAR(36) PRIMARY KEY)"))
    conn.execute(sa.text("CREATE TABLE email_users (email VARCHAR(255) PRIMARY KEY)"))
    conn.execute(
        sa.text(
            """
            CREATE TABLE oauth_tokens (
                id VARCHAR(36) PRIMARY KEY,
                gateway_id VARCHAR(36) NOT NULL,
                user_id VARCHAR(255) NOT NULL,
                app_user_email VARCHAR(255) NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_type VARCHAR(50),
                expires_at DATETIME,
                scopes TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                CONSTRAINT unique_gateway_user UNIQUE (gateway_id, user_id),
                FOREIGN KEY(gateway_id) REFERENCES gateways(id) ON DELETE CASCADE,
                FOREIGN KEY(app_user_email) REFERENCES email_users(email) ON DELETE CASCADE
            )
            """
        )
    )
    conn.execute(sa.text(f"CREATE UNIQUE INDEX {LOOKUP_INDEX} ON oauth_tokens (gateway_id, app_user_email)"))
    conn.commit()


def _table_names(conn) -> set[str]:
    """Return reflected table names."""
    return set(sa.inspect(conn).get_table_names())


def _unique_constraint_names(conn) -> set[str]:
    """Return reflected unique constraint names for oauth_tokens."""
    return {constraint.get("name") for constraint in sa.inspect(conn).get_unique_constraints(TABLE_NAME)}


def _index_names(conn) -> set[str]:
    """Return reflected index names for oauth_tokens."""
    return {index["name"] for index in sa.inspect(conn).get_indexes(TABLE_NAME)}


class TestOAuthTokensConstraintMigrationStructure:
    """Verify migration metadata and importability."""

    def test_migration_module_imports(self):
        """Migration module imports successfully."""
        assert importlib.import_module(MODULE_NAME) is not None

    def test_migration_revision_id(self):
        """Revision identifier matches expected value."""
        module = importlib.import_module(MODULE_NAME)
        assert module.revision == REVISION

    def test_migration_down_revision(self):
        """down_revision points to the expected parent revision."""
        module = importlib.import_module(MODULE_NAME)
        assert module.down_revision == DOWN_REVISION

    def test_migration_functions_have_no_parameters(self):
        """upgrade() and downgrade() remain standard Alembic entrypoints."""
        module = importlib.import_module(MODULE_NAME)
        assert len(pyinspect.signature(module.upgrade).parameters) == 0
        assert len(pyinspect.signature(module.downgrade).parameters) == 0


class TestOAuthTokensConstraintMigrationSqlite:
    """Functional SQLite coverage for the constraint fix migration."""

    def test_upgrade_renames_constraint_and_preserves_lookup_index(self):
        """upgrade() removes the old unique constraint and adds the new one on SQLite."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)

                assert OLD_CONSTRAINT in _unique_constraint_names(conn)
                assert NEW_CONSTRAINT not in _unique_constraint_names(conn)
                assert LOOKUP_INDEX in _index_names(conn)

                _run_upgrade(conn)

                constraint_names = _unique_constraint_names(conn)
                assert OLD_CONSTRAINT not in constraint_names
                assert NEW_CONSTRAINT in constraint_names
                assert LOOKUP_INDEX in _index_names(conn)
        finally:
            engine.dispose()

    def test_upgrade_allows_same_provider_user_for_distinct_app_users(self):
        """upgrade() permits two ContextForge users to store one provider identity."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                _run_upgrade(conn)

                conn.execute(sa.text("INSERT INTO gateways (id) VALUES ('gateway-1')"))
                conn.execute(sa.text("INSERT INTO email_users (email) VALUES ('alice@example.com'), ('bob@example.com')"))
                conn.execute(
                    sa.text(
                        "INSERT INTO oauth_tokens "
                        "(id, gateway_id, user_id, app_user_email, access_token) "
                        "VALUES "
                        "('token-1', 'gateway-1', 'provider-user-1', 'alice@example.com', 'token-a'), "
                        "('token-2', 'gateway-1', 'provider-user-1', 'bob@example.com', 'token-b')"
                    )
                )
                conn.commit()

                count = conn.execute(sa.text("SELECT COUNT(*) FROM oauth_tokens")).scalar_one()
                assert count == 2
        finally:
            engine.dispose()

    def test_downgrade_restores_old_constraint_and_preserves_lookup_index(self):
        """downgrade() restores the historical uniqueness shape on SQLite."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                _run_upgrade(conn)

                _run_downgrade(conn)

                constraint_names = _unique_constraint_names(conn)
                assert NEW_CONSTRAINT not in constraint_names
                assert OLD_CONSTRAINT in constraint_names
                assert LOOKUP_INDEX in _index_names(conn)
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent(self):
        """A second upgrade run is a no-op and keeps the fixed schema intact."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)

                _run_upgrade(conn)
                _run_upgrade(conn)

                constraint_names = _unique_constraint_names(conn)
                assert OLD_CONSTRAINT not in constraint_names
                assert NEW_CONSTRAINT in constraint_names
                assert LOOKUP_INDEX in _index_names(conn)
        finally:
            engine.dispose()

    def test_downgrade_is_idempotent(self):
        """A second downgrade run is a no-op and keeps the legacy schema intact."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                _run_upgrade(conn)

                _run_downgrade(conn)
                _run_downgrade(conn)

                constraint_names = _unique_constraint_names(conn)
                assert NEW_CONSTRAINT not in constraint_names
                assert OLD_CONSTRAINT in constraint_names
                assert LOOKUP_INDEX in _index_names(conn)
        finally:
            engine.dispose()

    def test_downgrade_fails_with_duplicate_gateway_user_pairs(self):
        """downgrade() raises RuntimeError when duplicate (gateway_id, user_id) pairs exist."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_pre_migration_schema(conn)
                _run_upgrade(conn)

                # Insert test data with duplicate (gateway_id, user_id) but different app_user_email
                conn.execute(sa.text("INSERT INTO gateways (id) VALUES ('gateway-1')"))
                conn.execute(sa.text("INSERT INTO email_users (email) VALUES ('alice@example.com'), ('bob@example.com')"))
                conn.execute(
                    sa.text(
                        "INSERT INTO oauth_tokens "
                        "(id, gateway_id, user_id, app_user_email, access_token) "
                        "VALUES "
                        "('token-1', 'gateway-1', 'provider-user-1', 'alice@example.com', 'token-a'), "
                        "('token-2', 'gateway-1', 'provider-user-1', 'bob@example.com', 'token-b')"
                    )
                )
                conn.commit()

                # Verify duplicates exist
                count = conn.execute(sa.text("SELECT COUNT(*) FROM oauth_tokens")).scalar_one()
                assert count == 2

                # Attempt downgrade should raise RuntimeError
                with pytest.raises(RuntimeError) as exc_info:
                    _run_downgrade(conn)

                # Verify error message contains expected details
                error_msg = str(exc_info.value)
                assert "Cannot downgrade migration 7ab59991e017" in error_msg
                assert "duplicate (gateway_id, user_id) pairs exist" in error_msg
                assert "gateway_id=gateway-1" in error_msg
                assert "user_id=provider-user-1" in error_msg
                assert "manually resolve these duplicates" in error_msg

                # Verify new constraint still exists (downgrade was aborted)
                constraint_names = _unique_constraint_names(conn)
                assert NEW_CONSTRAINT not in constraint_names  # Was dropped before duplicate check
                assert OLD_CONSTRAINT not in constraint_names  # Was never created due to error
        finally:
            engine.dispose()

    def test_upgrade_skips_when_oauth_tokens_missing(self):
        """upgrade() exits cleanly when oauth_tokens does not exist."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _run_upgrade(conn)
                assert TABLE_NAME not in _table_names(conn)
        finally:
            engine.dispose()

    def test_downgrade_skips_when_oauth_tokens_missing(self):
        """downgrade() exits cleanly when oauth_tokens does not exist."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _run_downgrade(conn)
                assert TABLE_NAME not in _table_names(conn)
        finally:
            engine.dispose()


class _InspectorState:
    """Minimal mutable inspector state for PostgreSQL branch tests."""

    def __init__(self, tables: set[str], unique_constraints: list[dict[str, str]]):
        self.tables = tables
        self.unique_constraints = unique_constraints

    def get_table_names(self):
        """Return reflected table names."""
        return list(self.tables)

    def get_unique_constraints(self, _table_name: str):
        """Return reflected unique constraints."""
        return list(self.unique_constraints)


class TestOAuthTokensConstraintMigrationPostgresql:
    """Validate PostgreSQL-specific Alembic operations and state transitions."""

    def test_upgrade_drops_old_constraint_and_creates_new_constraint(self):
        """upgrade() uses direct constraint operations on PostgreSQL."""
        module = importlib.import_module(MODULE_NAME)
        fake_conn = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        state = _InspectorState({TABLE_NAME}, [{"name": OLD_CONSTRAINT}])

        def _drop_constraint(name, _table_name, type_):
            assert name == OLD_CONSTRAINT
            assert type_ == "unique"
            state.unique_constraints = [constraint for constraint in state.unique_constraints if constraint.get("name") != OLD_CONSTRAINT]

        def _create_constraint(name, _table_name, columns):
            assert name == NEW_CONSTRAINT
            assert columns == ["gateway_id", "app_user_email"]
            state.unique_constraints.append({"name": NEW_CONSTRAINT})

        with (
            patch.object(module.op, "get_bind", return_value=fake_conn),
            patch.object(module.sa, "inspect", side_effect=lambda _conn: state),
            patch.object(module.op, "drop_constraint", side_effect=_drop_constraint) as drop_constraint,
            patch.object(module.op, "create_unique_constraint", side_effect=_create_constraint) as create_constraint,
        ):
            module.upgrade()

        assert drop_constraint.call_count == 1
        assert create_constraint.call_count == 1
        assert {constraint["name"] for constraint in state.unique_constraints} == {NEW_CONSTRAINT}

    def test_downgrade_drops_new_constraint_and_restores_old_constraint(self):
        """downgrade() restores the historical PostgreSQL constraint."""
        module = importlib.import_module(MODULE_NAME)

        # Mock connection with execute method that returns empty result (no duplicates)
        mock_result = SimpleNamespace(fetchall=lambda: [])
        fake_conn = SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"),
            execute=lambda _query: mock_result
        )
        state = _InspectorState({TABLE_NAME}, [{"name": NEW_CONSTRAINT}])

        def _drop_constraint(name, _table_name, type_):
            assert name == NEW_CONSTRAINT
            assert type_ == "unique"
            state.unique_constraints = [constraint for constraint in state.unique_constraints if constraint.get("name") != NEW_CONSTRAINT]

        def _create_constraint(name, _table_name, columns):
            assert name == OLD_CONSTRAINT
            assert columns == ["gateway_id", "user_id"]
            state.unique_constraints.append({"name": OLD_CONSTRAINT})

        with (
            patch.object(module.op, "get_bind", return_value=fake_conn),
            patch.object(module.sa, "inspect", side_effect=lambda _conn: state),
            patch.object(module.op, "drop_constraint", side_effect=_drop_constraint) as drop_constraint,
            patch.object(module.op, "create_unique_constraint", side_effect=_create_constraint) as create_constraint,
        ):
            module.downgrade()

        assert drop_constraint.call_count == 1
        assert create_constraint.call_count == 1
        assert {constraint["name"] for constraint in state.unique_constraints} == {OLD_CONSTRAINT}
