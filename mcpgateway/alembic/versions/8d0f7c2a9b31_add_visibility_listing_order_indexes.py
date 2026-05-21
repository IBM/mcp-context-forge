# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/8d0f7c2a9b31_add_visibility_listing_order_indexes.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

add visibility listing order indexes

Revision ID: 8d0f7c2a9b31
Revises: 351b43e1d273
Create Date: 2026-05-18 14:25:00.000000

The Alembic environment runs migrations inside a transaction, so PostgreSQL
CONCURRENTLY cannot be used here. A short lock timeout prevents indefinite
blocking; very large production tables can create these indexes concurrently
before running this migration.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8d0f7c2a9b31"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "351b43e1d273"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VISIBILITY_TABLES = ("tools", "resources", "prompts", "servers", "gateways", "a2a_agents")
REQUIRED_COLUMNS = {"id", "team_id", "owner_email", "visibility", "enabled", "created_at"}


def _index_specs(table_name: str) -> tuple[tuple[str, list[str], str], ...]:
    """Return ordered partial index definitions for one visibility table."""
    return (
        (
            f"idx_{table_name}_private_owner_team_order",
            ["team_id", "owner_email", "created_at", "id"],
            "enabled AND visibility = 'private'",
        ),
    )


def upgrade() -> None:
    """Add ordered partial indexes for visibility-filtered list queries."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    op.execute("SET LOCAL lock_timeout = '5s'")

    for table_name in VISIBILITY_TABLES:
        if table_name not in tables:
            continue

        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if not REQUIRED_COLUMNS.issubset(columns):
            continue

        existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        for index_name, index_columns, predicate in _index_specs(table_name):
            if index_name in existing_indexes:
                continue

            op.create_index(
                index_name,
                table_name,
                index_columns,
                unique=False,
                postgresql_where=sa.text(predicate),
            )


def downgrade() -> None:
    """Drop ordered partial indexes for visibility-filtered list queries."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    op.execute("SET LOCAL lock_timeout = '5s'")

    for table_name in VISIBILITY_TABLES:
        if table_name not in tables:
            continue

        existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        for index_name, _, _ in _index_specs(table_name):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name=table_name)
