# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/87e895734718_add_tools_name_index.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add non-unique index on tools.name.

Revision ID: 87e895734718
Revises: c7e91a2b4d60

Tool lookup and federated collision checks filter by ``tools.name``. The global
unique constraint on that column was removed for multi-tenancy (e28cd485ad3c),
which also removed the only index usable for those lookups. This migration adds
a plain, non-unique index. It is a lookup aid only: it does not enforce or
imply uniqueness, accepts existing duplicate names across teams and private
scopes, and does not close check-and-insert races.

Follow-up to #6534. Fixes #7044.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "87e895734718"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "c7e91a2b4d60"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "tools"
INDEX_NAME = "idx_tools_name"
COLUMNS = ["name"]


def _index_names(inspector) -> set[str]:
    """Return the names of all indexes on the tools table.

    Args:
        inspector: SQLAlchemy inspector bound to the migration connection.

    Returns:
        set[str]: Index names currently defined on ``tools``.
    """
    return {index["name"] for index in inspector.get_indexes(TABLE_NAME)}


def upgrade() -> None:
    """Create the non-unique ``tools.name`` index if it is missing."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME):
        return
    if INDEX_NAME in _index_names(inspector):
        return
    op.create_index(INDEX_NAME, TABLE_NAME, COLUMNS, unique=False)


def downgrade() -> None:
    """Drop the ``tools.name`` index if it exists."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME):
        return
    if INDEX_NAME not in _index_names(inspector):
        return
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
