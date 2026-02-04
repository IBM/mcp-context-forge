# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/v1a2b3c4d5e6_assign_default_viewer_role_to_existing_users.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Assign default viewer role to existing users without roles.

Revision ID: v1a2b3c4d5e6
Revises: b1b2b3b4b5b6
Create Date: 2026-02-04 12:30:00.000000

This migration assigns the default 'viewer' role to all existing users
who don't have any role assignments yet. This ensures backward compatibility
when RBAC is enabled on an existing system.
"""

# Standard
from datetime import datetime, timezone
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
    """Assign default viewer role to existing users without roles.

    This migration:
    1. Checks if the roles and user_roles tables exist
    2. Ensures the 'viewer' role exists
    3. Assigns 'viewer' role to all users who don't have any role assignments

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

    print("Assigning default 'viewer' role to existing users...")

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
                "permissions": '["tools.read", "resources.read"]',
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

    # Find users without any role assignments
    # Use database-specific boolean comparison for compatibility
    if dialect_name == "postgresql":
        # PostgreSQL uses TRUE/FALSE
        users_without_roles_query = text(
            """
            SELECT email FROM email_users
            WHERE email NOT IN (SELECT DISTINCT user_email FROM user_roles WHERE is_active = TRUE)
            AND is_active = TRUE
        """
        )
    else:
        # SQLite uses 1/0 for boolean
        users_without_roles_query = text(
            """
            SELECT email FROM email_users
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

    # Assign viewer role to each user
    now = datetime.now(timezone.utc)
    assigned_count = 0

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
        user_role_id = uuid.uuid4().hex

        try:
            bind.execute(
                insert_user_role,
                {
                    "id": user_role_id,
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
            assigned_count += 1
            print(f"  ✓ Assigned 'viewer' role to: {user_email}")
        except Exception as e:
            print(f"  ✗ Failed to assign role to {user_email}: {e}")

    print(f"\n✅ Successfully assigned 'viewer' role to {assigned_count} users.")
    print("\n💡 Next steps:")
    print("   • Users can now be upgraded to 'developer' or 'team_admin' roles via:")
    print("     POST /rbac/users/{user_email}/roles")
    print("   • Or use the Admin UI when role management is implemented")


def downgrade() -> None:
    """Remove viewer role assignments created by this migration.

    This only removes role assignments that were created by the 'system' user
    during this migration, preserving any manually assigned roles.
    Supports both PostgreSQL and SQLite databases.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Detect database dialect
    dialect_name = bind.dialect.name
    print(f"Detected database dialect: {dialect_name}")

    # Skip if tables don't exist
    if "user_roles" not in existing_tables:
        print("user_roles table not found. Nothing to downgrade.")
        return

    print("Removing migration-assigned 'viewer' roles...")

    try:
        # Use parameterized query to prevent SQL injection (Bandit B608)
        # Remove viewer roles with global scope (these were assigned by this migration)
        # Note: We can't filter by granted_by since it could be any admin/user
        delete_query = text(
            """
            DELETE FROM user_roles
            WHERE role_id IN (SELECT id FROM roles WHERE name = :role_name)
            AND scope = :scope
        """
        )

        result = bind.execute(delete_query, {"role_name": "viewer", "scope": "global"})
        print(f"✅ Removed {result.rowcount} migration-assigned 'viewer' role assignments.")
        print("⚠️  Note: This removes ALL global viewer roles, not just migration-created ones.")
    except Exception as e:
        print(f"Warning: Could not remove migration-assigned viewer roles: {e}")
