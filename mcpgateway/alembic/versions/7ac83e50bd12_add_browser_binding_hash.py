# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/7ac83e50bd12_add_browser_binding_hash.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add browser_binding_hash column to oauth_states.

Revision ID: 7ac83e50bd12
Revises: 4a7d9e2c6b18
Create Date: 2026-11-12
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7ac83e50bd12"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "4a7d9e2c6b18"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add browser_binding_hash to oauth_states when missing."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "oauth_states" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("oauth_states")}
    if "browser_binding_hash" in columns:
        return

    op.add_column("oauth_states", sa.Column("browser_binding_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Drop browser_binding_hash from oauth_states when present."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "oauth_states" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("oauth_states")}
    if "browser_binding_hash" not in columns:
        return

    op.drop_column("oauth_states", "browser_binding_hash")
