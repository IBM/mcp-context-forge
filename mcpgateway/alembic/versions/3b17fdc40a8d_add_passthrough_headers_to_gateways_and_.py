# -*- coding: utf-8 -*-
"""Add passthrough headers to gateways and global config

Revision ID: 3b17fdc40a8d
Revises: e75490e949b1
Create Date: 2025-08-08 03:45:46.489696

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "3b17fdc40a8d"
down_revision: Union[str, Sequence[str], None] = "e75490e949b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create global_config table
    op.create_table("global_config", sa.Column("id", sa.Integer(), nullable=False), sa.Column("passthrough_headers", sa.JSON(), nullable=True), sa.PrimaryKeyConstraint("id"))

    # Add passthrough_headers column to gateways table
    op.add_column("gateways", sa.Column("passthrough_headers", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove passthrough_headers column from gateways table
    op.drop_column("gateways", "passthrough_headers")

    # Drop global_config table
    op.drop_table("global_config")
