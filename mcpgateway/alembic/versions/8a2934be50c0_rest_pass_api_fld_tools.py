# -*- coding: utf-8 -*-
"""rest_pass_api_fld_tools

Revision ID: 8a2934be50c0
Revises: 9aaa90ad26d9
Create Date: 2025-10-17 12:19:39.576193

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8a2934be50c0"
down_revision: Union[str, Sequence[str], None] = "9aaa90ad26d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add Passthrough REST fields to tools table
    op.add_column("tools", sa.Column("base_url", sa.String(), nullable=True))
    op.add_column("tools", sa.Column("path_template", sa.String(), nullable=True))
    op.add_column("tools", sa.Column("query_mapping", sa.JSON(), nullable=True))
    op.add_column("tools", sa.Column("header_mapping", sa.JSON(), nullable=True))
    op.add_column("tools", sa.Column("timeout_ms", sa.Integer(), nullable=True))
    op.add_column("tools", sa.Column("expose_passthrough", sa.Boolean(), nullable=False, server_default="1"))
    op.add_column("tools", sa.Column("allowlist", sa.JSON(), nullable=True))
    op.add_column("tools", sa.Column("plugin_chain_pre", sa.JSON(), nullable=True))
    op.add_column("tools", sa.Column("plugin_chain_post", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove Passthrough REST fields from tools table
    op.drop_column("tools", "plugin_chain_post")
    op.drop_column("tools", "plugin_chain_pre")
    op.drop_column("tools", "allowlist")
    op.drop_column("tools", "expose_passthrough")
    op.drop_column("tools", "timeout_ms")
    op.drop_column("tools", "header_mapping")
    op.drop_column("tools", "query_mapping")
    op.drop_column("tools", "path_template")
    op.drop_column("tools", "base_url")
