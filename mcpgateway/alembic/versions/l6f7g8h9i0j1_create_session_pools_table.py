# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/l6f7g8h9i0j1_create_session_pools_table.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

create_session_pools_table

Revision ID: l6f7g8h9i0j1
Revises: k5e6f7g8h9i0
Create Date: 2025-12-02 12:05:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "l6f7g8h9i0j1"
down_revision: Union[str, Sequence[str], None] = "k5e6f7g8h9i0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Create session_pools table for managing session pools."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if table already exists
    if inspector.has_table("session_pools"):
        print("Table session_pools already exists. Skipping creation.")
        return

    # Create session_pools table with unique constraint defined inline
    op.create_table(
        "session_pools",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("server_id", sa.String(36), sa.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False, server_default="round_robin"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("min_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_size", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("timeout", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("active_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_acquisitions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_releases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_timeouts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("server_id", "name", name="uq_pool_server_name"),
    )

    # Create indexes for efficient queries
    op.create_index("idx_session_pools_server_id", "session_pools", ["server_id"])
    op.create_index("idx_session_pools_is_active", "session_pools", ["is_active"])

    print("Created session_pools table with indexes and constraints")


def downgrade() -> None:
    """Downgrade schema - Drop session_pools table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("session_pools"):
        print("Table session_pools does not exist. Skipping drop.")
        return

    # Drop indexes first
    try:
        op.drop_index("idx_session_pools_is_active", table_name="session_pools")
        op.drop_index("idx_session_pools_server_id", table_name="session_pools")
    except Exception as e:
        print(f"Warning: Could not drop indexes: {e}")

    # Drop table (unique constraint will be dropped automatically with table)
    op.drop_table("session_pools")
    print("Dropped session_pools table")


# Made with Bob
