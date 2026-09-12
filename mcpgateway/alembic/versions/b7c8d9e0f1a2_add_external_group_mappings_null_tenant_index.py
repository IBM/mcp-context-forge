# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/b7c8d9e0f1a2_add_external_group_mappings_null_tenant_index.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add_external_group_mappings_null_tenant_index

Revision ID: b7c8d9e0f1a2
Revises: e5f6a7b8c9d0
Create Date: 2026-09-12 09:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The plain unique constraint on (issuer, tenant, external_group_id) treats
# NULL tenants as distinct on both SQLite and PostgreSQL, so duplicate
# (issuer, external_group_id) rows could coexist when tenant IS NULL,
# weakening the one-group-to-one-team rule. This partial unique index closes
# the hole for the NULL-tenant case; the existing constraint keeps covering
# non-null tenants.
TABLE_NAME = "external_group_mappings"
INDEX_NAME = "uq_external_group_mappings_null_tenant"


def upgrade() -> None:
    """Create the partial unique index on (issuer, external_group_id) WHERE tenant IS NULL (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if the table does not exist (fresh DB uses db.py models directly,
    # which already declare this index on ExternalGroupMapping.__table_args__).
    if TABLE_NAME not in inspector.get_table_names():
        return

    indexes = {ix["name"] for ix in inspector.get_indexes(TABLE_NAME)}
    if INDEX_NAME not in indexes:
        op.create_index(
            INDEX_NAME,
            TABLE_NAME,
            ["issuer", "external_group_id"],
            unique=True,
            sqlite_where=sa.text("tenant IS NULL"),
            postgresql_where=sa.text("tenant IS NULL"),
        )


def downgrade() -> None:
    """Drop the partial unique index if present."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if TABLE_NAME not in inspector.get_table_names():
        return

    indexes = {ix["name"] for ix in inspector.get_indexes(TABLE_NAME)}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
