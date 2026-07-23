# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/12d4a0c7789c_add_team_id_to_oauth_states.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add_team_id_to_oauth_states

Revision ID: 12d4a0c7789c
Revises: d21698ae4a19
Create Date: 2026-07-10 17:57:41.233008
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12d4a0c7789c'  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = 'd21698ae4a19'  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add team_id column to oauth_states table for Vault token storage path."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if table exists (handles fresh DB using db.py models directly)
    if "oauth_states" not in inspector.get_table_names():
        return

    # Check if column already exists (idempotent)
    columns = [col["name"] for col in inspector.get_columns("oauth_states")]
    if "team_id" in columns:
        return

    # Add team_id column (nullable for backward compatibility with existing rows)
    with op.batch_alter_table("oauth_states", schema=None) as batch_op:
        batch_op.add_column(sa.Column("team_id", sa.String(255), nullable=True))


def downgrade() -> None:
    """Remove team_id column from oauth_states table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if table exists
    if "oauth_states" not in inspector.get_table_names():
        return

    # Check if column exists before dropping
    columns = [col["name"] for col in inspector.get_columns("oauth_states")]
    if "team_id" not in columns:
        return

    with op.batch_alter_table("oauth_states", schema=None) as batch_op:
        batch_op.drop_column("team_id")
