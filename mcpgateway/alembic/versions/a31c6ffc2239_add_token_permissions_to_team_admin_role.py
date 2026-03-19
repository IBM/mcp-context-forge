# -*- coding: utf-8 -*-
"""Add token permissions to team_admin role.

Revision ID: a31c6ffc2239
Revises: 207d8bbddd61
Create Date: 2026-02-13 00:13:15.111078

This data migration adds tokens.create, tokens.read, tokens.update,
and tokens.revoke permissions to the existing team_admin role so that
existing deployments pick up the new token management capabilities.

New deployments already get these via bootstrap_db.py.
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
revision: str = "a31c6ffc2239"
down_revision: Union[str, Sequence[str], None] = "207d8bbddd61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PERMISSIONS = [
    "tokens.create",
    "tokens.read",
    "tokens.update",
    "tokens.revoke",
]


def _load_permissions(raw_permissions: object) -> list[str]:
    """Normalize stored permissions into a list of strings.

    PostgreSQL JSON/JSONB columns return native Python lists via psycopg,
    while SQLite returns JSON-encoded strings. Handle both safely.

    Args:
        raw_permissions: Raw permissions value from the database row.

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


def upgrade() -> None:
    """Add token permissions to team_admin role.

    The migration is idempotent: permissions that already exist are skipped.
    Supports both PostgreSQL and SQLite databases.
    """
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Skip if RBAC tables don't exist yet (fresh installs handled by bootstrap_db)
    if "roles" not in existing_tables:
        print("roles table not found. Skipping migration.")
        return

    # Detect database dialect
    dialect_name = conn.dialect.name
    print(f"Detected database dialect: {dialect_name}")

    # Fetch current team_admin permissions
    row = conn.execute(
        text("SELECT id, permissions FROM roles WHERE name = :name LIMIT 1"),
        {"name": "team_admin"},
    ).fetchone()

    if not row:
        print("team_admin role not found. Skipping (bootstrap_db will create it).")
        return

    role_id = row[0]
    current_permissions = _load_permissions(row[1])

    # Merge new permissions (idempotent)
    updated = False
    for perm in NEW_PERMISSIONS:
        if perm not in current_permissions:
            current_permissions.append(perm)
            updated = True

    if not updated:
        print("team_admin role already has all token permissions. Nothing to do.")
        return

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

    conn.execute(
        update_query,
        {
            "permissions": json.dumps(current_permissions),
            "updated_at": now,
            "role_id": role_id,
        },
    )
    print(f"  Added {NEW_PERMISSIONS} to team_admin role permissions.")


def downgrade() -> None:
    """Remove token permissions from team_admin role."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "roles" not in existing_tables:
        return

    dialect_name = conn.dialect.name

    row = conn.execute(
        text("SELECT id, permissions FROM roles WHERE name = :name LIMIT 1"),
        {"name": "team_admin"},
    ).fetchone()

    if not row:
        return

    role_id = row[0]
    current_permissions = _load_permissions(row[1])

    # Remove the token permissions
    updated_permissions = [p for p in current_permissions if p not in NEW_PERMISSIONS]

    if len(updated_permissions) == len(current_permissions):
        return

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

    conn.execute(
        update_query,
        {
            "permissions": json.dumps(updated_permissions),
            "updated_at": now,
            "role_id": role_id,
        },
    )
    print(f"  Removed {NEW_PERMISSIONS} from team_admin role permissions.")
