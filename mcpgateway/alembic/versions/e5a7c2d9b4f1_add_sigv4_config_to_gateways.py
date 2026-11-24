# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/e5a7c2d9b4f1_add_sigv4_config_to_gateways.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add sigv4_config to gateways.

Revision ID: e5a7c2d9b4f1
Revises: 4a7d9e2c6b18

The column stores the AWS Signature V4 configuration of a gateway. The secret access
key and the session token inside it are encrypted. NULL means the gateway does not use SigV4.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "e5a7c2d9b4f1"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "4a7d9e2c6b18"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable sigv4_config column when it is missing."""
    inspector = sa.inspect(op.get_bind())
    if "gateways" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("gateways")]
    if "sigv4_config" in columns:
        return
    op.add_column("gateways", sa.Column("sigv4_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop the sigv4_config column when it exists."""
    inspector = sa.inspect(op.get_bind())
    if "gateways" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("gateways")]
    if "sigv4_config" not in columns:
        return
    with op.batch_alter_table("gateways") as batch:
        batch.drop_column("sigv4_config")
