# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/c8d9e0f1a2b3_add_grpc_sql_debug_platform.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add gRPC schema/health, governed SQL data APIs, and API debugging.

Revision ID: c8d9e0f1a2b3
Revises: d21698ae4a19
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "c8d9e0f1a2b3"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d21698ae4a19"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table_name: str) -> set[str]:
    """Return current columns for an existing table."""
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _add_columns(table_name: str, columns: list[sa.Column]) -> None:
    """Idempotently add nullable/defaulted columns without rebuilding tables."""
    if table_name not in sa.inspect(op.get_bind()).get_table_names():
        return
    existing = _column_names(table_name)
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)


def _ensure_index(table_name: str, index_name: str, columns: list[str]) -> None:
    """Create an index only when its table/columns exist and name is absent."""
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names() or not set(columns).issubset(_column_names(table_name)):
        return
    if index_name not in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    """Drop an index before removing any of its columns in SQLite batch mode."""
    inspector = sa.inspect(op.get_bind())
    if table_name in inspector.get_table_names() and index_name in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.drop_index(index_name, table_name=table_name)


def _ensure_foreign_key(table_name: str, constraint_name: str, local_column: str, remote_table: str, remote_column: str, ondelete: str) -> None:
    """Create a named foreign key when the reflected schema does not contain it."""
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names() or remote_table not in inspector.get_table_names() or local_column not in _column_names(table_name):
        return
    if any(local_column in (foreign_key.get("constrained_columns") or []) for foreign_key in inspector.get_foreign_keys(table_name)):
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.create_foreign_key(constraint_name, remote_table, [local_column], [remote_column], ondelete=ondelete)


def upgrade() -> None:
    """Create gRPC schema/health, governed SQL, and debug persistence state."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    _add_columns(
        "grpc_services",
        [
            sa.Column("discovery_mode", sa.String(20), nullable=False, server_default="auto"),
            sa.Column("active_artifact_id", sa.String(36), nullable=True),
            sa.Column("active_schema_hash", sa.String(64), nullable=True),
            sa.Column("reflected_schema_hash", sa.String(64), nullable=True),
            sa.Column("schema_drift", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("manifest_path", sa.String(1024), nullable=True),
            sa.Column("manifest_hash", sa.String(64), nullable=True),
            sa.Column("health_check_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("health_check_interval", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("health_check_timeout", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("health_failure_threshold", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("health_status", sa.String(20), nullable=False, server_default="unknown"),
            sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_health_error", sa.Text(), nullable=True),
        ],
    )

    if "grpc_schema_artifacts" not in tables:
        op.create_table(
            "grpc_schema_artifacts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("grpc_service_id", sa.String(36), sa.ForeignKey("grpc_services.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("source_type", sa.String(20), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("descriptor_set", sa.LargeBinary(), nullable=False),
            sa.Column("source_info", sa.JSON(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_by", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("grpc_service_id", "version", name="uq_grpc_schema_artifact_version"),
            sa.UniqueConstraint("grpc_service_id", "content_hash", name="uq_grpc_schema_artifact_hash"),
        )
        op.create_index("ix_grpc_schema_artifacts_grpc_service_id", "grpc_schema_artifacts", ["grpc_service_id"])
        op.create_index("ix_grpc_schema_artifacts_service_active", "grpc_schema_artifacts", ["grpc_service_id", "is_active"])

    if "grpc_health_samples" not in tables:
        op.create_table(
            "grpc_health_samples",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("grpc_service_id", sa.String(36), sa.ForeignKey("grpc_services.id", ondelete="CASCADE"), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("healthy", sa.Boolean(), nullable=False),
            sa.Column("check_type", sa.String(32), nullable=False),
            sa.Column("status_code", sa.String(64), nullable=True),
            sa.Column("latency_ms", sa.Float(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
        )
        op.create_index("ix_grpc_health_samples_grpc_service_id", "grpc_health_samples", ["grpc_service_id"])
        op.create_index("ix_grpc_health_service_timestamp", "grpc_health_samples", ["grpc_service_id", "timestamp"])

    if "grpc_metrics_hourly" not in tables:
        op.create_table(
            "grpc_metrics_hourly",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("grpc_service_id", sa.String(36), sa.ForeignKey("grpc_services.id", ondelete="SET NULL"), nullable=True),
            sa.Column("service_name", sa.String(255), nullable=False),
            sa.Column("method_name", sa.String(255), nullable=False),
            sa.Column("hour_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status_counts", sa.JSON(), nullable=False),
            sa.Column("p50_response_time", sa.Float(), nullable=True),
            sa.Column("p95_response_time", sa.Float(), nullable=True),
            sa.Column("p99_response_time", sa.Float(), nullable=True),
            sa.Column("request_bytes", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("response_bytes", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("grpc_service_id", "method_name", "hour_start", name="uq_grpc_metrics_service_method_hour"),
        )
        op.create_index("ix_grpc_metrics_hourly_grpc_service_id", "grpc_metrics_hourly", ["grpc_service_id"])
        op.create_index("ix_grpc_metrics_hourly_hour", "grpc_metrics_hourly", ["hour_start"])

    if "sql_data_sources" not in tables:
        op.create_table(
            "sql_data_sources",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False, unique=True),
            sa.Column("slug", sa.String(255), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("dialect", sa.String(40), nullable=False),
            sa.Column("connection_url", sa.Text(), nullable=False),
            sa.Column("masked_url", sa.String(767), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("reachable", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "sql_tables" not in tables:
        op.create_table(
            "sql_tables",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("source_id", sa.String(36), sa.ForeignKey("sql_data_sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("schema_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("schema_slug", sa.String(255), nullable=False),
            sa.Column("table_name", sa.String(255), nullable=False),
            sa.Column("table_slug", sa.String(255), nullable=False),
            sa.Column("object_type", sa.String(20), nullable=False, server_default="table"),
            sa.Column("columns", sa.JSON(), nullable=False),
            sa.Column("primary_key", sa.JSON(), nullable=False),
            sa.Column("unique_keys", sa.JSON(), nullable=False),
            sa.Column("schema_hash", sa.String(64), nullable=False),
            sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("exposed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("allow_query", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("allow_insert", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("allow_update", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("allow_delete", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("team_id", sa.String(36), sa.ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True),
            sa.Column("owner_email", sa.String(255), nullable=True),
            sa.Column("visibility", sa.String(20), nullable=False, server_default="private"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("source_id", "schema_name", "table_name", name="uq_sql_table_source_schema_name"),
            sa.UniqueConstraint("source_id", "schema_slug", "table_slug", name="uq_sql_table_source_slugs"),
        )
        op.create_index("ix_sql_tables_source_id", "sql_tables", ["source_id"])
        op.create_index("ix_sql_tables_scope", "sql_tables", ["team_id", "visibility", "exposed"])

    _add_columns(
        "tools",
        [
            sa.Column("sql_table_id", sa.String(36), nullable=True),
            sa.Column("source_operation", sa.String(20), nullable=True),
        ],
    )
    _ensure_index("tools", "ix_tools_sql_table_id", ["sql_table_id"])
    _ensure_foreign_key("tools", "fk_tools_sql_table_id_sql_tables", "sql_table_id", "sql_tables", "id", "SET NULL")

    if "sql_relations" not in tables:
        op.create_table(
            "sql_relations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("source_table_id", sa.String(36), sa.ForeignKey("sql_tables.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_table_id", sa.String(36), sa.ForeignKey("sql_tables.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("local_columns", sa.JSON(), nullable=False),
            sa.Column("remote_columns", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("source_table_id", "name", name="uq_sql_relation_source_name"),
        )
        op.create_index("ix_sql_relations_source_table_id", "sql_relations", ["source_table_id"])
        op.create_index("ix_sql_relations_target_table_id", "sql_relations", ["target_table_id"])

    if "api_sql_table_bindings" not in tables:
        op.create_table(
            "api_sql_table_bindings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tool_id", sa.String(36), sa.ForeignKey("tools.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sql_table_id", sa.String(36), sa.ForeignKey("sql_tables.id", ondelete="CASCADE"), nullable=False),
            sa.Column("access_mode", sa.String(20), nullable=False, server_default="read"),
            sa.Column("binding_type", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("created_by", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tool_id", "sql_table_id", name="uq_api_sql_table_binding"),
        )
        op.create_index("ix_api_sql_table_bindings_tool_id", "api_sql_table_bindings", ["tool_id"])
        op.create_index("ix_api_sql_table_bindings_sql_table_id", "api_sql_table_bindings", ["sql_table_id"])

    if "api_debug_history" not in tables:
        op.create_table(
            "api_debug_history",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_email", sa.String(255), nullable=False),
            sa.Column("tool_id", sa.String(36), sa.ForeignKey("tools.id", ondelete="SET NULL"), nullable=True),
            sa.Column("protocol", sa.String(20), nullable=False),
            sa.Column("request_preview", sa.JSON(), nullable=False),
            sa.Column("result_metadata", sa.JSON(), nullable=False),
            sa.Column("duration_ms", sa.Float(), nullable=True),
            sa.Column("status_code", sa.String(64), nullable=True),
            sa.Column("trace_id", sa.String(64), nullable=True),
            sa.Column("is_success", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_api_debug_history_owner_email", "api_debug_history", ["owner_email"])
        op.create_index("ix_api_debug_history_tool_id", "api_debug_history", ["tool_id"])
        op.create_index("ix_api_debug_owner_created", "api_debug_history", ["owner_email", "created_at"])

    _add_columns(
        "tool_metrics",
        [
            sa.Column("protocol", sa.String(20), nullable=True),
            sa.Column("status_code", sa.String(64), nullable=True),
            sa.Column("request_bytes", sa.BigInteger(), nullable=True),
            sa.Column("response_bytes", sa.BigInteger(), nullable=True),
            sa.Column("trace_id", sa.String(64), nullable=True),
            sa.Column("is_debug", sa.Boolean(), nullable=False, server_default=sa.false()),
        ],
    )
    _ensure_index("tool_metrics", "ix_tool_metrics_protocol", ["protocol"])
    _ensure_index("tool_metrics", "ix_tool_metrics_status_code", ["status_code"])
    _ensure_index("tool_metrics", "ix_tool_metrics_trace_id", ["trace_id"])
    _ensure_index("tool_metrics", "ix_tool_metrics_is_debug", ["is_debug"])


def downgrade() -> None:
    """Remove gRPC schema/health, governed SQL, and debug persistence state."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in ["api_debug_history", "api_sql_table_bindings", "sql_relations"]:
        if table_name in tables:
            op.drop_table(table_name)

    if "tools" in tables:
        _drop_index_if_exists("tools", "ix_tools_sql_table_id")
        existing = _column_names("tools")
        with op.batch_alter_table("tools") as batch_op:
            for column_name in ["source_operation", "sql_table_id"]:
                if column_name in existing:
                    batch_op.drop_column(column_name)

    for table_name in ["sql_tables", "sql_data_sources", "grpc_metrics_hourly", "grpc_health_samples", "grpc_schema_artifacts"]:
        if table_name in tables:
            op.drop_table(table_name)

    if "tool_metrics" in tables:
        for index_name in ["ix_tool_metrics_protocol", "ix_tool_metrics_status_code", "ix_tool_metrics_trace_id", "ix_tool_metrics_is_debug"]:
            _drop_index_if_exists("tool_metrics", index_name)
        existing = _column_names("tool_metrics")
        with op.batch_alter_table("tool_metrics") as batch_op:
            for column_name in ["is_debug", "trace_id", "response_bytes", "request_bytes", "status_code", "protocol"]:
                if column_name in existing:
                    batch_op.drop_column(column_name)

    if "grpc_services" in tables:
        existing = _column_names("grpc_services")
        with op.batch_alter_table("grpc_services") as batch_op:
            for column_name in [
                "last_health_error",
                "last_health_check",
                "consecutive_failures",
                "health_status",
                "health_failure_threshold",
                "health_check_timeout",
                "health_check_interval",
                "health_check_enabled",
                "schema_drift",
                "manifest_hash",
                "manifest_path",
                "reflected_schema_hash",
                "active_schema_hash",
                "active_artifact_id",
                "discovery_mode",
            ]:
                if column_name in existing:
                    batch_op.drop_column(column_name)
