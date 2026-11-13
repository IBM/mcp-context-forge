# -*- coding: utf-8 -*-
# pylint: disable=invalid-name,no-member
"""Location: ./mcpgateway/alembic/versions/7263b1a8c204_add_caller_session_pinning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add opt-in upstream session continuity for authenticated callers."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7263b1a8c204"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "4a7d9e2c6b18"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the disabled-by-default gateway setting when absent."""
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("gateways") and "pin_sessions_by_caller" not in {column["name"] for column in inspector.get_columns("gateways")}:
        op.add_column("gateways", sa.Column("pin_sessions_by_caller", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Remove the gateway setting when present."""
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("gateways") and "pin_sessions_by_caller" in {column["name"] for column in inspector.get_columns("gateways")}:
        with op.batch_alter_table("gateways") as batch_op:
            batch_op.drop_column("pin_sessions_by_caller")
