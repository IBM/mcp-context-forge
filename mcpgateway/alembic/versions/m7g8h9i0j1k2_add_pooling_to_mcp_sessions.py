# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/m7g8h9i0j1k2_add_pooling_to_mcp_sessions.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: IBM Bob

add_pooling_to_mcp_sessions

Revision ID: m7g8h9i0j1k2
Revises: l6f7g8h9i0j1
Create Date: 2025-12-02 12:10:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "m7g8h9i0j1k2"
down_revision: Union[str, Sequence[str], None] = "l6f7g8h9i0j1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add session pooling tracking fields to mcp_sessions table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("mcp_sessions"):
        print("Fresh database detected. Skipping migration.")
        return

    # Get existing columns
    columns = [col["name"] for col in inspector.get_columns("mcp_sessions")]

    # Add pooling tracking columns if they don't exist
    pooling_columns = {
        "pool_id": (sa.String(36), None, True),  # (type, default, nullable)
        "server_id": (sa.String(36), None, True),
        "is_pooled": (sa.Boolean(), False, False),
        "pool_acquired_at": (sa.DateTime(timezone=True), None, True),
        "pool_released_at": (sa.DateTime(timezone=True), None, True),
        "pool_reuse_count": (sa.Integer(), 0, False),
        "pool_last_error": (sa.Text(), None, True),
    }

    for col_name, (col_type, default_value, nullable) in pooling_columns.items():
        if col_name not in columns:
            try:
                if default_value is not None:
                    if isinstance(default_value, bool):
                        server_default = sa.text(str(default_value).lower())
                    else:
                        server_default = str(default_value)
                else:
                    server_default = None

                op.add_column(
                    "mcp_sessions",
                    sa.Column(col_name, col_type, nullable=nullable, server_default=server_default),
                )
                print(f"Added column {col_name} to mcp_sessions table")
            except Exception as e:
                print(f"Warning: Could not add column {col_name}: {e}")

    # Add foreign key constraints if they don't exist
    try:
        existing_fks = [fk["name"] for fk in inspector.get_foreign_keys("mcp_sessions")]
        
        if "fk_mcp_sessions_pool_id" not in existing_fks and "pool_id" in [col["name"] for col in inspector.get_columns("mcp_sessions")]:
            op.create_foreign_key(
                "fk_mcp_sessions_pool_id",
                "mcp_sessions",
                "session_pools",
                ["pool_id"],
                ["id"],
                ondelete="SET NULL"
            )
            print("Created foreign key constraint fk_mcp_sessions_pool_id")

        if "fk_mcp_sessions_server_id" not in existing_fks and "server_id" in [col["name"] for col in inspector.get_columns("mcp_sessions")]:
            op.create_foreign_key(
                "fk_mcp_sessions_server_id",
                "mcp_sessions",
                "servers",
                ["server_id"],
                ["id"],
                ondelete="SET NULL"
            )
            print("Created foreign key constraint fk_mcp_sessions_server_id")
    except Exception as e:
        print(f"Warning: Could not create foreign key constraints: {e}")

    # Create indexes for efficient queries
    try:
        existing_indexes = [idx["name"] for idx in inspector.get_indexes("mcp_sessions")]
        
        if "idx_mcp_sessions_pool_id" not in existing_indexes:
            op.create_index("idx_mcp_sessions_pool_id", "mcp_sessions", ["pool_id"])
            print("Created index idx_mcp_sessions_pool_id")
        
        if "idx_mcp_sessions_server_id" not in existing_indexes:
            op.create_index("idx_mcp_sessions_server_id", "mcp_sessions", ["server_id"])
            print("Created index idx_mcp_sessions_server_id")
        
        if "idx_mcp_sessions_is_pooled" not in existing_indexes:
            op.create_index("idx_mcp_sessions_is_pooled", "mcp_sessions", ["is_pooled"])
            print("Created index idx_mcp_sessions_is_pooled")
    except Exception as e:
        print(f"Warning: Could not create indexes: {e}")


def downgrade() -> None:
    """Downgrade schema - Remove session pooling fields from mcp_sessions table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("mcp_sessions"):
        return

    # Drop indexes first
    try:
        existing_indexes = [idx["name"] for idx in inspector.get_indexes("mcp_sessions")]
        
        for index_name in ["idx_mcp_sessions_is_pooled", "idx_mcp_sessions_server_id", "idx_mcp_sessions_pool_id"]:
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="mcp_sessions")
                print(f"Dropped index {index_name}")
    except Exception as e:
        print(f"Warning: Could not drop indexes: {e}")

    # Drop foreign key constraints
    try:
        existing_fks = [fk["name"] for fk in inspector.get_foreign_keys("mcp_sessions")]
        
        for fk_name in ["fk_mcp_sessions_server_id", "fk_mcp_sessions_pool_id"]:
            if fk_name in existing_fks:
                op.drop_constraint(fk_name, "mcp_sessions", type_="foreignkey")
                print(f"Dropped foreign key {fk_name}")
    except Exception as e:
        print(f"Warning: Could not drop foreign key constraints: {e}")

    # Get existing columns
    columns = [col["name"] for col in inspector.get_columns("mcp_sessions")]

    # Remove pooling columns if they exist
    pooling_columns = [
        "pool_last_error",
        "pool_reuse_count",
        "pool_released_at",
        "pool_acquired_at",
        "is_pooled",
        "server_id",
        "pool_id",
    ]

    for col_name in pooling_columns:
        if col_name in columns:
            try:
                op.drop_column("mcp_sessions", col_name)
                print(f"Dropped column {col_name} from mcp_sessions table")
            except Exception as e:
                print(f"Warning: Could not drop column {col_name}: {e}")

# Made with Bob
