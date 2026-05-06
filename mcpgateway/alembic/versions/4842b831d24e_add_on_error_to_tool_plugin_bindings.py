# -*- coding: utf-8 -*-
"""add on_error to tool_plugin_bindings

Revision ID: 4842b831d24e
Revises: bb43712cae28
Create Date: 2026-04-29
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "4842b831d24e"
down_revision: Union[str, Sequence[str], None] = "bb43712cae28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add on_error column to tool_plugin_bindings."""
    inspector = sa.inspect(op.get_bind())

    if "tool_plugin_bindings" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("tool_plugin_bindings")]
    if "on_error" in columns:
        return

    op.add_column("tool_plugin_bindings", sa.Column("on_error", sa.String(10), nullable=True))


def downgrade() -> None:
    """Remove on_error column from tool_plugin_bindings."""
    inspector = sa.inspect(op.get_bind())

    if "tool_plugin_bindings" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("tool_plugin_bindings")]
    if "on_error" not in columns:
        return

    op.drop_column("tool_plugin_bindings", "on_error")
