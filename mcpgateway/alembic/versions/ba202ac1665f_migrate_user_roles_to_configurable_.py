# -*- coding: utf-8 -*-
"""Migrate user roles to configurable defaults

Revision ID: ba202ac1665f
Revises: a31c6ffc2239
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
from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# First-Party
from mcpgateway.config import settings

# revision identifiers, used by Alembic.
revision: str = "ba202ac1665f"
down_revision: Union[str, Sequence[str], None] = "a31c6ffc2239"
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
    """Migrate user_roles to configurable default roles from settings.

    Phase 1 (conditional): Remap existing role assignments if configured defaults
    differ from the previous hardcoded values.

    Phase 2 (always): Backfill team-scoped RBAC roles for existing team members
    who don't have any, mapping owner→default_team_owner_role and
    member→default_team_member_role based on their actual membership role.
    """
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

    total = 0

    # Phase 1: Remap existing role assignments if defaults changed
    roles_changed = not (new_admin_role == OLD_ADMIN_ROLE and new_user_role == OLD_USER_ROLE and new_team_owner_role == OLD_TEAM_OWNER_ROLE and new_team_member_role == OLD_TEAM_MEMBER_ROLE)

    if roles_changed:
        print("=== Phase 1: Remapping user_roles to configurable defaults ===")
        total += _migrate_role(bind, OLD_ADMIN_ROLE, new_admin_role, "global")
        total += _migrate_role(bind, OLD_USER_ROLE, new_user_role, "global")
        total += _migrate_role(bind, OLD_TEAM_OWNER_ROLE, new_team_owner_role, "team")
        total += _migrate_role(bind, OLD_TEAM_MEMBER_ROLE, new_team_member_role, "team")

        # Also migrate ALL non-self-granted assignments for any changed role
        non_self_pairs = []
        if new_admin_role != OLD_ADMIN_ROLE:
            non_self_pairs.append((OLD_ADMIN_ROLE, new_admin_role, "global"))
        if new_user_role != OLD_USER_ROLE:
            non_self_pairs.append((OLD_USER_ROLE, new_user_role, "global"))
        if new_team_owner_role != OLD_TEAM_OWNER_ROLE:
            non_self_pairs.append((OLD_TEAM_OWNER_ROLE, new_team_owner_role, "team"))
        if new_team_member_role != OLD_TEAM_MEMBER_ROLE:
            non_self_pairs.append((OLD_TEAM_MEMBER_ROLE, new_team_member_role, "team"))

        for old_name, new_name, scope in non_self_pairs:
            old_role_id = _get_role_id(bind, old_name, scope)
            new_role_id = _get_role_id(bind, new_name, scope)
            if old_role_id and new_role_id:
                result = bind.execute(
                    text("UPDATE user_roles SET role_id = :new_id WHERE role_id = :old_id AND scope = :scope AND granted_by != user_email"),
                    {"new_id": new_role_id, "old_id": old_role_id, "scope": scope},
                )
                migrated = getattr(result, "rowcount", 0)
                total += migrated
                print(f"  ✓ Migrated {migrated} non-self-granted assignments: '{old_name}' -> '{new_name}' ({scope})")
    else:
        print("Phase 1: All default roles match previous hardcoded values. No remap needed.")

    # Phase 2: Backfill team-scoped roles for existing team members who don't have any
    # This always runs regardless of whether role names changed, to ensure all
    # team members have proper RBAC roles (handles pre-existing members from before RBAC)
    if "email_team_members" in existing_tables:
        print("\n=== Phase 2: Backfilling team-scoped RBAC roles for existing team members ===")
        team_member_role_id = _get_role_id(bind, new_team_member_role, "team")
        team_owner_role_id = _get_role_id(bind, new_team_owner_role, "team")

        if not team_member_role_id:
            print(f"  ⚠ Team member role '{new_team_member_role}' not found, skipping backfill")
        elif not team_owner_role_id:
            print(f"  ⚠ Team owner role '{new_team_owner_role}' not found, skipping backfill")
        else:
            # Find active team members who don't have any active team-scoped role
            # Include tm.role to map owners and members to correct RBAC roles
            result = bind.execute(
                text(
                    """
                    SELECT tm.user_email, tm.team_id, tm.role
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
                user_email, team_id, membership_role = member
                role_id = team_owner_role_id if membership_role == "owner" else team_member_role_id
                # Use self-grant for compatibility with deployments where granted_by
                # enforces a foreign key to email_users.email.
                bind.execute(
                    text(
                        "INSERT INTO user_roles (id, user_email, role_id, scope, scope_id, granted_by, granted_at, is_active) VALUES (:id, :user_email, :role_id, 'team', :team_id, :granted_by, :granted_at, true)"
                    ),
                    {
                        "id": _generate_uuid(),
                        "user_email": user_email,
                        "role_id": role_id,
                        "team_id": team_id,
                        "granted_by": user_email,
                        "granted_at": datetime.now(timezone.utc),
                    },
                )

            total += len(members_without_roles)
            print(f"  ✓ Created {len(members_without_roles)} team-scoped role assignments for existing team members")

    print(f"\n✅ Migration complete: {total} role assignments updated")


def downgrade() -> None:
    """Revert user_roles migration.

    Note: Phase 2 backfill rows (granted_by=user_email) cannot be selectively
    removed without risking deletion of legitimate role assignments. They are
    left intact as valid team-role grants.

    Role remap reversal (environment-dependent): Attempts to revert role name
    remapping using current runtime settings. WARNING: This assumes the current
    DEFAULT_*_ROLE env vars match those used during upgrade. If env vars have
    changed between upgrade and downgrade, the reversal may be incorrect.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "user_roles" not in existing_tables or "roles" not in existing_tables:
        print("RBAC tables not found. Skipping downgrade.")
        return

    print("=== Reverting user_roles migration ===")
    total = 0

    # Note: Phase 2 backfill rows used granted_by=user_email (self-grant) for
    # FK safety, so they cannot be distinguished from legitimate assignments.

    # Attempt role remap reversal (environment-dependent)
    new_admin_role = settings.default_admin_role
    new_user_role = settings.default_user_role
    new_team_owner_role = settings.default_team_owner_role
    new_team_member_role = settings.default_team_member_role

    if new_admin_role == OLD_ADMIN_ROLE and new_user_role == OLD_USER_ROLE and new_team_owner_role == OLD_TEAM_OWNER_ROLE and new_team_member_role == OLD_TEAM_MEMBER_ROLE:
        print("  All default roles match hardcoded values. No remap reversal needed.")
    else:
        print("\n  ⚠ WARNING: Role remap reversal depends on current environment settings")
        print("  matching those used during upgrade. Verify settings match if unexpected.")
        total += _migrate_role(bind, new_admin_role, OLD_ADMIN_ROLE, "global")
        total += _migrate_role(bind, new_user_role, OLD_USER_ROLE, "global")
        total += _migrate_role(bind, new_team_owner_role, OLD_TEAM_OWNER_ROLE, "team")
        total += _migrate_role(bind, new_team_member_role, OLD_TEAM_MEMBER_ROLE, "team")

        # Revert non-self-granted role assignments for all changed roles
        non_self_pairs = []
        if new_admin_role != OLD_ADMIN_ROLE:
            non_self_pairs.append((new_admin_role, OLD_ADMIN_ROLE, "global"))
        if new_user_role != OLD_USER_ROLE:
            non_self_pairs.append((new_user_role, OLD_USER_ROLE, "global"))
        if new_team_owner_role != OLD_TEAM_OWNER_ROLE:
            non_self_pairs.append((new_team_owner_role, OLD_TEAM_OWNER_ROLE, "team"))
        if new_team_member_role != OLD_TEAM_MEMBER_ROLE:
            non_self_pairs.append((new_team_member_role, OLD_TEAM_MEMBER_ROLE, "team"))

        for current_name, old_name, scope in non_self_pairs:
            current_role_id = _get_role_id(bind, current_name, scope)
            old_role_id = _get_role_id(bind, old_name, scope)
            if current_role_id and old_role_id:
                result = bind.execute(
                    text("UPDATE user_roles SET role_id = :old_id WHERE role_id = :new_id AND scope = :scope AND granted_by != user_email"),
                    {"old_id": old_role_id, "new_id": current_role_id, "scope": scope},
                )
                reverted = getattr(result, "rowcount", 0)
                total += reverted
                print(f"  ✓ Reverted {reverted} non-self-granted assignments: '{current_name}' -> '{old_name}' ({scope})")

    print(f"\n✅ Downgrade complete: {total} role assignments reverted")
