# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/a4c8e2f1b7d9_add_a2a_agent_cards_table.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add_a2a_agent_cards_table

Revision ID: a4c8e2f1b7d9
Revises: d3f6a9b1c5e8
Create Date: 2026-10-29 13:45:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a4c8e2f1b7d9"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d3f6a9b1c5e8"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the a2a_agent_cards table if it does not already exist."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agents" not in inspector.get_table_names():
        return
    if "a2a_agent_cards" in inspector.get_table_names():
        return

    op.create_table(
        "a2a_agent_cards",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("a2a_agent_id", sa.String(36), sa.ForeignKey("a2a_agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("card", sa.JSON(), nullable=False),
        sa.Column("detected_version", sa.String(20), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("etag", sa.String(255), nullable=True),
        sa.Column("max_age", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("a2a_agent_id", "version", name="uq_a2a_agent_cards_agent_version"),
    )
    op.create_index("ix_a2a_agent_cards_a2a_agent_id", "a2a_agent_cards", ["a2a_agent_id"])


def downgrade() -> None:
    """Drop the a2a_agent_cards table if it exists."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agent_cards" not in inspector.get_table_names():
        return

    op.drop_index("ix_a2a_agent_cards_a2a_agent_id", table_name="a2a_agent_cards")
    op.drop_table("a2a_agent_cards")
