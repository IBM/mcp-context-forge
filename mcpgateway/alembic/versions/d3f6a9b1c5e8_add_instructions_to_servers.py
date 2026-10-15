# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/d3f6a9b1c5e8_add_instructions_to_servers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add instructions to servers.

Revision ID: d3f6a9b1c5e8
Revises: a4b8c1d9e2f7

The column stores the instructions text that an operator sets on a virtual server.
NULL means "not set". An empty string means "send no instructions".
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "d3f6a9b1c5e8"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a4b8c1d9e2f7"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable instructions column when it is missing."""
    inspector = sa.inspect(op.get_bind())
    if "servers" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("servers")]
    if "instructions" in columns:
        return
    op.add_column("servers", sa.Column("instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the instructions column when it exists."""
    inspector = sa.inspect(op.get_bind())
    if "servers" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("servers")]
    if "instructions" not in columns:
        return
    with op.batch_alter_table("servers") as batch:
        batch.drop_column("instructions")
