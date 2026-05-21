# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/ba202ac1665f_migrate_user_roles_to_configurable_.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Migrate user roles to configurable defaults

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
import logging
from typing import Sequence, Union
import uuid

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "ba202ac1665f"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "f9a8b7c6d5e4"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Sentinel value written to user_roles.migration_source for rows inserted by
# Phase 2 backfill in this migration. Used by downgrade() to remove only
# the rows this migration created. The migration_source column is added by an
# earlier migration (v1a2b3c4d5e6) in the chain.
MIGRATION_SOURCE = "migration:ba202ac1665f"

# Previous hardcoded defaults
OLD_ADMIN_ROLE = "platform_admin"
OLD_USER_ROLE = "platform_viewer"
OLD_TEAM_OWNER_ROLE = "team_admin"
OLD_TEAM_MEMBER_ROLE = "viewer"

# Keys used to store config values in migration_metadata.
_META_KEYS = ("default_admin_role", "default_user_role", "default_team_owner_role", "default_team_member_role")


def _snapshot_config(bind, rev: str, values: dict) -> None:
    """Persist runtime config values into migration_metadata for hermetic downgrade.

    If the table does not exist (e.g. the schema was migrated before this fix
    was applied), emits a warning and skips — downgrade will fall back to live
    settings with a prominent warning.
    """
    inspector = sa.inspect(bind)
    if "migration_metadata" not in inspector.get_table_names():
        logger.warning("migration_metadata table not found; skipping config snapshot. " "Downgrade will use live settings (non-hermetic).")
        return
    for key, value in values.items():
        bind.execute(
            text(
                "INSERT INTO migration_metadata (revision, key, value, created_at) "
                "VALUES (:rev, :key, :value, :ts) "
                "ON CONFLICT (revision, key) DO UPDATE SET value = excluded.value, created_at = excluded.created_at"
            ),
            {"rev": rev, "key": key, "value": value, "ts": datetime.now(timezone.utc)},
        )
    print(f"  ✓ Snapshotted {len(values)} config value(s) into migration_metadata (revision={rev})")


def _read_config_snapshot(bind, rev: str) -> dict:
    """Read config values previously snapshotted by _snapshot_config.

    Returns an empty dict if the table is absent or has no rows for this
    revision (pre-fix databases).
    """
    inspector = sa.inspect(bind)
    if "migration_metadata" not in inspector.get_table_names():
        return {}
    rows = bind.execute(
        text("SELECT key, value FROM migration_metadata WHERE revision = :rev"),
        {"rev": rev},
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _delete_config_snapshot(bind, rev: str) -> None:
    """Remove snapshot rows for *rev* from migration_metadata after downgrade."""
    inspector = sa.inspect(bind)
    if "migration_metadata" not in inspector.get_table_names():
        return
    bind.execute(
        text("DELETE FROM migration_metadata WHERE revision = :rev"),
        {"rev": rev},
    )


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

    # Snapshot config values so downgrade() can be hermetic.
    _snapshot_config(
        bind,
        revision,
        {
            "default_admin_role": new_admin_role,
            "default_user_role": new_user_role,
            "default_team_owner_role": new_team_owner_role,
            "default_team_member_role": new_team_member_role,
        },
    )

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
            logger.warning("Team member role '%s' not found, skipping backfill", new_team_member_role)
        elif not team_owner_role_id:
            logger.warning("Team owner role '%s' not found, skipping backfill", new_team_owner_role)
        else:
            # Find active team members who don't have any active team-scoped role
            # Include tm.role to map owners and members to correct RBAC roles
            result = bind.execute(
                text("""
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
                    """),
            )
            members_without_roles = result.fetchall()

            # Tag inserted rows with migration_source = MIGRATION_SOURCE so
            # downgrade() can identify and remove only the rows this migration
            # created. The migration_source column is added by migration
            # v1a2b3c4d5e6 earlier in the chain. If for some reason it's
            # missing (e.g. a future chain reorder), fall back to the legacy
            # untagged INSERT so the migration still completes; downgrade
            # will then be best-effort.
            user_roles_columns = [col["name"] for col in inspector.get_columns("user_roles")]
            has_migration_source = "migration_source" in user_roles_columns
            if has_migration_source:
                insert_sql = text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, scope_id, granted_by, granted_at, is_active, migration_source) "
                    "VALUES (:id, :user_email, :role_id, 'team', :team_id, :granted_by, :granted_at, true, :migration_source)"
                )
            else:
                insert_sql = text(
                    "INSERT INTO user_roles (id, user_email, role_id, scope, scope_id, granted_by, granted_at, is_active) "
                    "VALUES (:id, :user_email, :role_id, 'team', :team_id, :granted_by, :granted_at, true)"
                )

            for member in members_without_roles:
                user_email, team_id, membership_role = member
                role_id = team_owner_role_id if membership_role == "owner" else team_member_role_id
                # Use self-grant for compatibility with deployments where granted_by
                # enforces a foreign key to email_users.email.
                params = {
                    "id": _generate_uuid(),
                    "user_email": user_email,
                    "role_id": role_id,
                    "team_id": team_id,
                    "granted_by": user_email,
                    "granted_at": datetime.now(timezone.utc),
                }
                if has_migration_source:
                    params["migration_source"] = MIGRATION_SOURCE
                bind.execute(insert_sql, params)

            total += len(members_without_roles)
            print(f"  ✓ Created {len(members_without_roles)} team-scoped role assignments for existing team members")

    print(f"\n✅ Migration complete: {total} role assignments updated")


def downgrade() -> None:
    """Revert user_roles migration.

    Phase 2 cleanup: deletes only the backfill rows that upgrade() inserted,
    identified by migration_source = MIGRATION_SOURCE.  Legitimate grants are
    untouched.

    Phase 1 reversal: reads the role-name config values from the
    migration_metadata snapshot written during upgrade() so the reversal is
    hermetic regardless of current env-var values.  Falls back to live settings
    with a warning for databases upgraded before this fix was applied.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "user_roles" not in existing_tables or "roles" not in existing_tables:
        print("RBAC tables not found. Skipping downgrade.")
        return

    print("=== Reverting user_roles migration ===")
    total = 0

    # Read the config values that were live at upgrade time (hermetic).
    # Falls back to live settings with a warning on pre-fix databases that
    # have no snapshot row.
    snapshot = _read_config_snapshot(bind, revision)
    if snapshot:
        new_admin_role = snapshot.get("default_admin_role", settings.default_admin_role)
        new_user_role = snapshot.get("default_user_role", settings.default_user_role)
        new_team_owner_role = snapshot.get("default_team_owner_role", settings.default_team_owner_role)
        new_team_member_role = snapshot.get("default_team_member_role", settings.default_team_member_role)
        print(f"  ✓ Loaded config snapshot from migration_metadata (revision={revision})")
    else:
        logger.warning("No config snapshot found in migration_metadata. " "Falling back to live settings — downgrade correctness depends on env vars matching upgrade time.")
        new_admin_role = settings.default_admin_role
        new_user_role = settings.default_user_role
        new_team_owner_role = settings.default_team_owner_role
        new_team_member_role = settings.default_team_member_role

    # Phase 2 cleanup: delete only rows that were inserted by Phase 2 backfill,
    # identified by migration_source = MIGRATION_SOURCE. Bootstrap, manual,
    # and SSO grants use other migration_source values (NULL, 'manual', 'sso',
    # etc.) and are preserved.
    user_roles_columns = [col["name"] for col in inspector.get_columns("user_roles")]
    if "migration_source" in user_roles_columns:
        try:
            result = bind.execute(
                text("DELETE FROM user_roles WHERE migration_source = :ms"),
                {"ms": MIGRATION_SOURCE},
            )
            removed = getattr(result, "rowcount", 0) or 0
            total += removed
            print(f"  ✓ Removed {removed} Phase 2 backfill rows (migration_source={MIGRATION_SOURCE})")
        except Exception as e:
            logger.warning("Could not remove Phase 2 backfill rows: %s", e)
    else:
        print("  ℹ user_roles.migration_source column not present; cannot identify Phase 2 rows. Skipping cleanup.")

    # Revert Phase 1 role remap using the snapshotted (or fallback) config values.
    # Wrap in try/finally to ensure snapshot cleanup happens even if Phase 1 fails.
    try:
        if new_admin_role == OLD_ADMIN_ROLE and new_user_role == OLD_USER_ROLE and new_team_owner_role == OLD_TEAM_OWNER_ROLE and new_team_member_role == OLD_TEAM_MEMBER_ROLE:
            print("  All default roles match hardcoded values. No remap reversal needed.")
        else:
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
    finally:
        # Clean up this migration's snapshot rows now that downgrade is done.
        # This runs unconditionally to prevent stale snapshots on retry.
        _delete_config_snapshot(bind, revision)

    print(f"\n✅ Downgrade complete: {total} role assignments reverted")
