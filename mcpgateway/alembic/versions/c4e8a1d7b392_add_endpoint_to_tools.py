# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/c4e8a1d7b392_add_endpoint_to_tools.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add endpoint to tools.

Revision ID: c4e8a1d7b392
Revises: b7e291a4c630

The column stores the gateway-relative path of a REST tool. At invocation time the
gateway URL and this path form the upstream URL. NULL means the tool stores an absolute
``url`` instead.

The downgrade drops the column. Older code needs an absolute ``url`` and does not know
``auth_type = 'inherit'``. The downgrade therefore disables each tool that has an
endpoint and clears ``auth_type`` on each inheriting tool. An operator re-enables those
tools after setting a URL and an auth type.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "c4e8a1d7b392"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b7e291a4c630"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable endpoint column when it is missing."""
    inspector = sa.inspect(op.get_bind())
    if "tools" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("tools")]
    if "endpoint" in columns:
        return
    op.add_column("tools", sa.Column("endpoint", sa.String(767), nullable=True))


def downgrade() -> None:
    """Disable and reset tools that use endpoint or inherit, then drop the endpoint column when it exists."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tools" not in inspector.get_table_names():
        return
    columns = [column["name"] for column in inspector.get_columns("tools")]
    if "endpoint" not in columns:
        return
    tools = sa.table("tools", sa.column("auth_type", sa.String), sa.column("enabled", sa.Boolean), sa.column("endpoint", sa.String))
    bind.execute(sa.update(tools).where(tools.c.endpoint.is_not(None)).values(enabled=False))
    bind.execute(sa.update(tools).where(tools.c.auth_type == "inherit").values(enabled=False, auth_type=None))
    with op.batch_alter_table("tools") as batch:
        batch.drop_column("endpoint")
