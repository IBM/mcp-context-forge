# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/f6b8d3e1a5c2_add_sigv4_config_to_tools.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add sigv4_config to tools.

Revision ID: f6b8d3e1a5c2
Revises: 7ac83e50bd12

The column stores the AWS Signature V4 configuration of a REST tool. The secret access
key and the session token inside it are encrypted. NULL means the tool has no SigV4
configuration of its own and inherits the gateway configuration, if any.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "f6b8d3e1a5c2"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "7ac83e50bd12"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable sigv4_config column when it is missing."""
    inspector = sa.inspect(op.get_bind())
    if "tools" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("tools")]
    if "sigv4_config" in columns:
        return
    op.add_column("tools", sa.Column("sigv4_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop the sigv4_config column when it exists."""
    inspector = sa.inspect(op.get_bind())
    if "tools" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("tools")]
    if "sigv4_config" not in columns:
        return
    with op.batch_alter_table("tools") as batch:
        batch.drop_column("sigv4_config")
