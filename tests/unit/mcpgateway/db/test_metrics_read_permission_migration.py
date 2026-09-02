# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_metrics_read_permission_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for metrics:read role backfill migration.
"""

# Standard
import importlib
import json
from unittest.mock import patch

# Third-Party
import pytest
from sqlalchemy import create_engine, text

MIGRATION_MODULE = "mcpgateway.alembic.versions.9935d863930b_add_metrics_read_to_default_roles"


@pytest.fixture
def migration():
    """Load migration module."""
    return importlib.import_module(MIGRATION_MODULE)


@pytest.fixture
def connection():
    """Create minimal roles table."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE roles (id TEXT PRIMARY KEY, name TEXT, scope TEXT, permissions TEXT, is_active BOOLEAN, updated_at TEXT)"))
        for index, (name, scope) in enumerate((("team_admin", "team"), ("developer", "team"), ("viewer", "team"), ("platform_viewer", "global"), ("platform_admin", "global"))):
            conn.execute(
                text("INSERT INTO roles VALUES (:id, :name, :scope, :permissions, true, NULL)"),
                {"id": str(index), "name": name, "scope": scope, "permissions": json.dumps(["tools.read"] if name != "platform_admin" else ["*"])},
            )
    with engine.begin() as conn:
        yield conn
    engine.dispose()


def _permissions(connection, role_name, role_id=None):
    """Read role permissions by name, or by id when duplicates exist."""
    if role_id is not None:
        raw = connection.execute(text("SELECT permissions FROM roles WHERE id = :id"), {"id": role_id}).scalar_one()
    else:
        raw = connection.execute(text("SELECT permissions FROM roles WHERE name = :name"), {"name": role_name}).scalar_one()
    return json.loads(raw)


def test_upgrade_and_downgrade_are_idempotent(migration, connection):
    """Backfill preserves grants, avoids duplicates, and cleanly reverses."""
    with patch.object(migration.op, "get_bind", return_value=connection):
        migration.upgrade()
        migration.upgrade()
        permissions = _permissions(connection, "platform_viewer")
        assert "tools.read" in permissions
        assert permissions.count("metrics:read") == 1

        migration.downgrade()
        migration.downgrade()
        assert _permissions(connection, "platform_viewer") == ["tools.read"]


def test_team_scoped_roles_are_not_granted(migration, connection):
    """Team-scoped roles must not receive a permission whose queries have no tenant filter."""
    with patch.object(migration.op, "get_bind", return_value=connection):
        migration.upgrade()
        for role_name in ("team_admin", "developer", "viewer"):
            assert _permissions(connection, role_name) == ["tools.read"]
        assert _permissions(connection, "platform_admin") == ["*"]


def test_inactive_duplicate_role_is_not_patched(migration, connection):
    """A soft-deleted same-name role must not absorb the grant instead of the live one.

    uq_roles_name_scope_active is a partial unique index, so inactive
    ('platform_viewer', 'global') rows are legal. Without an is_active filter the
    lookup can bind to the stale row, log success, and leave every non-admin user
    without metrics:read.
    """
    # Model the real sequence: the role was soft-deleted first, then recreated, so
    # the inactive row is the older one and an unordered LIMIT 1 reaches it first.
    connection.execute(text("DELETE FROM roles WHERE name = 'platform_viewer'"))
    connection.execute(
        text("INSERT INTO roles VALUES (:id, :name, :scope, :permissions, false, NULL)"),
        {"id": "stale", "name": "platform_viewer", "scope": "global", "permissions": json.dumps(["tools.read"])},
    )
    connection.execute(
        text("INSERT INTO roles VALUES (:id, :name, :scope, :permissions, true, NULL)"),
        {"id": "live", "name": "platform_viewer", "scope": "global", "permissions": json.dumps(["tools.read"])},
    )

    with patch.object(migration.op, "get_bind", return_value=connection):
        migration.upgrade()

    assert "metrics:read" in _permissions(connection, "platform_viewer", role_id="live")
    assert _permissions(connection, "platform_viewer", role_id="stale") == ["tools.read"]


def test_missing_roles_table_is_safe(migration):
    """Fresh databases without roles table are skipped."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection, patch.object(migration.op, "get_bind", return_value=connection):
        migration.upgrade()
        migration.downgrade()
    engine.dispose()
