# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
"""Add tools_include and tools_exclude columns to gateways table.

Revision ID: b3c4d5e6f7a8
Revises: a7f3c9e1b2d4
Create Date: 2026-04-03 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "b3c4d5e6f7a8"
down_revision = "a7f3c9e1b2d4"
branch_labels = None
depends_on = None


def upgrade():
    """Add tool filter columns to gateways."""
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_columns = {col["name"] for col in inspector.get_columns("gateways")}

    if "tools_include" not in existing_columns:
        op.add_column("gateways", sa.Column("tools_include", sa.JSON(), nullable=True, comment="Glob patterns to include tools (whitelist)"))
    if "tools_exclude" not in existing_columns:
        op.add_column("gateways", sa.Column("tools_exclude", sa.JSON(), nullable=True, comment="Glob patterns to exclude tools (blacklist)"))


def downgrade():
    """Remove tool filter columns from gateways."""
    with op.batch_alter_table("gateways", schema=None) as batch_op:
        batch_op.drop_column("tools_exclude")
        batch_op.drop_column("tools_include")
