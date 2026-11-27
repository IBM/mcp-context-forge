# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/c4e8a1d7f2b9_add_card_status_and_drift_flags_to_a2a.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add card status and drift flags to the A2A tables.

Revision ID: c4e8a1d7f2b9
Revises: b9d2f4a6c8e1

``a2a_agent_cards.status`` is ``applied``, ``pending``, ``rejected`` or ``superseded``.
Existing rows are ``applied``. ``a2a_agents.drifted`` marks an agent whose remote card
differs from the card it runs on. ``a2a_agents.unverified`` marks an agent saved with a
credential that no card fetch has checked.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "c4e8a1d7f2b9"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b9d2f4a6c8e1"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> list[str]:
    """Return the column names of a table.

    Args:
        table: Table name.

    Returns:
        Column names, or an empty list when the table does not exist.
    """
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return []
    return [column["name"] for column in inspector.get_columns(table)]


def upgrade() -> None:
    """Add the card status column and the two agent flags when they are missing."""
    card_columns = _columns("a2a_agent_cards")
    if card_columns and "status" not in card_columns:
        with op.batch_alter_table("a2a_agent_cards") as batch_op:
            batch_op.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="applied"))
    agent_columns = _columns("a2a_agents")
    for name in ("drifted", "unverified"):
        if agent_columns and name not in agent_columns:
            with op.batch_alter_table("a2a_agents") as batch_op:
                batch_op.add_column(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    """Drop the card status column and the two agent flags when they exist."""
    for name in ("drifted", "unverified"):
        if name in _columns("a2a_agents"):
            with op.batch_alter_table("a2a_agents") as batch_op:
                batch_op.drop_column(name)
    if "status" in _columns("a2a_agent_cards"):
        with op.batch_alter_table("a2a_agent_cards") as batch_op:
            batch_op.drop_column("status")
