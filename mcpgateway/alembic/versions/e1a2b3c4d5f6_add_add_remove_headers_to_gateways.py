# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/e1a2b3c4d5f6_add_add_remove_headers_to_gateways.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add add_headers and remove_headers columns to gateways table.

These support per-backend static header injection (add_headers) and header
stripping (remove_headers) as consumed by the dataplane BackendConfig contract.

Revision ID: e1a2b3c4d5f6
Revises: d21698ae4a19
Create Date: 2026-07-30
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e1a2b3c4d5f6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d21698ae4a19"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add add_headers and remove_headers columns to gateways table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "gateways" not in inspector.get_table_names():
        # Fresh database — models create the columns directly via db.py.
        return

    existing_columns = {col["name"] for col in inspector.get_columns("gateways")}

    if "add_headers" not in existing_columns:
        op.add_column("gateways", sa.Column("add_headers", sa.JSON(), nullable=True))

    if "remove_headers" not in existing_columns:
        op.add_column("gateways", sa.Column("remove_headers", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop add_headers and remove_headers columns from gateways table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "gateways" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("gateways")}

    if "remove_headers" in existing_columns:
        op.drop_column("gateways", "remove_headers")

    if "add_headers" in existing_columns:
        op.drop_column("gateways", "add_headers")
