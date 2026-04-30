# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Location: ./tests/unit/mcpgateway/db/test_rbac_permission_backfill_migration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Alembic migration abf8ac3b6008 (backfill admin.overview and servers.use).

Tests verify:
- Migration module structure (import, revision IDs, function signatures)
- Upgrade adds correct permissions idempotently
- Downgrade removes only the added permissions
- Edge cases: missing roles table, missing roles, empty permissions, pre-existing permissions
- Helper function _load_permissions handles all input types
"""

# Standard
import importlib
import inspect as pyinspect
import json

# Third-Party
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

MIGRATION_MODULE = "mcpgateway.alembic.versions.abf8ac3b6008_add_admin_overview_and_servers_use_to_"
EXPECTED_REVISION = "abf8ac3b6008"
EXPECTED_DOWN_REVISION = "64acf94cb7f2"

ROLE_PERMISSION_ADDITIONS = {
    "viewer": ["admin.overview", "servers.use"],
    "platform_viewer": ["admin.overview", "servers.use"],
    "developer": ["admin.overview"],
    "team_admin": ["admin.overview"],
}


@pytest.fixture()
def migration_module():
    """Import the migration module."""
    return importlib.import_module(MIGRATION_MODULE)


# ---------------------------------------------------------------------------
# Module structure tests
# ---------------------------------------------------------------------------


class TestMigrationModuleStructure:
    """Verify migration module structure and metadata."""

    def test_module_imports(self):
        """Migration module can be imported without errors."""
        module = importlib.import_module(MIGRATION_MODULE)
        assert module is not None

    def test_revision_id(self, migration_module):
        """Revision ID matches expected value."""
        assert migration_module.revision == EXPECTED_REVISION

    def test_down_revision(self, migration_module):
        """Down revision points to correct parent."""
        assert migration_module.down_revision == EXPECTED_DOWN_REVISION

    def test_has_upgrade_function(self, migration_module):
        """Module has a callable upgrade() function."""
        assert hasattr(migration_module, "upgrade")
        assert callable(migration_module.upgrade)

    def test_has_downgrade_function(self, migration_module):
        """Module has a callable downgrade() function."""
        assert hasattr(migration_module, "downgrade")
        assert callable(migration_module.downgrade)

    def test_upgrade_has_no_parameters(self, migration_module):
        """upgrade() accepts no parameters."""
        sig = pyinspect.signature(migration_module.upgrade)
        assert len(sig.parameters) == 0

    def test_downgrade_has_no_parameters(self, migration_module):
        """downgrade() accepts no parameters."""
        sig = pyinspect.signature(migration_module.downgrade)
        assert len(sig.parameters) == 0

    def test_role_permission_additions_constant(self, migration_module):
        """ROLE_PERMISSION_ADDITIONS matches expected structure."""
        assert migration_module.ROLE_PERMISSION_ADDITIONS == ROLE_PERMISSION_ADDITIONS


# ---------------------------------------------------------------------------
# _load_permissions helper tests
# ---------------------------------------------------------------------------


class TestLoadPermissions:
    """Test the _load_permissions helper handles all input types."""

    def test_none_returns_empty(self, migration_module):
        assert migration_module._load_permissions(None) == []

    def test_empty_string_returns_empty(self, migration_module):
        assert migration_module._load_permissions("") == []

    def test_json_string_returns_list(self, migration_module):
        result = migration_module._load_permissions('["tools.read", "tools.execute"]')
        assert result == ["tools.read", "tools.execute"]

    def test_bytes_json_returns_list(self, migration_module):
        result = migration_module._load_permissions(b'["tools.read"]')
        assert result == ["tools.read"]

    def test_bytearray_json_returns_list(self, migration_module):
        result = migration_module._load_permissions(bytearray(b'["a.b"]'))
        assert result == ["a.b"]

    def test_native_list_returns_list(self, migration_module):
        result = migration_module._load_permissions(["tools.read", "tools.execute"])
        assert result == ["tools.read", "tools.execute"]

    def test_invalid_json_returns_empty(self, migration_module):
        assert migration_module._load_permissions("{not json}") == []

    def test_filters_non_string_entries(self, migration_module):
        result = migration_module._load_permissions(["valid", 123, None, "also_valid"])
        assert result == ["valid", "also_valid"]

    def test_non_list_json_returns_empty(self, migration_module):
        result = migration_module._load_permissions('{"key": "value"}')
        assert result == []

    def test_integer_returns_empty(self, migration_module):
        assert migration_module._load_permissions(42) == []


# ---------------------------------------------------------------------------
# Functional upgrade/downgrade tests using in-memory SQLite
# ---------------------------------------------------------------------------


@pytest.fixture()
def migration_db():
    """Create an in-memory SQLite DB with a roles table pre-populated."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    with engine.connect() as conn:
        conn.execute(text("""
                CREATE TABLE roles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    permissions TEXT,
                    updated_at TEXT
                )
                """))
        # Pre-populate roles with realistic baseline permissions BEFORE the migration.
        # developer and team_admin already include servers.use and tools.execute in bootstrap_db.py.
        roles_data = [
            ("1", "viewer", json.dumps(["admin.dashboard", "tools.read", "resources.read"])),
            ("2", "platform_viewer", json.dumps(["admin.dashboard", "tools.read", "resources.read"])),
            ("3", "developer", json.dumps(["admin.dashboard", "tools.read", "tools.execute", "resources.read", "servers.use"])),
            ("4", "team_admin", json.dumps(["admin.dashboard", "tools.read", "tools.execute", "resources.read", "servers.use"])),
            ("5", "platform_admin", json.dumps(["*"])),
        ]
        for role_id, name, perms in roles_data:
            conn.execute(text("INSERT INTO roles (id, name, permissions) VALUES (:id, :name, :perms)"), {"id": role_id, "name": name, "perms": perms})
        conn.commit()

    yield engine
    engine.dispose()


def _get_role_permissions(conn, role_name: str) -> list[str]:
    """Helper to read permissions for a role."""
    row = conn.execute(text("SELECT permissions FROM roles WHERE name = :name"), {"name": role_name}).fetchone()
    if not row or not row[0]:
        return []
    return json.loads(row[0])


class TestUpgradeLogic:
    """Test upgrade() adds the correct permissions."""

    def test_upgrade_adds_permissions_to_viewer(self, migration_db, migration_module):
        """Viewer gains admin.overview and servers.use after upgrade."""
        with migration_db.connect() as conn:
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=True)
            conn.commit()

            perms = _get_role_permissions(conn, "viewer")
            assert "admin.overview" in perms
            assert "servers.use" in perms

    def test_upgrade_adds_admin_overview_to_developer(self, migration_db, migration_module):
        """Developer gains admin.overview after upgrade."""
        with migration_db.connect() as conn:
            migration_module._update_role_permissions(conn, "developer", ROLE_PERMISSION_ADDITIONS["developer"], add=True)
            conn.commit()

            perms = _get_role_permissions(conn, "developer")
            assert "admin.overview" in perms

    def test_upgrade_adds_admin_overview_to_team_admin(self, migration_db, migration_module):
        """Team admin gains admin.overview after upgrade."""
        with migration_db.connect() as conn:
            migration_module._update_role_permissions(conn, "team_admin", ROLE_PERMISSION_ADDITIONS["team_admin"], add=True)
            conn.commit()

            perms = _get_role_permissions(conn, "team_admin")
            assert "admin.overview" in perms

    def test_upgrade_preserves_existing_permissions(self, migration_db, migration_module):
        """Existing permissions are not removed during upgrade."""
        with migration_db.connect() as conn:
            original_perms = _get_role_permissions(conn, "viewer")
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=True)
            conn.commit()

            updated_perms = _get_role_permissions(conn, "viewer")
            for perm in original_perms:
                assert perm in updated_perms, f"Original permission '{perm}' was lost"

    def test_upgrade_does_not_duplicate_existing_permissions(self, migration_db, migration_module):
        """Permissions already present are not duplicated."""
        with migration_db.connect() as conn:
            # developer already has tools.execute and servers.use
            migration_module._update_role_permissions(conn, "developer", ROLE_PERMISSION_ADDITIONS["developer"], add=True)
            conn.commit()

            perms = _get_role_permissions(conn, "developer")
            assert perms.count("tools.execute") == 1
            assert perms.count("servers.use") == 1

    def test_upgrade_idempotent(self, migration_db, migration_module):
        """Running upgrade twice produces the same result."""
        with migration_db.connect() as conn:
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=True)
            conn.commit()
            first_perms = _get_role_permissions(conn, "viewer")

            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=True)
            conn.commit()
            second_perms = _get_role_permissions(conn, "viewer")

            assert first_perms == second_perms

    def test_upgrade_does_not_touch_platform_admin(self, migration_db, migration_module):
        """Platform admin (wildcard) is not modified."""
        with migration_db.connect() as conn:
            original_perms = _get_role_permissions(conn, "platform_admin")

            for role_name, permissions in ROLE_PERMISSION_ADDITIONS.items():
                migration_module._update_role_permissions(conn, role_name, permissions, add=True)
            conn.commit()

            final_perms = _get_role_permissions(conn, "platform_admin")
            assert final_perms == original_perms

    def test_upgrade_adds_servers_use_to_viewer(self, migration_db, migration_module):
        """Viewer gains servers.use after upgrade (required for transport access)."""
        with migration_db.connect() as conn:
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=True)
            conn.commit()

            perms = _get_role_permissions(conn, "viewer")
            assert "servers.use" in perms

    def test_upgrade_adds_servers_use_to_platform_viewer(self, migration_db, migration_module):
        """Platform viewer gains servers.use after upgrade."""
        with migration_db.connect() as conn:
            migration_module._update_role_permissions(conn, "platform_viewer", ROLE_PERMISSION_ADDITIONS["platform_viewer"], add=True)
            conn.commit()

            perms = _get_role_permissions(conn, "platform_viewer")
            assert "servers.use" in perms

    def test_upgrade_adds_all_expected_permissions_per_role(self, migration_db, migration_module):
        """Each role receives exactly the permissions defined in ROLE_PERMISSION_ADDITIONS."""
        with migration_db.connect() as conn:
            for role_name, expected_additions in ROLE_PERMISSION_ADDITIONS.items():
                migration_module._update_role_permissions(conn, role_name, expected_additions, add=True)
            conn.commit()

            for role_name, expected_additions in ROLE_PERMISSION_ADDITIONS.items():
                perms = _get_role_permissions(conn, role_name)
                for perm in expected_additions:
                    assert perm in perms, f"Role '{role_name}' missing expected permission '{perm}'"

    def test_upgrade_sets_updated_at(self, migration_db, migration_module):
        """Upgrade sets the updated_at timestamp."""
        with migration_db.connect() as conn:
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=True)
            conn.commit()

            row = conn.execute(text("SELECT updated_at FROM roles WHERE name = 'viewer'")).fetchone()
            assert row[0] is not None


class TestDowngradeLogic:
    """Test downgrade() removes only the added permissions."""

    def test_downgrade_removes_added_permissions(self, migration_db, migration_module):
        """Downgrade removes the permissions that were added."""
        with migration_db.connect() as conn:
            # First upgrade
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=True)
            conn.commit()

            # Then downgrade
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=False)
            conn.commit()

            perms = _get_role_permissions(conn, "viewer")
            assert "admin.overview" not in perms
            assert "servers.use" not in perms

    def test_downgrade_preserves_original_permissions(self, migration_db, migration_module):
        """Downgrade does not remove permissions that existed before upgrade."""
        with migration_db.connect() as conn:
            original_perms = _get_role_permissions(conn, "viewer")

            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=True)
            conn.commit()
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=False)
            conn.commit()

            final_perms = _get_role_permissions(conn, "viewer")
            assert sorted(final_perms) == sorted(original_perms)

    def test_downgrade_removes_servers_use_from_viewer(self, migration_db, migration_module):
        """Downgrade removes servers.use from viewer."""
        with migration_db.connect() as conn:
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=True)
            conn.commit()
            assert "servers.use" in _get_role_permissions(conn, "viewer")

            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=False)
            conn.commit()
            assert "servers.use" not in _get_role_permissions(conn, "viewer")

    def test_downgrade_all_roles(self, migration_db, migration_module):
        """Downgrade removes all added permissions from all four roles."""
        with migration_db.connect() as conn:
            for role_name, permissions in ROLE_PERMISSION_ADDITIONS.items():
                migration_module._update_role_permissions(conn, role_name, permissions, add=True)
            conn.commit()

            for role_name, permissions in ROLE_PERMISSION_ADDITIONS.items():
                migration_module._update_role_permissions(conn, role_name, permissions, add=False)
            conn.commit()

            for role_name, permissions in ROLE_PERMISSION_ADDITIONS.items():
                perms = _get_role_permissions(conn, role_name)
                for perm in permissions:
                    assert perm not in perms, f"Role '{role_name}' still has '{perm}' after downgrade"

    def test_upgrade_downgrade_restores_exact_original_state(self, migration_db, migration_module):
        """Full round-trip: upgrade then downgrade restores exact original permissions for all roles."""
        with migration_db.connect() as conn:
            # Capture original state
            originals = {}
            for role_name in ROLE_PERMISSION_ADDITIONS:
                originals[role_name] = sorted(_get_role_permissions(conn, role_name))

            # Upgrade
            for role_name, permissions in ROLE_PERMISSION_ADDITIONS.items():
                migration_module._update_role_permissions(conn, role_name, permissions, add=True)
            conn.commit()

            # Downgrade
            for role_name, permissions in ROLE_PERMISSION_ADDITIONS.items():
                migration_module._update_role_permissions(conn, role_name, permissions, add=False)
            conn.commit()

            # Verify exact restoration (catches the servers.use regression)
            for role_name, original_perms in originals.items():
                restored = sorted(_get_role_permissions(conn, role_name))
                assert restored == original_perms, (
                    f"Role '{role_name}' not restored after round-trip. " f"Lost: {set(original_perms) - set(restored)}, " f"Extra: {set(restored) - set(original_perms)}"
                )

    def test_downgrade_idempotent(self, migration_db, migration_module):
        """Running downgrade twice produces the same result."""
        with migration_db.connect() as conn:
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=True)
            conn.commit()

            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=False)
            conn.commit()
            first_perms = _get_role_permissions(conn, "viewer")

            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=False)
            conn.commit()
            second_perms = _get_role_permissions(conn, "viewer")

            assert first_perms == second_perms


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_role_skipped(self, migration_db, migration_module):
        """Non-existent role is skipped without error."""
        with migration_db.connect() as conn:
            # Should not raise
            migration_module._update_role_permissions(conn, "nonexistent_role", ["admin.overview"], add=True)
            conn.commit()

    def test_empty_permissions_field(self, migration_module):
        """Role with NULL/empty permissions gets new permissions."""
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE roles (id TEXT PRIMARY KEY, name TEXT NOT NULL, permissions TEXT, updated_at TEXT)"))
            conn.execute(text("INSERT INTO roles (id, name, permissions) VALUES ('1', 'viewer', NULL)"))
            conn.commit()

            migration_module._update_role_permissions(conn, "viewer", ["admin.overview"], add=True)
            conn.commit()

            perms = _get_role_permissions(conn, "viewer")
            assert perms == ["admin.overview"]

        engine.dispose()

    def test_all_four_roles_covered(self, migration_module):
        """Migration covers exactly the four expected roles."""
        expected_roles = {"viewer", "platform_viewer", "developer", "team_admin"}
        actual_roles = set(migration_module.ROLE_PERMISSION_ADDITIONS.keys())
        assert actual_roles == expected_roles

    def test_upgrade_skips_when_no_roles_table(self, migration_module):
        """upgrade() exits cleanly when the roles table does not exist."""
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        with engine.connect() as conn:
            # Empty database — no tables at all
            from unittest.mock import patch

            with patch("alembic.op.get_bind", return_value=conn):
                # Should not raise
                migration_module.upgrade()

        engine.dispose()

    def test_downgrade_skips_when_no_roles_table(self, migration_module):
        """downgrade() exits cleanly when the roles table does not exist."""
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        with engine.connect() as conn:
            from unittest.mock import patch

            with patch("alembic.op.get_bind", return_value=conn):
                # Should not raise
                migration_module.downgrade()

        engine.dispose()

    def test_downgrade_strips_pre_existing_permissions(self, migration_module):
        """Downgrade is not provenance-aware: it removes listed permissions
        even if they existed before the migration ran.

        Accepted trade-off: the migration targets system-bootstrapped roles
        whose baselines are known, so pre-existing customizations are unlikely.
        """
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE roles (id TEXT PRIMARY KEY, name TEXT NOT NULL, permissions TEXT, updated_at TEXT)"))
            # viewer already has admin.overview before migration
            conn.execute(
                text("INSERT INTO roles (id, name, permissions) VALUES (:id, :name, :perms)"),
                {"id": "1", "name": "viewer", "perms": json.dumps(["admin.dashboard", "tools.read", "admin.overview"])},
            )
            conn.commit()

            original = _get_role_permissions(conn, "viewer")
            assert "admin.overview" in original

            # upgrade is a no-op for admin.overview (already present), adds servers.use
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=True)
            conn.commit()
            after_upgrade = _get_role_permissions(conn, "viewer")
            assert "admin.overview" in after_upgrade
            assert "servers.use" in after_upgrade

            # downgrade removes both — including the pre-existing admin.overview
            migration_module._update_role_permissions(conn, "viewer", ROLE_PERMISSION_ADDITIONS["viewer"], add=False)
            conn.commit()
            after_downgrade = _get_role_permissions(conn, "viewer")
            assert "servers.use" not in after_downgrade
            assert "admin.overview" not in after_downgrade

        engine.dispose()

    def test_upgrade_via_entry_point(self, migration_db, migration_module):
        """upgrade() adds all expected permissions when called via its public entry point."""
        from unittest.mock import patch

        with migration_db.connect() as conn:
            originals = {r: _get_role_permissions(conn, r) for r in ROLE_PERMISSION_ADDITIONS}

            with patch("alembic.op.get_bind", return_value=conn):
                migration_module.upgrade()
            conn.commit()

            for role_name, additions in ROLE_PERMISSION_ADDITIONS.items():
                perms = _get_role_permissions(conn, role_name)
                for perm in additions:
                    assert perm in perms, f"upgrade() did not add '{perm}' to '{role_name}'"
                for perm in originals[role_name]:
                    assert perm in perms, f"upgrade() lost pre-existing '{perm}' from '{role_name}'"

    def test_downgrade_via_entry_point(self, migration_db, migration_module):
        """downgrade() removes only the added permissions when called via its public entry point."""
        from unittest.mock import patch

        with migration_db.connect() as conn:
            originals = {r: sorted(_get_role_permissions(conn, r)) for r in ROLE_PERMISSION_ADDITIONS}

            with patch("alembic.op.get_bind", return_value=conn):
                migration_module.upgrade()
            conn.commit()

            with patch("alembic.op.get_bind", return_value=conn):
                migration_module.downgrade()
            conn.commit()

            for role_name, original_perms in originals.items():
                restored = sorted(_get_role_permissions(conn, role_name))
                assert restored == original_perms, f"downgrade() did not restore '{role_name}'. " f"Lost: {set(original_perms) - set(restored)}, " f"Extra: {set(restored) - set(original_perms)}"
