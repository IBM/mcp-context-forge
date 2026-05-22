"""add_gateway_async_status

Revision ID: 47609bcf093a
Revises: e28566875fa4
Create Date: 2026-05-07 18:30:54.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "47609bcf093a"
down_revision: Union[str, None] = "e28566875fa4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add async status columns to gateway table."""
    inspector = sa.inspect(op.get_bind())

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "gateway" not in inspector.get_table_names():
        return

    # Get existing columns
    columns = [col["name"] for col in inspector.get_columns("gateway")]

    # Add status column if not exists
    if "status" not in columns:
        op.add_column("gateway", sa.Column("status", sa.String(20), nullable=False, server_default="active"))

    # Add status_message column if not exists
    if "status_message" not in columns:
        op.add_column("gateway", sa.Column("status_message", sa.Text(), nullable=True))

    # Add registration_attempts column if not exists
    if "registration_attempts" not in columns:
        op.add_column("gateway", sa.Column("registration_attempts", sa.Integer(), nullable=False, server_default="0"))

    # Add next_retry_at column if not exists
    if "next_retry_at" not in columns:
        op.add_column("gateway", sa.Column("next_retry_at", sa.DateTime(), nullable=True))

    # Add last_error column if not exists
    if "last_error" not in columns:
        op.add_column("gateway", sa.Column("last_error", sa.Text(), nullable=True))

    # Create index for worker queries if not exists
    indexes = [idx["name"] for idx in inspector.get_indexes("gateway")]
    if "ix_gateway_status_next_retry" not in indexes:
        op.create_index("ix_gateway_status_next_retry", "gateway", ["status", "next_retry_at"])


def downgrade() -> None:
    """Remove async status columns from gateway table."""
    inspector = sa.inspect(op.get_bind())

    # Skip if table doesn't exist
    if "gateway" not in inspector.get_table_names():
        return

    # Drop index if exists
    indexes = [idx["name"] for idx in inspector.get_indexes("gateway")]
    if "ix_gateway_status_next_retry" in indexes:
        op.drop_index("ix_gateway_status_next_retry", table_name="gateway")

    # Get existing columns
    columns = [col["name"] for col in inspector.get_columns("gateway")]

    # Drop columns if they exist
    if "last_error" in columns:
        op.drop_column("gateway", "last_error")
    if "next_retry_at" in columns:
        op.drop_column("gateway", "next_retry_at")
    if "registration_attempts" in columns:
        op.drop_column("gateway", "registration_attempts")
    if "status_message" in columns:
        op.drop_column("gateway", "status_message")
    if "status" in columns:
        op.drop_column("gateway", "status")
