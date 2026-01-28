# -*- coding: utf-8 -*-
"""add_output_schema_to_tools

Revision ID: 9aaa90ad26d9
Revises: 9c99ec6872ed
Create Date: 2025-10-15 17:29:38.801771

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9aaa90ad26d9"
down_revision: Union[str, Sequence[str], None] = "9c99ec6872ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database (tables created via create_all + stamp)
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Add output_schema column to tools table if it exists and column is missing
    if inspector.has_table("tools"):
        columns = [col["name"] for col in inspector.get_columns("tools")]
        if "output_schema" not in columns:
            op.add_column("tools", sa.Column("output_schema", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Remove output_schema column from tools table if it exists
    if inspector.has_table("tools"):
        columns = [col["name"] for col in inspector.get_columns("tools")]
        if "output_schema" in columns:
            op.drop_column("tools", "output_schema")
