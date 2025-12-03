# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/n8h9i0j1k2l3_create_pool_strategy_metrics_table.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

create_pool_strategy_metrics_table

Revision ID: n8h9i0j1k2l3
Revises: m7g8h9i0j1k2
Create Date: 2025-12-02 12:15:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "n8h9i0j1k2l3"
down_revision: Union[str, Sequence[str], None] = "m7g8h9i0j1k2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Create pool_strategy_metrics table for tracking pool performance."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if table already exists
    if inspector.has_table("pool_strategy_metrics"):
        print("Table pool_strategy_metrics already exists. Skipping creation.")
        return

    # Create pool_strategy_metrics table
    op.create_table(
        "pool_strategy_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("pool_id", sa.String(36), sa.ForeignKey("session_pools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("response_time", sa.Float(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("session_reused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("wait_time", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    # Create composite index for efficient time-based queries
    op.create_index(
        "idx_pool_strategy_timestamp",
        "pool_strategy_metrics",
        ["pool_id", "strategy", "timestamp"]
    )

    # Create additional indexes for common query patterns
    op.create_index("idx_pool_strategy_metrics_pool_id", "pool_strategy_metrics", ["pool_id"])
    op.create_index("idx_pool_strategy_metrics_strategy", "pool_strategy_metrics", ["strategy"])
    op.create_index("idx_pool_strategy_metrics_success", "pool_strategy_metrics", ["success"])
    op.create_index("idx_pool_strategy_metrics_timestamp", "pool_strategy_metrics", ["timestamp"])

    print("Created pool_strategy_metrics table with indexes")


def downgrade() -> None:
    """Downgrade schema - Drop pool_strategy_metrics table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("pool_strategy_metrics"):
        print("Table pool_strategy_metrics does not exist. Skipping drop.")
        return

    # Drop indexes first
    try:
        existing_indexes = [idx["name"] for idx in inspector.get_indexes("pool_strategy_metrics")]
        
        index_names = [
            "idx_pool_strategy_metrics_timestamp",
            "idx_pool_strategy_metrics_success",
            "idx_pool_strategy_metrics_strategy",
            "idx_pool_strategy_metrics_pool_id",
            "idx_pool_strategy_timestamp",
        ]
        
        for index_name in index_names:
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="pool_strategy_metrics")
                print(f"Dropped index {index_name}")
    except Exception as e:
        print(f"Warning: Could not drop indexes: {e}")

    # Drop table
    op.drop_table("pool_strategy_metrics")
    print("Dropped pool_strategy_metrics table")

# Made with Bob
