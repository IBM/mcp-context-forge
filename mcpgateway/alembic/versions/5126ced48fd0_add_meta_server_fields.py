# -*- coding: utf-8 -*-
"""Add meta-server fields to servers table

Revision ID: 5126ced48fd0
Revises: c3d4e5f6a7b8
Create Date: 2026-02-12 10:00:00.000000

"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "5126ced48fd0"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add server_type, hide_underlying_tools, meta_config, and meta_scope columns to servers."""
    inspector = sa.inspect(op.get_bind())

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "servers" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("servers")]

    if "server_type" not in columns:
        op.add_column("servers", sa.Column("server_type", sa.String(20), nullable=False, server_default="standard"))

    if "hide_underlying_tools" not in columns:
        op.add_column("servers", sa.Column("hide_underlying_tools", sa.Boolean(), nullable=False, server_default=sa.text("1")))

    if "meta_config" not in columns:
        op.add_column("servers", sa.Column("meta_config", sa.JSON(), nullable=True))

    if "meta_scope" not in columns:
        op.add_column("servers", sa.Column("meta_scope", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove meta-server fields from servers table."""
    inspector = sa.inspect(op.get_bind())

    if "servers" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("servers")]

    if "meta_scope" in columns:
        op.drop_column("servers", "meta_scope")
    if "meta_config" in columns:
        op.drop_column("servers", "meta_config")
    if "hide_underlying_tools" in columns:
        op.drop_column("servers", "hide_underlying_tools")
    if "server_type" in columns:
        op.drop_column("servers", "server_type")
