# -*- coding: utf-8 -*-
"""add observability saved queries

Revision ID: j4d5e6f7g8h9
Revises: i3c4d5e6f7g8
Create Date: 2025-01-06 12:00:00.000000

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "j4d5e6f7g8h9"
down_revision: Union[str, Sequence[str], None] = "i3c4d5e6f7g8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add observability_saved_queries table for storing filter presets."""
    op.create_table(
        "observability_saved_queries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("user_email", sa.String(length=255), nullable=False),
        sa.Column("filter_config", sa.JSON(), nullable=False),
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for performance
    op.create_index("idx_observability_saved_queries_user_email", "observability_saved_queries", ["user_email"])
    op.create_index("idx_observability_saved_queries_is_shared", "observability_saved_queries", ["is_shared"])
    op.create_index("idx_observability_saved_queries_created_at", "observability_saved_queries", ["created_at"])
    op.create_index("ix_observability_saved_queries_name", "observability_saved_queries", ["name"])


def downgrade() -> None:
    """Remove observability_saved_queries table."""
    op.drop_index("ix_observability_saved_queries_name", table_name="observability_saved_queries")
    op.drop_index("idx_observability_saved_queries_created_at", table_name="observability_saved_queries")
    op.drop_index("idx_observability_saved_queries_is_shared", table_name="observability_saved_queries")
    op.drop_index("idx_observability_saved_queries_user_email", table_name="observability_saved_queries")
    op.drop_table("observability_saved_queries")
