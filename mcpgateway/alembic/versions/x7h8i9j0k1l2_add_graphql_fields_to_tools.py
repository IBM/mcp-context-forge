# -*- coding: utf-8 -*-
"""Add GraphQL fields to tools table

Revision ID: x7h8i9j0k1l2
Revises: w6g7h8i9j0k1
Create Date: 2026-02-17 12:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "x7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "w6g7h8i9j0k1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add GraphQL-specific columns to the tools table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if tools table doesn't exist (fresh DB uses db.py models directly)
    if "tools" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("tools")]

    if "graphql_operation" not in columns:
        op.add_column("tools", sa.Column("graphql_operation", sa.Text(), nullable=True))

    if "graphql_variables_mapping" not in columns:
        op.add_column("tools", sa.Column("graphql_variables_mapping", sa.JSON(), nullable=True))

    if "graphql_field_selection" not in columns:
        op.add_column("tools", sa.Column("graphql_field_selection", sa.Text(), nullable=True))

    if "graphql_operation_type" not in columns:
        op.add_column("tools", sa.Column("graphql_operation_type", sa.String(20), nullable=True))


def downgrade() -> None:
    """Remove GraphQL-specific columns from the tools table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "tools" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("tools")]

    if "graphql_operation_type" in columns:
        op.drop_column("tools", "graphql_operation_type")

    if "graphql_field_selection" in columns:
        op.drop_column("tools", "graphql_field_selection")

    if "graphql_variables_mapping" in columns:
        op.drop_column("tools", "graphql_variables_mapping")

    if "graphql_operation" in columns:
        op.drop_column("tools", "graphql_operation")
