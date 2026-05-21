# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/64acf94cb7f2_cleanup_inactive_duplicate_user_roles.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

cleanup_inactive_duplicate_user_roles

Revision ID: 64acf94cb7f2
Revises: a3c38b6c2437
Create Date: 2026-03-13 10:07:53.737721

Remove inactive duplicate user_role rows where an active row exists for the
same (user_email, role_id, scope, scope_id) tuple. Fixes #3505.

This migration is idempotent and safe to run multiple times.
Handles both SQLite and PostgreSQL with dialect-specific SQL.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "64acf94cb7f2"
down_revision: Union[str, Sequence[str], None] = "a3c38b6c2437"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove inactive duplicates where active row exists.

    Handles both SQLite and PostgreSQL with dialect-specific SQL.
    Validates data integrity before cleanup and logs actions.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "user_roles" not in inspector.get_table_names():
        return

    # Check if cleanup already ran (idempotency check)
    result = bind.execute(text("""
        SELECT COUNT(*) as duplicate_count
        FROM user_roles ur1
        WHERE ur1.is_active = FALSE
        AND EXISTS (
            SELECT 1 FROM user_roles ur2
            WHERE ur2.user_email = ur1.user_email
            AND ur2.role_id = ur1.role_id
            AND ur2.scope = ur1.scope
            AND (ur2.scope_id = ur1.scope_id OR (ur2.scope_id IS NULL AND ur1.scope_id IS NULL))
            AND ur2.is_active = TRUE
        )
    """))
    duplicate_count = result.scalar()

    if duplicate_count == 0:
        # Already clean or no duplicates exist
        return

    print(f"Found {duplicate_count} inactive duplicate user_role rows to clean up")

    # Dialect-specific cleanup
    if bind.dialect.name == "postgresql":
        # PostgreSQL supports DELETE with EXISTS efficiently
        bind.execute(text("""
            DELETE FROM user_roles
            WHERE is_active = FALSE
            AND EXISTS (
                SELECT 1 FROM user_roles active
                WHERE active.user_email = user_roles.user_email
                AND active.role_id = user_roles.role_id
                AND active.scope = user_roles.scope
                AND (active.scope_id = user_roles.scope_id OR (active.scope_id IS NULL AND user_roles.scope_id IS NULL))
                AND active.is_active = TRUE
            )
        """))

        # No unique index added here: assign_role_to_user() allows re-assignment
        # when the current row is expired but still active (is_active=True,
        # expires_at in the past), which creates a second active row for the
        # same tuple. A partial unique index on is_active=TRUE would block that
        # legitimate flow with an IntegrityError. The application-level is_active
        # filter in get_user_role_assignment() is the primary defense.

    elif bind.dialect.name == "sqlite":
        # SQLite: Use subquery approach (more compatible)
        bind.execute(text("""
            DELETE FROM user_roles
            WHERE id IN (
                SELECT ur1.id
                FROM user_roles ur1
                WHERE ur1.is_active = 0
                AND EXISTS (
                    SELECT 1 FROM user_roles ur2
                    WHERE ur2.user_email = ur1.user_email
                    AND ur2.role_id = ur1.role_id
                    AND ur2.scope = ur1.scope
                    AND (ur2.scope_id = ur1.scope_id OR (ur2.scope_id IS NULL AND ur1.scope_id IS NULL))
                    AND ur2.is_active = 1
                )
            )
        """))
        print("Cleanup complete using SQLite-compatible SQL")

    else:
        # Other databases: use conservative approach
        bind.execute(text("""
            DELETE FROM user_roles
            WHERE id IN (
                SELECT ur1.id
                FROM user_roles ur1
                WHERE ur1.is_active = FALSE
                AND EXISTS (
                    SELECT 1 FROM user_roles ur2
                    WHERE ur2.user_email = ur1.user_email
                    AND ur2.role_id = ur1.role_id
                    AND ur2.scope = ur1.scope
                    AND (ur2.scope_id = ur1.scope_id OR (ur2.scope_id IS NULL AND ur1.scope_id IS NULL))
                    AND ur2.is_active = TRUE
                )
            )
        """))
        print(f"Cleanup complete using conservative approach for {bind.dialect.name}")

    print(f"Cleanup complete: removed {duplicate_count} inactive duplicate rows")


def downgrade() -> None:
    """No downgrade possible - deleted rows cannot be recovered.

    This is acceptable because:
    1. Deleted rows were inactive (soft-deleted) duplicates
    2. Active assignments remain intact
    3. No data loss of functional role assignments
    """
