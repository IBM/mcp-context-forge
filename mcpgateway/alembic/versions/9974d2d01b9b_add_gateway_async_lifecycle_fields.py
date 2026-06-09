"""add_gateway_async_lifecycle_fields

Revision ID: 9974d2d01b9b
Revises: 0a089912b5f0
Create Date: 2026-06-07 19:49:18.480755

Add async lifecycle fields to gateways table for Issue #4565.

This migration adds columns to support asynchronous gateway lifecycle operations
(create, update, delete) with 202 Accepted responses and background worker processing.

New columns:
- status: Gateway lifecycle state (pending, active, deleting)
- status_message: User-facing status description
- status_updated_at: Timestamp of last status change
- registration_attempts: Retry counter for exponential backoff
- next_retry_at: Timestamp for next retry attempt
- last_error: Technical error details (internal only, not exposed in API)
- created_by: User email for audit trail (already exists, included for completeness)
- team_id: Team ID for audit trail (already exists, included for completeness)

Indexes:
- ix_gateway_status_retry: Composite index on (status, next_retry_at) for worker polling
- ix_gateway_status: Index on status for metrics queries

Hermetic Downgrade:
This migration uses the hermetic downgrade pattern. No runtime config is needed
for downgrade because all new columns can be safely dropped without data dependencies.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = '9974d2d01b9b'  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = '0a089912b5f0'  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REVISION = '9974d2d01b9b'  # pragma: allowlist secret


def upgrade() -> None:
    """Add async lifecycle fields to gateways table."""
    bind = op.get_bind()
    inspector = inspect(bind)

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "gateways" not in inspector.get_table_names():
        return

    # Get existing columns
    columns = [col["name"] for col in inspector.get_columns("gateways")]

    # Add status column (default="active" for existing gateways)
    if "status" not in columns:
        op.add_column(
            "gateways",
            sa.Column("status", sa.String(20), nullable=False, server_default="active")
        )
        # Note: SQLite doesn't support ALTER COLUMN DROP DEFAULT, but keeping server_default
        # is harmless (db.py model default="active" will be used for new rows)

    # Add status_message column (user-facing status description)
    if "status_message" not in columns:
        op.add_column(
            "gateways",
            sa.Column("status_message", sa.String(500), nullable=True)
        )

    # Add status_updated_at column
    if "status_updated_at" not in columns:
        op.add_column(
            "gateways",
            sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True)
        )
        # Backfill status_updated_at with created_at for existing gateways
        if "created_at" in columns:
            bind.execute(
                text("UPDATE gateways SET status_updated_at = created_at WHERE status_updated_at IS NULL")
            )

    # Add registration_attempts column (retry counter)
    if "registration_attempts" not in columns:
        op.add_column(
            "gateways",
            sa.Column("registration_attempts", sa.Integer, nullable=False, server_default="0")
        )
        # Note: SQLite doesn't support ALTER COLUMN DROP DEFAULT, but keeping server_default
        # is harmless (db.py model default=0 will be used for new rows)

    # Add next_retry_at column (timestamp for next retry)
    if "next_retry_at" not in columns:
        op.add_column(
            "gateways",
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True)
        )

    # Add last_error column (technical error details, internal only)
    if "last_error" not in columns:
        op.add_column(
            "gateways",
            sa.Column("last_error", sa.Text, nullable=True)
        )

    # Note: created_by and team_id already exist in Gateway model (lines 4629, 4687 in db.py)
    # They are included in the plan for completeness but don't need migration

    # Create indexes for worker polling and metrics
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("gateways")]

    if "ix_gateway_status_retry" not in existing_indexes:
        op.create_index(
            "ix_gateway_status_retry",
            "gateways",
            ["status", "next_retry_at"],
            unique=False
        )

    if "ix_gateway_status" not in existing_indexes:
        op.create_index(
            "ix_gateway_status",
            "gateways",
            ["status"],
            unique=False
        )


def downgrade() -> None:
    """Remove async lifecycle fields from gateways table.

    Hermetic downgrade: No runtime config needed. All new columns can be safely
    dropped. Gateways in pending/deleting state will be lost (acceptable for rollback).
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    # Skip if table doesn't exist
    if "gateways" not in inspector.get_table_names():
        return

    # Drop indexes first
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("gateways")]

    if "ix_gateway_status" in existing_indexes:
        op.drop_index("ix_gateway_status", table_name="gateways")

    if "ix_gateway_status_retry" in existing_indexes:
        op.drop_index("ix_gateway_status_retry", table_name="gateways")

    # Drop columns
    columns = [col["name"] for col in inspector.get_columns("gateways")]

    if "last_error" in columns:
        op.drop_column("gateways", "last_error")

    if "next_retry_at" in columns:
        op.drop_column("gateways", "next_retry_at")

    if "registration_attempts" in columns:
        op.drop_column("gateways", "registration_attempts")

    if "status_updated_at" in columns:
        op.drop_column("gateways", "status_updated_at")

    if "status_message" in columns:
        op.drop_column("gateways", "status_message")

    if "status" in columns:
        op.drop_column("gateways", "status")

    # Note: created_by and team_id are NOT dropped (they existed before this migration)

# Made with Bob
