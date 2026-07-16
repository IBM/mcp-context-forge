# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_resource_name_uniqueness_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for migration 279184dfd71d (add_name_uniqueness_constraint_to_resources).

Tests verify:
- Migration module structure (import, functions, revision chain)
- Pre-flight duplicate-name detection in upgrade() raises RuntimeError instead of
  letting the unique-index creation fail with an opaque IntegrityError
- Functional execution of upgrade()/downgrade() on SQLite, including the
  skip-when-table-missing and skip-when-index-already-exists guards
"""

# Standard
import importlib
import inspect as pyinspect

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

MODULE_NAME = "mcpgateway.alembic.versions.279184dfd71d_add_name_uniqueness_constraint_to_"
REVISION = "279184dfd71d"  # pragma: allowlist secret
DOWN_REVISION = "e198602c3c1e"  # pragma: allowlist secret


class TestResourceNameUniquenessModuleStructure:
    """Test migration 279184dfd71d module structure."""

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
        """Test migration down_revision matches the docstring's Revises: header."""
        module = importlib.import_module(MODULE_NAME)
        assert module.down_revision == DOWN_REVISION
        assert f"Revises: {DOWN_REVISION}" in module.__doc__

    def test_migration_functions_have_no_parameters(self):
        """Test that upgrade() and downgrade() accept no parameters."""
        module = importlib.import_module(MODULE_NAME)
        assert len(pyinspect.signature(module.upgrade).parameters) == 0
        assert len(pyinspect.signature(module.downgrade).parameters) == 0


def _create_resources_table(conn):
    """Create a minimal `resources` table shaped like the pre-migration schema."""
    conn.execute(
        sa.text(
            """
            CREATE TABLE resources (
                id INTEGER PRIMARY KEY,
                uri VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                team_id VARCHAR(36),
                owner_email VARCHAR(255),
                gateway_id VARCHAR(36),
                visibility VARCHAR(20) DEFAULT 'public'
            )
            """
        )
    )


def _insert_resource(conn, *, name, team_id=None, owner_email=None, gateway_id=None):
    conn.execute(
        sa.text(
            """
            INSERT INTO resources (uri, name, team_id, owner_email, gateway_id)
            VALUES (:uri, :name, :team_id, :owner_email, :gateway_id)
            """
        ),
        {"uri": f"test://{name}/{team_id}/{gateway_id}", "name": name, "team_id": team_id, "owner_email": owner_email, "gateway_id": gateway_id},
    )


def _get_index_names(conn, table_name):
    # Inspector.get_indexes() silently drops expression-based indexes (e.g. the
    # COALESCE(team_id, '') indexes this migration creates), so verification here reads
    # sqlite_master directly rather than relying on reflection - same approach the migration's
    # own idempotency check uses.
    rows = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = :t"), {"t": table_name}).fetchall()
    return {r[0] for r in rows}


def _get_table_names(conn):
    inspector = sa.inspect(conn)
    return set(inspector.get_table_names())


class TestUpgradeFunctional:
    """Functional tests for upgrade() on SQLite."""

    def test_upgrade_creates_unique_indexes(self):
        """Test upgrade creates both unique indexes when no duplicates exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_resources_table(conn)
                _insert_resource(conn, name="alpha", owner_email="a@example.com")
                _insert_resource(conn, name="beta", owner_email="a@example.com")
                conn.commit()

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()

                indexes = _get_index_names(conn, "resources")
                assert "uq_team_owner_gateway_name_resource" in indexes
                assert "uq_team_owner_name_resource_local" in indexes
        finally:
            engine.dispose()

    def test_upgrade_raises_on_existing_duplicate_names(self):
        """Test upgrade aborts with a clear RuntimeError when duplicate names already
        exist under the same (team_id, owner_email, gateway_id) scope, instead of
        letting index creation fail with an opaque IntegrityError."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_resources_table(conn)
                _insert_resource(conn, name="dup", owner_email="a@example.com")
                _insert_resource(conn, name="dup", owner_email="a@example.com")
                conn.commit()

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    with pytest.raises(RuntimeError, match="duplicate name"):
                        module.upgrade()

                # Pre-flight check must fail before any index is created.
                indexes = _get_index_names(conn, "resources")
                assert "uq_team_owner_gateway_name_resource" not in indexes
                assert "uq_team_owner_name_resource_local" not in indexes
        finally:
            engine.dispose()

    def test_upgrade_allows_same_name_in_different_scopes(self):
        """Test upgrade succeeds when the same name is reused across different owners
        (not a real duplicate under the composite uniqueness scope)."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_resources_table(conn)
                _insert_resource(conn, name="shared", owner_email="a@example.com")
                _insert_resource(conn, name="shared", owner_email="b@example.com")
                conn.commit()

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()  # Should not raise

                indexes = _get_index_names(conn, "resources")
                assert "uq_team_owner_gateway_name_resource" in indexes
        finally:
            engine.dispose()

    def test_upgrade_skips_when_table_missing(self):
        """Test upgrade is a no-op when the resources table doesn't exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()  # Should not raise

                assert "resources" not in _get_table_names(conn)
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent_when_indexes_already_exist(self):
        """Test upgrade skips index creation when the indexes are already present."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_resources_table(conn)
                conn.commit()

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()
                    module.upgrade()  # Second run should not raise (index already exists)

                indexes = _get_index_names(conn, "resources")
                assert "uq_team_owner_gateway_name_resource" in indexes
        finally:
            engine.dispose()


class TestDowngradeFunctional:
    """Functional tests for downgrade() on SQLite."""

    def test_downgrade_drops_unique_indexes(self):
        """Test downgrade drops both unique indexes created by upgrade()."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_resources_table(conn)
                conn.commit()

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.upgrade()
                    module.downgrade()

                indexes = _get_index_names(conn, "resources")
                assert "uq_team_owner_gateway_name_resource" not in indexes
                assert "uq_team_owner_name_resource_local" not in indexes
        finally:
            engine.dispose()

    def test_downgrade_skips_when_table_missing(self):
        """Test downgrade is a no-op when the resources table doesn't exist."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.downgrade()  # Should not raise

                assert "resources" not in _get_table_names(conn)
        finally:
            engine.dispose()

    def test_downgrade_is_idempotent_when_indexes_absent(self):
        """Test downgrade is a no-op when the indexes were never created."""
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as conn:
                _create_resources_table(conn)
                conn.commit()

                ctx = MigrationContext.configure(conn, opts={"as_sql": False})
                with Operations.context(ctx):
                    module = importlib.import_module(MODULE_NAME)
                    module.downgrade()  # Should not raise

                assert "resources" in _get_table_names(conn)
        finally:
            engine.dispose()
