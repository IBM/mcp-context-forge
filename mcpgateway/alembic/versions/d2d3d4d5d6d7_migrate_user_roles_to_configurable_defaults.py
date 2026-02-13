# -*- coding: utf-8 -*-
"""migrate user roles to configurable defaults

Revision ID: d2d3d4d5d6d7
Revises: c1c2c3c4c5c6
Create Date: 2026-02-13 10:00:00.000000

Migrate existing user_roles assignments to use the configurable default role
names from settings. If settings match the previous hardcoded defaults, this
migration is a no-op.

Previous hardcoded defaults:
  - Admin global role: platform_admin
  - User global role: platform_viewer
  - Team owner role: team_admin

Configurable via:
  - DEFAULT_ADMIN_ROLE
  - DEFAULT_USER_ROLE
  - DEFAULT_TEAM_OWNER_ROLE
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# First-Party
from mcpgateway.config import settings

# revision identifiers, used by Alembic.
revision: str = "d2d3d4d5d6d7"
down_revision: Union[str, Sequence[str], None] = "c1c2c3c4c5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Previous hardcoded defaults
OLD_ADMIN_ROLE = "platform_admin"
OLD_USER_ROLE = "platform_viewer"
OLD_TEAM_OWNER_ROLE = "team_admin"


def _get_role_id(bind, role_name: str, scope: str):
    """Look up a role ID by name and scope."""
    result = bind.execute(
        text("SELECT id FROM roles WHERE name = :name AND scope = :scope LIMIT 1"),
        {"name": role_name, "scope": scope},
    ).fetchone()
    return result[0] if result else None


def _migrate_role(bind, old_role_name: str, new_role_name: str, scope: str) -> int:
    """Migrate user_roles from old role to new role. Returns count of updated rows."""
    if old_role_name == new_role_name:
        print(f"  - {scope} role '{old_role_name}' unchanged, skipping")
        return 0

    old_role_id = _get_role_id(bind, old_role_name, scope)
    if not old_role_id:
        print(f"  - Old role '{old_role_name}' ({scope}) not found, skipping")
        return 0

    new_role_id = _get_role_id(bind, new_role_name, scope)
    if not new_role_id:
        print(f"  - New role '{new_role_name}' ({scope}) not found, skipping")
        return 0

    result = bind.execute(
        text("UPDATE user_roles SET role_id = :new_id WHERE role_id = :old_id AND scope = :scope"),
        {"new_id": new_role_id, "old_id": old_role_id, "scope": scope},
    )
    count = getattr(result, "rowcount", 0)
    print(f"  ✓ Migrated {count} assignments: '{old_role_name}' -> '{new_role_name}' ({scope})")
    return count


def upgrade() -> None:
    """Migrate user_roles to configurable default roles from settings."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "user_roles" not in existing_tables or "roles" not in existing_tables:
        print("RBAC tables not found. Skipping migration.")
        return

    new_admin_role = settings.default_admin_role
    new_user_role = settings.default_user_role
    new_team_owner_role = settings.default_team_owner_role

    # Check if any role has changed from the old hardcoded defaults
    if new_admin_role == OLD_ADMIN_ROLE and new_user_role == OLD_USER_ROLE and new_team_owner_role == OLD_TEAM_OWNER_ROLE:
        print("All default roles match previous hardcoded values. No migration needed.")
        return

    print("=== Migrating user_roles to configurable defaults ===")
    total = 0
    total += _migrate_role(bind, OLD_ADMIN_ROLE, new_admin_role, "global")
    total += _migrate_role(bind, OLD_USER_ROLE, new_user_role, "global")
    total += _migrate_role(bind, OLD_TEAM_OWNER_ROLE, new_team_owner_role, "team")
    print(f"\n✅ Migration complete: {total} role assignments updated")


def downgrade() -> None:
    """Revert user_roles back to the old hardcoded default roles."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "user_roles" not in existing_tables or "roles" not in existing_tables:
        print("RBAC tables not found. Skipping downgrade.")
        return

    new_admin_role = settings.default_admin_role
    new_user_role = settings.default_user_role
    new_team_owner_role = settings.default_team_owner_role

    if new_admin_role == OLD_ADMIN_ROLE and new_user_role == OLD_USER_ROLE and new_team_owner_role == OLD_TEAM_OWNER_ROLE:
        print("All default roles match previous hardcoded values. No downgrade needed.")
        return

    print("=== Reverting user_roles to hardcoded defaults ===")
    total = 0
    total += _migrate_role(bind, new_admin_role, OLD_ADMIN_ROLE, "global")
    total += _migrate_role(bind, new_user_role, OLD_USER_ROLE, "global")
    total += _migrate_role(bind, new_team_owner_role, OLD_TEAM_OWNER_ROLE, "team")
    print(f"\n✅ Downgrade complete: {total} role assignments reverted")
