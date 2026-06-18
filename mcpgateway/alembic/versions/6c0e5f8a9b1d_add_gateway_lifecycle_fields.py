# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/6c0e5f8a9b1d_add_gateway_lifecycle_fields.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add_gateway_lifecycle_fields

Revision ID: 6c0e5f8a9b1d
Revises: 0a089912b5f0
Create Date: 2026-06-11
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "6c0e5f8a9b1d"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "0a089912b5f0"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


GATEWAY_TABLE = "gateways"
LIFECYCLE_INDEX = "idx_gateways_status_next_retry_at"
CLAIM_INDEX = "idx_gateways_lifecycle_claim"
LIFECYCLE_COLUMNS = (
    "status",
    "status_message",
    "registration_attempts",
    "next_retry_at",
    "last_error",
    "lifecycle_claimed_by",
    "lifecycle_claimed_at",
    "lifecycle_claim_expires_at",
)


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    """Return whether a table exists."""
    return table_name in inspector.get_table_names()


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    """Return column names for a table."""
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_exists(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    """Return whether an index exists on a table."""
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    """Add lifecycle state, retry metadata, and claim lease fields to gateways."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Fresh databases may already have model-created columns/indexes before this
    # migration runs, so every schema step stays existence-checked and idempotent.
    if not _table_exists(inspector, GATEWAY_TABLE):
        return

    columns = _column_names(inspector, GATEWAY_TABLE)

    if "status" not in columns:
        op.add_column(GATEWAY_TABLE, sa.Column("status", sa.String(length=20), nullable=False, server_default="active"))

    if "status_message" not in columns:
        op.add_column(GATEWAY_TABLE, sa.Column("status_message", sa.Text(), nullable=True))

    if "registration_attempts" not in columns:
        op.add_column(GATEWAY_TABLE, sa.Column("registration_attempts", sa.Integer(), nullable=False, server_default="0"))

    if "next_retry_at" not in columns:
        op.add_column(GATEWAY_TABLE, sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))

    if "last_error" not in columns:
        op.add_column(GATEWAY_TABLE, sa.Column("last_error", sa.Text(), nullable=True))

    if "lifecycle_claimed_by" not in columns:
        op.add_column(GATEWAY_TABLE, sa.Column("lifecycle_claimed_by", sa.String(length=64), nullable=True))

    if "lifecycle_claimed_at" not in columns:
        op.add_column(GATEWAY_TABLE, sa.Column("lifecycle_claimed_at", sa.DateTime(timezone=True), nullable=True))

    if "lifecycle_claim_expires_at" not in columns:
        op.add_column(GATEWAY_TABLE, sa.Column("lifecycle_claim_expires_at", sa.DateTime(timezone=True), nullable=True))

    inspector = sa.inspect(bind)
    columns = _column_names(inspector, GATEWAY_TABLE)
    if {"status", "next_retry_at"}.issubset(columns) and not _index_exists(inspector, GATEWAY_TABLE, LIFECYCLE_INDEX):
        op.create_index(LIFECYCLE_INDEX, GATEWAY_TABLE, ["status", "next_retry_at"], unique=False)

    inspector = sa.inspect(bind)
    columns = _column_names(inspector, GATEWAY_TABLE)
    if {"status", "next_retry_at", "lifecycle_claim_expires_at"}.issubset(columns) and not _index_exists(inspector, GATEWAY_TABLE, CLAIM_INDEX):
        op.create_index(CLAIM_INDEX, GATEWAY_TABLE, ["status", "next_retry_at", "lifecycle_claim_expires_at"], unique=False)


def downgrade() -> None:
    """Remove lifecycle state, retry metadata, and claim lease fields from gateways."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Keep downgrade resilient for partial/manual states by dropping only objects
    # that still exist on the current database.
    if not _table_exists(inspector, GATEWAY_TABLE):
        return

    if _index_exists(inspector, GATEWAY_TABLE, LIFECYCLE_INDEX):
        op.drop_index(LIFECYCLE_INDEX, table_name=GATEWAY_TABLE)

    if _index_exists(inspector, GATEWAY_TABLE, CLAIM_INDEX):
        op.drop_index(CLAIM_INDEX, table_name=GATEWAY_TABLE)

    inspector = sa.inspect(bind)
    columns = _column_names(inspector, GATEWAY_TABLE)
    for column_name in reversed(LIFECYCLE_COLUMNS):
        if column_name in columns:
            op.drop_column(GATEWAY_TABLE, column_name)
