# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/k5e6f7g8h9i0_add_session_pooling_to_servers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: IBM Bob

add_session_pooling_to_servers

Revision ID: k5e6f7g8h9i0
Revises: j4d5e6f7g8h9
Create Date: 2025-12-02 12:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "k5e6f7g8h9i0"
down_revision: Union[str, Sequence[str], None] = "9e028ecf59c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add session pooling configuration fields to servers table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("servers"):
        print("Fresh database detected. Skipping migration.")
        return

    # Get existing columns
    columns = [col["name"] for col in inspector.get_columns("servers")]

    # Add pooling configuration columns if they don't exist
    pooling_columns = {
        "pool_enabled": (sa.Boolean(), False),
        "pool_size": (sa.Integer(), 5),
        "pool_strategy": (sa.String(50), "round_robin"),
        "pool_min_size": (sa.Integer(), 1),
        "pool_max_size": (sa.Integer(), 10),
        "pool_timeout": (sa.Integer(), 30),
        "pool_recycle": (sa.Integer(), 3600),
        "pool_pre_ping": (sa.Boolean(), True),
        "pool_auto_adjust": (sa.Boolean(), False),
        "pool_response_threshold": (sa.Float(), 2.0),
    }

    for col_name, (col_type, default_value) in pooling_columns.items():
        if col_name not in columns:
            try:
                op.add_column(
                    "servers",
                    sa.Column(col_name, col_type, nullable=False, server_default=str(default_value) if not isinstance(default_value, bool) else sa.text(str(default_value).lower())),
                )
                print(f"Added column {col_name} to servers table")
            except Exception as e:
                print(f"Warning: Could not add column {col_name}: {e}")


def downgrade() -> None:
    """Downgrade schema - Remove session pooling fields from servers table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("servers"):
        return

    # Get existing columns
    columns = [col["name"] for col in inspector.get_columns("servers")]

    # Remove pooling columns if they exist
    pooling_columns = [
        "pool_enabled",
        "pool_size",
        "pool_strategy",
        "pool_min_size",
        "pool_max_size",
        "pool_timeout",
        "pool_recycle",
        "pool_pre_ping",
        "pool_auto_adjust",
        "pool_response_threshold",
    ]

    for col_name in reversed(pooling_columns):
        if col_name in columns:
            try:
                op.drop_column("servers", col_name)
                print(f"Dropped column {col_name} from servers table")
            except Exception as e:
                print(f"Warning: Could not drop column {col_name}: {e}")

# Made with Bob
