# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/733159a4fa74_add_display_name_to_tools.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add_display_name_to_tools

Revision ID: 733159a4fa74
Revises: 1fc1795f6983
Create Date: 2025-08-23 13:01:28.785095
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "733159a4fa74"
down_revision: Union[str, Sequence[str], None] = "1fc1795f6983"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add display_name column to tools table and populate smart defaults for existing tools."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def generate_display_name(technical_name: str) -> str:
        """Generate display name from technical name.

        Args:
            technical_name: The technical tool name

        Returns:
            str: Human-readable display name
        """
        # Standard
        import re

        if not technical_name:
            return ""
        # Replace underscores, hyphens, and dots with spaces
        display_name = re.sub(r"[_\-\.]+", " ", technical_name)
        # Remove extra whitespace and title case
        display_name = " ".join(display_name.split())
        if display_name:
            display_name = display_name.title()
        return display_name

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("tools"):
        print("Tools table not found. Skipping display_name migration.")
        return

    # Check if column already exists
    tools_columns = [col["name"] for col in inspector.get_columns("tools")]
    if "display_name" not in tools_columns:
        # Add the column first
        op.add_column("tools", sa.Column("display_name", sa.String(255), nullable=True))
        print("Added display_name column to tools table.")

        # Populate smart displayName for existing tools that don't have one
        connection = bind
        result = connection.execute(sa.text("SELECT id, original_name, custom_name FROM tools WHERE display_name IS NULL"))
        tools_to_update = result.fetchall()

        for tool in tools_to_update:
            # Use custom_name if available, otherwise original_name
            source_name = tool.custom_name if tool.custom_name else tool.original_name
            smart_display_name = generate_display_name(source_name)

            # Update only tools without existing display_name
            connection.execute(sa.text("UPDATE tools SET display_name = :display_name WHERE id = :tool_id AND display_name IS NULL"), {"display_name": smart_display_name, "tool_id": tool.id})

        if tools_to_update:
            print(f"Populated smart displayName for {len(tools_to_update)} existing tools.")

        connection.commit()
    else:
        print("display_name column already exists in tools table.")


def downgrade() -> None:
    """Remove display_name column from tools table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("tools"):
        tools_columns = [col["name"] for col in inspector.get_columns("tools")]
        if "display_name" in tools_columns:
            op.drop_column("tools", "display_name")
            print("Removed display_name column from tools table.")
