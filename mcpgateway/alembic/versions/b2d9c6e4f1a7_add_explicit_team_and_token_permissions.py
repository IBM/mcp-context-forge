# -*- coding: utf-8 -*-
"""Add explicit team read and token self-management permissions to default roles.

Revision ID: b2d9c6e4f1a7
Revises: a4f1c7d8e9b0
Create Date: 2026-02-23 18:05:00.000000

This data migration keeps role behavior consistent after removing implicit
permission fallbacks by adding explicit grants for:
- teams.read on developer/viewer/platform_viewer
- tokens.create/read/update/revoke on team_admin/developer/viewer/platform_viewer
"""

# Standard
from datetime import datetime, timezone
import json
from typing import Dict, List, Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "b2d9c6e4f1a7"
down_revision: Union[str, Sequence[str], None] = "a4f1c7d8e9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE_PERMISSION_ADDITIONS: Dict[str, List[str]] = {
    "team_admin": [
        "tokens.create",
        "tokens.read",
        "tokens.update",
        "tokens.revoke",
    ],
    "developer": [
        "teams.read",
        "tokens.create",
        "tokens.read",
        "tokens.update",
        "tokens.revoke",
    ],
    "viewer": [
        "teams.read",
        "tokens.create",
        "tokens.read",
        "tokens.update",
        "tokens.revoke",
    ],
    "platform_viewer": [
        "teams.read",
        "tokens.create",
        "tokens.read",
        "tokens.update",
        "tokens.revoke",
    ],
}


def _load_permissions(raw_permissions: object) -> List[str]:
    """Normalize stored permissions into a list of strings.

    Args:
        raw_permissions: Permissions persisted in the database. May be ``None``,
            JSON text, bytes, or a Python list.

    Returns:
        List[str]: A normalized list containing only string permission entries.
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


def _apply_permission_updates(additions_by_role: Dict[str, List[str]]) -> None:
    """Apply role permission additions idempotently.

    Args:
        additions_by_role: Mapping of role name to permissions that must be
            present after migration.
    """
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "roles" not in existing_tables:
        print("roles table not found. Skipping migration.")
        return

    dialect_name = conn.dialect.name
    now = datetime.now(timezone.utc)

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

    for role_name, additions in additions_by_role.items():
        row = conn.execute(
            text("SELECT id, permissions FROM roles WHERE name = :name LIMIT 1"),
            {"name": role_name},
        ).fetchone()
        if not row:
            print(f"Role '{role_name}' not found. Skipping.")
            continue

        role_id = row[0]
        current_permissions = _load_permissions(row[1])

        updated = False
        for permission in additions:
            if permission not in current_permissions:
                current_permissions.append(permission)
                updated = True

        if not updated:
            print(f"Role '{role_name}' already has required permissions.")
            continue

        conn.execute(
            update_query,
            {
                "permissions": json.dumps(current_permissions),
                "updated_at": now,
                "role_id": role_id,
            },
        )
        print(f"Updated role '{role_name}' permissions.")


def upgrade() -> None:
    """Apply explicit team/token permissions to default roles."""
    _apply_permission_updates(ROLE_PERMISSION_ADDITIONS)


def downgrade() -> None:
    """Remove permissions that were added by this migration."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()
    if "roles" not in existing_tables:
        return

    removals_by_role = ROLE_PERMISSION_ADDITIONS
    dialect_name = conn.dialect.name
    now = datetime.now(timezone.utc)

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

    for role_name, removals in removals_by_role.items():
        row = conn.execute(
            text("SELECT id, permissions FROM roles WHERE name = :name LIMIT 1"),
            {"name": role_name},
        ).fetchone()
        if not row:
            continue

        role_id = row[0]
        current_permissions = _load_permissions(row[1])
        updated_permissions = [perm for perm in current_permissions if perm not in removals]

        if len(updated_permissions) == len(current_permissions):
            continue

        conn.execute(
            update_query,
            {
                "permissions": json.dumps(updated_permissions),
                "updated_at": now,
                "role_id": role_id,
            },
        )
