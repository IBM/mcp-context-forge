# -*- coding: utf-8 -*-
"""Add refresh_interval_seconds and last_refresh_at to gateways table.

Revision ID: a8f3b2c1d4e5
Revises: 5f3c681b05e1
Create Date: 2026-01-09

This migration adds two new columns to the gateways table for per-gateway
refresh configuration:
- refresh_interval_seconds: Per-gateway refresh interval (nullable, uses global default if NULL)
- last_refresh_at: Timestamp of the last successful tools/resources/prompts refresh
"""

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = "a8f3b2c1d4e5"
down_revision = "5f3c681b05e1"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def upgrade() -> None:
    """Add refresh_interval_seconds and last_refresh_at columns to gateways table if missing."""

    if not _column_exists("gateways", "refresh_interval_seconds"):
        op.add_column(
            "gateways",
            sa.Column(
                "refresh_interval_seconds",
                sa.Integer(),
                nullable=True,
                comment="Per-gateway refresh interval in seconds; NULL uses global default",
            ),
        )

    if not _column_exists("gateways", "last_refresh_at"):
        op.add_column(
            "gateways",
            sa.Column(
                "last_refresh_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="Timestamp of the last successful tools/resources/prompts refresh",
            ),
        )


def downgrade() -> None:
    """Remove refresh_interval_seconds and last_refresh_at columns from gateways table if present."""

    if _column_exists("gateways", "last_refresh_at"):
        op.drop_column("gateways", "last_refresh_at")

    if _column_exists("gateways", "refresh_interval_seconds"):
        op.drop_column("gateways", "refresh_interval_seconds")
