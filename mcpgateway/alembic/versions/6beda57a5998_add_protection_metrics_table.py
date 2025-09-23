"""Add protection metrics table

Revision ID: 6beda57a5998
Revises: add_oauth_tokens_table
Create Date: 2025-08-31 21:18:31.249992
Author: Madhavan Kidambi
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "6beda57a5998"
down_revision: Union[str, Sequence[str], None] = "add_oauth_tokens_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add protection_metrics table for storing protection metrics."""
    # Create protection_metric table
    op.create_table(
        "protection_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("client_id", sa.Text, nullable=True),
        sa.Column("client_ip", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("method", sa.Text, nullable=False),
        sa.Column("rate_limit_key", sa.Text, nullable=True),
        sa.Column("metric_type", sa.Text, nullable=False, default="rate_limit"),
        sa.Column("current_usage", sa.Integer, nullable=True),
        sa.Column("limit", sa.Integer, nullable=True),
        sa.Column("remaining", sa.Integer, nullable=True),
        sa.Column("reset_time", sa.Integer, nullable=True),
        sa.Column("is_blocked", sa.Boolean, nullable=True, default=False),
        sa.UniqueConstraint("id", "id", name="unique_metric_id"),
    )

    print("Successfully created protection_metrics table")


def downgrade() -> None:
    """Remove protection_metrics table."""
    # Check if we're dealing with a fresh database
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if "protection_metrics" not in tables:
        print("protection_metrics table not found. Skipping migration.")
        return

    # Remove protection_metrics table
    op.drop_table("protection_metrics")

    print("Successfully removed protection_metrics table.")
