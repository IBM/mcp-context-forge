# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/615af4ab94b4_add_gateway_client_cert_and_key.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add_gateway_client_cert_and_key

Revision ID: 615af4ab94b4
Revises: 20a0e0538ac5
Create Date: 2026-03-20 10:47:06.592968
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "615af4ab94b4"
down_revision: Union[str, Sequence[str], None] = "20a0e0538ac5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "gateways" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("gateways")]

    if "client_cert" not in columns:
        op.add_column("gateways", sa.Column("client_cert", sa.Text(), nullable=True))

    if "client_key" not in columns:
        op.add_column("gateways", sa.Column("client_key", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "gateways" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("gateways")]

    if "client_cert" in columns:
        op.drop_column("gateways", "client_cert")

    if "client_key" in columns:
        op.drop_column("gateways", "client_key")
