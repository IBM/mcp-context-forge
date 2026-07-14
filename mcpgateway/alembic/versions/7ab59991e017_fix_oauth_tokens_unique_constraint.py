# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/7ab59991e017_fix_oauth_tokens_unique_constraint.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: mcp-contextforge-team

fix_oauth_tokens_unique_constraint

The migration 14ac971cee42 added app_user_email column and created a unique index
idx_oauth_gateway_user on (gateway_id, app_user_email), but failed to drop the
original UniqueConstraint 'unique_gateway_user' on (gateway_id, user_id).

This causes multi-user OAuth flows to fail because the old constraint prevents
multiple ContextForge users from storing tokens for the same OAuth provider user.

This migration:
1. Drops the old UniqueConstraint 'unique_gateway_user' on (gateway_id, user_id)
2. Creates the new UniqueConstraint 'uq_oauth_gateway_user' on (gateway_id, app_user_email)
3. Keeps idx_oauth_gateway_user as a regular index for query performance

    Revision ID: 7ab59991e017
    Revises: b6c7d8e9f0a1
    Create Date: 2026-06-12 10:18:32.623237"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7ab59991e017"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e9f0a1"
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

    # For SQLite and PostgreSQL, handle constraint migration differently
    if dialect_name == "sqlite":
        # SQLite requires table recreation to change constraints
        # Use batch_alter_table which handles this automatically
        if old_constraint_exists:
            print("SQLite detected: Using batch mode to fix constraints...")
            with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
                batch_op.drop_constraint("unique_gateway_user", type_="unique")
                batch_op.create_unique_constraint("uq_oauth_gateway_user", ["gateway_id", "app_user_email"])
            print("✓ Dropped 'unique_gateway_user' and created 'uq_oauth_gateway_user'")
        else:
            # Old constraint doesn't exist, just check if we need to create the new one
            inspector = sa.inspect(conn)  # Refresh inspector after batch operation
            unique_constraints = inspector.get_unique_constraints("oauth_tokens")
            new_constraint_exists = any(uc.get("name") == "uq_oauth_gateway_user" for uc in unique_constraints)

            if not new_constraint_exists:
                with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
                    batch_op.create_unique_constraint("uq_oauth_gateway_user", ["gateway_id", "app_user_email"])
                print("✓ Created new UniqueConstraint 'uq_oauth_gateway_user'")
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

        if not new_constraint_exists:
            op.create_unique_constraint("uq_oauth_gateway_user", "oauth_tokens", ["gateway_id", "app_user_email"])
            print("✓ Created new UniqueConstraint 'uq_oauth_gateway_user' on (gateway_id, app_user_email)")
        else:
            print("New UniqueConstraint 'uq_oauth_gateway_user' already exists")

    # Note: idx_oauth_gateway_user remains as a regular index for query performance
    # It was created in migration 14ac971cee42 as a unique index, but the constraint
    # provides the actual uniqueness enforcement


def downgrade() -> None:
    """Restore original unique constraint on (gateway_id, user_id)."""

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

    # Check if old constraint already exists
    inspector = sa.inspect(conn)  # Refresh inspector after constraint drop
    unique_constraints = inspector.get_unique_constraints("oauth_tokens")
    old_constraint_exists = any(uc.get("name") == "unique_gateway_user" for uc in unique_constraints)

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
