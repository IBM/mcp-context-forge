# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/u5e6f7a8b9c0_add_a2a_agent_protocol_binding.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add protocol_binding to a2a_agents.

Revision ID: u5e6f7a8b9c0
Revises: e5a1c7b9d3f2

The column stores the wire binding an agent was registered with: "jsonrpc" or "http_json".
NULL means "not set". Those rows keep the agent_type and trailing slash heuristic.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "u5e6f7a8b9c0"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e5a1c7b9d3f2"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable protocol_binding column when it is missing."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agents" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("a2a_agents")]
    if "protocol_binding" in columns:
        return
    op.add_column("a2a_agents", sa.Column("protocol_binding", sa.String(20), nullable=True))


def downgrade() -> None:
    """Drop the protocol_binding column when it exists."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agents" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("a2a_agents")]
    if "protocol_binding" not in columns:
        return
    with op.batch_alter_table("a2a_agents") as batch:
        batch.drop_column("protocol_binding")
