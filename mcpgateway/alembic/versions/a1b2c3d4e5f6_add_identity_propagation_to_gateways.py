# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/a1b2c3d4e5f6_add_identity_propagation_to_gateways.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add identity_propagation to gateways

Revision ID: a1b2c3d4e5f6
Revises: d2b501bf4262
Create Date: 2026-02-17
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d2b501bf4262"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add identity_propagation JSON column to gateways table."""
    inspector = sa.inspect(op.get_bind())

    if "gateways" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("gateways")]
    if "identity_propagation" in columns:
        return

    op.add_column("gateways", sa.Column("identity_propagation", sa.JSON(), nullable=True, comment="Per-gateway identity propagation config overrides"))


def downgrade() -> None:
    """Remove identity_propagation column from gateways table."""
    inspector = sa.inspect(op.get_bind())

    if "gateways" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("gateways")]
    if "identity_propagation" not in columns:
        return

    op.drop_column("gateways", "identity_propagation")
