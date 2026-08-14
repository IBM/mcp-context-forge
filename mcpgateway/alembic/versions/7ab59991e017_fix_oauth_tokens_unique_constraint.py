# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/7ab59991e017_fix_oauth_tokens_unique_constraint.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

fix_oauth_tokens_unique_constraint

The migration 14ac971cee42 added app_user_email column and created a unique index
idx_oauth_gateway_user on (gateway_id, app_user_email), but failed to drop the
original UniqueConstraint 'unique_gateway_user' on (gateway_id, user_id).

This causes multi-user OAuth flows to fail because the old constraint prevents
multiple ContextForge users from storing tokens for the same OAuth provider user.

This migration:
1. Drops the old UniqueConstraint 'unique_gateway_user' on (gateway_id, user_id)
2. Creates the new UniqueConstraint 'uq_oauth_gateway_user' on (gateway_id, app_user_email)
3. Drops redundant idx_oauth_gateway_user (uniqueness enforced by constraint)

    Revision ID: 7ab59991e017
    Revises: c9f8e7d6a4b3
    Create Date: 2026-06-12 10:18:32.623237
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7ab59991e017"
down_revision: Union[str, Sequence[str], None] = "c9f8e7d6a4b3" #pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix oauth_tokens unique constraint to allow multi-user OAuth."""

    # Check if oauth_tokens table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "oauth_tokens" not in inspector.get_table_names():
        # Table doesn't exist, nothing to upgrade
        print("oauth_tokens table not found. Skipping migration.")
        return

    # Get database dialect for engine-specific handling
    dialect_name = conn.dialect.name.lower()

    # Check if old constraint exists before trying to drop it
    inspector = sa.inspect(conn)  # Refresh inspector for current state
    unique_constraints = inspector.get_unique_constraints("oauth_tokens")
    old_constraint_exists = any(uc.get("name") == "unique_gateway_user" for uc in unique_constraints)
    lookup_index_exists = any(index["name"] == "idx_oauth_gateway_user" for index in inspector.get_indexes("oauth_tokens"))

    # For SQLite and PostgreSQL, handle constraint migration differently
    if dialect_name == "sqlite":
        # SQLite requires table recreation to change constraints
        # Use batch_alter_table which handles this automatically
        if old_constraint_exists:
            print("SQLite detected: Using batch mode to fix constraints...")
            with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
                batch_op.drop_constraint("unique_gateway_user", type_="unique")
                if lookup_index_exists:
                    batch_op.drop_index("idx_oauth_gateway_user")
                batch_op.create_unique_constraint("uq_oauth_gateway_user", ["gateway_id", "app_user_email"])
            print("✓ Dropped 'unique_gateway_user' and created 'uq_oauth_gateway_user'")
        else:
            # Old constraint doesn't exist, just check if we need to create the new one
            inspector = sa.inspect(conn)  # Refresh inspector after batch operation
            unique_constraints = inspector.get_unique_constraints("oauth_tokens")
            new_constraint_exists = any(uc.get("name") == "uq_oauth_gateway_user" for uc in unique_constraints)

            if not new_constraint_exists:
                with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
                    if lookup_index_exists:
                        batch_op.drop_index("idx_oauth_gateway_user")
                    batch_op.create_unique_constraint("uq_oauth_gateway_user", ["gateway_id", "app_user_email"])
                print("✓ Created new UniqueConstraint 'uq_oauth_gateway_user'")
            elif lookup_index_exists:
                op.drop_index("idx_oauth_gateway_user", "oauth_tokens")
                print("✓ Dropped redundant unique index 'idx_oauth_gateway_user'")
            else:
                print("New UniqueConstraint 'uq_oauth_gateway_user' already exists")
    else:
        # PostgreSQL can drop and create constraints independently
        if old_constraint_exists:
            op.drop_constraint("unique_gateway_user", "oauth_tokens", type_="unique")
            print("✓ Dropped old UniqueConstraint 'unique_gateway_user' on (gateway_id, user_id)")
        else:
            print("Old UniqueConstraint 'unique_gateway_user' not found (already dropped or never existed)")

        # Check if new constraint already exists
        inspector = sa.inspect(conn)  # Refresh inspector after constraint drop
        unique_constraints = inspector.get_unique_constraints("oauth_tokens")
        new_constraint_exists = any(uc.get("name") == "uq_oauth_gateway_user" for uc in unique_constraints)

        if lookup_index_exists:
            op.drop_index("idx_oauth_gateway_user", "oauth_tokens")
            print("✓ Dropped redundant unique index 'idx_oauth_gateway_user'")

        if not new_constraint_exists:
            op.create_unique_constraint("uq_oauth_gateway_user", "oauth_tokens", ["gateway_id", "app_user_email"])
            print("✓ Created new UniqueConstraint 'uq_oauth_gateway_user' on (gateway_id, app_user_email)")
        else:
            print("New UniqueConstraint 'uq_oauth_gateway_user' already exists")


def downgrade() -> None:
    """Restore original unique constraint on (gateway_id, user_id).

    Raises:
        RuntimeError: If duplicate (gateway_id, user_id) pairs exist that would
                     violate the restored constraint. Operators must manually
                     resolve duplicates before downgrading.
    """

    # Check if oauth_tokens table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "oauth_tokens" not in inspector.get_table_names():
        # Table doesn't exist, nothing to downgrade
        print("oauth_tokens table not found. Skipping downgrade.")
        return

    # Get database dialect for engine-specific handling
    dialect_name = conn.dialect.name.lower()

    # Check if new constraint exists before trying to drop it
    inspector = sa.inspect(conn)  # Refresh inspector for current state
    unique_constraints = inspector.get_unique_constraints("oauth_tokens")
    new_constraint_exists = any(uc.get("name") == "uq_oauth_gateway_user" for uc in unique_constraints)

    old_constraint_exists = any(uc.get("name") == "unique_gateway_user" for uc in unique_constraints)
    lookup_index_exists = any(index["name"] == "idx_oauth_gateway_user" for index in inspector.get_indexes("oauth_tokens"))

    # Validate that restoring the legacy constraint is possible before any DDL.
    if not old_constraint_exists:
        duplicate_check = conn.execute(
            sa.text(
                """
                SELECT gateway_id, user_id, COUNT(*) as cnt
                FROM oauth_tokens
                GROUP BY gateway_id, user_id
                HAVING COUNT(*) > 1
                """
            )
        ).fetchall()

        if duplicate_check:
            duplicate_details = "\n".join(
                [f"  - gateway_id={gw_id}, user_id={u_id}, count={cnt}" for gw_id, u_id, cnt in duplicate_check[:5]]  # Show first 5
            )
            if len(duplicate_check) > 5:
                duplicate_details += f"\n  ... and {len(duplicate_check) - 5} more"

            raise RuntimeError(
                f"Cannot downgrade migration 7ab59991e017: "  # nosec B608 - human-readable error text, not an executed SQL statement
                f"{len(duplicate_check)} duplicate (gateway_id, user_id) pairs exist.\n\n"
                f"This is expected after the upgrade enabled multi-user OAuth support. "
                f"Multiple ContextForge users can now store tokens for the same OAuth provider user.\n\n"
                f"Duplicate pairs found:\n{duplicate_details}\n\n"
                f"To downgrade, you must manually resolve these duplicates first.\n"
                f"See docs/docs/manage/dcr.md for resolution steps:\n"
                f"  1. Identify duplicates: SELECT gateway_id, user_id, COUNT(*) FROM oauth_tokens GROUP BY gateway_id, user_id HAVING COUNT(*) > 1\n"
                f"  2. Choose resolution strategy (keep newest, keep specific user, or delete all)\n"
                f"  3. Verify no duplicates remain\n"
                f"  4. Retry downgrade"
            )

    # Drop the new UniqueConstraint if it exists
    if new_constraint_exists:
        if dialect_name == "sqlite":
            with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
                batch_op.drop_constraint("uq_oauth_gateway_user", type_="unique")
            print("Dropped UniqueConstraint 'uq_oauth_gateway_user' on (gateway_id, app_user_email)")
        else:
            op.drop_constraint("uq_oauth_gateway_user", "oauth_tokens", type_="unique")
            print("Dropped UniqueConstraint 'uq_oauth_gateway_user' on (gateway_id, app_user_email)")
    else:
        print("UniqueConstraint 'uq_oauth_gateway_user' not found")

    # Restore the old UniqueConstraint if it doesn't exist
    if not old_constraint_exists:
        if dialect_name == "sqlite":
            with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
                batch_op.create_unique_constraint("unique_gateway_user", ["gateway_id", "user_id"])
            print("Restored old UniqueConstraint 'unique_gateway_user' on (gateway_id, user_id)")
        else:
            op.create_unique_constraint("unique_gateway_user", "oauth_tokens", ["gateway_id", "user_id"])
            print("Restored old UniqueConstraint 'unique_gateway_user' on (gateway_id, user_id)")
    else:
        print("Old UniqueConstraint 'unique_gateway_user' already exists")

    if not lookup_index_exists:
        op.create_index("idx_oauth_gateway_user", "oauth_tokens", ["gateway_id", "app_user_email"], unique=True)
        print("Restored unique index 'idx_oauth_gateway_user' on (gateway_id, app_user_email)")
