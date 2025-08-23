# -*- coding: utf-8 -*-
"""add_display_name_to_tools

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
    """Add display_name column to tools table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("tools"):
        print("Tools table not found. Skipping display_name migration.")
        return

    # Check if column already exists
    tools_columns = [col["name"] for col in inspector.get_columns("tools")]
    if "display_name" not in tools_columns:
        op.add_column("tools", sa.Column("display_name", sa.String(), nullable=True))
        print("Added display_name column to tools table.")
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
