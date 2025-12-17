# -*- coding: utf-8 -*-
"""Add performance monitoring tables for system metrics tracking.

Revision ID: m7g8h9i0j1k2
Revises: l6f7g8h9i0j1
Create Date: 2025-12-17 10:00:00.000000

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "m7g8h9i0j1k2"
down_revision: Union[str, Sequence[str], None] = "l6f7g8h9i0j1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add performance monitoring tables."""
    # Check if tables already exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Create performance_snapshots table
    if "performance_snapshots" not in existing_tables:
        op.create_table(
            "performance_snapshots",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("host", sa.String(length=255), nullable=False),
            sa.Column("worker_id", sa.String(length=64), nullable=True),
            sa.Column("metrics_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_performance_snapshots_timestamp", "performance_snapshots", ["timestamp"])
        op.create_index("idx_performance_snapshots_host_timestamp", "performance_snapshots", ["host", "timestamp"])
        op.create_index("idx_performance_snapshots_created_at", "performance_snapshots", ["created_at"])

    # Create performance_aggregates table
    if "performance_aggregates" not in existing_tables:
        op.create_table(
            "performance_aggregates",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_type", sa.String(length=20), nullable=False),
            sa.Column("host", sa.String(length=255), nullable=True),
            # Request aggregates
            sa.Column("requests_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requests_2xx", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requests_4xx", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requests_5xx", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_response_time_ms", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("p95_response_time_ms", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("peak_requests_per_second", sa.Float(), nullable=False, server_default="0.0"),
            # Resource aggregates
            sa.Column("avg_cpu_percent", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("avg_memory_percent", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("peak_cpu_percent", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("peak_memory_percent", sa.Float(), nullable=False, server_default="0.0"),
            # Timestamps
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("period_type", "period_start", "host", name="uq_performance_aggregate_period_host"),
        )
        op.create_index("idx_performance_aggregates_period", "performance_aggregates", ["period_type", "period_start"])
        op.create_index("idx_performance_aggregates_host_period", "performance_aggregates", ["host", "period_type", "period_start"])


def downgrade() -> None:
    """Remove performance monitoring tables."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "performance_aggregates" in existing_tables:
        op.drop_index("idx_performance_aggregates_host_period", table_name="performance_aggregates")
        op.drop_index("idx_performance_aggregates_period", table_name="performance_aggregates")
        op.drop_table("performance_aggregates")

    if "performance_snapshots" in existing_tables:
        op.drop_index("idx_performance_snapshots_created_at", table_name="performance_snapshots")
        op.drop_index("idx_performance_snapshots_host_timestamp", table_name="performance_snapshots")
        op.drop_index("idx_performance_snapshots_timestamp", table_name="performance_snapshots")
        op.drop_table("performance_snapshots")
