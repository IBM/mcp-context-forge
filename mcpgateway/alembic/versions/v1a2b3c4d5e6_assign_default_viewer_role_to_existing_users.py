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
- Users with is_admin=true get 'platform_admin' role
- Regular users get 'viewer' role

This ensures backward compatibility when RBAC is enabled on an existing system.
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
    """Assign default roles to existing users without roles.

    This migration:
    1. Checks if the roles and user_roles tables exist
    2. Ensures the 'viewer' and 'platform_admin' roles exist
    3. Assigns 'platform_admin' role to users with is_admin=true
    4. Assigns 'viewer' role to regular users without role assignments

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

    print("Assigning default roles to existing users (platform_admin for admins, viewer for others)...")

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

    # Get the platform_admin role ID
    platform_admin_role_query = text("SELECT id FROM roles WHERE name = :role_name LIMIT 1")
    platform_admin_role_result = bind.execute(platform_admin_role_query, {"role_name": "platform_admin"}).fetchone()

    if not platform_admin_role_result:
        print("Warning: 'platform_admin' role not found. Creating it now...")

        # Create platform_admin role if it doesn't exist
        platform_admin_role_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)

        bind.execute(
            insert_role,
            {
                "id": platform_admin_role_id,
                "name": "platform_admin",
                "description": "Full platform administration access",
                "scope": "global",
                "permissions": '["*"]',
                "inherits_from": None,
                "created_by": "system",
                "is_system_role": True,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        print(f"Created 'platform_admin' role with ID: {platform_admin_role_id}")
    else:
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
    now = datetime.now(timezone.utc)
    assigned_admin_count = 0
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
        else:
            role_id = viewer_role_id

        try:
            bind.execute(
                insert_user_role,
                {
                    "id": user_role_id,
                    "user_email": user_email,
                    "role_id": role_id,
                    "scope": "global",
                    "scope_id": None,
                    "granted_by": granted_by_email,
                    "granted_at": now,
                    "expires_at": None,
                    "is_active": True,
                },
            )
            if is_admin:
                assigned_admin_count += 1
                print(f"  ✓ Assigned 'platform_admin' role to: {user_email}")
            else:
                assigned_viewer_count += 1
                print(f"  ✓ Assigned 'viewer' role to: {user_email}")
        except Exception as e:
            print(f"  ✗ Failed to assign role to {user_email}: {e}")

    print(f"\n✅ Successfully assigned roles to {assigned_admin_count + assigned_viewer_count} users:")
    print(f"   • {assigned_admin_count} platform_admin role(s)")
    print(f"   • {assigned_viewer_count} viewer role(s)")
    print("\n💡 Next steps:")
    print("   • Regular users can be upgraded to 'developer' or 'team_admin' roles via:")
    print("     POST /rbac/users/{user_email}/roles")
    print("   • Admin users now have full platform_admin access")
    print("   • Or use the Admin UI when role management is implemented")


def downgrade() -> None:
    """Remove role assignments created by this migration.

    This removes viewer and platform_admin role assignments that
    were created during this migration.
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

    print("Removing migration-assigned roles...")

    try:
        # Find role IDs for viewer and platform_admin explicitly to avoid driver-specific
        # parameter binding issues with SQL IN lists.
        protected_email = "admin@example.com"

        # Collect ALL role IDs that match the names, there may be multiple (team/global)
        role_rows = bind.execute(text("SELECT id, name FROM roles WHERE name IN ('viewer','platform_admin')")).fetchall()

        role_ids = [r[0] for r in role_rows]

        if not role_ids:
            print("No viewer or platform_admin roles found; nothing to remove.")
            return

        # Use SQLAlchemy Core to perform a parameterized delete and avoid
        # constructing SQL with f-strings (Bandit B608).
        user_roles_table = sa.table("user_roles", sa.column("role_id"), sa.column("user_email"))

        delete_stmt = sa.delete(user_roles_table).where(
            user_roles_table.c.role_id.in_(role_ids),
            sa.or_(user_roles_table.c.user_email.is_(None), user_roles_table.c.user_email != protected_email),
        )

        result = bind.execute(delete_stmt)
        print(f"✅ Removed {result.rowcount} migration-assigned role assignments (excluding admin@example.com).")
        print("⚠️  Note: This removes viewer and platform_admin roles except for the protected admin account admin@example.com.")
    except Exception as e:
        print(f"Warning: Could not remove migration-assigned roles: {e}")
