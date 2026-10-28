# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/a4b8c1d9e2f7_add_upstream_instructions_to_gateways.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add upstream_instructions to gateways.

Revision ID: a4b8c1d9e2f7
Revises: c7e91a2b4d60

The column stores the instructions text that an upstream MCP server returns at connect time.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "a4b8c1d9e2f7"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "c7e91a2b4d60"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable upstream_instructions column when it is missing."""
    inspector = sa.inspect(op.get_bind())
    if "gateways" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("gateways")]
    if "upstream_instructions" in columns:
        return
    op.add_column("gateways", sa.Column("upstream_instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the upstream_instructions column when it exists."""
    inspector = sa.inspect(op.get_bind())
    if "gateways" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("gateways")]
    if "upstream_instructions" not in columns:
        return
    with op.batch_alter_table("gateways") as batch:
        batch.drop_column("upstream_instructions")
