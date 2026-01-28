# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/e75490e949b1_add_improved_status_to_tables.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Add enabled and reachable columns in tools and gateways tables and migrate data (is_active ➜ enabled,reachable).

Revision ID: e75490e949b1
Revises: e4fc04d1a442
Create Date: 2025-07-02 17:12:40.678256
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# Revision identifiers.
revision: str = "e75490e949b1"
down_revision: Union[str, Sequence[str], None] = "e4fc04d1a442"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    """
    Renames 'is_active' to 'enabled' and adds a new 'reachable' column (default True)
    in both 'tools' and 'gateways' tables.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("tools") and not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping status migration.")
        return

    # Only modify tables if they exist and have the columns we're trying to modify
    if inspector.has_table("tools"):
        columns = [col["name"] for col in inspector.get_columns("tools")]
        if "is_active" in columns:
            try:
                op.alter_column("tools", "is_active", new_column_name="enabled")
            except Exception as e:
                print(f"Warning: Could not rename is_active to enabled in tools: {e}")

        if "reachable" not in columns:
            try:
                op.add_column("tools", sa.Column("reachable", sa.Boolean(), nullable=False, server_default=sa.true()))
            except Exception as e:
                print(f"Warning: Could not add reachable column to tools: {e}")

    if inspector.has_table("gateways"):
        columns = [col["name"] for col in inspector.get_columns("gateways")]
        if "is_active" in columns:
            try:
                op.alter_column("gateways", "is_active", new_column_name="enabled")
            except Exception as e:
                print(f"Warning: Could not rename is_active to enabled in gateways: {e}")

        if "reachable" not in columns:
            try:
                op.add_column("gateways", sa.Column("reachable", sa.Boolean(), nullable=False, server_default=sa.true()))
            except Exception as e:
                print(f"Warning: Could not add reachable column to gateways: {e}")


def downgrade():
    """
    Reverts the changes by renaming 'enabled' back to 'is_active'
    and dropping the 'reachable' column in both 'tools' and 'gateways' tables.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("tools"):
        columns = [col["name"] for col in inspector.get_columns("tools")]
        if "enabled" in columns:
            try:
                op.alter_column("tools", "enabled", new_column_name="is_active")
            except Exception as e:
                print(f"Warning: Could not rename enabled to is_active in tools: {e}")
        if "reachable" in columns:
            try:
                op.drop_column("tools", "reachable")
            except Exception as e:
                print(f"Warning: Could not drop reachable column from tools: {e}")

    if inspector.has_table("gateways"):
        columns = [col["name"] for col in inspector.get_columns("gateways")]
        if "enabled" in columns:
            try:
                op.alter_column("gateways", "enabled", new_column_name="is_active")
            except Exception as e:
                print(f"Warning: Could not rename enabled to is_active in gateways: {e}")
        if "reachable" in columns:
            try:
                op.drop_column("gateways", "reachable")
            except Exception as e:
                print(f"Warning: Could not drop reachable column from gateways: {e}")
