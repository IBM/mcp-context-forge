# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/3b17fdc40a8d_add_passthrough_headers_to_gateways_and_.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Add passthrough headers to gateways and global config

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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping passthrough headers migration.")
        return

    # Create global_config table if it doesn't exist
    if not inspector.has_table("global_config"):
        op.create_table("global_config", sa.Column("id", sa.Integer(), nullable=False), sa.Column("passthrough_headers", sa.JSON(), nullable=True), sa.PrimaryKeyConstraint("id"))

    # Add passthrough_headers column to gateways table if it doesn't exist
    if inspector.has_table("gateways"):
        columns = [col["name"] for col in inspector.get_columns("gateways")]
        if "passthrough_headers" not in columns:
            op.add_column("gateways", sa.Column("passthrough_headers", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Remove passthrough_headers column from gateways table if it exists
    if inspector.has_table("gateways"):
        columns = [col["name"] for col in inspector.get_columns("gateways")]
        if "passthrough_headers" in columns:
            op.drop_column("gateways", "passthrough_headers")

    # Drop global_config table if it exists
    if inspector.has_table("global_config"):
        op.drop_table("global_config")
