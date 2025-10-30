# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/h2b3c4d5e6f7_add_oauth_config_to_a2a_agents.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add oauth config and passthrough headers to a2a agents

Revision ID: h2b3c4d5e6f7
Revises: 3c89a45f32e5
Create Date: 2025-10-30 22:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "h2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "3c89a45f32e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add oauth_config and passthrough_headers columns to a2a_agents table."""
    # Check if we're dealing with a fresh database
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if "a2a_agents" not in tables:
        print("a2a_agents table not found. Skipping migration.")
        return

    # Check which columns already exist
    columns = [col["name"] for col in inspector.get_columns("a2a_agents")]

    columns_to_add = []
    if "oauth_config" not in columns:
        columns_to_add.append(
            ("oauth_config", sa.Column("oauth_config", sa.JSON(), nullable=True, comment="OAuth 2.0 configuration including grant_type, client_id, encrypted client_secret, URLs, and scopes"))
        )

    if "passthrough_headers" not in columns:
        columns_to_add.append(("passthrough_headers", sa.Column("passthrough_headers", sa.JSON(), nullable=True, comment="List of headers allowed to be passed through to the agent")))

    # Add columns using batch mode for SQLite compatibility
    if columns_to_add:
        try:
            with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
                for col_name, col_def in columns_to_add:
                    batch_op.add_column(col_def)
                    print(f"Successfully added {col_name} column to a2a_agents table.")
        except Exception as e:
            print(f"Warning: Could not add columns to a2a_agents: {e}")
    else:
        print("All columns already exist in a2a_agents.")

    # Add missing team/visibility indexes for consistent performance with other resource tables
    # These indexes are critical for multitenancy queries that filter by owner_email, team_id, and visibility
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("a2a_agents")]

    indexes_to_create = [
        ("idx_a2a_agents_team_visibility", ["team_id", "visibility"]),
        ("idx_a2a_agents_owner_visibility", ["owner_email", "visibility"]),
    ]

    for index_name, columns in indexes_to_create:
        if index_name not in existing_indexes:
            try:
                op.create_index(index_name, "a2a_agents", columns)
                print(f"Successfully created index {index_name} on a2a_agents table.")
            except Exception as e:
                print(f"Warning: Could not create index {index_name}: {e}")


def downgrade() -> None:
    """Remove oauth_config and passthrough_headers columns from a2a_agents table."""
    # Check if we're dealing with a fresh database
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if "a2a_agents" not in tables:
        print("a2a_agents table not found. Skipping migration.")
        return

    # Drop indexes first (if they exist)
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("a2a_agents")]

    indexes_to_drop = ["idx_a2a_agents_owner_visibility", "idx_a2a_agents_team_visibility"]

    for index_name in indexes_to_drop:
        if index_name in existing_indexes:
            try:
                op.drop_index(index_name, "a2a_agents")
                print(f"Successfully dropped index {index_name} from a2a_agents table.")
            except Exception as e:
                print(f"Warning: Could not drop index {index_name}: {e}")

    # Check which columns exist before trying to drop them
    columns = [col["name"] for col in inspector.get_columns("a2a_agents")]

    columns_to_drop = []
    if "passthrough_headers" in columns:
        columns_to_drop.append("passthrough_headers")
    if "oauth_config" in columns:
        columns_to_drop.append("oauth_config")

    if not columns_to_drop:
        print("No columns to remove from a2a_agents. Skipping migration.")
        return

    # Remove columns using batch mode for SQLite compatibility
    try:
        with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
            for col_name in columns_to_drop:
                batch_op.drop_column(col_name)
                print(f"Successfully removed {col_name} column from a2a_agents table.")
    except Exception as e:
        print(f"Warning: Could not drop columns from a2a_agents: {e}")
