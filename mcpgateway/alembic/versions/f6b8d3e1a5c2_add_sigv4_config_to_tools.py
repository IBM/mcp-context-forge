# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/f6b8d3e1a5c2_add_sigv4_config_to_tools.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add sigv4_config to tools.

Revision ID: f6b8d3e1a5c2
Revises: a7c3e9d1b5f2

The column stores the AWS Signature V4 configuration of a REST tool. The secret access
key and the session token inside it are encrypted. NULL means the tool has no SigV4
configuration of its own and inherits the gateway configuration, if any.

The downgrade drops the column. Older code does not know ``auth_type = 'sigv4'`` on a
tool, so the downgrade first disables each tool that uses it and clears its
``auth_type``. An operator re-enables those tools after setting another auth type.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "f6b8d3e1a5c2"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a7c3e9d1b5f2"  # pragma: allowlist secret
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
    """Disable and reset tools that use sigv4, then drop the sigv4_config column when it exists."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tools" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("tools")]
    if "sigv4_config" not in columns:
        return
    tools = sa.table("tools", sa.column("auth_type", sa.String), sa.column("enabled", sa.Boolean))
    bind.execute(sa.update(tools).where(tools.c.auth_type == "sigv4").values(enabled=False, auth_type=None))
    with op.batch_alter_table("tools") as batch:
        batch.drop_column("sigv4_config")
