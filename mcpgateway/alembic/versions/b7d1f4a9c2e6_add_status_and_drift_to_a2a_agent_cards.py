# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/b7d1f4a9c2e6_add_status_and_drift_to_a2a_agent_cards.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add_status_and_drift_to_a2a_agent_cards

Revision ID: b7d1f4a9c2e6
Revises: a4c8e2f1b7d9
Create Date: 2026-10-29 15:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b7d1f4a9c2e6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a4c8e2f1b7d9"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add status and drift columns to a2a_agent_cards if they do not exist."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agent_cards" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("a2a_agent_cards")}
    if "status" not in columns:
        op.add_column("a2a_agent_cards", sa.Column("status", sa.String(20), nullable=False, server_default="applied"))
    if "drift" not in columns:
        op.add_column("a2a_agent_cards", sa.Column("drift", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop status and drift columns from a2a_agent_cards if they exist."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agent_cards" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("a2a_agent_cards")}
    with op.batch_alter_table("a2a_agent_cards") as batch:
        if "drift" in columns:
            batch.drop_column("drift")
        if "status" in columns:
            batch.drop_column("status")
