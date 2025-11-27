# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/add_toolops_test_case_table.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jay Bandlamudi

add_a2a_agents_and_metrics

Revision ID: add_a2a_agents_and_metrics
Revises: add_oauth_tokens_table
Create Date: 2025-11-27 10:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "add_toolops_test_cases_table"
down_revision: Union[str, Sequence[str], None] = "z1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add toolops test cases table"""

    # Check if table already exists (for development scenarios)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "toolops_test_cases" not in existing_tables:
        # Create a2a_agents table with unique constraints included (SQLite compatible)
        op.create_table(
            "toolops_test_cases",
            sa.Column("tool_id", sa.String(255), primary_key=True),
            sa.Column("test_cases", sa.JSON(), nullable=True),
            sa.Column("run_status", sa.String(255), nullable=True),
        )


def downgrade() -> None:
    """Reverse the toolops test cases tables."""
    # Check if tables exist before trying to drop indexes/tables
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Drop tables (if they exist)
    for table_name in ["toolops_test_cases"]:
        if table_name in existing_tables:
            try:
                op.drop_table(table_name)
            except Exception as e:
                print(f"Warning: Could not drop table {table_name}: {e}")
