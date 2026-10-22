# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/524170c21d7c_add_expires_at_to_rbac_rules.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add expires_at to rbac_rules

Revision ID: 524170c21d7c
Revises: b4fa82402c6b
Create Date: 2026-10-04
"""

# Standard
from typing import Sequence, Union

# Third-Party
import sqlalchemy as sa
from alembic import op

revision: str = "524170c21d7c"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b4fa82402c6b"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add expires_at to rbac_rules."""
    inspector = sa.inspect(op.get_bind())
    if "rbac_rules" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("rbac_rules")]
    if "expires_at" in columns:
        return
    op.add_column("rbac_rules", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Drop expires_at from rbac_rules."""
    inspector = sa.inspect(op.get_bind())
    if "rbac_rules" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("rbac_rules")]
    if "expires_at" not in columns:
        return
    op.drop_column("rbac_rules", "expires_at")
