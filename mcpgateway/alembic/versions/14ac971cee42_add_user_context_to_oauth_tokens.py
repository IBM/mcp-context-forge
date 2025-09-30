# -*- coding: utf-8 -*-
"""add_user_context_to_oauth_tokens

Revision ID: 14ac971cee42
Revises: e182847d89e6
Create Date: 2025-09-19 23:18:00.710347

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "14ac971cee42"
down_revision: Union[str, Sequence[str], None] = "e182847d89e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add app_user_email to oauth_tokens for user-specific token handling."""

    # Check if oauth_tokens table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "oauth_tokens" not in inspector.get_table_names():
        # Table doesn't exist, nothing to upgrade
        print("oauth_tokens table not found. Skipping migration.")
        return

    # First, delete all existing OAuth tokens as they lack user context
    # This is a security fix - existing tokens are vulnerable
    # Check if oauth_tokens table has data and delete it
    # We need to be careful not to cause transaction aborts
    has_tokens = False
    token_count = 0

    # Check if we can access the table
    columns = inspector.get_columns("oauth_tokens")
    if columns:  # Table exists and is accessible
        result = conn.execute(sa.text("SELECT COUNT(*) FROM oauth_tokens")).scalar()
        token_count = result if result else 0
        has_tokens = token_count > 0

    if has_tokens:
        op.execute("DELETE FROM oauth_tokens")
        print(f"Deleted {token_count} existing OAuth tokens (security fix)")
    elif token_count == 0:
        print("No existing OAuth tokens to delete")

    # Get database dialect for engine-specific handling
    dialect_name = conn.dialect.name.lower()

    # Add app_user_email column - handle nullable constraint differently per database
    if dialect_name == "sqlite":
        # SQLite doesn't support adding NOT NULL columns to existing tables with data
        # even though we deleted all rows, we need to handle this carefully
        with op.batch_alter_table("oauth_tokens") as batch_op:
            batch_op.add_column(sa.Column("app_user_email", sa.String(255), nullable=False, server_default=""))
            # Remove the server default after adding the column
            batch_op.alter_column("app_user_email", server_default=None)
    else:
        # PostgreSQL and MySQL can handle adding NOT NULL columns to empty tables
        op.add_column("oauth_tokens", sa.Column("app_user_email", sa.String(255), nullable=False))

    # Add foreign key constraint to ensure referential integrity
    # SQLite with batch mode will handle foreign keys properly
    if dialect_name == "sqlite":
        with op.batch_alter_table("oauth_tokens") as batch_op:
            batch_op.create_foreign_key("fk_oauth_app_user", "email_users", ["app_user_email"], ["email"], ondelete="CASCADE")
    else:
        op.create_foreign_key("fk_oauth_app_user", "oauth_tokens", "email_users", ["app_user_email"], ["email"], ondelete="CASCADE")

    # Create unique index to ensure one token per user per gateway
    op.create_index("idx_oauth_gateway_user", "oauth_tokens", ["gateway_id", "app_user_email"], unique=True)

    # Drop the old index if it exists (gateway_id only)
    # Check if index exists before trying to drop it to avoid transaction issues
    index_exists = False
    if dialect_name == "postgresql":
        result = conn.execute(sa.text("SELECT 1 FROM pg_indexes WHERE tablename = 'oauth_tokens' AND indexname = 'idx_oauth_tokens_gateway_user'")).fetchone()
        index_exists = result is not None
    elif dialect_name == "mysql":
        result = conn.execute(
            sa.text("SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'oauth_tokens' AND index_name = 'idx_oauth_tokens_gateway_user'")
        ).fetchone()
        index_exists = result is not None
    elif dialect_name == "sqlite":
        result = conn.execute(sa.text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_oauth_tokens_gateway_user'")).fetchone()
        index_exists = result is not None

    if index_exists:
        op.drop_index("idx_oauth_tokens_gateway_user", "oauth_tokens")
        print("Dropped old index idx_oauth_tokens_gateway_user")
    else:
        print("Old index idx_oauth_tokens_gateway_user not found (expected for new installations)")

    # Create oauth_states table for CSRF protection in multi-worker deployments
    op.create_table(
        "oauth_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("gateway_id", sa.String(36), sa.ForeignKey("gateways.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(500), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create index for efficient lookups
    op.create_index("idx_oauth_state_lookup", "oauth_states", ["gateway_id", "state"])


def downgrade() -> None:
    """Remove user context from oauth_tokens and oauth_states table."""

    # Drop oauth_states table first
    op.drop_index("idx_oauth_state_lookup", "oauth_states")
    op.drop_table("oauth_states")

    # Check if oauth_tokens table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "oauth_tokens" not in inspector.get_table_names():
        # Table doesn't exist, nothing to downgrade
        print("oauth_tokens table not found. Skipping downgrade.")
        return

    # Get database dialect for engine-specific handling
    dialect_name = conn.dialect.name.lower()

    # Drop the unique index if it exists
    # Check if index exists before trying to drop it to avoid transaction issues
    index_exists = False
    if dialect_name == "postgresql":
        result = conn.execute(sa.text("SELECT 1 FROM pg_indexes WHERE tablename = 'oauth_tokens' AND indexname = 'idx_oauth_gateway_user'")).fetchone()
        index_exists = result is not None
    elif dialect_name == "mysql":
        result = conn.execute(
            sa.text("SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'oauth_tokens' AND index_name = 'idx_oauth_gateway_user'")
        ).fetchone()
        index_exists = result is not None
    elif dialect_name == "sqlite":
        result = conn.execute(sa.text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_oauth_gateway_user'")).fetchone()
        index_exists = result is not None

    if index_exists:
        op.drop_index("idx_oauth_gateway_user", "oauth_tokens")
        print("Dropped index idx_oauth_gateway_user")
    else:
        print("Index idx_oauth_gateway_user not found (expected if upgrade was incomplete)")

    if dialect_name == "sqlite":
        # SQLite requires batch mode for dropping foreign keys and columns
        with op.batch_alter_table("oauth_tokens") as batch_op:
            # SQLite doesn't have explicit foreign key constraints to drop in batch mode
            # The foreign key will be removed when we drop the column
            batch_op.drop_column("app_user_email")
    else:
        # Drop the foreign key constraint for PostgreSQL and MySQL
        op.drop_constraint("fk_oauth_app_user", "oauth_tokens", type_="foreignkey")

        # Drop the column
        op.drop_column("oauth_tokens", "app_user_email")

    # Note: We don't restore deleted tokens as they were insecure
