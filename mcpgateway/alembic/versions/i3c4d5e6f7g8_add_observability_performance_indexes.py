# -*- coding: utf-8 -*-
"""add observability performance indexes

Revision ID: i3c4d5e6f7g8
Revises: a23a08d61eb0
Create Date: 2025-01-05 12:00:00.000000

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i3c4d5e6f7g8"
down_revision: Union[str, Sequence[str], None] = "a23a08d61eb0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add performance indexes for observability tables.

    These composite indexes optimize common query patterns:
    - Filtering by time range WITH status (composite)
    - Filtering by duration (new)
    - Filtering by HTTP method WITH time (composite)
    - Filtering by resource type WITH time (composite)
    - Filtering by span kind WITH status (composite)

    Note: Basic indexes (status, start_time, resource_type, etc.) already exist
    from the initial migration. This migration adds COMPOSITE indexes only.
    """
    # ObservabilityTrace composite indexes
    op.create_index("ix_observability_traces_status_start_time", "observability_traces", ["status", "start_time"])
    op.create_index("ix_observability_traces_duration_ms", "observability_traces", ["duration_ms"])
    op.create_index("ix_observability_traces_http_method_start_time", "observability_traces", ["http_method", "start_time"])
    op.create_index("ix_observability_traces_name", "observability_traces", ["name"])

    # ObservabilitySpan composite indexes
    op.create_index("ix_observability_spans_trace_id_start_time", "observability_spans", ["trace_id", "start_time"])
    op.create_index("ix_observability_spans_resource_type_start_time", "observability_spans", ["resource_type", "start_time"])
    op.create_index("ix_observability_spans_kind_status", "observability_spans", ["kind", "status"])
    op.create_index("ix_observability_spans_duration_ms", "observability_spans", ["duration_ms"])
    op.create_index("ix_observability_spans_name", "observability_spans", ["name"])

    # ObservabilityEvent composite index
    op.create_index("ix_observability_events_span_id_timestamp", "observability_events", ["span_id", "timestamp"])


def downgrade() -> None:
    """Remove observability performance indexes."""
    # Drop ObservabilityEvent composite index
    op.drop_index("ix_observability_events_span_id_timestamp", table_name="observability_events")

    # Drop ObservabilitySpan composite indexes
    op.drop_index("ix_observability_spans_name", table_name="observability_spans")
    op.drop_index("ix_observability_spans_duration_ms", table_name="observability_spans")
    op.drop_index("ix_observability_spans_kind_status", table_name="observability_spans")
    op.drop_index("ix_observability_spans_resource_type_start_time", table_name="observability_spans")
    op.drop_index("ix_observability_spans_trace_id_start_time", table_name="observability_spans")

    # Drop ObservabilityTrace composite indexes
    op.drop_index("ix_observability_traces_name", table_name="observability_traces")
    op.drop_index("ix_observability_traces_http_method_start_time", table_name="observability_traces")
    op.drop_index("ix_observability_traces_duration_ms", table_name="observability_traces")
    op.drop_index("ix_observability_traces_status_start_time", table_name="observability_traces")
