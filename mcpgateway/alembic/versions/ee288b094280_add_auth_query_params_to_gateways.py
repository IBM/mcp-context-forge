# -*- coding: utf-8 -*-
"""Add auth_query_params column to gateways table.

Revision ID: ee288b094280
Revises: 43c07ed25a24
Create Date: 2026-01-19

Supports query parameter authentication for upstream MCP servers.
See Issue #1580.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ee288b094280"
down_revision: Union[str, Sequence[str], None] = "43c07ed25a24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add auth_query_params column to gateways table."""
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    # Handle gateways table
    if "gateways" in tables:
        columns = [col["name"] for col in inspector.get_columns("gateways")]
        if "auth_query_params" not in columns:
            try:
                with op.batch_alter_table("gateways", schema=None) as batch_op:
                    batch_op.add_column(
                        sa.Column(
                            "auth_query_params",
                            sa.JSON(),
                            nullable=True,
                            comment="Encrypted query parameters for authentication",
                        )
                    )
                print("Successfully added auth_query_params column to gateways table.")
            except Exception as e:
                print(f"Warning: Could not add auth_query_params column to gateways: {e}")
        else:
            print("auth_query_params column already exists in gateways. Skipping.")


def downgrade() -> None:
    """Remove auth_query_params column from gateways table."""
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    # Handle gateways table
    if "gateways" in tables:
        columns = [col["name"] for col in inspector.get_columns("gateways")]
        if "auth_query_params" in columns:
            try:
                with op.batch_alter_table("gateways", schema=None) as batch_op:
                    batch_op.drop_column("auth_query_params")
            except Exception as e:
                print(f"Warning: Could not drop auth_query_params column from gateways: {e}")
