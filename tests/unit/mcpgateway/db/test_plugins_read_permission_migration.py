# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/db/test_plugins_read_permission_migration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for plugins.read role backfill migration.
"""

# Standard
import importlib
import json
from unittest.mock import patch

# Third-Party
import pytest
from sqlalchemy import create_engine, text

MIGRATION_MODULE = "mcpgateway.alembic.versions.e4f5a6b7c8d9_add_plugins_read_permission"


@pytest.fixture
def migration():
    """Load migration module."""
    return importlib.import_module(MIGRATION_MODULE)


@pytest.fixture
def connection():
    """Create minimal roles table."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE roles (id TEXT PRIMARY KEY, name TEXT, scope TEXT, permissions TEXT, "
                "is_active BOOLEAN, updated_at TEXT)"
            )
        )
        for index, (name, scope) in enumerate((("team_admin", "team"), ("developer", "team"), ("viewer", "team"), ("platform_viewer", "global"), ("platform_admin", "global"))):
            conn.execute(
                text("INSERT INTO roles VALUES (:id, :name, :scope, :permissions, true, NULL)"),
                {"id": str(index), "name": name, "scope": scope, "permissions": json.dumps(["tools.read"] if name != "platform_admin" else ["*"])},
            )
    with engine.begin() as conn:
        yield conn
    engine.dispose()


def _permissions(connection, role_name):
    """Read role permissions."""
    raw = connection.execute(text("SELECT permissions FROM roles WHERE name = :name"), {"name": role_name}).scalar_one()
    return json.loads(raw)


def test_upgrade_and_downgrade_are_idempotent(migration, connection):
    """Backfill preserves grants, avoids duplicates, and cleanly reverses."""
    with patch.object(migration.op, "get_bind", return_value=connection):
        migration.upgrade()
        migration.upgrade()
        for role_name, _scope in migration.ROLE_SCOPES:
            permissions = _permissions(connection, role_name)
            assert "tools.read" in permissions
            assert permissions.count("plugins.read") == 1
        assert _permissions(connection, "viewer") == ["tools.read"]
        assert _permissions(connection, "platform_viewer") == ["tools.read"]
        assert _permissions(connection, "platform_admin") == ["*"]

        migration.downgrade()
        migration.downgrade()
        for role_name, _scope in migration.ROLE_SCOPES:
            assert _permissions(connection, role_name) == ["tools.read"]


def test_missing_roles_table_is_safe(migration):
    """Fresh databases without roles table are skipped."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection, patch.object(migration.op, "get_bind", return_value=connection):
        migration.upgrade()
        migration.downgrade()
    engine.dispose()
