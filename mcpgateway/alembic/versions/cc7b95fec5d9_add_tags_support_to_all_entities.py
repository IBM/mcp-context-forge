# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/cc7b95fec5d9_add_tags_support_to_all_entities.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add_tags_support_to_all_entities

Revision ID: cc7b95fec5d9
Revises: e75490e949b1
Create Date: 2025-08-06 22:27:08.682814
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision: str = "cc7b95fec5d9"
down_revision: Union[str, Sequence[str], None] = "e75490e949b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add tags JSON column to all entity tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Define tables to add tags to
    tables = ["tools", "resources", "prompts", "servers", "gateways"]

    # Add tags column to each table if it doesn't exist
    for table_name in tables:
        if inspector.has_table(table_name):
            columns = [col["name"] for col in inspector.get_columns(table_name)]
            if "tags" not in columns:
                is_postgresql = bind.dialect.name == "postgresql"
                col_type = pg.JSONB() if is_postgresql else sa.JSON()
                default = sa.text("'[]'::jsonb") if is_postgresql else sa.text("'[]'")
                op.add_column(
                    table_name,
                    sa.Column("tags", col_type, nullable=True, server_default=default),
                )

    # Create safe B-tree indexes (avoid GIN to prevent transaction abortion)
    # GIN indexes can be added separately after migration completes successfully
    for table_name in tables:
        if inspector.has_table(table_name):
            index_name = f"idx_{table_name}_tags"
            try:
                existing_indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]
                if index_name not in existing_indexes:
                    # Create simple B-tree index that works on both PostgreSQL and SQLite
                    # This avoids PostgreSQL GIN operator class errors that abort transactions
                    op.create_index(index_name, table_name, ["tags"])
                    print(f"Created B-tree index {index_name} on {table_name}.tags")
            except Exception as e:
                print(f"Warning: Could not create index {index_name}: {e}")


def downgrade() -> None:
    """Downgrade schema - Remove tags columns from all entity tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Define tables to remove tags from
    tables = ["tools", "resources", "prompts", "servers", "gateways"]

    # Drop indexes first (if they exist)
    for table_name in tables:
        if inspector.has_table(table_name):
            index_name = f"idx_{table_name}_tags"
            try:
                existing_indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]
                if index_name in existing_indexes:
                    op.drop_index(index_name, table_name=table_name)
            except Exception as e:
                print(f"Warning: Could not drop index {index_name}: {e}")

    # Drop tags columns (if they exist)
    for table_name in reversed(tables):  # Reverse order for safety
        if inspector.has_table(table_name):
            columns = [col["name"] for col in inspector.get_columns(table_name)]
            if "tags" in columns:
                try:
                    op.drop_column(table_name, "tags")
                except Exception as e:
                    print(f"Warning: Could not drop column tags from {table_name}: {e}")
