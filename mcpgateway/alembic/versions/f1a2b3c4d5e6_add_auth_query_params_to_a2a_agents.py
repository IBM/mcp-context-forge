# -*- coding: utf-8 -*-
"""Add auth_query_params column to a2a_agents table.

Revision ID: f1a2b3c4d5e6
Revises: ee288b094280
Create Date: 2026-01-19

Supports query parameter authentication for A2A agents.
See Issue #2195.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "ee288b094280"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add auth_query_params column to a2a_agents table."""
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if "a2a_agents" in tables:
        columns = [col["name"] for col in inspector.get_columns("a2a_agents")]
        if "auth_query_params" not in columns:
            try:
                with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
                    batch_op.add_column(
                        sa.Column(
                            "auth_query_params",
                            sa.JSON(),
                            nullable=True,
                            comment="Encrypted query parameters for authentication",
                        )
                    )
                print("Successfully added auth_query_params column to a2a_agents table.")
            except Exception as e:
                print(f"Warning: Could not add auth_query_params column to a2a_agents: {e}")
        else:
            print("auth_query_params column already exists in a2a_agents. Skipping.")


def downgrade() -> None:
    """Remove auth_query_params column from a2a_agents table."""
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if "a2a_agents" in tables:
        columns = [col["name"] for col in inspector.get_columns("a2a_agents")]
        if "auth_query_params" in columns:
            try:
                with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
                    batch_op.drop_column("auth_query_params")
            except Exception as e:
                print(f"Warning: Could not drop auth_query_params column from a2a_agents: {e}")
