# -*- coding: utf-8 -*-
"""add foreign key indexes phase 1

Revision ID: n8h9i0j1k2l3
Revises: m7g8h9i0j1k2
Create Date: 2025-12-18 05:49:00.000000

Phase 1 of Database Indexing Optimization (Issue #1353)
This migration adds indexes on foreign key columns to improve query performance
for JOIN operations and foreign key constraint checks.

Foreign keys without indexes can cause performance issues because:
1. JOIN queries need to scan the entire table
2. Foreign key constraint checks (INSERT/UPDATE/DELETE) are slower
3. Cascading deletes/updates require full table scans

This migration focuses on the most frequently accessed foreign keys.
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
    """Add indexes on foreign key columns for improved query performance.
    
    Note: Some foreign keys already have indexes (marked with index=True in models):
    - observability_spans.trace_id
    - observability_spans.parent_span_id
    - observability_events.span_id
    - observability_metrics.trace_id
    - security_events.log_entry_id
    - email_api_tokens.user_email
    - email_api_tokens.team_id
    - registered_oauth_clients.gateway_id
    
    This migration adds indexes for the remaining foreign keys.
    """
    
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


def downgrade() -> None:
    """Remove foreign key indexes."""
    
    # Remove indexes in reverse order
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

# Made with Bob
