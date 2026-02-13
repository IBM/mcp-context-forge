"""Migrate user roles to configurable defaults

Revision ID: ba202ac1665f
Revises: c1c2c3c4c5c6
Create Date: 2026-02-13 16:43:04.089267

Migrate existing user_roles assignments to use the configurable default role
names from settings. If settings match the previous hardcoded defaults, this
migration is a no-op.

Previous hardcoded defaults:
  - Admin global role: platform_admin
  - User global role: platform_viewer
  - Team owner role: team_admin
  - Team member role: viewer

Configurable via:
  - DEFAULT_ADMIN_ROLE
  - DEFAULT_USER_ROLE
  - DEFAULT_TEAM_OWNER_ROLE
  - DEFAULT_TEAM_MEMBER_ROLE
"""

# Standard
import uuid
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# First-Party
from mcpgateway.config import settings

# revision identifiers, used by Alembic.
revision: str = "ba202ac1665f"
down_revision: Union[str, Sequence[str], None] = "c1c2c3c4c5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Previous hardcoded defaults
OLD_ADMIN_ROLE = "platform_admin"
OLD_USER_ROLE = "platform_viewer"
OLD_TEAM_OWNER_ROLE = "team_admin"
OLD_TEAM_MEMBER_ROLE = "viewer"


def _generate_uuid() -> str:
    """Generate a UUID string compatible with both PostgreSQL and SQLite.
    
    Returns:
        str: UUID str
    """
    return str(uuid.uuid4())


def _get_role_id(bind, role_name: str, scope: str):
    """Look up a role ID by name and scope.

    Args:
        bind: SQLAlchemy bind connection for executing queries.
        role_name: Name of the role to look up.
        scope: Scope of the role (e.g., 'global', 'team').

    Returns:
        str or None: The role ID if found, otherwise None.
    """
    result = bind.execute(
        text("SELECT id FROM roles WHERE name = :name AND scope = :scope LIMIT 1"),
        {"name": role_name, "scope": scope},
    ).fetchone()
    return result[0] if result else None


def _migrate_role(bind, old_role_name: str, new_role_name: str, scope: str) -> int:
    """Migrate self-granted user_roles from old role to new role.

    Only updates assignments where granted_by = user_email (auto-assigned
    defaults from user creation), leaving manually granted roles untouched.

    Args:
        bind: SQLAlchemy bind connection for executing queries.
        old_role_name: Name of the role to migrate from.
        new_role_name: Name of the role to migrate to.
        scope: Scope of the role (e.g., 'global', 'team').

    Returns:
        int: Count of updated role assignments.
    """
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
        text("UPDATE user_roles SET role_id = :new_id WHERE role_id = :old_id AND scope = :scope AND granted_by = user_email"),
        {"new_id": new_role_id, "old_id": old_role_id, "scope": scope},
    )
    count = getattr(result, "rowcount", 0)
    print(f"  ✓ Migrated {count} self-granted assignments: '{old_role_name}' -> '{new_role_name}' ({scope})")
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
    new_team_member_role = settings.default_team_member_role

    # Check if any role has changed from the old hardcoded defaults
    if new_admin_role == OLD_ADMIN_ROLE and new_user_role == OLD_USER_ROLE and new_team_owner_role == OLD_TEAM_OWNER_ROLE and new_team_member_role == OLD_TEAM_MEMBER_ROLE:
        print("All default roles match previous hardcoded values. No migration needed.")
        return

    print("=== Migrating user_roles to configurable defaults ===")
    total = 0
    total += _migrate_role(bind, OLD_ADMIN_ROLE, new_admin_role, "global")
    total += _migrate_role(bind, OLD_USER_ROLE, new_user_role, "global")
    total += _migrate_role(bind, OLD_TEAM_OWNER_ROLE, new_team_owner_role, "team")
    total += _migrate_role(bind, OLD_TEAM_MEMBER_ROLE, new_team_member_role, "team")

    # Also migrate/update existing team member roles if they differ
    if new_team_member_role != OLD_TEAM_MEMBER_ROLE:
        old_role_id = _get_role_id(bind, OLD_TEAM_MEMBER_ROLE, "team")
        new_role_id = _get_role_id(bind, new_team_member_role, "team")
        if old_role_id and new_role_id:
            result = bind.execute(
                text("UPDATE user_roles SET role_id = :new_id WHERE role_id = :old_id AND scope = :scope"),
                {"new_id": new_role_id, "old_id": old_role_id, "scope": "team"},
            )
            migrated = getattr(result, "rowcount", 0)
            total += migrated
            print(f"  ✓ Migrated {migrated} team member role assignments: '{OLD_TEAM_MEMBER_ROLE}' -> '{new_team_member_role}'")
            new_role_id = _get_role_id(bind, new_team_member_role, "team")
            if old_role_id and new_role_id:
                result = bind.execute(
                    text("UPDATE user_roles SET role_id = :new_id WHERE role_id = :old_id AND scope = :scope"),
                    {"new_id": new_role_id, "old_id": old_role_id, "scope": "team"},
                )
                migrated = getattr(result, "rowcount", 0)
                total += migrated
                print(f"  ✓ Migrated {migrated} team member role assignments: '{OLD_TEAM_MEMBER_ROLE}' -> '{new_team_member_role}'")

    # Create team-scoped roles for existing team members who don't have any
    if "email_team_members" in existing_tables:
        print("\n=== Creating team-scoped roles for existing team members ===")
        team_member_role_id = _get_role_id(bind, new_team_member_role, "team")
        if team_member_role_id:
            # Find team members who don't have any team-scoped role in user_roles
            # Fetch in Python to handle UUID generation for both PostgreSQL and SQLite
            result = bind.execute(
                text(
                    """
                    SELECT tm.user_email, tm.team_id
                    FROM email_team_members tm
                    WHERE tm.is_active = true
                    AND NOT EXISTS (
                        SELECT 1 FROM user_roles ur
                        WHERE ur.user_email = tm.user_email
                        AND ur.scope = 'team'
                        AND ur.scope_id = tm.team_id
                        AND ur.is_active = true
                    )
                    """
                ),
            )
            members_without_roles = result.fetchall()

            for member in members_without_roles:
                user_email, team_id = member
                bind.execute(
                    text("INSERT INTO user_roles (id, user_email, role_id, scope, scope_id, granted_by, is_active) VALUES (:id, :user_email, :role_id, 'team', :team_id, 'system_migration', true)"),
                    {"id": _generate_uuid(), "user_email": user_email, "role_id": team_member_role_id, "team_id": team_id},
                )

            total += len(members_without_roles)
            print(f"  ✓ Created {len(members_without_roles)} team-scoped role assignments for existing team members")
        else:
            print(f"  ⚠ Team member role '{new_team_member_role}' not found, skipping team member role creation")

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
    new_team_member_role = settings.default_team_member_role

    if new_admin_role == OLD_ADMIN_ROLE and new_user_role == OLD_USER_ROLE and new_team_owner_role == OLD_TEAM_OWNER_ROLE and new_team_member_role == OLD_TEAM_MEMBER_ROLE:
        print("All default roles match previous hardcoded values. No downgrade needed.")
        return

    print("=== Reverting user_roles to hardcoded defaults ===")
    total = 0
    total += _migrate_role(bind, new_admin_role, OLD_ADMIN_ROLE, "global")
    total += _migrate_role(bind, new_user_role, OLD_USER_ROLE, "global")
    total += _migrate_role(bind, new_team_owner_role, OLD_TEAM_OWNER_ROLE, "team")
    total += _migrate_role(bind, new_team_member_role, OLD_TEAM_MEMBER_ROLE, "team")
    print(f"\n✅ Downgrade complete: {total} role assignments reverted")
