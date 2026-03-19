# -*- coding: utf-8 -*-
"""Add LLM permissions to default RBAC roles.

Revision ID: 9f5d93ced2b3
Revises: y8i9j0k1l2m3
Create Date: 2026-02-23 11:09:14.709030

Backfills default role permission sets so existing deployments receive:
- team_admin: llm.read, llm.invoke
- developer: llm.read, llm.invoke
- viewer: llm.read
- platform_viewer: llm.read
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
revision: str = "9f5d93ced2b3"
down_revision: Union[str, Sequence[str], None] = "y8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE_PERMISSION_ADDITIONS = {
    "team_admin": ["llm.read", "llm.invoke"],
    "developer": ["llm.read", "llm.invoke"],
    "viewer": ["llm.read"],
    "platform_viewer": ["llm.read"],
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
        return

    dialect_name = conn.dialect.name
    if dialect_name == "postgresql":
        update_query = text(
            """
            UPDATE roles
            SET permissions = CAST(:permissions AS JSONB), updated_at = :updated_at
            WHERE id = :role_id
            """
        )
    else:
        update_query = text(
            """
            UPDATE roles
            SET permissions = :permissions, updated_at = :updated_at
            WHERE id = :role_id
            """
        )

    conn.execute(
        update_query,
        {
            "permissions": json.dumps(updated_permissions),
            "updated_at": datetime.now(timezone.utc),
            "role_id": role_id,
        },
    )


def upgrade() -> None:
    """Backfill LLM permissions into default role records."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "roles" not in inspector.get_table_names():
        print("roles table not found. Skipping migration.")
        return

    for role_name, permissions in ROLE_PERMISSION_ADDITIONS.items():
        _update_role_permissions(conn, role_name, permissions, add=True)


def downgrade() -> None:
    """Remove LLM permissions from default role records."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "roles" not in inspector.get_table_names():
        return

    for role_name, permissions in ROLE_PERMISSION_ADDITIONS.items():
        _update_role_permissions(conn, role_name, permissions, add=False)
