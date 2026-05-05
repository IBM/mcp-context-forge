# -*- coding: utf-8 -*-
"""add on_error check constraint to tool_plugin_bindings

Revision ID: 926d3e07d098
Revises: 9c45d2e63bc0
Create Date: 2026-05-05
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "926d3e07d098"
down_revision: Union[str, Sequence[str], None] = "9c45d2e63bc0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_tool_plugin_bindings_on_error_valid"


def upgrade() -> None:
    """Add CHECK constraint to on_error column."""
    inspector = sa.inspect(op.get_bind())

    if "tool_plugin_bindings" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_check_constraints("tool_plugin_bindings")}
    if CONSTRAINT_NAME in existing:
        return

    op.create_check_constraint(
        CONSTRAINT_NAME,
        "tool_plugin_bindings",
        "on_error IN ('fail', 'ignore', 'disable') OR on_error IS NULL",
    )


def downgrade() -> None:
    """Remove CHECK constraint from on_error column."""
    inspector = sa.inspect(op.get_bind())

    if "tool_plugin_bindings" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_check_constraints("tool_plugin_bindings")}
    if CONSTRAINT_NAME not in existing:
        return

    op.drop_constraint(CONSTRAINT_NAME, "tool_plugin_bindings", type_="check")
