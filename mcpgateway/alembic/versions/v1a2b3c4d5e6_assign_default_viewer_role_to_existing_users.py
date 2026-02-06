# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/v1a2b3c4d5e6_assign_default_viewer_role_to_existing_users.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Assign default roles to existing users without roles.

Revision ID: v1a2b3c4d5e6
Revises: b1b2b3b4b5b6
Create Date: 2026-02-04 12:30:00.000000

This migration assigns appropriate default roles to all existing users
who don't have any role assignments yet:
- Users with is_admin=true get 'platform_admin' role with platform scope
- Regular users get 'viewer' role with team scope

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
down_revision: Union[str, Sequence[str], None] = "b1b2b3b4b5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Assign default roles to existing users without roles and update role permissions.

    This migration:
    1. Checks if the roles and user_roles tables exist
    2. Adds 'admin.dashboard', 'gateways.read', and 'servers.read' permissions to all roles except 'platform_admin'
    3. Ensures the 'viewer' and 'platform_admin' roles exist with correct permissions
    4. Assigns 'platform_admin' role to users with is_admin=true (with platform scope)
    5. Assigns 'viewer' role to regular users without role assignments (with team scope)

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
        print("RBAC tables not found. Skipping default role assignment.")
        return

    # Skip if email_users table doesn't exist
    if "email_users" not in existing_tables:
        print("email_users table not found. Skipping default role assignment.")
        return

    # Step 1: Update existing roles to include 'admin.dashboard', 'gateways.read', and 'servers.read' permissions
    print("Updating role permissions to include 'admin.dashboard', 'gateways.read', and 'servers.read'...")

    # Get all roles except platform_admin
    roles_query = text("SELECT id, name, permissions FROM roles WHERE name != :platform_admin")
    roles_to_update = bind.execute(roles_query, {"platform_admin": "platform_admin"}).fetchall()

    updated_roles_count = 0
    for role_row in roles_to_update:
        role_id = role_row[0]
        role_name = role_row[1]
        permissions_raw = role_row[2]

        # Parse permissions - handle both string JSON and native list/dict types
        try:
            if isinstance(permissions_raw, str):
                # SQLite stores as JSON string
                permissions = json.loads(permissions_raw) if permissions_raw else []
            elif isinstance(permissions_raw, list):
                # PostgreSQL JSONB returns as native Python list
                permissions = permissions_raw
            else:
                # Fallback for other types
                permissions = []
        except (json.JSONDecodeError, TypeError, ValueError):
            permissions = []

        # Ensure permissions is a list
        if not isinstance(permissions, list):
            permissions = []

        # Check if any of the required permissions are missing
        permissions_to_add = []
        if "admin.dashboard" not in permissions:
            permissions_to_add.append("admin.dashboard")
        if "gateways.read" not in permissions:
            permissions_to_add.append("gateways.read")
        if "servers.read" not in permissions:
            permissions_to_add.append("servers.read")

        if permissions_to_add:
            # Append missing permissions to the end of existing permissions
            permissions.extend(permissions_to_add)

            # Update the role with new permissions
            # Use database-specific JSON handling
            if dialect_name == "postgresql":
                # PostgreSQL: Cast to JSONB
                update_role_query = text(
                    """
                    UPDATE roles
                    SET permissions = CAST(:permissions AS JSONB), updated_at = :updated_at
                    WHERE id = :role_id
                    """
                )
            else:
                # SQLite: Store as JSON string
                update_role_query = text(
                    """
                    UPDATE roles
                    SET permissions = :permissions, updated_at = :updated_at
                    WHERE id = :role_id
                    """
                )

            bind.execute(
                update_role_query,
                {
                    "permissions": json.dumps(permissions),
                    "updated_at": datetime.now(timezone.utc),
                    "role_id": role_id,
                },
            )
            updated_roles_count += 1
            print(f"  ✓ Added {permissions_to_add} permission(s) to role '{role_name}': {permissions}")

    if updated_roles_count > 0:
        print(f"✅ Updated {updated_roles_count} role(s) with 'admin.dashboard', 'gateways.read', and 'servers.read' permissions.")
    else:
        print("All roles already have 'admin.dashboard', 'gateways.read', and 'servers.read' permissions.")

    print("\nAssigning default roles to existing users (team_admin for admins, viewer for others)...")

    # Get the viewer role ID (using parameterized query for security)
    viewer_role_query = text("SELECT id FROM roles WHERE name = :role_name LIMIT 1")
    viewer_role_result = bind.execute(viewer_role_query, {"role_name": "viewer"}).fetchone()

    if not viewer_role_result:
        print("Warning: 'viewer' role not found. Creating it now...")

        # Create viewer role if it doesn't exist
        viewer_role_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)

        # Use parameterized query to prevent SQL injection (Bandit B608)
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
                "id": viewer_role_id,
                "name": "viewer",
                "description": "Read-only access to team resources",
                "scope": "team",
                "permissions": '["admin.dashboard", "gateways.read", "servers.read", "teams.join", "tools.read", "resources.read", "prompts.read"]',
                "inherits_from": None,
                "created_by": "system",
                "is_system_role": True,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        print(f"Created 'viewer' role with ID: {viewer_role_id}")
    else:
        viewer_role_id = viewer_role_result[0]
        print(f"Found existing 'viewer' role with ID: {viewer_role_id}")

    # Get the platform_admin role ID
    platform_admin_role_query = text("SELECT id FROM roles WHERE name = :role_name LIMIT 1")
    platform_admin_role_result = bind.execute(platform_admin_role_query, {"role_name": "platform_admin"}).fetchone()

    platform_admin_role_id = platform_admin_role_result[0]
    print(f"Found existing 'platform_admin' role with ID: {platform_admin_role_id}")

    # Find users without any role assignments, including their is_admin status
    # Use database-specific boolean comparison for compatibility
    if dialect_name == "postgresql":
        # PostgreSQL uses TRUE/FALSE
        users_without_roles_query = text(
            """
            SELECT email, is_admin FROM email_users
            WHERE email NOT IN (SELECT DISTINCT user_email FROM user_roles WHERE is_active = TRUE)
            AND is_active = TRUE
        """
        )
    else:
        # SQLite uses 1/0 for boolean
        users_without_roles_query = text(
            """
            SELECT email, is_admin FROM email_users
            WHERE email NOT IN (SELECT DISTINCT user_email FROM user_roles WHERE is_active = 1)
            AND is_active = 1
        """
        )

    users_without_roles = bind.execute(users_without_roles_query).fetchall()

    if not users_without_roles:
        print("All active users already have role assignments. Nothing to do.")
        return

    print(f"Found {len(users_without_roles)} users without role assignments.")

    # Find an admin user to use as granted_by, or use first user
    # granted_by has a foreign key constraint to email_users.email
    if dialect_name == "postgresql":
        admin_user_query = text(
            """
            SELECT email FROM email_users
            WHERE is_admin = TRUE
            ORDER BY created_at ASC
            LIMIT 1
        """
        )
    else:
        admin_user_query = text(
            """
            SELECT email FROM email_users
            WHERE is_admin = 1
            ORDER BY created_at ASC
            LIMIT 1
        """
        )

    admin_user_result = bind.execute(admin_user_query).fetchone()

    if admin_user_result:
        granted_by_email = admin_user_result[0]
        print(f"Using admin user '{granted_by_email}' as granted_by for role assignments.")
    else:
        # No admin user found, use first active user
        if dialect_name == "postgresql":
            first_user_query = text(
                """
                SELECT email FROM email_users
                WHERE is_active = TRUE
                ORDER BY created_at ASC
                LIMIT 1
            """
            )
        else:
            first_user_query = text(
                """
                SELECT email FROM email_users
                WHERE is_active = 1
                ORDER BY created_at ASC
                LIMIT 1
            """
            )

        first_user_result = bind.execute(first_user_query).fetchone()
        if first_user_result:
            granted_by_email = first_user_result[0]
            print(f"No admin found. Using first user '{granted_by_email}' as granted_by for role assignments.")
        else:
            print("No users found to use as granted_by. Cannot assign roles.")
            return

    # Assign appropriate role to each user (platform_admin for admins, viewer for others)
    # Admin users get platform scope, regular users get team scope
    now = datetime.now(timezone.utc)
    assigned_platform_admin_count = 0
    assigned_viewer_count = 0

    # Use parameterized query to prevent SQL injection (Bandit B608)
    insert_user_role = text(
        """
        INSERT INTO user_roles (id, user_email, role_id, scope, scope_id,
                              granted_by, granted_at, expires_at, is_active)
        VALUES (:id, :user_email, :role_id, :scope, :scope_id,
                :granted_by, :granted_at, :expires_at, :is_active)
    """
    )

    for user_row in users_without_roles:
        user_email = user_row[0]
        is_admin = user_row[1]
        user_role_id = uuid.uuid4().hex

        # Determine which role to assign based on is_admin flag
        if is_admin:
            role_id = platform_admin_role_id
            scope_value = "global"
        else:
            role_id = viewer_role_id
            scope_value = "team"

        try:
            bind.execute(
                insert_user_role,
                {
                    "id": user_role_id,
                    "user_email": user_email,
                    "role_id": role_id,
                    "scope": scope_value,
                    "scope_id": None,
                    "granted_by": granted_by_email,
                    "granted_at": now,
                    "expires_at": None,
                    "is_active": True,
                },
            )
            if is_admin:
                assigned_platform_admin_count += 1
                print(f"  ✓ Assigned 'platform_admin' role to: {user_email}")
            else:
                assigned_viewer_count += 1
                print(f"  ✓ Assigned 'viewer' role to: {user_email}")
        except Exception as e:
            print(f"  ✗ Failed to assign role to {user_email}: {e}")

    print(f"\n✅ Successfully assigned roles to {assigned_platform_admin_count + assigned_viewer_count} users:")
    print(f"   • {assigned_platform_admin_count} platform_admin role(s)")
    print(f"   • {assigned_viewer_count} viewer role(s)")
    print("\n💡 Next steps:")
    print("   • Regular users can be upgraded to 'developer' role via:")
    print("     POST /rbac/users/{user_email}/roles")
    print("   • Admin users now have platform_admin access")
    print("   • Or use the Admin UI when role management is implemented")


def downgrade() -> None:
    """Remove role assignments and permission updates created by this migration.

    This migration downgrade:
    1. Removes 'admin.dashboard', 'gateways.read', and 'servers.read' permissions from all roles except 'platform_admin'
    2. Removes all role assignments EXCEPT those with platform_admin role

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

    # Step 1: Remove 'admin.dashboard', 'gateways.read', and 'servers.read' permissions from roles (except platform_admin)
    print("Removing 'admin.dashboard', 'gateways.read', and 'servers.read' permissions from roles...")

    # Get all roles except platform_admin
    roles_query = text("SELECT id, name, permissions FROM roles WHERE name != :platform_admin")
    roles_to_update = bind.execute(roles_query, {"platform_admin": "platform_admin"}).fetchall()

    updated_roles_count = 0

    for role_row in roles_to_update:
        role_id = role_row[0]
        role_name = role_row[1]
        permissions_raw = role_row[2]

        # Parse permissions - handle both string JSON and native list/dict types
        try:
            if isinstance(permissions_raw, str):
                # SQLite stores as JSON string
                permissions = json.loads(permissions_raw) if permissions_raw else []
            elif isinstance(permissions_raw, list):
                # PostgreSQL JSONB returns as native Python list
                permissions = permissions_raw
            else:
                # Fallback for other types
                permissions = []
        except (json.JSONDecodeError, TypeError, ValueError):
            permissions = []

        # Ensure permissions is a list
        if not isinstance(permissions, list):
            permissions = []

        # Check if any of the permissions are present and remove them
        permissions_removed = []
        if "admin.dashboard" in permissions:
            permissions.remove("admin.dashboard")
            permissions_removed.append("admin.dashboard")
        if "gateways.read" in permissions:
            permissions.remove("gateways.read")
            permissions_removed.append("gateways.read")
        if "servers.read" in permissions:
            permissions.remove("servers.read")
            permissions_removed.append("servers.read")

        if permissions_removed:
            # Update the role with new permissions
            # Use database-specific JSON handling
            if dialect_name == "postgresql":
                # PostgreSQL: Cast to JSONB
                update_role_query = text(
                    """
                    UPDATE roles
                    SET permissions = CAST(:permissions AS JSONB), updated_at = :updated_at
                    WHERE id = :role_id
                    """
                )
            else:
                # SQLite: Store as JSON string
                update_role_query = text(
                    """
                    UPDATE roles
                    SET permissions = :permissions, updated_at = :updated_at
                    WHERE id = :role_id
                    """
                )

            bind.execute(
                update_role_query,
                {
                    "permissions": json.dumps(permissions),
                    "updated_at": datetime.now(timezone.utc),
                    "role_id": role_id,
                },
            )
            updated_roles_count += 1
            print(f"  ✓ Removed {permissions_removed} permission(s) from role '{role_name}': {permissions}")

    if updated_roles_count > 0:
        print(f"✅ Removed 'admin.dashboard', 'gateways.read', and 'servers.read' permissions from {updated_roles_count} role(s).")
    else:
        print("No roles had 'admin.dashboard', 'gateways.read', or 'servers.read' permissions to remove.")

    # Step 2: Remove migration-assigned role assignments (keeping admin@example.com)
    print("\nRemoving migration-assigned roles (preserving user_email=admin@example.com)...")

    try:
        # Delete all user_roles except for the system admin email
        delete_sql = text("DELETE FROM user_roles WHERE user_email != :keep_email")
        result = bind.execute(delete_sql, {"keep_email": "admin@example.com"})
        # result.rowcount is supported by DBAPI result proxies
        print(f"✅ Removed {getattr(result, 'rowcount', 'unknown')} role assignments (preserved admin@example.com).")
    except Exception as e:
        print(f"Warning: Could not remove migration-assigned roles: {e}")
