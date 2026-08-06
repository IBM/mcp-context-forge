# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/e4f5a6b7c8d9_add_plugins_read_permission.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add plugins.read permission to privileged built-in roles.

Revision ID: e4f5a6b7c8d9
Revises: e1a2b3c4d5f6
Create Date: 2026-07-28 00:00:00.000000
"""

# Standard
from datetime import datetime, timezone
import json
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "e4f5a6b7c8d9"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "7ab59991e017"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSION = "plugins.read"
ROLE_SCOPES = (
    ("team_admin", "team"),
    ("developer", "team"),
)


def _load_permissions(raw_permissions: object) -> list[str]:
    """Normalize stored role permissions.

    Args:
        raw_permissions: Database JSON value.

    Returns:
        Permission strings.
    """
    if not raw_permissions:
        return []
    if isinstance(raw_permissions, (bytes, bytearray)):
        raw_permissions = raw_permissions.decode("utf-8")
    if isinstance(raw_permissions, str):
        try:
            raw_permissions = json.loads(raw_permissions)
        except json.JSONDecodeError:
            return []
    return [permission for permission in raw_permissions if isinstance(permission, str)] if isinstance(raw_permissions, list) else []


def _update_permission(role_name: str, scope: str, add: bool) -> None:
    """Add or remove permission without changing unrelated role grants."""
    bind = op.get_bind()
    row = bind.execute(
        text("SELECT id, permissions FROM roles WHERE name = :name AND scope = :scope AND is_active = true LIMIT 1"),
        {"name": role_name, "scope": scope},
    ).fetchone()
    if not row:
        return

    permissions = _load_permissions(row[1])
    updated = list(permissions)
    if add and PERMISSION not in updated:
        updated.append(PERMISSION)
    elif not add:
        updated = [permission for permission in updated if permission != PERMISSION]
    if updated == permissions:
        return

    permission_json = json.dumps(updated)
    if bind.dialect.name == "postgresql":
        statement = text("UPDATE roles SET permissions = CAST(:permissions AS JSONB), updated_at = :updated_at WHERE id = :role_id")
    else:
        statement = text("UPDATE roles SET permissions = :permissions, updated_at = :updated_at WHERE id = :role_id")
    bind.execute(statement, {"permissions": permission_json, "updated_at": datetime.now(timezone.utc), "role_id": row[0]})


def upgrade() -> None:
    """Grant plugins.read to existing privileged built-in roles."""
    if "roles" not in sa.inspect(op.get_bind()).get_table_names():
        return
    for role_name, scope in ROLE_SCOPES:
        _update_permission(role_name, scope, add=True)


def downgrade() -> None:
    """Remove plugins.read from existing privileged built-in roles."""
    if "roles" not in sa.inspect(op.get_bind()).get_table_names():
        return
    for role_name, scope in ROLE_SCOPES:
        _update_permission(role_name, scope, add=False)
