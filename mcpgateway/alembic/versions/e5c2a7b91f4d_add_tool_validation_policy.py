# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/e5c2a7b91f4d_add_tool_validation_policy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add the tool validation policy columns.

Revision ID: e5c2a7b91f4d
Revises: d3f6a9b1c5e8

``tool_validation_policy`` on gateways and tools stores a CEL expression that decides
whether a tool may be registered. NULL inherits: a tool inherits its gateway, a gateway
inherits the global settings.

``validation_refusal`` on tools stores why the policy refused a discovered tool. The tool
stays disabled while it is set. NULL means the tool was not refused.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "e5c2a7b91f4d"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d3f6a9b1c5e8"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = {
    "gateways": ("tool_validation_policy",),
    "tools": ("tool_validation_policy", "validation_refusal"),
}


def upgrade() -> None:
    """Add each nullable text column to its table when the table exists and lacks it."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()
    for table, columns in COLUMNS.items():
        if table not in existing_tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column not in present:
                op.add_column(table, sa.Column(column, sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop each column from its table when the table has it."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()
    for table, columns in COLUMNS.items():
        if table not in existing_tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        to_drop = [column for column in columns if column in present]
        if not to_drop:
            continue
        with op.batch_alter_table(table) as batch:
            for column in to_drop:
                batch.drop_column(column)
