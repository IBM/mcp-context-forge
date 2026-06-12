# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/7ab59991e017_fix_oauth_tokens_unique_constraint.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan-Marius Catanus

fix_oauth_tokens_unique_constraint

Fixes bug #5191: oauth_tokens unique constraint blocks multi-user OAuth for DCR clients

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
Revises: 0a089912b5f0
Create Date: 2026-06-12 10:18:32.623237
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7ab59991e017"
down_revision: Union[str, Sequence[str], None] = "0a089912b5f0"
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
    old_constraint_exists = False
    if dialect_name == "postgresql":
        result = conn.execute(sa.text("SELECT 1 FROM pg_constraint WHERE conname = 'unique_gateway_user' " "AND conrelid = 'oauth_tokens'::regclass")).fetchone()
        old_constraint_exists = result is not None
    elif dialect_name == "sqlite":
        # SQLite stores constraints in the table definition
        # We need to check the schema
        result = conn.execute(sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name='oauth_tokens'")).fetchone()
        if result:
            table_sql = result[0]
            old_constraint_exists = "unique_gateway_user" in table_sql.lower()

    # For SQLite and PostgreSQL, handle constraint migration differently
    if dialect_name == "sqlite":
        # SQLite requires table recreation to change constraints
        # Alembic's batch mode doesn't always properly handle constraint changes,
        # so we use manual table recreation for reliability
        if old_constraint_exists:
            print("SQLite detected: Recreating table to fix constraints...")

            # Step 1: Rename old table
            op.rename_table("oauth_tokens", "oauth_tokens_old")

            # Step 2: Create new table with correct constraint
            op.create_table(
                "oauth_tokens",
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("gateway_id", sa.String(36), nullable=False),
                sa.Column("user_id", sa.String(255), nullable=False),
                sa.Column("app_user_email", sa.String(255), nullable=False),
                sa.Column("access_token", sa.Text, nullable=False),
                sa.Column("refresh_token", sa.Text, nullable=True),
                sa.Column("token_type", sa.String(50), server_default="Bearer"),
                sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("scopes", sa.JSON, nullable=True),
                sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
                sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
                sa.ForeignKeyConstraint(["gateway_id"], ["gateways.id"], ondelete="CASCADE"),
                sa.ForeignKeyConstraint(["app_user_email"], ["email_users.email"], ondelete="CASCADE"),
                sa.UniqueConstraint("gateway_id", "app_user_email", name="uq_oauth_gateway_user"),
            )

            # Step 3: Copy data from old table
            conn.execute(sa.text("INSERT INTO oauth_tokens SELECT * FROM oauth_tokens_old"))

            # Step 4: Drop old table
            op.drop_table("oauth_tokens_old")

            # Step 5: Recreate index (non-unique since constraint handles uniqueness)
            op.create_index("idx_oauth_gateway_user", "oauth_tokens", ["gateway_id", "app_user_email"], unique=False)

            print("✓ Dropped 'unique_gateway_user' and created 'uq_oauth_gateway_user'")
        else:
            # Old constraint doesn't exist, just check if we need to create the new one
            result = conn.execute(sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name='oauth_tokens'")).fetchone()
            new_constraint_exists = False
            if result:
                table_sql = result[0]
                new_constraint_exists = "uq_oauth_gateway_user" in table_sql.lower()

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
        result = conn.execute(sa.text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_oauth_gateway_user' " "AND conrelid = 'oauth_tokens'::regclass")).fetchone()
        new_constraint_exists = result is not None

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
    new_constraint_exists = False
    if dialect_name == "postgresql":
        result = conn.execute(sa.text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_oauth_gateway_user' " "AND conrelid = 'oauth_tokens'::regclass")).fetchone()
        new_constraint_exists = result is not None
    elif dialect_name == "sqlite":
        result = conn.execute(sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name='oauth_tokens'")).fetchone()
        if result:
            table_sql = result[0]
            new_constraint_exists = "uq_oauth_gateway_user" in table_sql.lower()

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
    old_constraint_exists = False
    if dialect_name == "postgresql":
        result = conn.execute(sa.text("SELECT 1 FROM pg_constraint WHERE conname = 'unique_gateway_user' " "AND conrelid = 'oauth_tokens'::regclass")).fetchone()
        old_constraint_exists = result is not None
    elif dialect_name == "sqlite":
        result = conn.execute(sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name='oauth_tokens'")).fetchone()
        if result:
            table_sql = result[0]
            old_constraint_exists = "unique_gateway_user" in table_sql.lower()

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
