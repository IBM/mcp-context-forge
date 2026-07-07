# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/aa2b3c4d5e6f_add_auto_approval_status_to_tools.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Mehta

add_auto_approval_status_to_tools

Revision ID: aa2b3c4d5e6f
Revises: 43c07ed25a24
Create Date: 2026-07-07 13:24:00.000000

Add auto_approval_status field to tools table to support automatic approval
of tool invocations without requiring manual review.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "aa2b3c4d5e6f"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "43c07ed25a24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add auto_approval_status column to tools table."""
    inspector = sa.inspect(op.get_bind())

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "tools" not in inspector.get_table_names():
        return

    # Skip if column already exists
    columns = [col["name"] for col in inspector.get_columns("tools")]
    if "auto_approval_status" not in columns:
        op.add_column("tools", sa.Column("auto_approval_status", sa.Boolean(), nullable=False, server_default=sa.false(), comment="Auto-approval status for the tool"))




def downgrade() -> None:
    """Remove auto_approval_status column from tools table."""
    inspector = sa.inspect(op.get_bind())

    # Skip if fresh database
    if not inspector.has_table("tools"):
        return

    # Remove endpoint column if it exists
    columns = [col["name"] for col in inspector.get_columns("tools")]
    if "auto_approval_status" in columns:
        op.drop_column("tools", "auto_approval_status")

# Made with Bob
