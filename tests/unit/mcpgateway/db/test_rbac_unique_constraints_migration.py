# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_rbac_unique_constraints_migration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for migration d21698ae4a19 (add_rbac_unique_constraints_race_fix).

Tests verify:
- Migration module structure (import, revision chain, function signatures)
- Roles deduplication keeps the oldest role by created_at and deactivates others
- user_roles remapping: assignments pointing at a duplicate role are remapped to the kept role
  *before* that duplicate role is deactivated, so list_user_roles() join on active roles still works
- user_roles deduplication prefers unexpired assignments over expired ones, and newest-granted wins
  among same-expiry rows
- Partial unique index creation is idempotent (safe to run twice)
- upgrade() and downgrade() are no-ops when the tables do not exist
"""

# Standard
import importlib
import inspect as pyinspect
from datetime import datetime, timedelta, timezone

# Third-Party
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

MODULE_NAME = "mcpgateway.alembic.versions.d21698ae4a19_add_rbac_unique_constraints_race_fix"
REVISION = "d21698ae4a19"  # pragma: allowlist secret
DOWN_REVISION = "b6c7d8e9f0a1"  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine():
    """Return an in-memory SQLite engine."""
    return sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def _create_tables(conn):
    """Create minimal roles and user_roles tables matching the production schema."""
    conn.execute(text("""
        CREATE TABLE roles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'global',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """))
    conn.execute(text("""
        CREATE TABLE user_roles (
            id TEXT PRIMARY KEY,
            user_email TEXT NOT NULL,
            role_id TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'global',
            scope_id TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            granted_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT
        )
    """))
    conn.commit()


def _run_upgrade(conn):
    """Run the migration upgrade() with the given connection."""
    ctx = MigrationContext.configure(conn, opts={"as_sql": False})
    with Operations.context(ctx):
        module = importlib.import_module(MODULE_NAME)
        module.upgrade()


def _run_downgrade(conn):
    """Run the migration downgrade() with the given connection."""
    ctx = MigrationContext.configure(conn, opts={"as_sql": False})
    with Operations.context(ctx):
        module = importlib.import_module(MODULE_NAME)
        module.downgrade()


def _get_table_names(conn):
    inspector = sa.inspect(conn)
    return set(inspector.get_table_names())


def _get_index_names(conn, table):
    inspector = sa.inspect(conn)
    return {idx["name"] for idx in inspector.get_indexes(table)}


def _now_str(offset_seconds=0):
    """Return an ISO datetime string offset from now by `offset_seconds`."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Module structure tests
# ---------------------------------------------------------------------------


class TestModuleStructure:
    """Verify migration module metadata and function signatures."""

    def test_module_imports(self):
        """Migration module can be imported without errors."""
        module = importlib.import_module(MODULE_NAME)
        assert module is not None

    def test_revision_id(self):
        """Revision ID matches expected value."""
        module = importlib.import_module(MODULE_NAME)
        assert module.revision == REVISION

    def test_down_revision(self):
        """Down revision points to the correct parent."""
        module = importlib.import_module(MODULE_NAME)
        assert module.down_revision == DOWN_REVISION

    def test_has_upgrade_function(self):
        """Module has a callable upgrade() function."""
        module = importlib.import_module(MODULE_NAME)
        assert callable(module.upgrade)

    def test_has_downgrade_function(self):
        """Module has a callable downgrade() function."""
        module = importlib.import_module(MODULE_NAME)
        assert callable(module.downgrade)

    def test_upgrade_accepts_no_params(self):
        """upgrade() takes no parameters."""
        module = importlib.import_module(MODULE_NAME)
        assert len(pyinspect.signature(module.upgrade).parameters) == 0

    def test_downgrade_accepts_no_params(self):
        """downgrade() takes no parameters."""
        module = importlib.import_module(MODULE_NAME)
        assert len(pyinspect.signature(module.downgrade).parameters) == 0


# ---------------------------------------------------------------------------
# No-op when tables are absent
# ---------------------------------------------------------------------------


class TestNoopWithoutTables:
    """Migration is a no-op when the target tables do not exist."""

    def test_upgrade_skips_when_tables_missing(self):
        """upgrade() exits cleanly on an empty database."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _run_upgrade(conn)
                # No tables created by migration itself
                assert "roles" not in _get_table_names(conn)
        finally:
            engine.dispose()

    def test_downgrade_skips_when_tables_missing(self):
        """downgrade() exits cleanly on an empty database."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _run_downgrade(conn)
                assert "roles" not in _get_table_names(conn)
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# Roles deduplication
# ---------------------------------------------------------------------------


class TestRolesDeduplications:
    """Roles table deduplication keeps oldest active role by (name, scope)."""

    def test_no_duplicates_untouched(self):
        """No rows are changed when there are no duplicates."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r1','admin','global',1,'2024-01-01')"))
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r2','viewer','global',1,'2024-01-02')"))
                conn.commit()

                _run_upgrade(conn)

                rows = conn.execute(text("SELECT id, is_active FROM roles ORDER BY id")).fetchall()
                assert len(rows) == 2
                for row in rows:
                    assert row[1] == 1, f"Role {row[0]} should still be active"
        finally:
            engine.dispose()

    def test_duplicate_roles_oldest_kept(self):
        """When two active roles share (name, scope), the oldest (earliest created_at) is kept."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                # r1 is older — it should be kept
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r1','admin','global',1,'2024-01-01')"))
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r2','admin','global',1,'2024-06-01')"))
                conn.commit()

                _run_upgrade(conn)

                r1 = conn.execute(text("SELECT is_active FROM roles WHERE id='r1'")).scalar()
                r2 = conn.execute(text("SELECT is_active FROM roles WHERE id='r2'")).scalar()
                assert r1 == 1, "Oldest role should remain active"
                assert r2 == 0, "Newer duplicate should be deactivated"
        finally:
            engine.dispose()

    def test_inactive_roles_not_touched(self):
        """Inactive roles are not re-activated or further modified."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r1','admin','global',1,'2024-01-01')"))
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r2','admin','global',0,'2023-01-01')"))
                conn.commit()

                _run_upgrade(conn)

                r1 = conn.execute(text("SELECT is_active FROM roles WHERE id='r1'")).scalar()
                r2 = conn.execute(text("SELECT is_active FROM roles WHERE id='r2'")).scalar()
                assert r1 == 1
                assert r2 == 0  # remains inactive
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# user_roles remapping (review comment #1)
# ---------------------------------------------------------------------------


class TestUserRolesRemapping:
    """Assignments pointing at a duplicate role are remapped to the kept role."""

    def test_assignment_remapped_before_role_deactivated(self):
        """user_roles.role_id is updated to the kept role id before the duplicate is deactivated."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                # Two duplicate active roles — r1 (oldest) will be kept, r2 deactivated
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r1','admin','global',1,'2024-01-01')"))
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r2','admin','global',1,'2024-06-01')"))
                # Assignment points at r2 (the duplicate that will be deactivated)
                conn.execute(text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, is_active, granted_at) "
                    "VALUES ('ur1','alice@example.com','r2','global',1,'2024-06-01')"
                ))
                conn.commit()

                _run_upgrade(conn)

                # Assignment must now point at r1 (the kept role)
                role_id = conn.execute(text("SELECT role_id FROM user_roles WHERE id='ur1'")).scalar()
                assert role_id == "r1", f"Assignment should be remapped to r1 but got {role_id}"

                # r2 should be deactivated
                r2_active = conn.execute(text("SELECT is_active FROM roles WHERE id='r2'")).scalar()
                assert r2_active == 0
        finally:
            engine.dispose()

    def test_assignment_to_kept_role_unchanged(self):
        """Assignments already pointing at the kept role are not altered."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r1','admin','global',1,'2024-01-01')"))
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r2','admin','global',1,'2024-06-01')"))
                # Assignment already points at r1 (the winner)
                conn.execute(text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, is_active, granted_at) "
                    "VALUES ('ur1','bob@example.com','r1','global',1,'2024-01-15')"
                ))
                conn.commit()

                _run_upgrade(conn)

                role_id = conn.execute(text("SELECT role_id FROM user_roles WHERE id='ur1'")).scalar()
                assert role_id == "r1"
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# user_roles deduplication ordering (review comment #2)
# ---------------------------------------------------------------------------


class TestUserRolesDeduplicationOrdering:
    """Unexpired assignments are preferred over expired ones when deduplicating user_roles."""

    def test_unexpired_kept_over_expired(self):
        """When one assignment is expired and one is not, the unexpired one is kept."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active) VALUES ('r1','admin','global',1)"))

                past = _now_str(-3600)      # expired 1 hour ago
                future = _now_str(+86400)   # expires in 24 hours

                # ur1: granted earlier but already expired
                conn.execute(text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, is_active, granted_at, expires_at) "
                    "VALUES ('ur1','alice@example.com','r1','global',1,'2024-01-01',:past)"
                ), {"past": past})
                # ur2: granted later but still valid
                conn.execute(text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, is_active, granted_at, expires_at) "
                    "VALUES ('ur2','alice@example.com','r1','global',1,'2024-06-01',:future)"
                ), {"future": future})
                conn.commit()

                _run_upgrade(conn)

                ur1_active = conn.execute(text("SELECT is_active FROM user_roles WHERE id='ur1'")).scalar()
                ur2_active = conn.execute(text("SELECT is_active FROM user_roles WHERE id='ur2'")).scalar()
                assert ur2_active == 1, "Unexpired assignment should be kept active"
                assert ur1_active == 0, "Expired assignment should be deactivated as the duplicate"
        finally:
            engine.dispose()

    def test_null_expires_at_treated_as_unexpired(self):
        """An assignment with NULL expires_at (never expires) is treated as unexpired."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active) VALUES ('r1','admin','global',1)"))

                past = _now_str(-3600)

                # ur1: expired
                conn.execute(text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, is_active, granted_at, expires_at) "
                    "VALUES ('ur1','bob@example.com','r1','global',1,'2024-01-01',:past)"
                ), {"past": past})
                # ur2: never-expiring (NULL)
                conn.execute(text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, is_active, granted_at, expires_at) "
                    "VALUES ('ur2','bob@example.com','r1','global',1,'2024-06-01',NULL)"
                ))
                conn.commit()

                _run_upgrade(conn)

                ur1_active = conn.execute(text("SELECT is_active FROM user_roles WHERE id='ur1'")).scalar()
                ur2_active = conn.execute(text("SELECT is_active FROM user_roles WHERE id='ur2'")).scalar()
                assert ur2_active == 1, "Never-expiring assignment should be kept"
                assert ur1_active == 0, "Expired assignment should be deactivated"
        finally:
            engine.dispose()

    def test_among_unexpired_newest_granted_wins(self):
        """Among multiple unexpired assignments, the most recently granted one is kept."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active) VALUES ('r1','admin','global',1)"))

                future = _now_str(+86400)

                # ur1: unexpired but granted earlier
                conn.execute(text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, is_active, granted_at, expires_at) "
                    "VALUES ('ur1','carol@example.com','r1','global',1,'2024-01-01',:future)"
                ), {"future": future})
                # ur2: unexpired and granted more recently
                conn.execute(text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, is_active, granted_at, expires_at) "
                    "VALUES ('ur2','carol@example.com','r1','global',1,'2024-09-01',:future)"
                ), {"future": future})
                conn.commit()

                _run_upgrade(conn)

                ur1_active = conn.execute(text("SELECT is_active FROM user_roles WHERE id='ur1'")).scalar()
                ur2_active = conn.execute(text("SELECT is_active FROM user_roles WHERE id='ur2'")).scalar()
                assert ur2_active == 1, "Most recently granted unexpired assignment should be kept"
                assert ur1_active == 0, "Earlier-granted assignment should be deactivated"
        finally:
            engine.dispose()

    def test_with_scope_id_unexpired_preferred(self):
        """Prefer unexpired assignments for team-scoped (scope_id IS NOT NULL) duplicates too."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active) VALUES ('r1','viewer','team',1)"))

                past = _now_str(-3600)
                future = _now_str(+86400)

                # Expired assignment
                conn.execute(text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, scope_id, is_active, granted_at, expires_at) "
                    "VALUES ('ur1','dave@example.com','r1','team','team-abc',1,'2024-01-01',:past)"
                ), {"past": past})
                # Unexpired assignment
                conn.execute(text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, scope_id, is_active, granted_at, expires_at) "
                    "VALUES ('ur2','dave@example.com','r1','team','team-abc',1,'2024-06-01',:future)"
                ), {"future": future})
                conn.commit()

                _run_upgrade(conn)

                ur1_active = conn.execute(text("SELECT is_active FROM user_roles WHERE id='ur1'")).scalar()
                ur2_active = conn.execute(text("SELECT is_active FROM user_roles WHERE id='ur2'")).scalar()
                assert ur2_active == 1
                assert ur1_active == 0
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# Index creation and idempotency
# ---------------------------------------------------------------------------


class TestIndexCreation:
    """Partial unique indexes are created by upgrade() and dropped by downgrade()."""

    def test_upgrade_creates_indexes(self):
        """upgrade() creates the three expected partial unique indexes."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                conn.commit()
                _run_upgrade(conn)

                role_indexes = _get_index_names(conn, "roles")
                ur_indexes = _get_index_names(conn, "user_roles")

                assert "uq_roles_name_scope_active" in role_indexes
                assert "uq_user_roles_email_role_scope_null_active" in ur_indexes
                assert "uq_user_roles_email_role_scope_id_active" in ur_indexes
        finally:
            engine.dispose()

    def test_upgrade_idempotent(self):
        """Running upgrade() twice does not raise an error."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                conn.commit()
                _run_upgrade(conn)
                # Second run must not raise
                _run_upgrade(conn)
        finally:
            engine.dispose()

    def test_downgrade_drops_indexes(self):
        """downgrade() removes the indexes created by upgrade()."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                conn.commit()
                _run_upgrade(conn)
                _run_downgrade(conn)

                role_indexes = _get_index_names(conn, "roles")
                ur_indexes = _get_index_names(conn, "user_roles")

                assert "uq_roles_name_scope_active" not in role_indexes
                assert "uq_user_roles_email_role_scope_null_active" not in ur_indexes
                assert "uq_user_roles_email_role_scope_id_active" not in ur_indexes
        finally:
            engine.dispose()

    def test_downgrade_does_not_reactivate_deduped_rows(self):
        """Soft-deleted duplicates remain inactive after downgrade (audit trail preserved)."""
        engine = _make_engine()
        try:
            with engine.connect() as conn:
                _create_tables(conn)
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r1','admin','global',1,'2024-01-01')"))
                conn.execute(text("INSERT INTO roles (id, name, scope, is_active, created_at) VALUES ('r2','admin','global',1,'2024-06-01')"))
                conn.commit()

                _run_upgrade(conn)
                _run_downgrade(conn)

                r2_active = conn.execute(text("SELECT is_active FROM roles WHERE id='r2'")).scalar()
                assert r2_active == 0, "Deduped role must stay inactive after downgrade"
        finally:
            engine.dispose()
