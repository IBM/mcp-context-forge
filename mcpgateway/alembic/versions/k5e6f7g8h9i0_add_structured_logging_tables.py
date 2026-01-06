# -*- coding: utf-8 -*-
"""Add structured logging tables

Revision ID: k5e6f7g8h9i0
Revises: 356a2d4eed6f
Create Date: 2025-01-15 12:00:00.000000

"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "k5e6f7g8h9i0"
down_revision = "356a2d4eed6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add structured logging tables."""
    # Create structured_log_entries table
    op.create_table(
        "structured_log_entries",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("component", sa.String(100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("logger", sa.String(255), nullable=True),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_path", sa.String(500), nullable=True),
        sa.Column("request_method", sa.String(10), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("operation_type", sa.String(100), nullable=True),
        sa.Column("is_security_event", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("security_severity", sa.String(20), nullable=True),
        sa.Column("threat_indicators", sa.JSON(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=True),
        sa.Column("performance_metrics", sa.JSON(), nullable=True),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=True),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("environment", sa.String(50), nullable=False, server_default="production"),
        sa.Column("trace_id", sa.String(32), nullable=True),
        sa.Column("span_id", sa.String(16), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for structured_log_entries
    op.create_index("ix_structured_log_entries_timestamp", "structured_log_entries", ["timestamp"], unique=False)
    op.create_index("ix_structured_log_entries_level", "structured_log_entries", ["level"], unique=False)
    op.create_index("ix_structured_log_entries_component", "structured_log_entries", ["component"], unique=False)
    op.create_index("ix_structured_log_entries_correlation_id", "structured_log_entries", ["correlation_id"], unique=False)
    op.create_index("ix_structured_log_entries_request_id", "structured_log_entries", ["request_id"], unique=False)
    op.create_index("ix_structured_log_entries_user_id", "structured_log_entries", ["user_id"], unique=False)
    op.create_index("ix_structured_log_entries_user_email", "structured_log_entries", ["user_email"], unique=False)
    op.create_index("ix_structured_log_entries_operation_type", "structured_log_entries", ["operation_type"], unique=False)
    op.create_index("ix_structured_log_entries_is_security_event", "structured_log_entries", ["is_security_event"], unique=False)
    op.create_index("ix_structured_log_entries_security_severity", "structured_log_entries", ["security_severity"], unique=False)
    op.create_index("ix_structured_log_entries_trace_id", "structured_log_entries", ["trace_id"], unique=False)

    # Composite indexes matching db.py
    op.create_index("idx_log_correlation_time", "structured_log_entries", ["correlation_id", "timestamp"], unique=False)
    op.create_index("idx_log_user_time", "structured_log_entries", ["user_id", "timestamp"], unique=False)
    op.create_index("idx_log_level_time", "structured_log_entries", ["level", "timestamp"], unique=False)
    op.create_index("idx_log_component_time", "structured_log_entries", ["component", "timestamp"], unique=False)
    op.create_index("idx_log_security", "structured_log_entries", ["is_security_event", "security_severity", "timestamp"], unique=False)
    op.create_index("idx_log_operation", "structured_log_entries", ["operation_type", "timestamp"], unique=False)
    op.create_index("idx_log_trace", "structured_log_entries", ["trace_id", "timestamp"], unique=False)

    # Create performance_metrics table
    op.create_table(
        "performance_metrics",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("operation_type", sa.String(100), nullable=False),
        sa.Column("component", sa.String(100), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("avg_duration_ms", sa.Float(), nullable=False),
        sa.Column("min_duration_ms", sa.Float(), nullable=False),
        sa.Column("max_duration_ms", sa.Float(), nullable=False),
        sa.Column("p50_duration_ms", sa.Float(), nullable=False),
        sa.Column("p95_duration_ms", sa.Float(), nullable=False),
        sa.Column("p99_duration_ms", sa.Float(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("metric_metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for performance_metrics
    op.create_index("ix_performance_metrics_timestamp", "performance_metrics", ["timestamp"], unique=False)
    op.create_index("ix_performance_metrics_component", "performance_metrics", ["component"], unique=False)
    op.create_index("ix_performance_metrics_operation_type", "performance_metrics", ["operation_type"], unique=False)
    op.create_index("ix_performance_metrics_window_start", "performance_metrics", ["window_start"], unique=False)
    op.create_index("idx_perf_operation_time", "performance_metrics", ["operation_type", "window_start"], unique=False)
    op.create_index("idx_perf_component_time", "performance_metrics", ["component", "window_start"], unique=False)
    op.create_index("idx_perf_window", "performance_metrics", ["window_start", "window_end"], unique=False)

    # Create security_events table
    op.create_table(
        "security_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("log_entry_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("client_ip", sa.String(45), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("action_taken", sa.String(100), nullable=True),
        sa.Column("threat_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("threat_indicators", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("failed_attempts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(255), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("alert_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("alert_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alert_recipients", sa.JSON(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["log_entry_id"], ["structured_log_entries.id"]),
    )

    # Create indexes for security_events
    op.create_index("ix_security_events_timestamp", "security_events", ["timestamp"], unique=False)
    op.create_index("ix_security_events_detected_at", "security_events", ["detected_at"], unique=False)
    op.create_index("ix_security_events_correlation_id", "security_events", ["correlation_id"], unique=False)
    op.create_index("ix_security_events_event_type", "security_events", ["event_type"], unique=False)
    op.create_index("ix_security_events_severity", "security_events", ["severity"], unique=False)
    op.create_index("ix_security_events_category", "security_events", ["category"], unique=False)
    op.create_index("ix_security_events_user_id", "security_events", ["user_id"], unique=False)
    op.create_index("ix_security_events_user_email", "security_events", ["user_email"], unique=False)
    op.create_index("ix_security_events_client_ip", "security_events", ["client_ip"], unique=False)
    op.create_index("ix_security_events_log_entry_id", "security_events", ["log_entry_id"], unique=False)
    op.create_index("ix_security_events_resolved", "security_events", ["resolved"], unique=False)
    op.create_index("idx_security_type_time", "security_events", ["event_type", "timestamp"], unique=False)
    op.create_index("idx_security_severity_time", "security_events", ["severity", "timestamp"], unique=False)
    op.create_index("idx_security_user_time", "security_events", ["user_id", "timestamp"], unique=False)
    op.create_index("idx_security_ip_time", "security_events", ["client_ip", "timestamp"], unique=False)
    op.create_index("idx_security_unresolved", "security_events", ["resolved", "severity", "timestamp"], unique=False)

    # Create audit_trails table
    op.create_table(
        "audit_trails",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("resource_name", sa.String(500), nullable=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("team_id", sa.String(36), nullable=True),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_path", sa.String(500), nullable=True),
        sa.Column("request_method", sa.String(10), nullable=True),
        sa.Column("old_values", sa.JSON(), nullable=True),
        sa.Column("new_values", sa.JSON(), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=True),
        sa.Column("data_classification", sa.String(50), nullable=True),
        sa.Column("requires_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for audit_trails
    op.create_index("ix_audit_trails_timestamp", "audit_trails", ["timestamp"], unique=False)
    op.create_index("ix_audit_trails_correlation_id", "audit_trails", ["correlation_id"], unique=False)
    op.create_index("ix_audit_trails_request_id", "audit_trails", ["request_id"], unique=False)
    op.create_index("ix_audit_trails_action", "audit_trails", ["action"], unique=False)
    op.create_index("ix_audit_trails_resource_type", "audit_trails", ["resource_type"], unique=False)
    op.create_index("ix_audit_trails_resource_id", "audit_trails", ["resource_id"], unique=False)
    op.create_index("ix_audit_trails_user_id", "audit_trails", ["user_id"], unique=False)
    op.create_index("ix_audit_trails_user_email", "audit_trails", ["user_email"], unique=False)
    op.create_index("ix_audit_trails_team_id", "audit_trails", ["team_id"], unique=False)
    op.create_index("ix_audit_trails_data_classification", "audit_trails", ["data_classification"], unique=False)
    op.create_index("ix_audit_trails_requires_review", "audit_trails", ["requires_review"], unique=False)
    op.create_index("ix_audit_trails_success", "audit_trails", ["success"], unique=False)
    op.create_index("idx_audit_action_time", "audit_trails", ["action", "timestamp"], unique=False)
    op.create_index("idx_audit_resource_time", "audit_trails", ["resource_type", "resource_id", "timestamp"], unique=False)
    op.create_index("idx_audit_user_time", "audit_trails", ["user_id", "timestamp"], unique=False)
    op.create_index("idx_audit_classification", "audit_trails", ["data_classification", "timestamp"], unique=False)
    op.create_index("idx_audit_review", "audit_trails", ["requires_review", "timestamp"], unique=False)


def downgrade() -> None:
    """Remove structured logging tables."""
    op.drop_table("audit_trails")
    op.drop_table("security_events")
    op.drop_table("performance_metrics")
    op.drop_table("structured_log_entries")
