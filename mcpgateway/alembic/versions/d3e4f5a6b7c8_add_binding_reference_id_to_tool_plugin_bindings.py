# -*- coding: utf-8 -*-
"""Add binding_reference_id to tool_plugin_bindings.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-04-10
"""

# Standard
from typing import Sequence, Union

# Third-Party
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable binding_reference_id column and index to tool_plugin_bindings."""
    op.add_column(
        "tool_plugin_bindings",
        sa.Column("binding_reference_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_tool_plugin_bindings_binding_reference_id",
        "tool_plugin_bindings",
        ["binding_reference_id"],
    )


def downgrade() -> None:
    """Remove binding_reference_id column and index from tool_plugin_bindings."""
    op.drop_index(
        "ix_tool_plugin_bindings_binding_reference_id",
        table_name="tool_plugin_bindings",
    )
    op.drop_column("tool_plugin_bindings", "binding_reference_id")
