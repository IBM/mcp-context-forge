"""add_rbac_unique_constraints_race_fix

Fixes issue #4482 - RBAC role/user_role seeder race when fast-path skips advisory lock.

Adds database-level unique constraints to prevent duplicate active roles and user role
assignments when multiple replicas/workers bootstrap concurrently. This is defense-in-depth:
even with the advisory lock in place today, the DB should be the ultimate authority on
uniqueness.

Changes:
1. Deduplicates any existing duplicate active rows (keeps oldest by created_at/granted_at)
2. Adds partial unique index on roles(name, scope) WHERE is_active = true
3. Adds partial unique indexes on user_roles for both nullable and non-nullable scope_id cases

Supports both PostgreSQL and SQLite databases.

Revision ID: d21698ae4a19
Revises: 9fb98535724d
Create Date: 2026-05-06 12:35:58.142694

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text, inspect


# revision identifiers, used by Alembic.
revision: str = 'd21698ae4a19'  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = 'w7x8y9z0a1b2'  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add unique constraints for RBAC tables."""
    bind = op.get_bind()
    inspector = inspect(bind)
    dialect = bind.dialect.name

    # Skip if tables don't exist (fresh DB uses db.py models directly)
    existing_tables = inspector.get_table_names()
    if "roles" not in existing_tables or "user_roles" not in existing_tables:
        return

    # =============================================================================
    # STEP 1: Deduplicate roles table - keep oldest active role by (name, scope)
    # =============================================================================

    # Find duplicate active roles (same name+scope combination)
    # Strategy: soft-delete (set is_active=false) for duplicates, keep oldest by created_at

    # PostgreSQL uses DELETE...RETURNING, SQLite needs subquery approach
    if dialect == 'postgresql':
        dedupe_roles_sql = text("""
            UPDATE roles
            SET is_active = false
            WHERE id IN (
                SELECT r.id
                FROM roles r
                INNER JOIN (
                    SELECT name, scope, MIN(created_at) as oldest_created_at
                    FROM roles
                    WHERE is_active = true
                    GROUP BY name, scope
                    HAVING COUNT(*) > 1
                ) dupes ON r.name = dupes.name
                       AND r.scope = dupes.scope
                       AND r.created_at > dupes.oldest_created_at
                WHERE r.is_active = true
            )
        """)
    else:  # SQLite
        dedupe_roles_sql = text("""
            UPDATE roles
            SET is_active = 0
            WHERE id IN (
                SELECT r.id
                FROM roles r
                INNER JOIN (
                    SELECT name, scope, MIN(created_at) as oldest_created_at
                    FROM roles
                    WHERE is_active = 1
                    GROUP BY name, scope
                    HAVING COUNT(*) > 1
                ) dupes ON r.name = dupes.name
                       AND r.scope = dupes.scope
                       AND r.created_at > dupes.oldest_created_at
                WHERE r.is_active = 1
            )
        """)

    result = bind.execute(dedupe_roles_sql)
    deduped_roles_count = result.rowcount
    if deduped_roles_count > 0:
        print(f"Deduped {deduped_roles_count} duplicate active role(s) - set is_active=false for newer duplicates")

    # =============================================================================
    # STEP 2: Deduplicate user_roles table - keep oldest active assignment
    # =============================================================================

    # For user_roles, we need to handle scope_id IS NULL and IS NOT NULL separately
    # Strategy: soft-delete duplicates, keep oldest by granted_at

    # Handle scope_id IS NULL case
    if dialect == 'postgresql':
        dedupe_user_roles_null_scope_sql = text("""
            UPDATE user_roles
            SET is_active = false
            WHERE id IN (
                SELECT ur.id
                FROM user_roles ur
                INNER JOIN (
                    SELECT user_email, role_id, scope, MIN(granted_at) as oldest_granted_at
                    FROM user_roles
                    WHERE is_active = true AND scope_id IS NULL
                    GROUP BY user_email, role_id, scope
                    HAVING COUNT(*) > 1
                ) dupes ON ur.user_email = dupes.user_email
                       AND ur.role_id = dupes.role_id
                       AND ur.scope = dupes.scope
                       AND ur.scope_id IS NULL
                       AND ur.granted_at > dupes.oldest_granted_at
                WHERE ur.is_active = true
            )
        """)
    else:  # SQLite
        dedupe_user_roles_null_scope_sql = text("""
            UPDATE user_roles
            SET is_active = 0
            WHERE id IN (
                SELECT ur.id
                FROM user_roles ur
                INNER JOIN (
                    SELECT user_email, role_id, scope, MIN(granted_at) as oldest_granted_at
                    FROM user_roles
                    WHERE is_active = 1 AND scope_id IS NULL
                    GROUP BY user_email, role_id, scope
                    HAVING COUNT(*) > 1
                ) dupes ON ur.user_email = dupes.user_email
                       AND ur.role_id = dupes.role_id
                       AND ur.scope = dupes.scope
                       AND ur.scope_id IS NULL
                       AND ur.granted_at > dupes.oldest_granted_at
                WHERE ur.is_active = 1
            )
        """)

    result = bind.execute(dedupe_user_roles_null_scope_sql)
    deduped_user_roles_null = result.rowcount

    # Handle scope_id IS NOT NULL case
    if dialect == 'postgresql':
        dedupe_user_roles_with_scope_sql = text("""
            UPDATE user_roles
            SET is_active = false
            WHERE id IN (
                SELECT ur.id
                FROM user_roles ur
                INNER JOIN (
                    SELECT user_email, role_id, scope, scope_id, MIN(granted_at) as oldest_granted_at
                    FROM user_roles
                    WHERE is_active = true AND scope_id IS NOT NULL
                    GROUP BY user_email, role_id, scope, scope_id
                    HAVING COUNT(*) > 1
                ) dupes ON ur.user_email = dupes.user_email
                       AND ur.role_id = dupes.role_id
                       AND ur.scope = dupes.scope
                       AND ur.scope_id = dupes.scope_id
                       AND ur.granted_at > dupes.oldest_granted_at
                WHERE ur.is_active = true
            )
        """)
    else:  # SQLite
        dedupe_user_roles_with_scope_sql = text("""
            UPDATE user_roles
            SET is_active = 0
            WHERE id IN (
                SELECT ur.id
                FROM user_roles ur
                INNER JOIN (
                    SELECT user_email, role_id, scope, scope_id, MIN(granted_at) as oldest_granted_at
                    FROM user_roles
                    WHERE is_active = 1 AND scope_id IS NOT NULL
                    GROUP BY user_email, role_id, scope, scope_id
                    HAVING COUNT(*) > 1
                ) dupes ON ur.user_email = dupes.user_email
                       AND ur.role_id = dupes.role_id
                       AND ur.scope = dupes.scope
                       AND ur.scope_id = dupes.scope_id
                       AND ur.granted_at > dupes.oldest_granted_at
                WHERE ur.is_active = 1
            )
        """)

    result = bind.execute(dedupe_user_roles_with_scope_sql)
    deduped_user_roles_with_scope = result.rowcount

    total_deduped_user_roles = deduped_user_roles_null + deduped_user_roles_with_scope
    if total_deduped_user_roles > 0:
        print(f"Deduped {total_deduped_user_roles} duplicate active user_role(s) - set is_active=false for newer duplicates")

    # =============================================================================
    # STEP 3: Add partial unique indexes
    # =============================================================================

    # Check if indexes already exist (idempotency)
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('roles')]

    # Partial unique index on roles(name, scope) WHERE is_active = true
    # This prevents duplicate active roles with same name+scope
    if 'uq_roles_name_scope_active' not in existing_indexes:
        if dialect == 'postgresql':
            bind.execute(text(
                "CREATE UNIQUE INDEX uq_roles_name_scope_active "
                "ON roles (name, scope) "
                "WHERE is_active = true"
            ))
        elif dialect == 'sqlite':
            bind.execute(text(
                "CREATE UNIQUE INDEX uq_roles_name_scope_active "
                "ON roles (name, scope) "
                "WHERE is_active = 1"
            ))
        else:
            # For other databases, create without WHERE clause (less optimal but works)
            # Note: This will only allow one row per (name, scope) total, not just active ones
            print(f"WARNING: Dialect '{dialect}' may not support partial indexes. Creating full unique index.")
            bind.execute(text(
                "CREATE UNIQUE INDEX uq_roles_name_scope_active "
                "ON roles (name, scope)"
            ))
        print("Created unique index: uq_roles_name_scope_active")

    # Check user_roles indexes
    existing_user_roles_indexes = [idx['name'] for idx in inspector.get_indexes('user_roles')]

    # Partial unique index on user_roles(user_email, role_id, scope) WHERE scope_id IS NULL AND is_active = true
    if 'uq_user_roles_email_role_scope_null_active' not in existing_user_roles_indexes:
        if dialect == 'postgresql':
            bind.execute(text(
                "CREATE UNIQUE INDEX uq_user_roles_email_role_scope_null_active "
                "ON user_roles (user_email, role_id, scope) "
                "WHERE scope_id IS NULL AND is_active = true"
            ))
        elif dialect == 'sqlite':
            bind.execute(text(
                "CREATE UNIQUE INDEX uq_user_roles_email_role_scope_null_active "
                "ON user_roles (user_email, role_id, scope) "
                "WHERE scope_id IS NULL AND is_active = 1"
            ))
        else:
            # Fallback: unique on (user_email, role_id, scope) without WHERE
            print(f"WARNING: Dialect '{dialect}' may not support partial indexes. Creating full unique index.")
            bind.execute(text(
                "CREATE UNIQUE INDEX uq_user_roles_email_role_scope_null_active "
                "ON user_roles (user_email, role_id, scope)"
            ))
        print("Created unique index: uq_user_roles_email_role_scope_null_active")

    # Partial unique index on user_roles(user_email, role_id, scope, scope_id) WHERE scope_id IS NOT NULL AND is_active = true
    if 'uq_user_roles_email_role_scope_id_active' not in existing_user_roles_indexes:
        if dialect == 'postgresql':
            bind.execute(text(
                "CREATE UNIQUE INDEX uq_user_roles_email_role_scope_id_active "
                "ON user_roles (user_email, role_id, scope, scope_id) "
                "WHERE scope_id IS NOT NULL AND is_active = true"
            ))
        elif dialect == 'sqlite':
            bind.execute(text(
                "CREATE UNIQUE INDEX uq_user_roles_email_role_scope_id_active "
                "ON user_roles (user_email, role_id, scope, scope_id) "
                "WHERE scope_id IS NOT NULL AND is_active = 1"
            ))
        else:
            # Fallback: unique on all four columns without WHERE
            print(f"WARNING: Dialect '{dialect}' may not support partial indexes. Creating full unique index.")
            bind.execute(text(
                "CREATE UNIQUE INDEX uq_user_roles_email_role_scope_id_active "
                "ON user_roles (user_email, role_id, scope, scope_id)"
            ))
        print("Created unique index: uq_user_roles_email_role_scope_id_active")


def downgrade() -> None:
    """Downgrade schema - remove unique constraints."""
    bind = op.get_bind()
    inspector = inspect(bind)

    # Skip if tables don't exist
    existing_tables = inspector.get_table_names()
    if "roles" not in existing_tables or "user_roles" not in existing_tables:
        return

    # Drop the unique indexes if they exist
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('roles')]
    if 'uq_roles_name_scope_active' in existing_indexes:
        op.drop_index('uq_roles_name_scope_active', table_name='roles')
        print("Dropped unique index: uq_roles_name_scope_active")

    existing_user_roles_indexes = [idx['name'] for idx in inspector.get_indexes('user_roles')]
    if 'uq_user_roles_email_role_scope_null_active' in existing_user_roles_indexes:
        op.drop_index('uq_user_roles_email_role_scope_null_active', table_name='user_roles')
        print("Dropped unique index: uq_user_roles_email_role_scope_null_active")

    if 'uq_user_roles_email_role_scope_id_active' in existing_user_roles_indexes:
        op.drop_index('uq_user_roles_email_role_scope_id_active', table_name='user_roles')
        print("Dropped unique index: uq_user_roles_email_role_scope_id_active")

    # Note: We do NOT reactivate the deduped rows on downgrade
    # The soft-deleted duplicates remain inactive for audit purposes
