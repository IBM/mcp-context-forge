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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database (tables created via create_all + stamp)
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Add Passthrough REST fields to tools table if it exists
    if inspector.has_table("tools"):
        columns = [col["name"] for col in inspector.get_columns("tools")]
        new_columns = [
            ("base_url", sa.Column("base_url", sa.String(), nullable=True)),
            ("path_template", sa.Column("path_template", sa.String(), nullable=True)),
            ("query_mapping", sa.Column("query_mapping", sa.JSON(), nullable=True)),
            ("header_mapping", sa.Column("header_mapping", sa.JSON(), nullable=True)),
            ("timeout_ms", sa.Column("timeout_ms", sa.Integer(), nullable=True)),
            ("expose_passthrough", sa.Column("expose_passthrough", sa.Boolean(), nullable=False, server_default="1")),
            ("allowlist", sa.Column("allowlist", sa.JSON(), nullable=True)),
            ("plugin_chain_pre", sa.Column("plugin_chain_pre", sa.JSON(), nullable=True)),
            ("plugin_chain_post", sa.Column("plugin_chain_post", sa.JSON(), nullable=True)),
        ]
        for col_name, col_def in new_columns:
            if col_name not in columns:
                op.add_column("tools", col_def)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Remove Passthrough REST fields from tools table if it exists
    if inspector.has_table("tools"):
        columns = [col["name"] for col in inspector.get_columns("tools")]
        drop_columns = ["plugin_chain_post", "plugin_chain_pre", "allowlist", "expose_passthrough", "timeout_ms", "header_mapping", "query_mapping", "path_template", "base_url"]
        for col_name in drop_columns:
            if col_name in columns:
                op.drop_column("tools", col_name)
