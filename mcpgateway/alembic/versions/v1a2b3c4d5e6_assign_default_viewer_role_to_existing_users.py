# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/v1a2b3c4d5e6_assign_default_viewer_role_to_existing_users.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Update role permissions and assign default roles to existing users.

Revision ID: v1a2b3c4d5e6
Revises: 04cda6733305
Create Date: 2026-02-04 12:30:00.000000

This migration:
1. Updates permissions for team_admin, developer, and viewer roles
2. Creates platform_viewer role with global scope
3. Assigns roles to existing users:
   - Admin users: team_admin (team scope) + platform_admin (global scope)
   - Non-admin users: team_admin (team scope) + viewer (global scope)
   - Preserves admin@example.com records unchanged

This ensures backward compatibility when RBAC is enabled on an existing system.
"""

# Standard
from datetime import datetime, timezone
import json
from typing import Sequence, Union
import uuid

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "v1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "04cda6733305"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Define new role permissions
ROLE_PERMISSIONS = {
    "team_admin": [
        "admin.dashboard",
        "gateways.read",
        "servers.read",
        "teams.read",
        "teams.update",
        "teams.join",
        "teams.manage_members",
        "tools.read",
        "tools.execute",
        "resources.read",
        "prompts.read",
        "a2a.read",
        "gateways.create",
        "servers.create",
        "tools.create",
        "resources.create",
        "prompts.create",
        "a2a.create",
        "gateways.update",
        "servers.update",
        "tools.update",
        "resources.update",
        "prompts.update",
        "a2a.update",
        "gateways.delete",
        "servers.delete",
        "tools.delete",
        "resources.delete",
        "prompts.delete",
        "a2a.delete",
        "a2a.invoke",
    ],
    "developer": [
        "admin.dashboard",
        "gateways.read",
        "servers.read",
        "teams.join",
        "tools.read",
        "tools.execute",
        "resources.read",
        "prompts.read",
        "a2a.read",
        "gateways.create",
        "servers.create",
        "tools.create",
        "resources.create",
        "prompts.create",
        "a2a.create",
        "gateways.update",
        "servers.update",
        "tools.update",
        "resources.update",
        "prompts.update",
        "a2a.update",
        "gateways.delete",
        "servers.delete",
        "tools.delete",
        "resources.delete",
        "prompts.delete",
        "a2a.delete",
        "a2a.invoke",
    ],
    "viewer": [
        "admin.dashboard",
        "gateways.read",
        "servers.read",
        "teams.join",
        "tools.read",
        "resources.read",
        "prompts.read",
        "a2a.read",
    ],
    "platform_viewer": [
        "admin.dashboard",
        "gateways.read",
        "servers.read",
        "teams.join",
        "tools.read",
        "resources.read",
        "prompts.read",
        "a2a.read",
    ],
}


def upgrade() -> None:
    """Update role permissions and assign default roles to existing users.

    This migration:
    1. Updates permissions for team_admin, developer, and viewer roles
    2. Creates platform_viewer role with global scope
    3. Assigns roles to existing users (excluding admin@example.com):
       - Admin users: team_admin (team scope) + platform_admin (global scope)
       - Non-admin users: team_admin (team scope) + viewer (global scope)

    The migration is idempotent and safe to run multiple times.
    Supports both PostgreSQL and SQLite databases.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Detect database dialect
    dialect_name = bind.dialect.name
    print(f"Detected database dialect: {dialect_name}")

    # Skip if RBAC tables don't exist yet
    if "roles" not in existing_tables or "user_roles" not in existing_tables:
        print("RBAC tables not found. Skipping migration.")
        return

    # Skip if email_users table doesn't exist
    if "email_users" not in existing_tables:
        print("email_users table not found. Skipping migration.")
        return

    # Skip if teams table doesn't exist
    if "teams" not in existing_tables:
        print("teams table not found. Skipping migration.")
        return

    now = datetime.now(timezone.utc)

    # Step 1: Update existing role permissions
    print("\n=== Step 1: Updating role permissions ===")
    for role_name, new_permissions in ROLE_PERMISSIONS.items():
        if role_name == "platform_viewer":
            continue  # Handle separately

        role_query = text("SELECT id FROM roles WHERE name = :role_name LIMIT 1")
        role_result = bind.execute(role_query, {"role_name": role_name}).fetchone()

        if role_result:
            role_id = role_result[0]
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

            bind.execute(
                update_query,
                {
                    "permissions": json.dumps(new_permissions),
                    "updated_at": now,
                    "role_id": role_id,
                },
            )
            print(f"  ✓ Updated '{role_name}' role permissions")
        else:
            print(f"  ⚠ Role '{role_name}' not found, skipping")

    # Step 2: Create platform_viewer role if it doesn't exist
    print("\n=== Step 2: Creating platform_viewer role ===")
    platform_viewer_query = text("SELECT id FROM roles WHERE name = :role_name LIMIT 1")
    platform_viewer_result = bind.execute(platform_viewer_query, {"role_name": "platform_viewer"}).fetchone()

    if not platform_viewer_result:
        platform_viewer_id = str(uuid.uuid4())
        insert_role = text(
            """
            INSERT INTO roles (id, name, description, scope, permissions, inherits_from,
                             created_by, is_system_role, is_active, created_at, updated_at)
            VALUES (:id, :name, :description, :scope, :permissions, :inherits_from,
                    :created_by, :is_system_role, :is_active, :created_at, :updated_at)
        """
        )

        bind.execute(
            insert_role,
            {
                "id": platform_viewer_id,
                "name": "platform_viewer",
                "description": "Read-only access to resources and admin UI",
                "scope": "global",
                "permissions": json.dumps(ROLE_PERMISSIONS["platform_viewer"]),
                "inherits_from": None,
                "created_by": "admin@example.com",
                "is_system_role": True,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        print(f"  ✓ Created 'platform_viewer' role with ID: {platform_viewer_id}")
    else:
        print("  ℹ 'platform_viewer' role already exists")

    # Step 3: Get role IDs for assignment
    print("\n=== Step 3: Fetching role IDs ===")
    team_admin_query = text("SELECT id FROM roles WHERE name = :role_name LIMIT 1")
    team_admin_result = bind.execute(team_admin_query, {"role_name": "team_admin"}).fetchone()
    if not team_admin_result:
        print("  ✗ 'team_admin' role not found. Cannot proceed with user role assignment.")
        return
    team_admin_role_id = team_admin_result[0]
    print(f"  ✓ Found 'team_admin' role: {team_admin_role_id}")

    viewer_query = text("SELECT id FROM roles WHERE name = :role_name LIMIT 1")
    viewer_result = bind.execute(viewer_query, {"role_name": "viewer"}).fetchone()
    if not viewer_result:
        print("  ✗ 'viewer' role not found. Cannot proceed with user role assignment.")
        return
    viewer_role_id = viewer_result[0]
    print(f"  ✓ Found 'viewer' role: {viewer_role_id}")

    platform_admin_query = text("SELECT id FROM roles WHERE name = :role_name LIMIT 1")
    platform_admin_result = bind.execute(platform_admin_query, {"role_name": "platform_admin"}).fetchone()
    if not platform_admin_result:
        print("  ✗ 'platform_admin' role not found. Cannot proceed with user role assignment.")
        return
    platform_admin_role_id = platform_admin_result[0]
    print(f"  ✓ Found 'platform_admin' role: {platform_admin_role_id}")

    # Step 4: Find users without role assignments (excluding admin@example.com)
    print("\n=== Step 4: Finding users without role assignments ===")
    if dialect_name == "postgresql":
        users_query = text(
            """
            SELECT eu.email, eu.is_admin, t.id as team_id
            FROM email_users eu
            LEFT JOIN teams t ON t.name = eu.email AND t.is_personal = TRUE
            WHERE eu.email NOT IN (SELECT DISTINCT user_email FROM user_roles WHERE is_active = TRUE)
            AND eu.is_active = TRUE
            AND eu.email != :admin_email
        """
        )
    else:
        users_query = text(
            """
            SELECT eu.email, eu.is_admin, t.id as team_id
            FROM email_users eu
            LEFT JOIN teams t ON t.name = eu.email AND t.is_personal = 1
            WHERE eu.email NOT IN (SELECT DISTINCT user_email FROM user_roles WHERE is_active = 1)
            AND eu.is_active = 1
            AND eu.email != :admin_email
        """
        )

    users_without_roles = bind.execute(users_query, {"admin_email": "admin@example.com"}).fetchall()

    if not users_without_roles:
        print("  ℹ All active users (except admin@example.com) already have role assignments.")
        return

    print(f"  ✓ Found {len(users_without_roles)} users without role assignments")

    # Step 5: Assign roles to users
    print("\n=== Step 5: Assigning roles to users ===")
    insert_user_role = text(
        """
        INSERT INTO user_roles (id, user_email, role_id, scope, scope_id,
                              granted_by, granted_at, expires_at, is_active)
        VALUES (:id, :user_email, :role_id, :scope, :scope_id,
                :granted_by, :granted_at, :expires_at, :is_active)
    """
    )

    granted_by_email = "admin@example.com"
    assigned_count = 0

    for user_row in users_without_roles:
        user_email = user_row[0]
        is_admin = user_row[1]
        team_id = user_row[2]

        if not team_id:
            print(f"  ⚠ User {user_email} has no personal team, skipping")
            continue

        try:
            # Assign team_admin role with team scope
            team_admin_assignment_id = str(uuid.uuid4())
            bind.execute(
                insert_user_role,
                {
                    "id": team_admin_assignment_id,
                    "user_email": user_email,
                    "role_id": team_admin_role_id,
                    "scope": "team",
                    "scope_id": team_id,
                    "granted_by": granted_by_email,
                    "granted_at": now,
                    "expires_at": None,
                    "is_active": True,
                },
            )

            # Assign second role based on is_admin flag
            if is_admin:
                # Admin users get platform_admin with global scope
                global_role_assignment_id = str(uuid.uuid4())
                bind.execute(
                    insert_user_role,
                    {
                        "id": global_role_assignment_id,
                        "user_email": user_email,
                        "role_id": platform_admin_role_id,
                        "scope": "global",
                        "scope_id": None,
                        "granted_by": granted_by_email,
                        "granted_at": now,
                        "expires_at": None,
                        "is_active": True,
                    },
                )
                print(f"  ✓ Assigned 'team_admin' (team) + 'platform_admin' (global) to: {user_email}")
            else:
                # Non-admin users get viewer with global scope
                global_role_assignment_id = str(uuid.uuid4())
                bind.execute(
                    insert_user_role,
                    {
                        "id": global_role_assignment_id,
                        "user_email": user_email,
                        "role_id": viewer_role_id,
                        "scope": "global",
                        "scope_id": None,
                        "granted_by": granted_by_email,
                        "granted_at": now,
                        "expires_at": None,
                        "is_active": True,
                    },
                )
                print(f"  ✓ Assigned 'team_admin' (team) + 'viewer' (global) to: {user_email}")

            assigned_count += 1
        except Exception as e:
            print(f"  ✗ Failed to assign roles to {user_email}: {e}")

    print(f"\n✅ Successfully assigned roles to {assigned_count} users")
    print("   • Each user received 2 roles:")
    print("     - team_admin with team scope (for their personal team)")
    print("     - platform_admin (admins) or viewer (non-admins) with global scope")


def downgrade() -> None:
    """Revert role permission updates and remove role assignments.

    This migration downgrade:
    1. Reverts permissions for team_admin, developer, and viewer roles to original values
    2. Removes platform_viewer role
    3. Removes all role assignments EXCEPT those for admin@example.com

    Supports both PostgreSQL and SQLite databases.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Detect database dialect
    dialect_name = bind.dialect.name
    print(f"Detected database dialect: {dialect_name}")

    # Skip if tables don't exist
    if "user_roles" not in existing_tables or "roles" not in existing_tables:
        print("Required tables not found. Nothing to downgrade.")
        return

    now = datetime.now(timezone.utc)

    # Step 1: Revert role permissions to original values
    print("\n=== Step 1: Reverting role permissions ===")
    original_permissions = {
        "team_admin": [
            "teams.read",
            "teams.update",
            "teams.join",
            "teams.manage_members",
            "tools.read",
            "tools.execute",
            "resources.read",
            "prompts.read",
        ],
        "developer": [
            "teams.join",
            "tools.read",
            "tools.execute",
            "resources.read",
            "prompts.read",
        ],
        "viewer": [
            "teams.join",
            "tools.read",
            "resources.read",
            "prompts.read",
        ],
    }

    for role_name, old_permissions in original_permissions.items():
        role_query = text("SELECT id FROM roles WHERE name = :role_name LIMIT 1")
        role_result = bind.execute(role_query, {"role_name": role_name}).fetchone()

        if role_result:
            role_id = role_result[0]
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

            bind.execute(
                update_query,
                {
                    "permissions": json.dumps(old_permissions),
                    "updated_at": now,
                    "role_id": role_id,
                },
            )
            print(f"  ✓ Reverted '{role_name}' role permissions")

    # Step 2: Remove platform_viewer role
    print("\n=== Step 2: Removing platform_viewer role ===")
    try:
        delete_role = text("DELETE FROM roles WHERE name = :role_name")
        result = bind.execute(delete_role, {"role_name": "platform_viewer"})
        if hasattr(result, "rowcount") and result.rowcount > 0:
            print("  ✓ Removed 'platform_viewer' role")
        else:
            print("  ℹ 'platform_viewer' role not found")
    except Exception as e:
        print(f"  ⚠ Could not remove 'platform_viewer' role: {e}")

    # Step 3: Remove migration-assigned role assignments (keeping admin@example.com)
    print("\n=== Step 3: Removing migration-assigned roles ===")
    try:
        delete_sql = text("DELETE FROM user_roles WHERE user_email != :keep_email")
        result = bind.execute(delete_sql, {"keep_email": "admin@example.com"})
        rowcount = getattr(result, "rowcount", "unknown")
        print(f"  ✓ Removed {rowcount} role assignments (preserved admin@example.com)")
    except Exception as e:
        print(f"  ⚠ Could not remove migration-assigned roles: {e}")

    print("\n✅ Downgrade completed")

# Made with Bob
