# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/7a3a6305ddb6_add_kind_to_a2a_agent_cards.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add_kind_to_a2a_agent_cards

Revision ID: 7a3a6305ddb6
Revises: a4c8e2f1b7d9
Create Date: 2026-11-13 14:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7a3a6305ddb6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a4c8e2f1b7d9"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the kind column to a2a_agent_cards if it does not already exist."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agent_cards" not in inspector.get_table_names():
        return
    if "kind" in [col["name"] for col in inspector.get_columns("a2a_agent_cards")]:
        return

    op.add_column("a2a_agent_cards", sa.Column("kind", sa.String(20), nullable=False, server_default="public"))


def downgrade() -> None:
    """Drop the kind column from a2a_agent_cards if it exists."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agent_cards" not in inspector.get_table_names():
        return
    if "kind" not in [col["name"] for col in inspector.get_columns("a2a_agent_cards")]:
        return

    with op.batch_alter_table("a2a_agent_cards") as batch_op:
        batch_op.drop_column("kind")
