# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/add_oauth_tokens_table.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add oauth tokens table

Revision ID: add_oauth_tokens_table
Revises: f8c9d3e2a1b4
Create Date: 2024-12-20 11:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "add_oauth_tokens_table"
down_revision: Union[str, Sequence[str], None] = "f8c9d3e2a1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add oauth_tokens table for storing OAuth access and refresh tokens."""
    # Check if we're dealing with a fresh database
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if "gateways" not in tables:
        print("Fresh database detected. Skipping migration.")
        return

    # Create oauth_tokens table
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("gateway_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("access_token", sa.Text, nullable=False),
        sa.Column("refresh_token", sa.Text, nullable=True),
        sa.Column("token_type", sa.String(50), nullable=True, default="Bearer"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        # Foreign key constraint
        sa.ForeignKeyConstraint(["gateway_id"], ["gateways.id"], ondelete="CASCADE"),
        # Unique constraint
        sa.UniqueConstraint("gateway_id", "user_id", name="unique_gateway_user"),
    )

    # Create indexes for efficient token lookup
    op.create_index("idx_oauth_tokens_gateway_user", "oauth_tokens", ["gateway_id", "user_id"])
    op.create_index("idx_oauth_tokens_expires", "oauth_tokens", ["expires_at"])

    print("Successfully created oauth_tokens table with indexes.")


def downgrade() -> None:
    """Remove oauth_tokens table."""
    # Check if we're dealing with a fresh database
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if "oauth_tokens" not in tables:
        print("oauth_tokens table not found. Skipping migration.")
        return

    # Remove oauth_tokens table
    op.drop_table("oauth_tokens")

    print("Successfully removed oauth_tokens table.")
