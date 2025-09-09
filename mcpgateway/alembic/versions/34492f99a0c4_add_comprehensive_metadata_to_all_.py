# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/34492f99a0c4_add_comprehensive_metadata_to_all_.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add_comprehensive_metadata_to_all_entities

Revision ID: 34492f99a0c4
Revises: eb17fd368f9d
Create Date: 2025-08-18 08:06:17.141169
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "34492f99a0c4"
down_revision: Union[str, Sequence[str], None] = "eb17fd368f9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add comprehensive metadata columns to all entity tables for audit tracking."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping metadata migration.")
        return

    tables = ["tools", "resources", "prompts", "servers", "gateways"]

    # Define metadata columns to add
    metadata_columns = [
        ("created_by", sa.String(255), True),
        ("created_from_ip", sa.String(45), True),
        ("created_via", sa.String(100), True),
        ("created_user_agent", sa.Text(), True),
        ("modified_by", sa.String(255), True),
        ("modified_from_ip", sa.String(45), True),
        ("modified_via", sa.String(100), True),
        ("modified_user_agent", sa.Text(), True),
        ("import_batch_id", sa.String(36), True),
        ("federation_source", sa.String(255), True),
        ("version", sa.Integer(), False, "1"),  # Not nullable, with default
    ]

    # Add columns to each table if they don't exist
    for table in tables:
        if inspector.has_table(table):
            columns = [col["name"] for col in inspector.get_columns(table)]

            for col_name, col_type, nullable, *default in metadata_columns:
                if col_name not in columns:
                    try:
                        if default:
                            op.add_column(table, sa.Column(col_name, col_type, nullable=nullable, server_default=default[0]))
                        else:
                            op.add_column(table, sa.Column(col_name, col_type, nullable=nullable))
                        print(f"Added column {col_name} to {table}")
                    except Exception as e:
                        print(f"Warning: Could not add column {col_name} to {table}: {e}")

    # Create indexes for query performance (safe B-tree indexes)
    # Note: modified_at column doesn't exist in schema, so we skip it
    index_definitions = [
        ("created_by", ["created_by"]),
        ("created_at", ["created_at"]),
        ("created_via", ["created_via"]),
    ]

    for table in tables:
        if inspector.has_table(table):
            try:
                existing_indexes = [idx["name"] for idx in inspector.get_indexes(table)]
            except Exception as e:
                print(f"Warning: Could not get indexes for {table}: {e}")
                continue

            for index_suffix, columns in index_definitions:
                index_name = f"idx_{table}_{index_suffix}"
                if index_name not in existing_indexes:
                    # Check if the column exists before creating index
                    table_columns = [col["name"] for col in inspector.get_columns(table)]
                    if all(col in table_columns for col in columns):
                        try:
                            op.create_index(index_name, table, columns)
                            print(f"Created index {index_name}")
                        except Exception as e:
                            print(f"Warning: Could not create index {index_name}: {e}")
                    else:
                        print(f"Skipping index {index_name} - required columns {columns} not found in {table}")


def downgrade() -> None:
    """Remove comprehensive metadata columns from all entity tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = ["tools", "resources", "prompts", "servers", "gateways"]

    # Index names to drop (modified_at doesn't exist, so skip it)
    index_suffixes = ["created_by", "created_at", "created_via"]

    # Drop indexes first (if they exist)
    for table in tables:
        if inspector.has_table(table):
            try:
                existing_indexes = [idx["name"] for idx in inspector.get_indexes(table)]
            except Exception as e:
                print(f"Warning: Could not get indexes for {table}: {e}")
                continue

            for suffix in index_suffixes:
                index_name = f"idx_{table}_{suffix}"
                if index_name in existing_indexes:
                    try:
                        op.drop_index(index_name, table)
                        print(f"Dropped index {index_name}")
                    except Exception as e:
                        print(f"Warning: Could not drop index {index_name}: {e}")

    # Metadata columns to drop (in reverse order for safety)
    metadata_columns = [
        "version",
        "federation_source",
        "import_batch_id",
        "modified_user_agent",
        "modified_via",
        "modified_from_ip",
        "modified_by",
        "created_user_agent",
        "created_via",
        "created_from_ip",
        "created_by",
    ]

    # Drop metadata columns (if they exist)
    for table in reversed(tables):  # Reverse order for safety
        if inspector.has_table(table):
            columns = [col["name"] for col in inspector.get_columns(table)]

            for col_name in metadata_columns:
                if col_name in columns:
                    try:
                        op.drop_column(table, col_name)
                        print(f"Dropped column {col_name} from {table}")
                    except Exception as e:
                        print(f"Warning: Could not drop column {col_name} from {table}: {e}")
