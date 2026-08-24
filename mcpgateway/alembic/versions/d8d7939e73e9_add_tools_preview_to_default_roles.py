# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/d8d7939e73e9_add_tools_preview_to_default_roles.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add tools.preview permission to team-scoped default roles.

Revision ID: d8d7939e73e9
Revises: db41939315aa
Create Date: 2026-08-20 15:07:12.198295

Backfills the tools.preview permission into the team-scoped viewer, developer,
and team_admin roles so existing deployments can dry-run tool invocations
without granting tools.execute. platform_admin already holds "*" and needs no
change; platform_viewer is intentionally left untouched, matching the
precedent set by cbedf4e580e0 for tools.execute.
"""

# Standard
from datetime import datetime, timezone
import json
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "d8d7939e73e9"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "db41939315aa"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLE_PERMISSION_ADDITIONS: list[tuple[str, str, list[str]]] = [
    # (role_name, scope, permissions_to_add)
    ("viewer", "team", ["tools.preview"]),
    ("developer", "team", ["tools.preview"]),
    ("team_admin", "team", ["tools.preview"]),
]


def _load_permissions(raw_permissions: object) -> list[str]:
    """Normalize stored role permissions into a list of strings.

    Args:
        raw_permissions: Raw permissions value from the role row.

    Returns:
        list[str]: Normalized list of permission strings.
    """
    if not raw_permissions:
        return []

    parsed = raw_permissions
    if isinstance(parsed, (bytes, bytearray)):
        parsed = parsed.decode("utf-8")

    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return []

    if isinstance(parsed, list):
        return [perm for perm in parsed if isinstance(perm, str)]

    return []


def _update_role_permissions(conn, role_name: str, scope: str, permissions: list[str], add: bool) -> None:
    """Add or remove permissions from a role, idempotently.

    Args:
        conn: Active Alembic connection.
        role_name: Role name to update.
        scope: Role scope ('team' or 'global') to disambiguate roles with the same name.
        permissions: Permission values to add or remove.
        add: When True, add permissions; when False, remove permissions.
    """
    row = conn.execute(
        text("SELECT id, permissions FROM roles WHERE name = :name AND scope = :scope AND is_active = true LIMIT 1"),
        {"name": role_name, "scope": scope},
    ).fetchone()

    if not row:
        print(f"{role_name} role not found. Skipping.")
        return

    role_id = row[0]
    current_permissions = _load_permissions(row[1])

    if add:
        updated_permissions = list(current_permissions)
        for permission in permissions:
            if permission not in updated_permissions:
                updated_permissions.append(permission)
    else:
        updated_permissions = [permission for permission in current_permissions if permission not in permissions]

    if updated_permissions == current_permissions:
        print(f"{role_name} role already has the required permissions. Skipping.")
        return

    dialect_name = conn.dialect.name
    if dialect_name == "postgresql":
        update_query = text("""
            UPDATE roles
            SET permissions = CAST(:permissions AS JSONB), updated_at = :updated_at
            WHERE id = :role_id
            """)
    else:
        update_query = text("""
            UPDATE roles
            SET permissions = :permissions, updated_at = :updated_at
            WHERE id = :role_id
            """)

    conn.execute(
        update_query,
        {
            "permissions": json.dumps(updated_permissions),
            "updated_at": datetime.now(timezone.utc),
            "role_id": role_id,
        },
    )
    print(f"Updated role '{role_name}' permissions.")


def upgrade() -> None:
    """Backfill tools.preview permission into the viewer, developer, and team_admin roles."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "roles" not in inspector.get_table_names():
        print("roles table not found. Skipping migration.")
        return

    for role_name, scope, permissions in ROLE_PERMISSION_ADDITIONS:
        _update_role_permissions(conn, role_name, scope, permissions, add=True)


def downgrade() -> None:
    """Remove tools.preview permission from the viewer, developer, and team_admin roles."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "roles" not in inspector.get_table_names():
        return

    for role_name, scope, permissions in ROLE_PERMISSION_ADDITIONS:
        _update_role_permissions(conn, role_name, scope, permissions, add=False)
