# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/abf8ac3b6008_add_admin_overview_and_servers_use_to_.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Add admin.overview and servers.use permissions to viewer roles.

Revision ID: abf8ac3b6008
Revises: 64acf94cb7f2
Create Date: 2026-03-02 21:54:28.873091

Backfills default role permission sets so existing deployments receive:
- viewer: admin.overview, servers.use
- platform_viewer: admin.overview, servers.use
- developer: admin.overview
- team_admin: admin.overview

Note: developer and team_admin already have servers.use in their baseline
definitions, so it is intentionally not included here to avoid a destructive
downgrade that would strip a pre-existing permission.
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
revision: str = "abf8ac3b6008"
down_revision: Union[str, Sequence[str], None] = "64acf94cb7f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLE_PERMISSION_ADDITIONS = {
    "viewer": ["admin.overview", "servers.use"],
    "platform_viewer": ["admin.overview", "servers.use"],
    "developer": ["admin.overview"],
    "team_admin": ["admin.overview"],
}


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


def _update_role_permissions(conn, role_name: str, permissions: list[str], add: bool) -> None:
    """Add or remove permissions from a role, idempotently.

    Args:
        conn: Active Alembic connection.
        role_name: Role name to update.
        permissions: Permission values to add or remove.
        add: When True, add permissions; when False, remove permissions.
    """
    row = conn.execute(
        text("SELECT id, permissions FROM roles WHERE name = :name LIMIT 1"),
        {"name": role_name},
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
    """Backfill missing permissions into viewer, platform_viewer, developer, and team_admin role records."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "roles" not in inspector.get_table_names():
        print("roles table not found. Skipping migration.")
        return

    for role_name, permissions in ROLE_PERMISSION_ADDITIONS.items():
        _update_role_permissions(conn, role_name, permissions, add=True)


def downgrade() -> None:
    """Remove migration-added permissions from viewer, platform_viewer, developer, and team_admin role records."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "roles" not in inspector.get_table_names():
        return

    for role_name, permissions in ROLE_PERMISSION_ADDITIONS.items():
        _update_role_permissions(conn, role_name, permissions, add=False)
