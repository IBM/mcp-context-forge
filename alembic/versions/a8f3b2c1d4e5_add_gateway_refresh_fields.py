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

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a8f3b2c1d4e5'
down_revision = '77243f5bfce5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add refresh_interval_seconds and last_refresh_at columns to gateways table."""
    # Add refresh_interval_seconds column
    op.add_column('gateways', sa.Column(
        'refresh_interval_seconds',
        sa.Integer(),
        nullable=True,
        comment='Per-gateway refresh interval in seconds; NULL uses global default'
    ))

    # Add last_refresh_at column
    op.add_column('gateways', sa.Column(
        'last_refresh_at',
        sa.DateTime(timezone=True),
        nullable=True,
        comment='Timestamp of the last successful tools/resources/prompts refresh'
    ))


def downgrade() -> None:
    """Remove refresh_interval_seconds and last_refresh_at columns from gateways table."""
    op.drop_column('gateways', 'last_refresh_at')
    op.drop_column('gateways', 'refresh_interval_seconds')
