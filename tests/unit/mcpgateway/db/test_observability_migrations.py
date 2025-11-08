# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_observability_migrations.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for observability Alembic migrations.

Tests verify:
- Migration modules can be imported
- Upgrade and downgrade functions exist
- Migration revision IDs are correct
- Dependencies are properly defined
- No syntax errors in migration code
- Cross-database SQL compatibility
"""

# Standard
import importlib
import inspect as pyinspect
import re

# Third-Party
import pytest


# Migration module information
OBSERVABILITY_MIGRATIONS = [
    {
        "module": "mcpgateway.alembic.versions.a23a08d61eb0_add_observability_tables",
        "revision": "a23a08d61eb0",
        "down_revision": "a706a3320c56",
        "description": "add_observability_tables",
    },
    {
        "module": "mcpgateway.alembic.versions.i3c4d5e6f7g8_add_observability_performance_indexes",
        "revision": "i3c4d5e6f7g8",
        "down_revision": "a23a08d61eb0",
        "description": "add observability performance indexes",
    },
    {
        "module": "mcpgateway.alembic.versions.j4d5e6f7g8h9_add_observability_saved_queries",
        "revision": "j4d5e6f7g8h9",
        "down_revision": "i3c4d5e6f7g8",
        "description": "add observability saved queries",
    },
]


class TestObservabilityMigrationModules:
    """Test that all observability migration modules are valid."""

    @pytest.mark.parametrize("migration_info", OBSERVABILITY_MIGRATIONS)
    def test_migration_module_imports(self, migration_info):
        """Test that migration module can be imported."""
        module_name = migration_info["module"]

        try:
            module = importlib.import_module(module_name)
            assert module is not None, f"Module {module_name} imported as None"
        except ImportError as e:
            pytest.fail(f"Failed to import {module_name}: {e}")

    @pytest.mark.parametrize("migration_info", OBSERVABILITY_MIGRATIONS)
    def test_migration_has_upgrade_function(self, migration_info):
        """Test that migration has an upgrade() function."""
        module_name = migration_info["module"]
        module = importlib.import_module(module_name)

        assert hasattr(module, "upgrade"), f"{module_name} missing upgrade() function"
        assert callable(module.upgrade), f"{module_name}.upgrade is not callable"

    @pytest.mark.parametrize("migration_info", OBSERVABILITY_MIGRATIONS)
    def test_migration_has_downgrade_function(self, migration_info):
        """Test that migration has a downgrade() function."""
        module_name = migration_info["module"]
        module = importlib.import_module(module_name)

        assert hasattr(module, "downgrade"), f"{module_name} missing downgrade() function"
        assert callable(module.downgrade), f"{module_name}.downgrade is not callable"

    @pytest.mark.parametrize("migration_info", OBSERVABILITY_MIGRATIONS)
    def test_migration_revision_id_correct(self, migration_info):
        """Test that migration has correct revision ID."""
        module_name = migration_info["module"]
        expected_revision = migration_info["revision"]

        module = importlib.import_module(module_name)

        assert hasattr(module, "revision"), f"{module_name} missing revision variable"
        assert module.revision == expected_revision, f"{module_name} has incorrect revision: {module.revision} != {expected_revision}"

    @pytest.mark.parametrize("migration_info", OBSERVABILITY_MIGRATIONS)
    def test_migration_down_revision_correct(self, migration_info):
        """Test that migration has correct down_revision."""
        module_name = migration_info["module"]
        expected_down_revision = migration_info["down_revision"]

        module = importlib.import_module(module_name)

        assert hasattr(module, "down_revision"), f"{module_name} missing down_revision variable"
        assert module.down_revision == expected_down_revision, f"{module_name} has incorrect down_revision: {module.down_revision} != {expected_down_revision}"

    @pytest.mark.parametrize("migration_info", OBSERVABILITY_MIGRATIONS)
    def test_migration_functions_have_no_parameters(self, migration_info):
        """Test that upgrade() and downgrade() accept no parameters."""
        module_name = migration_info["module"]
        module = importlib.import_module(module_name)

        # Check upgrade function signature
        upgrade_sig = pyinspect.signature(module.upgrade)
        assert len(upgrade_sig.parameters) == 0, f"{module_name}.upgrade() should have no parameters"

        # Check downgrade function signature
        downgrade_sig = pyinspect.signature(module.downgrade)
        assert len(downgrade_sig.parameters) == 0, f"{module_name}.downgrade() should have no parameters"


class TestObservabilityTablesMigration:
    """Test migration a23a08d61eb0 (add observability tables)."""

    def test_creates_four_tables(self):
        """Test that migration creates 4 observability tables."""
        module = importlib.import_module("mcpgateway.alembic.versions.a23a08d61eb0_add_observability_tables")

        # Get source code
        source = pyinspect.getsource(module.upgrade)

        # Count create_table calls
        create_table_count = source.count("op.create_table")
        assert create_table_count == 4, f"Expected 4 create_table calls, found {create_table_count}"

        # Verify table names
        assert "observability_traces" in source
        assert "observability_spans" in source
        assert "observability_events" in source
        assert "observability_metrics" in source

    def test_downgrade_drops_four_tables(self):
        """Test that downgrade drops all 4 tables."""
        module = importlib.import_module("mcpgateway.alembic.versions.a23a08d61eb0_add_observability_tables")

        source = pyinspect.getsource(module.downgrade)

        drop_table_count = source.count("op.drop_table")
        assert drop_table_count == 4, f"Expected 4 drop_table calls, found {drop_table_count}"

    def test_uses_datetime_with_timezone(self):
        """Test that DateTime columns use timezone=True."""
        module = importlib.import_module("mcpgateway.alembic.versions.a23a08d61eb0_add_observability_tables")

        source = pyinspect.getsource(module.upgrade)

        # Should use DateTime(timezone=True)
        assert "DateTime(timezone=True)" in source, "Missing DateTime(timezone=True)"

    def test_uses_json_column_type(self):
        """Test that JSON columns are used for attributes."""
        module = importlib.import_module("mcpgateway.alembic.versions.a23a08d61eb0_add_observability_tables")

        source = pyinspect.getsource(module.upgrade)

        # Should use sa.JSON()
        assert "sa.JSON()" in source, "Missing sa.JSON() column type"

    def test_foreign_keys_have_cascade_delete(self):
        """Test that foreign keys have CASCADE delete."""
        module = importlib.import_module("mcpgateway.alembic.versions.a23a08d61eb0_add_observability_tables")

        source = pyinspect.getsource(module.upgrade)

        # Should have ondelete="CASCADE"
        assert 'ondelete="CASCADE"' in source, "Missing CASCADE delete on foreign keys"


class TestObservabilityPerformanceIndexes:
    """Test migration i3c4d5e6f7g8 (add performance indexes)."""

    def test_uses_op_create_index_not_raw_sql(self):
        """Test that migration uses op.create_index() instead of raw SQL."""
        module = importlib.import_module("mcpgateway.alembic.versions.i3c4d5e6f7g8_add_observability_performance_indexes")

        source = pyinspect.getsource(module.upgrade)

        # Should use op.create_index
        assert "op.create_index" in source, "Missing op.create_index calls"

        # Should NOT use raw SQL with IF NOT EXISTS
        assert "CREATE INDEX IF NOT EXISTS" not in source, "Should not use raw SQL with IF NOT EXISTS"
        assert "op.execute" not in source, "Should not use op.execute for index creation"

    def test_uses_op_drop_index_not_raw_sql(self):
        """Test that downgrade uses op.drop_index() instead of raw SQL."""
        module = importlib.import_module("mcpgateway.alembic.versions.i3c4d5e6f7g8_add_observability_performance_indexes")

        source = pyinspect.getsource(module.downgrade)

        # Should use op.drop_index
        assert "op.drop_index" in source, "Missing op.drop_index calls"

        # Should NOT use raw SQL with IF EXISTS
        assert "DROP INDEX IF EXISTS" not in source, "Should not use raw SQL with IF EXISTS"
        assert "op.execute" not in source, "Should not use op.execute for index dropping"

    def test_creates_composite_indexes(self):
        """Test that migration creates composite indexes."""
        module = importlib.import_module("mcpgateway.alembic.versions.i3c4d5e6f7g8_add_observability_performance_indexes")

        source = pyinspect.getsource(module.upgrade)

        # Check for multi-column indexes
        assert '["status", "start_time"]' in source or "['status', 'start_time']" in source, "Missing composite index on status+start_time"
        assert '["trace_id", "start_time"]' in source or "['trace_id', 'start_time']" in source, "Missing composite index on trace_id+start_time"

    def test_downgrade_drops_indexes_in_reverse_order(self):
        """Test that downgrade drops indexes (reverse order is good practice)."""
        module = importlib.import_module("mcpgateway.alembic.versions.i3c4d5e6f7g8_add_observability_performance_indexes")

        source = pyinspect.getsource(module.downgrade)

        # Count drop_index calls
        drop_count = source.count("op.drop_index")
        create_source = pyinspect.getsource(module.upgrade)
        create_count = create_source.count("op.create_index")

        assert drop_count == create_count, f"Downgrade should drop {create_count} indexes, but drops {drop_count}"

    def test_specifies_table_name_in_drop_index(self):
        """Test that op.drop_index includes table_name parameter."""
        module = importlib.import_module("mcpgateway.alembic.versions.i3c4d5e6f7g8_add_observability_performance_indexes")

        source = pyinspect.getsource(module.downgrade)

        # Should specify table_name for cross-database compatibility
        assert "table_name=" in source, "op.drop_index should specify table_name parameter"


class TestObservabilitySavedQueries:
    """Test migration j4d5e6f7g8h9 (add saved queries table)."""

    def test_boolean_uses_sa_false_not_string(self):
        """Test that Boolean server_default uses sa.false() not string '0'."""
        module = importlib.import_module("mcpgateway.alembic.versions.j4d5e6f7g8h9_add_observability_saved_queries")

        source = pyinspect.getsource(module.upgrade)

        # Should use sa.false() for Boolean
        assert "sa.false()" in source, "Boolean server_default should use sa.false()"

        # Should NOT use string "0" for Boolean
        assert 'sa.Boolean(), nullable=False, server_default="0"' not in source, "Should not use string '0' for Boolean server_default"

    def test_integer_uses_sa_text_for_default(self):
        """Test that Integer server_default uses sa.text('0')."""
        module = importlib.import_module("mcpgateway.alembic.versions.j4d5e6f7g8h9_add_observability_saved_queries")

        source = pyinspect.getsource(module.upgrade)

        # Should use sa.text("0") for Integer
        assert 'sa.text("0")' in source, "Integer server_default should use sa.text('0')"

    def test_no_duplicate_user_email_index(self):
        """Test that there's only ONE index on user_email column."""
        module = importlib.import_module("mcpgateway.alembic.versions.j4d5e6f7g8h9_add_observability_saved_queries")

        source = pyinspect.getsource(module.upgrade)

        # Count how many times we create an index on user_email
        user_email_index_count = 0

        # Look for index creation lines containing user_email
        for line in source.split("\n"):
            if "op.create_index" in line and "user_email" in line:
                user_email_index_count += 1

        assert user_email_index_count == 1, f"Expected 1 user_email index, found {user_email_index_count}"

    def test_downgrade_drops_correct_number_of_indexes(self):
        """Test that downgrade drops the same number of indexes as upgrade creates."""
        module = importlib.import_module("mcpgateway.alembic.versions.j4d5e6f7g8h9_add_observability_saved_queries")

        upgrade_source = pyinspect.getsource(module.upgrade)
        downgrade_source = pyinspect.getsource(module.downgrade)

        create_count = upgrade_source.count("op.create_index")
        drop_count = downgrade_source.count("op.drop_index")

        assert drop_count == create_count, f"Downgrade should drop {create_count} indexes, but drops {drop_count}"

    def test_uses_current_timestamp_for_datetime_defaults(self):
        """Test that DateTime columns use CURRENT_TIMESTAMP for server defaults."""
        module = importlib.import_module("mcpgateway.alembic.versions.j4d5e6f7g8h9_add_observability_saved_queries")

        source = pyinspect.getsource(module.upgrade)

        # Should use sa.text("CURRENT_TIMESTAMP") for DateTime
        assert 'sa.text("CURRENT_TIMESTAMP")' in source, "DateTime columns should use sa.text('CURRENT_TIMESTAMP')"


class TestCrossDatabaseCompatibility:
    """Test cross-database compatibility concerns."""

    def test_no_mysql_specific_if_not_exists(self):
        """Test that migrations don't use MySQL < 8.0.13 incompatible IF NOT EXISTS."""
        for migration_info in OBSERVABILITY_MIGRATIONS:
            module = importlib.import_module(migration_info["module"])
            upgrade_source = pyinspect.getsource(module.upgrade)
            downgrade_source = pyinspect.getsource(module.downgrade)

            # Should not use raw SQL with IF NOT EXISTS / IF EXISTS
            assert "IF NOT EXISTS" not in upgrade_source, f"{migration_info['module']} uses IF NOT EXISTS (MySQL < 8.0.13 incompatible)"
            assert "IF EXISTS" not in downgrade_source, f"{migration_info['module']} uses IF EXISTS (MySQL < 8.0.13 incompatible)"

    def test_uses_sqlalchemy_types_not_raw_sql_types(self):
        """Test that migrations use SQLAlchemy types (sa.*) not raw SQL types."""
        for migration_info in OBSERVABILITY_MIGRATIONS:
            module = importlib.import_module(migration_info["module"])
            source = pyinspect.getsource(module.upgrade)

            # Should use sa.String, sa.Integer, etc.
            if "create_table" in source:
                assert "sa.String" in source or "sa.Text" in source or "sa.Integer" in source, f"{migration_info['module']} should use SQLAlchemy types"

    def test_datetime_columns_use_timezone_parameter(self):
        """Test that DateTime columns specify timezone parameter."""
        module = importlib.import_module("mcpgateway.alembic.versions.a23a08d61eb0_add_observability_tables")

        source = pyinspect.getsource(module.upgrade)

        # All DateTime columns should specify timezone=True
        datetime_matches = re.findall(r"sa\.DateTime\([^)]*\)", source)

        for match in datetime_matches:
            assert "timezone=True" in match, f"DateTime column missing timezone parameter: {match}"


class TestMigrationChain:
    """Test that migrations form a proper chain."""

    def test_migrations_form_continuous_chain(self):
        """Test that down_revision of each migration matches previous revision."""
        # Check that chain is continuous
        revisions = {m["revision"]: m["down_revision"] for m in OBSERVABILITY_MIGRATIONS}

        # i3c4d5e6f7g8 should depend on a23a08d61eb0
        assert revisions["i3c4d5e6f7g8"] == "a23a08d61eb0"

        # j4d5e6f7g8h9 should depend on i3c4d5e6f7g8
        assert revisions["j4d5e6f7g8h9"] == "i3c4d5e6f7g8"

    def test_no_circular_dependencies(self):
        """Test that there are no circular dependencies in migration chain."""
        revisions = {m["revision"]: m["down_revision"] for m in OBSERVABILITY_MIGRATIONS}

        # Build dependency graph and check for cycles
        visited = set()

        for revision in revisions:
            path = []
            current = revision

            while current and current not in visited:
                if current in path:
                    pytest.fail(f"Circular dependency detected: {' -> '.join(path + [current])}")
                path.append(current)
                current = revisions.get(current)

            visited.update(path)

    def test_all_migrations_have_unique_revisions(self):
        """Test that all migration revisions are unique."""
        revisions = [m["revision"] for m in OBSERVABILITY_MIGRATIONS]

        assert len(revisions) == len(set(revisions)), "Duplicate revision IDs found"
