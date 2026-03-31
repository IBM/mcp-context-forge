"""add_user_id_to_tool_metrics

Revision ID: 318935c50562
Revises: f2a3b4c5d6e7
Create Date: 2026-03-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "318935c50562"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable user_id column and composite index to tool_metrics."""
    inspector = sa.inspect(op.get_bind())

    if "tool_metrics" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("tool_metrics")]
    if "user_id" not in columns:
        op.add_column("tool_metrics", sa.Column("user_id", sa.String(255), nullable=True))
        op.create_index("ix_tool_metrics_user_id", "tool_metrics", ["user_id"])

    indexes = {idx["name"] for idx in inspector.get_indexes("tool_metrics")}
    if "ix_tool_metrics_user_id_timestamp" not in indexes:
        op.create_index("ix_tool_metrics_user_id_timestamp", "tool_metrics", ["user_id", "timestamp"])


def downgrade() -> None:
    """Remove user_id column and associated indexes from tool_metrics."""
    inspector = sa.inspect(op.get_bind())

    if "tool_metrics" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("tool_metrics")}
    if "ix_tool_metrics_user_id_timestamp" in indexes:
        op.drop_index("ix_tool_metrics_user_id_timestamp", table_name="tool_metrics")
    if "ix_tool_metrics_user_id" in indexes:
        op.drop_index("ix_tool_metrics_user_id", table_name="tool_metrics")

    columns = [col["name"] for col in inspector.get_columns("tool_metrics")]
    if "user_id" in columns:
        op.drop_column("tool_metrics", "user_id")
