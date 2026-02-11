# -*- coding: utf-8 -*-
"""add_gateway_mode_field

Revision ID: 207d8bbddd61
Revises: 04cda6733305
Create Date: 2026-01-21 09:48:44.636655

"""
# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "207d8bbddd61"
down_revision: Union[str, Sequence[str], None] = "c1c2c3c4c5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add gateway_mode column to gateways table."""
    # Check if table exists before attempting to add column
    inspector = sa.inspect(op.get_bind())

    # Skip if table doesn't exist (fresh DB uses models.py directly)
    if "gateways" not in inspector.get_table_names():
        return

    # Skip if column already exists
    columns = [col["name"] for col in inspector.get_columns("gateways")]
    if "gateway_mode" in columns:
        return

    # Add gateway_mode column with default value 'cache'
    op.add_column(
        "gateways", sa.Column("gateway_mode", sa.String(length=20), nullable=False, server_default="cache", comment="Gateway mode: 'cache' (database caching) or 'direct_proxy' (pass-through mode)")
    )


def downgrade() -> None:
    """Downgrade schema - remove gateway_mode column from gateways table."""
    # Check if table exists
    inspector = sa.inspect(op.get_bind())

    if "gateways" not in inspector.get_table_names():
        return

    # Check if column exists before dropping
    columns = [col["name"] for col in inspector.get_columns("gateways")]
    if "gateway_mode" not in columns:
        return

    op.drop_column("gateways", "gateway_mode")
