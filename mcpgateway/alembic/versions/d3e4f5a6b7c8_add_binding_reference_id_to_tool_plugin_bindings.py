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
revision: str = "d3e4f5a6b7c8"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable binding_reference_id column and index to tool_plugin_bindings."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "tool_plugin_bindings" not in inspector.get_table_names():
        return

    # Skip if column already exists (idempotent re-run guard)
    columns = [col["name"] for col in inspector.get_columns("tool_plugin_bindings")]
    if "binding_reference_id" not in columns:
        op.add_column(
            "tool_plugin_bindings",
            sa.Column("binding_reference_id", sa.String(255), nullable=True),
        )

    # Add index only if it doesn't already exist
    indexes = [idx["name"] for idx in inspector.get_indexes("tool_plugin_bindings")]
    if "ix_tool_plugin_bindings_binding_reference_id" not in indexes:
        op.create_index(
            "ix_tool_plugin_bindings_binding_reference_id",
            "tool_plugin_bindings",
            ["binding_reference_id"],
        )


def downgrade() -> None:
    """Remove binding_reference_id column and index from tool_plugin_bindings."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if table doesn't exist
    if "tool_plugin_bindings" not in inspector.get_table_names():
        return

    # Drop index if it exists
    indexes = [idx["name"] for idx in inspector.get_indexes("tool_plugin_bindings")]
    if "ix_tool_plugin_bindings_binding_reference_id" in indexes:
        op.drop_index(
            "ix_tool_plugin_bindings_binding_reference_id",
            table_name="tool_plugin_bindings",
        )

    # Drop column if it exists
    columns = [col["name"] for col in inspector.get_columns("tool_plugin_bindings")]
    if "binding_reference_id" in columns:
        op.drop_column("tool_plugin_bindings", "binding_reference_id")
