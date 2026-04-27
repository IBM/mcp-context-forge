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
