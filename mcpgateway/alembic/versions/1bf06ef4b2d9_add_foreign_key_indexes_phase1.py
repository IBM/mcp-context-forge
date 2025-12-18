"""add foreign key indexes phase1

Revision ID: 1bf06ef4b2d9
Revises: m7g8h9i0j1k2
Create Date: 2025-12-18 10:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1bf06ef4b2d9"
down_revision: Union[str, Sequence[str], None] = "m7g8h9i0j1k2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add indexes on all foreign key columns for improved JOIN performance.

    This migration implements Phase 1 of issue #1353: Database Indexing Optimization.
    It creates indexes on foreign key columns that don't already have them to improve
    query performance, especially for JOINs and foreign key constraint checks.

    Foreign keys already indexed (skipped - have index=True in model definition):
    - email_api_tokens.user_email
    - email_api_tokens.team_id
    - email_auth_events.user_email
    - observability_spans.trace_id
    - observability_spans.parent_span_id
    - observability_events.span_id
    - observability_metrics.trace_id
    - registered_oauth_clients.gateway_id
    - structured_log_entries.log_entry_id (if exists)
    """

    # Metrics tables foreign keys
    op.create_index("ix_tool_metrics_tool_id", "tool_metrics", ["tool_id"])
    op.create_index("ix_resource_metrics_resource_id", "resource_metrics", ["resource_id"])
    op.create_index("ix_prompt_metrics_prompt_id", "prompt_metrics", ["prompt_id"])
    op.create_index("ix_server_metrics_server_id", "server_metrics", ["server_id"])
    op.create_index("ix_a2a_agent_metrics_a2a_agent_id", "a2a_agent_metrics", ["a2a_agent_id"])

    # Core resource foreign keys
    op.create_index("ix_tools_gateway_id", "tools", ["gateway_id"])
    op.create_index("ix_tools_team_id", "tools", ["team_id"])
    op.create_index("ix_resources_gateway_id", "resources", ["gateway_id"])
    op.create_index("ix_resources_team_id", "resources", ["team_id"])
    op.create_index("ix_prompts_gateway_id", "prompts", ["gateway_id"])
    op.create_index("ix_prompts_team_id", "prompts", ["team_id"])
    op.create_index("ix_a2a_agents_team_id", "a2a_agents", ["team_id"])

    # User and Role Management Foreign Keys
    op.create_index("ix_user_roles_user_email", "user_roles", ["user_email"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])
    op.create_index("ix_user_roles_granted_by", "user_roles", ["granted_by"])

    # Team Management Foreign Keys
    op.create_index("ix_email_teams_created_by", "email_teams", ["created_by"])

    op.create_index("ix_email_team_members_team_id", "email_team_members", ["team_id"])
    op.create_index("ix_email_team_members_user_email", "email_team_members", ["user_email"])
    op.create_index("ix_email_team_members_invited_by", "email_team_members", ["invited_by"])

    op.create_index("ix_email_team_member_history_team_member_id", "email_team_member_history", ["team_member_id"])
    op.create_index("ix_email_team_member_history_team_id", "email_team_member_history", ["team_id"])
    op.create_index("ix_email_team_member_history_user_email", "email_team_member_history", ["user_email"])
    op.create_index("ix_email_team_member_history_action_by", "email_team_member_history", ["action_by"])

    op.create_index("ix_email_team_invitations_team_id", "email_team_invitations", ["team_id"])
    op.create_index("ix_email_team_invitations_invited_by", "email_team_invitations", ["invited_by"])

    op.create_index("ix_email_team_join_requests_team_id", "email_team_join_requests", ["team_id"])
    op.create_index("ix_email_team_join_requests_user_email", "email_team_join_requests", ["user_email"])
    op.create_index("ix_email_team_join_requests_reviewed_by", "email_team_join_requests", ["reviewed_by"])

    op.create_index("ix_pending_user_approvals_approved_by", "pending_user_approvals", ["approved_by"])

    # Resource Subscriptions
    op.create_index("ix_resource_subscriptions_resource_id", "resource_subscriptions", ["resource_id"])

    # Server Foreign Keys
    op.create_index("ix_servers_team_id", "servers", ["team_id"])

    # Gateway Foreign Keys
    op.create_index("ix_gateways_team_id", "gateways", ["team_id"])

    # gRPC Service Foreign Keys
    op.create_index("ix_grpc_services_team_id", "grpc_services", ["team_id"])

    # Session Management Foreign Keys
    op.create_index("ix_mcp_messages_session_id", "mcp_messages", ["session_id"])

    # OAuth Foreign Keys
    op.create_index("ix_oauth_tokens_gateway_id", "oauth_tokens", ["gateway_id"])
    op.create_index("ix_oauth_tokens_app_user_email", "oauth_tokens", ["app_user_email"])

    op.create_index("ix_oauth_states_gateway_id", "oauth_states", ["gateway_id"])

    # registered_oauth_clients.gateway_id already has index=True in model definition

    # API Token Foreign Keys
    op.create_index("ix_email_api_tokens_server_id", "email_api_tokens", ["server_id"])

    # Token Revocation Foreign Keys
    op.create_index("ix_token_revocations_revoked_by", "token_revocations", ["revoked_by"])

    # SSO Foreign Keys
    op.create_index("ix_sso_auth_sessions_provider_id", "sso_auth_sessions", ["provider_id"])
    op.create_index("ix_sso_auth_sessions_user_email", "sso_auth_sessions", ["user_email"])


def downgrade() -> None:
    """Remove foreign key indexes."""

    # SSO Foreign Keys
    op.drop_index("ix_sso_auth_sessions_user_email", table_name="sso_auth_sessions")
    op.drop_index("ix_sso_auth_sessions_provider_id", table_name="sso_auth_sessions")

    # Token Revocation Foreign Keys
    op.drop_index("ix_token_revocations_revoked_by", table_name="token_revocations")

    # API Token Foreign Keys
    op.drop_index("ix_email_api_tokens_server_id", table_name="email_api_tokens")

    # OAuth Foreign Keys
    op.drop_index("ix_registered_oauth_clients_gateway_id", table_name="registered_oauth_clients")
    op.drop_index("ix_oauth_states_gateway_id", table_name="oauth_states")
    op.drop_index("ix_oauth_tokens_app_user_email", table_name="oauth_tokens")
    op.drop_index("ix_oauth_tokens_gateway_id", table_name="oauth_tokens")

    # Session Management Foreign Keys
    op.drop_index("ix_mcp_messages_session_id", table_name="mcp_messages")

    # gRPC Service Foreign Keys
    op.drop_index("ix_grpc_services_team_id", table_name="grpc_services")

    # Gateway Foreign Keys
    op.drop_index("ix_gateways_team_id", table_name="gateways")

    # Server Foreign Keys
    op.drop_index("ix_servers_team_id", table_name="servers")

    # Resource Subscriptions
    op.drop_index("ix_resource_subscriptions_resource_id", table_name="resource_subscriptions")

    # Team Management Foreign Keys
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

    # User and Role Management Foreign Keys
    op.drop_index("ix_user_roles_granted_by", table_name="user_roles")
    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_index("ix_user_roles_user_email", table_name="user_roles")

    # Core resource foreign keys
    op.drop_index("ix_a2a_agents_team_id", table_name="a2a_agents")
    op.drop_index("ix_prompts_team_id", table_name="prompts")
    op.drop_index("ix_prompts_gateway_id", table_name="prompts")
    op.drop_index("ix_resources_team_id", table_name="resources")
    op.drop_index("ix_resources_gateway_id", table_name="resources")
    op.drop_index("ix_tools_team_id", table_name="tools")
    op.drop_index("ix_tools_gateway_id", table_name="tools")

    # Metrics tables foreign keys
    op.drop_index("ix_a2a_agent_metrics_a2a_agent_id", table_name="a2a_agent_metrics")
    op.drop_index("ix_server_metrics_server_id", table_name="server_metrics")
    op.drop_index("ix_prompt_metrics_prompt_id", table_name="prompt_metrics")
    op.drop_index("ix_resource_metrics_resource_id", table_name="resource_metrics")
    op.drop_index("ix_tool_metrics_tool_id", table_name="tool_metrics")
