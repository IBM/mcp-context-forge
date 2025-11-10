# -*- coding: utf-8 -*-
"""add_observability_tables

Revision ID: a23a08d61eb0
Revises: a706a3320c56
Create Date: 2025-11-05 02:37:14.539024

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a23a08d61eb0"
down_revision: Union[str, Sequence[str], None] = "a706a3320c56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add observability tables."""

    # Create observability_traces table
    op.create_table(
        "observability_traces",
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unset"),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("http_method", sa.String(length=10), nullable=True),
        sa.Column("http_url", sa.String(length=767), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("user_email", sa.String(length=255), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("resource_attributes", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("trace_id"),
    )
    op.create_index("idx_observability_traces_start_time", "observability_traces", ["start_time"])
    op.create_index("idx_observability_traces_user_email", "observability_traces", ["user_email"])
    op.create_index("idx_observability_traces_status", "observability_traces", ["status"])
    op.create_index("idx_observability_traces_http_status_code", "observability_traces", ["http_status_code"])

    # Create observability_spans table
    op.create_table(
        "observability_spans",
        sa.Column("span_id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("parent_span_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="internal"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unset"),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("resource_name", sa.String(length=255), nullable=True),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trace_id"], ["observability_traces.trace_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_span_id"], ["observability_spans.span_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("span_id"),
    )
    op.create_index("idx_observability_spans_trace_id", "observability_spans", ["trace_id"])
    op.create_index("idx_observability_spans_parent_span_id", "observability_spans", ["parent_span_id"])
    op.create_index("idx_observability_spans_start_time", "observability_spans", ["start_time"])
    op.create_index("idx_observability_spans_resource_type", "observability_spans", ["resource_type"])
    op.create_index("idx_observability_spans_resource_name", "observability_spans", ["resource_name"])

    # Create observability_events table
    op.create_table(
        "observability_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("span_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("exception_type", sa.String(length=255), nullable=True),
        sa.Column("exception_message", sa.Text(), nullable=True),
        sa.Column("exception_stacktrace", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["span_id"], ["observability_spans.span_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_observability_events_span_id", "observability_events", ["span_id"])
    op.create_index("idx_observability_events_timestamp", "observability_events", ["timestamp"])
    op.create_index("idx_observability_events_severity", "observability_events", ["severity"])

    # Create observability_metrics table
    op.create_table(
        "observability_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("metric_type", sa.String(length=20), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", sa.String(length=36), nullable=True),
        sa.Column("trace_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trace_id"], ["observability_traces.trace_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_observability_metrics_name_timestamp", "observability_metrics", ["name", "timestamp"])
    op.create_index("idx_observability_metrics_resource_type", "observability_metrics", ["resource_type"])
    op.create_index("idx_observability_metrics_trace_id", "observability_metrics", ["trace_id"])


def downgrade() -> None:
    """Downgrade schema - remove observability tables."""
    op.drop_index("idx_observability_metrics_trace_id", table_name="observability_metrics")
    op.drop_index("idx_observability_metrics_resource_type", table_name="observability_metrics")
    op.drop_index("idx_observability_metrics_name_timestamp", table_name="observability_metrics")
    op.drop_table("observability_metrics")

    op.drop_index("idx_observability_events_severity", table_name="observability_events")
    op.drop_index("idx_observability_events_timestamp", table_name="observability_events")
    op.drop_index("idx_observability_events_span_id", table_name="observability_events")
    op.drop_table("observability_events")

    op.drop_index("idx_observability_spans_resource_name", table_name="observability_spans")
    op.drop_index("idx_observability_spans_resource_type", table_name="observability_spans")
    op.drop_index("idx_observability_spans_start_time", table_name="observability_spans")
    op.drop_index("idx_observability_spans_parent_span_id", table_name="observability_spans")
    op.drop_index("idx_observability_spans_trace_id", table_name="observability_spans")
    op.drop_table("observability_spans")

    op.drop_index("idx_observability_traces_http_status_code", table_name="observability_traces")
    op.drop_index("idx_observability_traces_status", table_name="observability_traces")
    op.drop_index("idx_observability_traces_user_email", table_name="observability_traces")
    op.drop_index("idx_observability_traces_start_time", table_name="observability_traces")
    op.drop_table("observability_traces")
