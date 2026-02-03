# -*- coding: utf-8 -*-
"""Reconcile missing indexes for bootstrap-created databases

Revision ID: c2d3e4f5g6h7
Revises: b1b2b3b4b5b6
Create Date: 2026-02-03
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5g6h7"
down_revision: Union[str, Sequence[str], None] = "b1b2b3b4b5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_SPECS = [
    ("idx_a2a_agent_metrics_a2a_agent_id", "a2a_agent_metrics", ["a2a_agent_id"], False),
    ("idx_a2a_agent_metrics_agent_id", "a2a_agent_metrics", ["a2a_agent_id"], False),
    ("idx_a2a_agent_metrics_agent_is_success", "a2a_agent_metrics", ["a2a_agent_id", "is_success"], False),
    ("idx_a2a_agent_metrics_timestamp", "a2a_agent_metrics", ["timestamp"], False),
    ("idx_a2a_agents_agent_type", "a2a_agents", ["agent_type"], False),
    ("idx_a2a_agents_enabled", "a2a_agents", ["enabled"], False),
    ("idx_a2a_agents_name", "a2a_agents", ["name"], False),
    ("idx_a2a_agents_slug", "a2a_agents", ["slug"], False),
    ("idx_a2a_agents_slug_visibility", "a2a_agents", ["slug", "visibility"], False),
    # NOTE: idx_a2a_agents_tags removed - PostgreSQL cannot create B-tree indexes on JSON columns
    ("idx_a2a_agents_team_id", "a2a_agents", ["team_id"], False),
    ("idx_a2a_agents_team_visibility_active_created", "a2a_agents", ["team_id", "visibility", "enabled", "created_at"], False),
    ("idx_a2a_agents_visibility", "a2a_agents", ["visibility"], False),
    ("idx_a2a_agents_visibility_active_created", "a2a_agents", ["visibility", "enabled", "created_at"], False),
    ("idx_email_api_tokens_last_used", "email_api_tokens", ["last_used"], False),
    ("idx_email_api_tokens_server_id", "email_api_tokens", ["server_id"], False),
    ("idx_email_api_tokens_team_active_created", "email_api_tokens", ["team_id", "is_active", "created_at"], False),
    ("idx_email_api_tokens_user_active_created", "email_api_tokens", ["user_email", "is_active", "created_at"], False),
    ("ix_email_api_tokens_created_at_id", "email_api_tokens", ["created_at", "id"], False),
    ("ix_email_api_tokens_user_email_created_at", "email_api_tokens", ["user_email", "created_at"], False),
    ("idx_email_auth_events_event_type", "email_auth_events", ["event_type"], False),
    ("idx_email_auth_events_ip_address", "email_auth_events", ["ip_address"], False),
    ("idx_email_auth_events_ip_time", "email_auth_events", ["ip_address", "timestamp"], False),
    ("idx_email_auth_events_success", "email_auth_events", ["success"], False),
    ("idx_email_auth_events_success_time", "email_auth_events", ["success", "timestamp"], False),
    ("idx_email_auth_events_timestamp", "email_auth_events", ["timestamp"], False),
    ("idx_email_auth_events_type_success_time", "email_auth_events", ["event_type", "success", "timestamp"], False),
    ("idx_email_auth_events_user_type_time", "email_auth_events", ["user_email", "event_type", "timestamp"], False),
    ("ix_email_auth_events_timestamp_id", "email_auth_events", ["timestamp", "id"], False),
    ("ix_email_auth_events_user_email_timestamp", "email_auth_events", ["user_email", "timestamp"], False),
    ("idx_email_team_invitations_email_active_created", "email_team_invitations", ["email", "is_active", "invited_at"], False),
    ("idx_email_team_invitations_invited_by", "email_team_invitations", ["invited_by"], False),
    ("idx_email_team_invitations_team_active_created", "email_team_invitations", ["team_id", "is_active", "invited_at"], False),
    ("idx_email_team_invitations_team_id", "email_team_invitations", ["team_id"], False),
    ("idx_email_team_join_requests_reviewed_by", "email_team_join_requests", ["reviewed_by"], False),
    ("idx_email_team_join_requests_team_id", "email_team_join_requests", ["team_id"], False),
    ("idx_email_team_join_requests_team_status_time", "email_team_join_requests", ["team_id", "status", "requested_at"], False),
    ("idx_email_team_join_requests_user_email", "email_team_join_requests", ["user_email"], False),
    ("idx_email_team_join_requests_user_status_time", "email_team_join_requests", ["user_email", "status", "requested_at"], False),
    ("idx_email_team_member_history_action_by", "email_team_member_history", ["action_by"], False),
    ("idx_email_team_member_history_team_id", "email_team_member_history", ["team_id"], False),
    ("idx_email_team_member_history_team_member_id", "email_team_member_history", ["team_member_id"], False),
    ("idx_email_team_member_history_user_email", "email_team_member_history", ["user_email"], False),
    ("idx_email_team_members_invited_by", "email_team_members", ["invited_by"], False),
    ("idx_email_team_members_team_active_count", "email_team_members", ["team_id", "is_active"], False),
    ("idx_email_team_members_team_id", "email_team_members", ["team_id"], False),
    ("idx_email_team_members_team_role_active", "email_team_members", ["team_id", "role", "is_active"], False),
    ("idx_email_team_members_user_email", "email_team_members", ["user_email"], False),
    ("idx_email_team_members_user_team_active", "email_team_members", ["user_email", "team_id", "is_active"], False),
    ("idx_email_teams_created_by", "email_teams", ["created_by"], False),
    ("idx_email_teams_creator_personal_active", "email_teams", ["created_by", "is_personal", "is_active"], False),
    ("idx_email_teams_visibility_active_created", "email_teams", ["visibility", "is_active", "created_at"], False),
    ("ix_email_teams_created_at_id", "email_teams", ["created_at", "id"], False),
    ("ix_email_users_created_at_email", "email_users", ["created_at", "email"], False),
    ("idx_gateways_owner_visibility", "gateways", ["owner_email", "visibility"], False),
    ("idx_gateways_team_id", "gateways", ["team_id"], False),
    ("idx_gateways_team_visibility", "gateways", ["team_id", "visibility"], False),
    ("idx_gateways_team_visibility_active_created", "gateways", ["team_id", "visibility", "enabled", "created_at"], False),
    ("idx_gateways_visibility_active_created", "gateways", ["visibility", "enabled", "created_at"], False),
    ("ix_gateways_created_at_id", "gateways", ["created_at", "id"], False),
    ("ix_gateways_team_id_created_at", "gateways", ["team_id", "created_at"], False),
    ("idx_grpc_services_team_id", "grpc_services", ["team_id"], False),
    ("idx_llm_models_provider_id", "llm_models", ["provider_id"], False),
    ("idx_mcp_messages_session_id", "mcp_messages", ["session_id"], False),
    ("idx_oauth_states_gateway_id", "oauth_states", ["gateway_id"], False),
    ("idx_oauth_gateway_user", "oauth_tokens", ["gateway_id", "app_user_email"], True),
    ("idx_oauth_tokens_app_user_email", "oauth_tokens", ["app_user_email"], False),
    ("idx_oauth_tokens_expires", "oauth_tokens", ["expires_at"], False),
    ("idx_oauth_tokens_gateway_id", "oauth_tokens", ["gateway_id"], False),
    ("idx_oauth_tokens_gateway_user_created", "oauth_tokens", ["gateway_id", "app_user_email", "created_at"], False),
    ("ix_observability_events_span_id_timestamp", "observability_events", ["span_id", "timestamp"], False),
    ("idx_observability_spans_resource_status_time", "observability_spans", ["resource_type", "status", "start_time"], False),
    ("idx_observability_spans_trace_resource_time", "observability_spans", ["trace_id", "resource_type", "start_time"], False),
    ("ix_observability_spans_duration_ms", "observability_spans", ["duration_ms"], False),
    ("ix_observability_spans_kind_status", "observability_spans", ["kind", "status"], False),
    ("ix_observability_spans_name", "observability_spans", ["name"], False),
    ("ix_observability_spans_resource_type_start_time", "observability_spans", ["resource_type", "start_time"], False),
    ("ix_observability_spans_trace_id_start_time", "observability_spans", ["trace_id", "start_time"], False),
    ("idx_observability_traces_status_method_time", "observability_traces", ["status", "http_method", "start_time"], False),
    ("idx_observability_traces_user_status_time", "observability_traces", ["user_email", "status", "start_time"], False),
    ("ix_observability_traces_duration_ms", "observability_traces", ["duration_ms"], False),
    ("ix_observability_traces_http_method_start_time", "observability_traces", ["http_method", "start_time"], False),
    ("ix_observability_traces_name", "observability_traces", ["name"], False),
    ("ix_observability_traces_status_start_time", "observability_traces", ["status", "start_time"], False),
    ("idx_pending_user_approvals_approved_by", "pending_user_approvals", ["approved_by"], False),
    ("idx_permission_audit_log_granted", "permission_audit_log", ["granted"], False),
    ("idx_permission_audit_log_permission", "permission_audit_log", ["permission"], False),
    ("idx_permission_audit_log_resource_granted_time", "permission_audit_log", ["resource_type", "granted", "timestamp"], False),
    ("idx_permission_audit_log_resource_type", "permission_audit_log", ["resource_type"], False),
    ("idx_permission_audit_log_team_id", "permission_audit_log", ["team_id"], False),
    ("idx_permission_audit_log_team_time", "permission_audit_log", ["team_id", "timestamp"], False),
    ("idx_permission_audit_log_timestamp", "permission_audit_log", ["timestamp"], False),
    ("idx_permission_audit_log_user_email", "permission_audit_log", ["user_email"], False),
    ("idx_permission_audit_log_user_time", "permission_audit_log", ["user_email", "timestamp"], False),
    ("idx_prompt_metrics_prompt_id", "prompt_metrics", ["prompt_id"], False),
    ("idx_prompt_metrics_prompt_is_success", "prompt_metrics", ["prompt_id", "is_success"], False),
    ("idx_prompt_metrics_prompt_timestamp", "prompt_metrics", ["prompt_id", "timestamp"], False),
    ("idx_prompts_gateway_id", "prompts", ["gateway_id"], False),
    ("idx_prompts_owner_visibility", "prompts", ["owner_email", "visibility"], False),
    ("idx_prompts_team_id", "prompts", ["team_id"], False),
    ("idx_prompts_team_visibility", "prompts", ["team_id", "visibility"], False),
    ("idx_prompts_team_visibility_active_created", "prompts", ["team_id", "visibility", "enabled", "created_at"], False),
    ("idx_prompts_visibility_active_created", "prompts", ["visibility", "enabled", "created_at"], False),
    ("ix_prompts_created_at_name", "prompts", ["created_at", "name"], False),
    ("ix_prompts_team_id_created_at", "prompts", ["team_id", "created_at"], False),
    ("idx_resource_metrics_resource_id", "resource_metrics", ["resource_id"], False),
    ("idx_resource_metrics_resource_is_success", "resource_metrics", ["resource_id", "is_success"], False),
    ("idx_resource_metrics_resource_timestamp", "resource_metrics", ["resource_id", "timestamp"], False),
    ("idx_resource_subscriptions_resource_id", "resource_subscriptions", ["resource_id"], False),
    ("idx_resources_gateway_id", "resources", ["gateway_id"], False),
    ("idx_resources_owner_visibility", "resources", ["owner_email", "visibility"], False),
    ("idx_resources_team_id", "resources", ["team_id"], False),
    ("idx_resources_team_visibility", "resources", ["team_id", "visibility"], False),
    ("idx_resources_team_visibility_active_created", "resources", ["team_id", "visibility", "enabled", "created_at"], False),
    ("idx_resources_visibility_active_created", "resources", ["visibility", "enabled", "created_at"], False),
    ("ix_resources_created_at_uri", "resources", ["created_at", "uri"], False),
    ("ix_resources_team_id_created_at", "resources", ["team_id", "created_at"], False),
    ("idx_roles_created_by", "roles", ["created_by"], False),
    ("idx_roles_inherits_from", "roles", ["inherits_from"], False),
    ("ix_security_events_detected_at", "security_events", ["detected_at"], False),
    ("idx_server_a2a_association_a2a_agent_id", "server_a2a_association", ["a2a_agent_id"], False),
    ("idx_server_a2a_association_server_id", "server_a2a_association", ["server_id"], False),
    ("idx_server_metrics_server_id", "server_metrics", ["server_id"], False),
    ("idx_server_metrics_server_is_success", "server_metrics", ["server_id", "is_success"], False),
    ("idx_server_metrics_server_timestamp", "server_metrics", ["server_id", "timestamp"], False),
    ("idx_server_prompt_association_prompt_id", "server_prompt_association", ["prompt_id"], False),
    ("idx_server_prompt_association_server_id", "server_prompt_association", ["server_id"], False),
    ("idx_server_resource_association_resource_id", "server_resource_association", ["resource_id"], False),
    ("idx_server_resource_association_server_id", "server_resource_association", ["server_id"], False),
    ("idx_server_tool_association_server_id", "server_tool_association", ["server_id"], False),
    ("idx_server_tool_association_tool_id", "server_tool_association", ["tool_id"], False),
    ("idx_servers_owner_visibility", "servers", ["owner_email", "visibility"], False),
    ("idx_servers_team_id", "servers", ["team_id"], False),
    ("idx_servers_team_visibility", "servers", ["team_id", "visibility"], False),
    ("idx_servers_team_visibility_active_created", "servers", ["team_id", "visibility", "enabled", "created_at"], False),
    ("idx_servers_visibility_active_created", "servers", ["visibility", "enabled", "created_at"], False),
    ("ix_servers_created_at_id", "servers", ["created_at", "id"], False),
    ("ix_servers_team_id_created_at", "servers", ["team_id", "created_at"], False),
    ("idx_sso_auth_sessions_provider_id", "sso_auth_sessions", ["provider_id"], False),
    ("idx_sso_auth_sessions_provider_user_created", "sso_auth_sessions", ["provider_id", "user_email", "created_at"], False),
    ("idx_sso_auth_sessions_user_email", "sso_auth_sessions", ["user_email"], False),
    ("idx_token_revocations_revoked_at", "token_revocations", ["revoked_at"], False),
    ("idx_token_revocations_revoked_by", "token_revocations", ["revoked_by"], False),
    ("idx_token_usage_logs_timestamp", "token_usage_logs", ["timestamp"], False),
    ("idx_token_usage_logs_token_jti", "token_usage_logs", ["token_jti"], False),
    ("idx_token_usage_logs_user_email", "token_usage_logs", ["user_email"], False),
    ("idx_tool_metrics_tool_id", "tool_metrics", ["tool_id"], False),
    ("idx_tool_metrics_tool_is_success", "tool_metrics", ["tool_id", "is_success"], False),
    ("idx_tool_metrics_tool_timestamp", "tool_metrics", ["tool_id", "timestamp"], False),
    ("idx_tools_gateway_id", "tools", ["gateway_id"], False),
    ("idx_tools_owner_visibility", "tools", ["owner_email", "visibility"], False),
    ("idx_tools_team_id", "tools", ["team_id"], False),
    ("idx_tools_team_visibility", "tools", ["team_id", "visibility"], False),
    ("idx_tools_team_visibility_active_created", "tools", ["team_id", "visibility", "enabled", "created_at"], False),
    ("idx_tools_visibility_active_created", "tools", ["visibility", "enabled", "created_at"], False),
    ("ix_tools_created_at_id", "tools", ["created_at", "id"], False),
    ("ix_tools_team_id_created_at", "tools", ["team_id", "created_at"], False),
    ("idx_user_roles_granted_by", "user_roles", ["granted_by"], False),
    ("idx_user_roles_role_id", "user_roles", ["role_id"], False),
    ("idx_user_roles_role_scope_active", "user_roles", ["role_id", "scope", "is_active"], False),
    ("idx_user_roles_scope", "user_roles", ["scope"], False),
    ("idx_user_roles_scope_id", "user_roles", ["scope_id"], False),
    ("idx_user_roles_user_email", "user_roles", ["user_email"], False),
    ("idx_user_roles_user_scope_active", "user_roles", ["user_email", "scope", "is_active"], False),
]


def _index_exists(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    """Return True if an index with the given name exists on the table.

    Args:
        inspector: SQLAlchemy inspector bound to the current connection.
        table_name: Name of the table to inspect.
        index_name: Name of the index to check.

    Returns:
        bool: True when the index exists, otherwise False.
    """
    try:
        return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))
    except Exception:
        return False


def _index_exists_on_columns(inspector: sa.Inspector, table_name: str, columns: list[str]) -> bool:
    """Return True if an index exists that covers exactly the given columns.

    Args:
        inspector: SQLAlchemy inspector bound to the current connection.
        table_name: Name of the table to inspect.
        columns: Column names that should be indexed.

    Returns:
        bool: True when a matching index exists, otherwise False.
    """
    try:
        existing = inspector.get_indexes(table_name)
    except Exception:
        return False
    target = set(columns)
    for idx in existing:
        cols = idx.get("column_names") or []
        if set(cols) == target:
            return True
    return False


def _ensure_index(inspector: sa.Inspector, name: str, table: str, columns: list[str], unique: bool) -> None:
    """Create an index if the table exists and no matching index is present.

    Args:
        inspector: SQLAlchemy inspector bound to the current connection.
        name: Index name to create.
        table: Table name to create the index on.
        columns: Column names to include in the index.
        unique: Whether to create a unique index.
    """
    if not inspector.has_table(table):
        return
    if _index_exists(inspector, table, name):
        return
    if _index_exists_on_columns(inspector, table, columns):
        return
    op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    """Create missing indexes that are migration-only for bootstrap-created schemas."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    dialect = conn.dialect.name

    for name, table, columns, unique in INDEX_SPECS:
        if dialect == "postgresql" and name == "idx_email_team_members_team_active_count":
            continue
        _ensure_index(inspector, name, table, columns, unique)

    if dialect == "postgresql":
        if inspector.has_table("email_team_members") and not _index_exists(inspector, "email_team_members", "idx_email_team_members_team_active_partial"):
            op.create_index(
                "idx_email_team_members_team_active_partial",
                "email_team_members",
                ["team_id"],
                postgresql_where=sa.text("is_active = true"),
            )


def downgrade() -> None:
    """No-op downgrade for reconciliation-only migration."""
    # No-op: reconciliation migration only.
    return
