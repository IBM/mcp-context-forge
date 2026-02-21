# -*- coding: utf-8 -*-
"""Add VFS server type columns to servers table.

Revision ID: a1b2c3d4e5f6
Revises: x7h8i9j0k1l2
Create Date: 2026-02-19

Adds server_type, stub_format, and mount_rules columns to the servers table
for Virtual Tool Filesystem (VFS) support.
"""

# Future
from __future__ import annotations

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "x7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add server_type, stub_format, and mount_rules columns."""
    inspector = sa.inspect(op.get_bind())

    if "servers" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("servers")]

    if "server_type" not in columns:
        op.add_column("servers", sa.Column("server_type", sa.String(length=32), nullable=False, server_default="standard"))
        op.create_index("ix_servers_server_type", "servers", ["server_type"])

    if "stub_format" not in columns:
        op.add_column("servers", sa.Column("stub_format", sa.String(length=32), nullable=True))

    if "mount_rules" not in columns:
        op.add_column("servers", sa.Column("mount_rules", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove VFS columns from servers table."""
    inspector = sa.inspect(op.get_bind())

    if "servers" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("servers")]

    if "mount_rules" in columns:
        op.drop_column("servers", "mount_rules")
    if "stub_format" in columns:
        op.drop_column("servers", "stub_format")
    if "server_type" in columns:
        op.drop_index("ix_servers_server_type", table_name="servers")
        op.drop_column("servers", "server_type")
