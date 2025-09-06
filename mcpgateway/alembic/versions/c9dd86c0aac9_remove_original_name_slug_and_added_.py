# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/c9dd86c0aac9_remove_original_name_slug_and_added_.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

remove original_name_slug and added custom_name

Revision ID: c9dd86c0aac9
Revises: add_oauth_tokens_table
Create Date: 2025-08-19 15:15:26.509036
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c9dd86c0aac9"
down_revision: Union[str, Sequence[str], None] = "add_oauth_tokens_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("tools"):
        print("Fresh database detected. Skipping custom name migration.")
        return

    # Only modify tables if they exist and have the columns we're trying to modify
    if inspector.has_table("tools"):
        columns = [col["name"] for col in inspector.get_columns("tools")]

        # Rename original_name_slug to custom_name_slug if it exists
        if "original_name_slug" in columns:
            try:
                op.alter_column("tools", "original_name_slug", new_column_name="custom_name_slug")
            except Exception as e:
                print(f"Warning: Could not rename original_name_slug to custom_name_slug: {e}")

        # Add custom_name column if it doesn't exist
        if "custom_name" not in columns:
            try:
                op.add_column("tools", sa.Column("custom_name", sa.String(255), nullable=True))
                # Only try to update if original_name column exists
                if "original_name" in columns:
                    op.execute("UPDATE tools SET custom_name = original_name")
            except Exception as e:
                print(f"Warning: Could not add custom_name column: {e}")
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("tools"):
        columns = [col["name"] for col in inspector.get_columns("tools")]

        # Remove custom_name column if it exists
        if "custom_name" in columns:
            try:
                op.drop_column("tools", "custom_name")
            except Exception as e:
                print(f"Warning: Could not drop custom_name column: {e}")

        # Rename custom_name_slug back to original_name_slug if it exists
        if "custom_name_slug" in columns:
            try:
                op.alter_column("tools", "custom_name_slug", new_column_name="original_name_slug")
            except Exception as e:
                print(f"Warning: Could not rename custom_name_slug to original_name_slug: {e}")
    # ### end Alembic commands ###
