# -*- coding: utf-8 -*-
"""Add refresh_interval_seconds and last_refresh_at to gateways table.

Revision ID: a8f3b2c1d4e5
Revises: 77243f5bfce5
Create Date: 2026-01-09

This migration adds two new columns to the gateways table for per-gateway
refresh configuration:
- refresh_interval_seconds: Per-gateway refresh interval (nullable, uses global default if NULL)
- last_refresh_at: Timestamp of the last successful tools/resources/prompts refresh
"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a8f3b2c1d4e5"
down_revision = "77243f5bfce5"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check whether a column exists in a given database table.

    Args:
        table_name: Name of the database table to inspect.
        column_name: Name of the column to check for existence.

    Returns:
        True if the column exists in the table, False otherwise.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def upgrade() -> None:
    """Add refresh-related columns to the gateways table if they are missing.

    This migration conditionally adds:
    - `refresh_interval_seconds`: A per-gateway refresh interval override.
    - `last_refresh_at`: Timestamp of the last successful refresh.

    Columns are added only if they do not already exist, allowing the
    migration to be safely re-run or applied to partially migrated schemas.
    """

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
    """Remove refresh-related columns from the gateways table if present.

    This rollback conditionally drops:
    - `last_refresh_at`
    - `refresh_interval_seconds`

    Columns are removed only if they exist, ensuring safe downgrade behavior
    across different schema states.
    """

    if _column_exists("gateways", "last_refresh_at"):
        op.drop_column("gateways", "last_refresh_at")

    if _column_exists("gateways", "refresh_interval_seconds"):
        op.drop_column("gateways", "refresh_interval_seconds")
