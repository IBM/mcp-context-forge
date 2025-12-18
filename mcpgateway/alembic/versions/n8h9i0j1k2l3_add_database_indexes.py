# -*- coding: utf-8 -*-
"""add database indexes

Revision ID: n8h9i0j1k2l3
Revises: m7g8h9i0j1k2
Create Date: 2025-12-18 05:49:00.000000

Complete Database Indexing Optimization (Issue #1353)
This migration adds both foreign key indexes and composite indexes to improve
query performance across the entire application.

Phase 1 - Foreign Key Indexes:
Foreign keys without indexes can cause performance issues because:
1. JOIN queries need to scan the entire table
2. Foreign key constraint checks (INSERT/UPDATE/DELETE) are slower
3. Cascading deletes/updates require full table scans

Phase 2 - Composite Indexes:
Composite indexes are beneficial when:
1. Multiple columns are frequently used together in WHERE clauses
2. Queries filter on one column and sort by another
3. Covering indexes can eliminate table lookups

This migration focuses on the most frequently used query patterns:
- Team + visibility filtering
- Team + active status filtering
- User + team membership queries
- Status + timestamp ordering
- Foreign key + timestamp ordering
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n8h9i0j1k2l3"
down_revision: Union[str, Sequence[str], None] = "m7g8h9i0j1k2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add foreign key and composite indexes for improved query performance.

    Note: Some foreign keys already have indexes (marked with index=True in models):
    - observability_spans.trace_id
    - observability_spans.parent_span_id
    - observability_events.span_id
    - observability_metrics.trace_id
    - security_events.log_entry_id
    - email_api_tokens.user_email
    - email_api_tokens.team_id
    - registered_oauth_clients.gateway_id

    This migration adds indexes for the remaining foreign keys and composite indexes
    for common query patterns.
    """

    # ========================================================================
    # PHASE 1: Foreign Key Indexes
    # ========================================================================

    # Role and RBAC foreign keys
    op.create_index("ix_roles_inherits_from", "roles", ["inherits_from"], unique=False)
    op.create_index("ix_roles_created_by", "roles", ["created_by"], unique=False)
    op.create_index("ix_user_roles_user_email", "user_roles", ["user_email"], unique=False)
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"], unique=False)
    op.create_index("ix_user_roles_granted_by", "user_roles", ["granted_by"], unique=False)

    # Team management foreign keys
    op.create_index("ix_email_teams_created_by", "email_teams", ["created_by"], unique=False)
    op.create_index("ix_email_team_members_team_id", "email_team_members", ["team_id"], unique=False)
    op.create_index("ix_email_team_members_user_email", "email_team_members", ["user_email"], unique=False)
    op.create_index("ix_email_team_members_invited_by", "email_team_members", ["invited_by"], unique=False)

    # Team member history foreign keys
    op.create_index("ix_email_team_member_history_team_member_id", "email_team_member_history", ["team_member_id"], unique=False)
    op.create_index("ix_email_team_member_history_team_id", "email_team_member_history", ["team_id"], unique=False)
    op.create_index("ix_email_team_member_history_user_email", "email_team_member_history", ["user_email"], unique=False)
    op.create_index("ix_email_team_member_history_action_by", "email_team_member_history", ["action_by"], unique=False)

    # Team invitation foreign keys
    op.create_index("ix_email_team_invitations_team_id", "email_team_invitations", ["team_id"], unique=False)
    op.create_index("ix_email_team_invitations_invited_by", "email_team_invitations", ["invited_by"], unique=False)

    # Team join request foreign keys
    op.create_index("ix_email_team_join_requests_team_id", "email_team_join_requests", ["team_id"], unique=False)
    op.create_index("ix_email_team_join_requests_user_email", "email_team_join_requests", ["user_email"], unique=False)
    op.create_index("ix_email_team_join_requests_reviewed_by", "email_team_join_requests", ["reviewed_by"], unique=False)

    # Pending user approval foreign keys
    op.create_index("ix_pending_user_approvals_approved_by", "pending_user_approvals", ["approved_by"], unique=False)

    # Metrics foreign keys
    op.create_index("ix_tool_metrics_tool_id", "tool_metrics", ["tool_id"], unique=False)
    op.create_index("ix_resource_metrics_resource_id", "resource_metrics", ["resource_id"], unique=False)
    op.create_index("ix_server_metrics_server_id", "server_metrics", ["server_id"], unique=False)
    op.create_index("ix_prompt_metrics_prompt_id", "prompt_metrics", ["prompt_id"], unique=False)
    op.create_index("ix_a2a_agent_metrics_a2a_agent_id", "a2a_agent_metrics", ["a2a_agent_id"], unique=False)

    # Core entity foreign keys (gateway_id, team_id)
    op.create_index("ix_tools_gateway_id", "tools", ["gateway_id"], unique=False)
    op.create_index("ix_tools_team_id", "tools", ["team_id"], unique=False)
    op.create_index("ix_resources_gateway_id", "resources", ["gateway_id"], unique=False)
    op.create_index("ix_resources_team_id", "resources", ["team_id"], unique=False)
    op.create_index("ix_prompts_gateway_id", "prompts", ["gateway_id"], unique=False)
    op.create_index("ix_prompts_team_id", "prompts", ["team_id"], unique=False)
    op.create_index("ix_servers_team_id", "servers", ["team_id"], unique=False)
    op.create_index("ix_gateways_team_id", "gateways", ["team_id"], unique=False)
    op.create_index("ix_a2a_agents_team_id", "a2a_agents", ["team_id"], unique=False)
    op.create_index("ix_grpc_services_team_id", "grpc_services", ["team_id"], unique=False)

    # Resource subscription foreign keys
    op.create_index("ix_resource_subscriptions_resource_id", "resource_subscriptions", ["resource_id"], unique=False)

    # OAuth foreign keys
    op.create_index("ix_oauth_tokens_gateway_id", "oauth_tokens", ["gateway_id"], unique=False)
    op.create_index("ix_oauth_tokens_app_user_email", "oauth_tokens", ["app_user_email"], unique=False)
    op.create_index("ix_oauth_states_gateway_id", "oauth_states", ["gateway_id"], unique=False)

    # API token foreign keys
    op.create_index("ix_email_api_tokens_server_id", "email_api_tokens", ["server_id"], unique=False)

    # Token revocation foreign keys
    op.create_index("ix_token_revocations_revoked_by", "token_revocations", ["revoked_by"], unique=False)

    # SSO foreign keys
    op.create_index("ix_sso_auth_sessions_provider_id", "sso_auth_sessions", ["provider_id"], unique=False)
    op.create_index("ix_sso_auth_sessions_user_email", "sso_auth_sessions", ["user_email"], unique=False)

    # LLM provider foreign keys
    op.create_index("ix_llm_models_provider_id", "llm_models", ["provider_id"], unique=False)

    # ========================================================================
    # PHASE 2: Composite Indexes
    # ========================================================================
    
    # ------------------------------------------------------------------------
    # Team Management Composite Indexes
    # ------------------------------------------------------------------------
    
    # Team membership queries (user + team + active status)
    op.create_index(
        "ix_email_team_members_user_team_active",
        "email_team_members",
        ["user_email", "team_id", "is_active"],
        unique=False,
    )
    
    # Team member role queries (team + role + active)
    op.create_index(
        "ix_email_team_members_team_role_active",
        "email_team_members",
        ["team_id", "role", "is_active"],
        unique=False,
    )
    
    # Team invitations (team + active + created timestamp)
    op.create_index(
        "ix_email_team_invitations_team_active_created",
        "email_team_invitations",
        ["team_id", "is_active", "invited_at"],
        unique=False,
    )
    
    # Team invitations by email (email + active + created)
    op.create_index(
        "ix_email_team_invitations_email_active_created",
        "email_team_invitations",
        ["email", "is_active", "invited_at"],
        unique=False,
    )
    
    # Team join requests (team + status + timestamp)
    op.create_index(
        "ix_email_team_join_requests_team_status_time",
        "email_team_join_requests",
        ["team_id", "status", "requested_at"],
        unique=False,
    )
    
    # Team join requests by user (user + status + timestamp)
    op.create_index(
        "ix_email_team_join_requests_user_status_time",
        "email_team_join_requests",
        ["user_email", "status", "requested_at"],
        unique=False,
    )
    
    # Team listing (visibility + is_active + created)
    op.create_index(
        "ix_email_teams_visibility_active_created",
        "email_teams",
        ["visibility", "is_active", "created_at"],
        unique=False,
    )
    
    # Personal team lookup (created_by + is_personal + active)
    op.create_index(
        "ix_email_teams_creator_personal_active",
        "email_teams",
        ["created_by", "is_personal", "is_active"],
        unique=False,
    )
    
    # ------------------------------------------------------------------------
    # Core Entity Composite Indexes (Tools, Resources, Prompts, Servers)
    # ------------------------------------------------------------------------
    
    # Tools: team + visibility + enabled + created (common listing query)
    op.create_index(
        "ix_tools_team_visibility_active_created",
        "tools",
        ["team_id", "visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # Tools: visibility + enabled + created (public listing)
    op.create_index(
        "ix_tools_visibility_active_created",
        "tools",
        ["visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # Resources: team + visibility + enabled + created
    op.create_index(
        "ix_resources_team_visibility_active_created",
        "resources",
        ["team_id", "visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # Resources: visibility + enabled + created
    op.create_index(
        "ix_resources_visibility_active_created",
        "resources",
        ["visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # Prompts: team + visibility + enabled + created
    op.create_index(
        "ix_prompts_team_visibility_active_created",
        "prompts",
        ["team_id", "visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # Prompts: visibility + enabled + created
    op.create_index(
        "ix_prompts_visibility_active_created",
        "prompts",
        ["visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # Servers: team + visibility + enabled + created
    op.create_index(
        "ix_servers_team_visibility_active_created",
        "servers",
        ["team_id", "visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # Servers: visibility + enabled + created
    op.create_index(
        "ix_servers_visibility_active_created",
        "servers",
        ["visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # Gateways: team + visibility + enabled + created
    op.create_index(
        "ix_gateways_team_visibility_active_created",
        "gateways",
        ["team_id", "visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # Gateways: visibility + enabled + created
    op.create_index(
        "ix_gateways_visibility_active_created",
        "gateways",
        ["visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # A2A Agents: team + visibility + enabled + created
    op.create_index(
        "ix_a2a_agents_team_visibility_active_created",
        "a2a_agents",
        ["team_id", "visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # A2A Agents: visibility + enabled + created
    op.create_index(
        "ix_a2a_agents_visibility_active_created",
        "a2a_agents",
        ["visibility", "enabled", "created_at"],
        unique=False,
    )
    
    # ------------------------------------------------------------------------
    # Observability Composite Indexes
    # ------------------------------------------------------------------------
    
    # Traces: user + status + time (user activity queries)
    op.create_index(
        "ix_observability_traces_user_status_time",
        "observability_traces",
        ["user_email", "status", "start_time"],
        unique=False,
    )
    
    # Traces: status + http_method + time (error analysis)
    op.create_index(
        "ix_observability_traces_status_method_time",
        "observability_traces",
        ["status", "http_method", "start_time"],
        unique=False,
    )
    
    # Spans: trace + resource_type + time (trace analysis)
    op.create_index(
        "ix_observability_spans_trace_resource_time",
        "observability_spans",
        ["trace_id", "resource_type", "start_time"],
        unique=False,
    )
    
    # Spans: resource_type + status + time (resource monitoring)
    op.create_index(
        "ix_observability_spans_resource_status_time",
        "observability_spans",
        ["resource_type", "status", "start_time"],
        unique=False,
    )
    
    # ------------------------------------------------------------------------
    # Authentication & Token Composite Indexes
    # ------------------------------------------------------------------------
    
    # API Tokens: user + active + created (user token listing)
    op.create_index(
        "ix_email_api_tokens_user_active_created",
        "email_api_tokens",
        ["user_email", "is_active", "created_at"],
        unique=False,
    )
    
    # API Tokens: team + active + created (team token listing)
    op.create_index(
        "ix_email_api_tokens_team_active_created",
        "email_api_tokens",
        ["team_id", "is_active", "created_at"],
        unique=False,
    )
    
    # Auth Events: user + event_type + timestamp (user activity audit)
    op.create_index(
        "ix_email_auth_events_user_type_time",
        "email_auth_events",
        ["user_email", "event_type", "timestamp"],
        unique=False,
    )
    
    # SSO Sessions: provider + user + created (session lookup)
    op.create_index(
        "ix_sso_auth_sessions_provider_user_created",
        "sso_auth_sessions",
        ["provider_id", "user_email", "created_at"],
        unique=False,
    )
    
    # OAuth Tokens: gateway + user + created (token lookup)
    op.create_index(
        "ix_oauth_tokens_gateway_user_created",
        "oauth_tokens",
        ["gateway_id", "app_user_email", "created_at"],
        unique=False,
    )
    
    # ------------------------------------------------------------------------
    # Metrics Composite Indexes
    # ------------------------------------------------------------------------
    
    # Tool Metrics: tool + timestamp (time-series queries)
    op.create_index(
        "ix_tool_metrics_tool_timestamp",
        "tool_metrics",
        ["tool_id", "timestamp"],
        unique=False,
    )
    
    # Resource Metrics: resource + timestamp
    op.create_index(
        "ix_resource_metrics_resource_timestamp",
        "resource_metrics",
        ["resource_id", "timestamp"],
        unique=False,
    )
    
    # Server Metrics: server + timestamp
    op.create_index(
        "ix_server_metrics_server_timestamp",
        "server_metrics",
        ["server_id", "timestamp"],
        unique=False,
    )
    
    # Prompt Metrics: prompt + timestamp
    op.create_index(
        "ix_prompt_metrics_prompt_timestamp",
        "prompt_metrics",
        ["prompt_id", "timestamp"],
        unique=False,
    )
    
    # ------------------------------------------------------------------------
    # RBAC Composite Indexes
    # ------------------------------------------------------------------------
    
    # User Roles: user + scope + active (permission checks)
    op.create_index(
        "ix_user_roles_user_scope_active",
        "user_roles",
        ["user_email", "scope", "is_active"],
        unique=False,
    )
    
    # User Roles: role + scope + active (role membership queries)
    op.create_index(
        "ix_user_roles_role_scope_active",
        "user_roles",
        ["role_id", "scope", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    """Remove all foreign key and composite indexes."""
    
    # ========================================================================
    # Remove Composite Indexes (Phase 2) - in reverse order
    # ========================================================================
    
    # RBAC
    op.drop_index("ix_user_roles_role_scope_active", table_name="user_roles")
    op.drop_index("ix_user_roles_user_scope_active", table_name="user_roles")
    
    # Metrics
    op.drop_index("ix_prompt_metrics_prompt_timestamp", table_name="prompt_metrics")
    op.drop_index("ix_server_metrics_server_timestamp", table_name="server_metrics")
    op.drop_index("ix_resource_metrics_resource_timestamp", table_name="resource_metrics")
    op.drop_index("ix_tool_metrics_tool_timestamp", table_name="tool_metrics")
    
    # Authentication & Tokens
    op.drop_index("ix_oauth_tokens_gateway_user_created", table_name="oauth_tokens")
    op.drop_index("ix_sso_auth_sessions_provider_user_created", table_name="sso_auth_sessions")
    op.drop_index("ix_email_auth_events_user_type_time", table_name="email_auth_events")
    op.drop_index("ix_email_api_tokens_team_active_created", table_name="email_api_tokens")
    op.drop_index("ix_email_api_tokens_user_active_created", table_name="email_api_tokens")
    
    # Observability
    op.drop_index("ix_observability_spans_resource_status_time", table_name="observability_spans")
    op.drop_index("ix_observability_spans_trace_resource_time", table_name="observability_spans")
    op.drop_index("ix_observability_traces_status_method_time", table_name="observability_traces")
    op.drop_index("ix_observability_traces_user_status_time", table_name="observability_traces")
    
    # Core Entities
    op.drop_index("ix_a2a_agents_visibility_active_created", table_name="a2a_agents")
    op.drop_index("ix_a2a_agents_team_visibility_active_created", table_name="a2a_agents")
    op.drop_index("ix_gateways_visibility_active_created", table_name="gateways")
    op.drop_index("ix_gateways_team_visibility_active_created", table_name="gateways")
    op.drop_index("ix_servers_visibility_active_created", table_name="servers")
    op.drop_index("ix_servers_team_visibility_active_created", table_name="servers")
    op.drop_index("ix_prompts_visibility_active_created", table_name="prompts")
    op.drop_index("ix_prompts_team_visibility_active_created", table_name="prompts")
    op.drop_index("ix_resources_visibility_active_created", table_name="resources")
    op.drop_index("ix_resources_team_visibility_active_created", table_name="resources")
    op.drop_index("ix_tools_visibility_active_created", table_name="tools")
    op.drop_index("ix_tools_team_visibility_active_created", table_name="tools")
    
    # Team Management
    op.drop_index("ix_email_teams_creator_personal_active", table_name="email_teams")
    op.drop_index("ix_email_teams_visibility_active_created", table_name="email_teams")
    op.drop_index("ix_email_team_join_requests_user_status_time", table_name="email_team_join_requests")
    op.drop_index("ix_email_team_join_requests_team_status_time", table_name="email_team_join_requests")
    op.drop_index("ix_email_team_invitations_email_active_created", table_name="email_team_invitations")
    op.drop_index("ix_email_team_invitations_team_active_created", table_name="email_team_invitations")
    op.drop_index("ix_email_team_members_team_role_active", table_name="email_team_members")
    op.drop_index("ix_email_team_members_user_team_active", table_name="email_team_members")
    
    # ========================================================================
    # Remove Foreign Key Indexes (Phase 1) - in reverse order
    # ========================================================================
    
    op.drop_index("ix_llm_models_provider_id", table_name="llm_models")
    op.drop_index("ix_sso_auth_sessions_user_email", table_name="sso_auth_sessions")
    op.drop_index("ix_sso_auth_sessions_provider_id", table_name="sso_auth_sessions")
    op.drop_index("ix_token_revocations_revoked_by", table_name="token_revocations")
    op.drop_index("ix_email_api_tokens_server_id", table_name="email_api_tokens")
    op.drop_index("ix_oauth_states_gateway_id", table_name="oauth_states")
    op.drop_index("ix_oauth_tokens_app_user_email", table_name="oauth_tokens")
    op.drop_index("ix_oauth_tokens_gateway_id", table_name="oauth_tokens")
    op.drop_index("ix_resource_subscriptions_resource_id", table_name="resource_subscriptions")
    op.drop_index("ix_grpc_services_team_id", table_name="grpc_services")
    op.drop_index("ix_a2a_agents_team_id", table_name="a2a_agents")
    op.drop_index("ix_gateways_team_id", table_name="gateways")
    op.drop_index("ix_servers_team_id", table_name="servers")
    op.drop_index("ix_prompts_team_id", table_name="prompts")
    op.drop_index("ix_prompts_gateway_id", table_name="prompts")
    op.drop_index("ix_resources_team_id", table_name="resources")
    op.drop_index("ix_resources_gateway_id", table_name="resources")
    op.drop_index("ix_tools_team_id", table_name="tools")
    op.drop_index("ix_tools_gateway_id", table_name="tools")
    op.drop_index("ix_a2a_agent_metrics_a2a_agent_id", table_name="a2a_agent_metrics")
    op.drop_index("ix_prompt_metrics_prompt_id", table_name="prompt_metrics")
    op.drop_index("ix_server_metrics_server_id", table_name="server_metrics")
    op.drop_index("ix_resource_metrics_resource_id", table_name="resource_metrics")
    op.drop_index("ix_tool_metrics_tool_id", table_name="tool_metrics")
    op.drop_index("ix_pending_user_approvals_approved_by", table_name="pending_user_approvals")
    op.drop_index("ix_email_team_join_requests_reviewed_by", table_name="email_team_join_requests")
    op.drop_index("ix_email_team_join_requests_user_email", table_name="email_team_join_requests")
    op.drop_index("ix_email_team_join_requests_team_id", table_name="email_team_join_requests")
    op.drop_index("ix_email_team_invitations_invited_by", table_name="email_team_invitations")
    op.drop_index("ix_email_team_invitations_team_id", table_name="email_team_invitations")
    op.drop_index("ix_email_team_member_history_action_by", table_name="email_team_member_history")
    op.drop_index("ix_email_team_member_history_user_email", table_name="email_team_member_history")
    op.drop_index("ix_email_team_member_history_team_id", table_name="email_team_member_history")
    op.drop_index("ix_email_team_member_history_team_member_id", table_name="email_team_member_history")
    op.drop_index("ix_email_team_members_invited_by", table_name="email_team_members")
    op.drop_index("ix_email_team_members_user_email", table_name="email_team_members")
    op.drop_index("ix_email_team_members_team_id", table_name="email_team_members")
    op.drop_index("ix_email_teams_created_by", table_name="email_teams")
    op.drop_index("ix_user_roles_granted_by", table_name="user_roles")
    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_index("ix_user_roles_user_email", table_name="user_roles")
    op.drop_index("ix_roles_created_by", table_name="roles")
    op.drop_index("ix_roles_inherits_from", table_name="roles")

