# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/b9d2f4a6c8e1_add_checked_at_to_a2a_agent_cards.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add checked_at to a2a_agent_cards.

Revision ID: b9d2f4a6c8e1
Revises: f2c3d4e5a6b7

The column holds the time of the last re-fetch that found the card unchanged.
NULL means no re-fetch has checked the card since it was stored.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "b9d2f4a6c8e1"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "f2c3d4e5a6b7"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable checked_at column when it is missing."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agent_cards" not in inspector.get_table_names():
        return
    if "checked_at" in [column["name"] for column in inspector.get_columns("a2a_agent_cards")]:
        return
    with op.batch_alter_table("a2a_agent_cards") as batch_op:
        batch_op.add_column(sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Drop the checked_at column when it exists."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agent_cards" not in inspector.get_table_names():
        return
    if "checked_at" not in [column["name"] for column in inspector.get_columns("a2a_agent_cards")]:
        return
    with op.batch_alter_table("a2a_agent_cards") as batch_op:
        batch_op.drop_column("checked_at")
