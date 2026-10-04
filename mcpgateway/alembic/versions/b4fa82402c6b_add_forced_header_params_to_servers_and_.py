# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/b4fa82402c6b_add_forced_header_params_to_servers_and_.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add forced_header_params to servers and gateways

Revision ID: b4fa82402c6b
Revises: 86a6a377e442
Create Date: 2026-10-04
"""

# Standard
from typing import Sequence, Union

# Third-Party
import sqlalchemy as sa
from alembic import op

revision: str = "b4fa82402c6b"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "86a6a377e442"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the forced_header_params JSON columns."""
    inspector = sa.inspect(op.get_bind())
    if "servers" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("servers")]
        if "forced_header_params" not in columns:
            op.add_column("servers", sa.Column("forced_header_params", sa.JSON(), nullable=True))
    if "gateways" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("gateways")]
        if "forced_header_params" not in columns:
            op.add_column("gateways", sa.Column("forced_header_params", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop the forced_header_params columns."""
    inspector = sa.inspect(op.get_bind())
    if "servers" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("servers")]
        if "forced_header_params" in columns:
            op.drop_column("servers", "forced_header_params")
    if "gateways" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("gateways")]
        if "forced_header_params" in columns:
            op.drop_column("gateways", "forced_header_params")
