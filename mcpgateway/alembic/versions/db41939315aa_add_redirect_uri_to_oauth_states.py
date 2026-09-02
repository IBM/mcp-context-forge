# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/db41939315aa_add_redirect_uri_to_oauth_states.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add redirect_uri column to oauth_states.

Revision ID: db41939315aa
Revises: 9935d863930b
Create Date: 2026-08-14 12:47:18.662212
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "db41939315aa"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "9935d863930b"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add redirect_uri to oauth_states when missing."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "oauth_states" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("oauth_states")}
    if "redirect_uri" in columns:
        return

    op.add_column("oauth_states", sa.Column("redirect_uri", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    """Drop redirect_uri from oauth_states when present."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "oauth_states" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("oauth_states")}
    if "redirect_uri" not in columns:
        return

    op.drop_column("oauth_states", "redirect_uri")
