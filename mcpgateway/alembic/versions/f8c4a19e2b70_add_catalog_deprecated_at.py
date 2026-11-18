# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/f8c4a19e2b70_add_catalog_deprecated_at.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add deprecated_at to tools and deprecated / deprecated_at to resources and prompts.

Revision ID: f8c4a19e2b70
Revises: 7ac83e50bd12
Create Date: 2026-11-18
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f8c4a19e2b70"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "7ac83e50bd12"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE_COLUMNS = (
    ("tools", (("deprecated_at", sa.DateTime(timezone=True)),)),
    (
        "resources",
        (
            ("deprecated", sa.Boolean()),
            ("deprecated_at", sa.DateTime(timezone=True)),
        ),
    ),
    (
        "prompts",
        (
            ("deprecated", sa.Boolean()),
            ("deprecated_at", sa.DateTime(timezone=True)),
        ),
    ),
)


def upgrade() -> None:
    """Add catalog deprecation columns used to retain stale tools, resources, and prompts."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table_name, columns in _TABLE_COLUMNS:
        if table_name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, column_type in columns:
            if column_name in existing_columns:
                continue
            if column_name == "deprecated":
                op.add_column(table_name, sa.Column(column_name, column_type, nullable=False, server_default=sa.false()))
            else:
                op.add_column(table_name, sa.Column(column_name, column_type, nullable=True))
        # Re-inspect after adds so later tables still see a fresh column list if needed
        inspector = sa.inspect(bind)


def downgrade() -> None:
    """Remove catalog deprecation columns when present."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table_name, columns in _TABLE_COLUMNS:
        if table_name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, _column_type in reversed(columns):
            if column_name not in existing_columns:
                continue
            op.drop_column(table_name, column_name)
        inspector = sa.inspect(bind)
