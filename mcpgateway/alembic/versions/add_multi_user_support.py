# -*- coding: utf-8 -*-
"""Add multi-user support

Revision ID: multi_user_001
Revises: add_a2a_agents_and_metrics
Create Date: 2025-01-23 10:00:00.000000

"""
# Standard
import uuid

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "multi_user_001"
down_revision = "733159a4fa74"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade to add multi-user support."""

    # Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False, default=lambda: str(uuid.uuid4())),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, default=False),
        sa.Column("password_reset_token", sa.String(255), nullable=True),
        sa.Column("password_reset_expires", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, default=0),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("email"),
    )

    # Create indexes for users table
    op.create_index("idx_users_username", "users", ["username"])
    op.create_index("idx_users_email", "users", ["email"])
    op.create_index("idx_users_active", "users", ["is_active"])

    # Create user_sessions table
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(), nullable=False, default=lambda: str(uuid.uuid4())),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_token", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for user_sessions table
    op.create_index("idx_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("idx_user_sessions_expires", "user_sessions", ["expires_at"])
    op.create_index("idx_user_sessions_token", "user_sessions", ["session_token"])

    # Create api_tokens table
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.String(), nullable=False, default=lambda: str(uuid.uuid4())),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("jti", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("scopes", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti"),
        sa.UniqueConstraint("user_id", "name", name="uq_user_token_name"),
    )

    # Create indexes for api_tokens table
    op.create_index("idx_api_tokens_user_id", "api_tokens", ["user_id"])
    op.create_index("idx_api_tokens_jti", "api_tokens", ["jti"])
    op.create_index("idx_api_tokens_active", "api_tokens", ["is_active"])

    # Create auth_events table for audit logging
    op.create_table(
        "auth_events",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for auth_events table
    op.create_index("idx_auth_events_user_id", "auth_events", ["user_id"])
    op.create_index("idx_auth_events_timestamp", "auth_events", ["timestamp"])
    op.create_index("idx_auth_events_event_type", "auth_events", ["event_type"])
    op.create_index("idx_auth_events_success", "auth_events", ["success"])

    # Create teams table
    op.create_table(
        "teams",
        sa.Column("id", sa.String(), nullable=False, default=lambda: str(uuid.uuid4())),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    # Create indexes for teams table
    op.create_index("idx_teams_created_by", "teams", ["created_by"])
    op.create_index("idx_teams_active", "teams", ["is_active"])

    # Create team_members table
    op.create_table(
        "team_members",
        sa.Column("id", sa.String(), nullable=False, default=lambda: str(uuid.uuid4())),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("invited_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_user_membership"),
    )

    # Create indexes for team_members table
    op.create_index("idx_team_members_team_id", "team_members", ["team_id"])
    op.create_index("idx_team_members_user_id", "team_members", ["user_id"])
    op.create_index("idx_team_members_role", "team_members", ["role"])

    # Create team_invitations table
    op.create_table(
        "team_invitations",
        sa.Column("id", sa.String(), nullable=False, default=lambda: str(uuid.uuid4())),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, default="member"),
        sa.Column("invited_by", sa.String(), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(), nullable=True),
        sa.Column("token", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "email", name="uq_team_email_invitation"),
        sa.UniqueConstraint("token"),
    )

    # Create indexes for team_invitations table
    op.create_index("idx_team_invitations_team_id", "team_invitations", ["team_id"])
    op.create_index("idx_team_invitations_email", "team_invitations", ["email"])
    op.create_index("idx_team_invitations_token", "team_invitations", ["token"])
    op.create_index("idx_team_invitations_expires", "team_invitations", ["expires_at"])

    # Add user ownership and scoping columns to existing resource tables
    # SQLite doesn't support adding foreign keys after creation, so we'll add columns without constraints
    # The relationships will be handled in the ORM models

    # Tools table
    op.add_column("tools", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column("tools", sa.Column("scope_type", sa.String(50), nullable=False, server_default="global"))
    op.add_column("tools", sa.Column("scope_team_id", sa.String(), nullable=True))
    op.create_index("idx_tools_user_id", "tools", ["user_id"])
    op.create_index("idx_tools_scope_type", "tools", ["scope_type"])
    op.create_index("idx_tools_scope_team_id", "tools", ["scope_team_id"])

    # Resources table
    op.add_column("resources", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column("resources", sa.Column("scope_type", sa.String(50), nullable=False, server_default="global"))
    op.add_column("resources", sa.Column("scope_team_id", sa.String(), nullable=True))
    op.create_index("idx_resources_user_id", "resources", ["user_id"])
    op.create_index("idx_resources_scope_type", "resources", ["scope_type"])
    op.create_index("idx_resources_scope_team_id", "resources", ["scope_team_id"])

    # Prompts table
    op.add_column("prompts", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column("prompts", sa.Column("scope_type", sa.String(50), nullable=False, server_default="global"))
    op.add_column("prompts", sa.Column("scope_team_id", sa.String(), nullable=True))
    op.create_index("idx_prompts_user_id", "prompts", ["user_id"])
    op.create_index("idx_prompts_scope_type", "prompts", ["scope_type"])
    op.create_index("idx_prompts_scope_team_id", "prompts", ["scope_team_id"])

    # Servers table
    op.add_column("servers", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column("servers", sa.Column("scope_type", sa.String(50), nullable=False, server_default="global"))
    op.add_column("servers", sa.Column("scope_team_id", sa.String(), nullable=True))
    op.create_index("idx_servers_user_id", "servers", ["user_id"])
    op.create_index("idx_servers_scope_type", "servers", ["scope_type"])
    op.create_index("idx_servers_scope_team_id", "servers", ["scope_team_id"])

    # Gateways table
    op.add_column("gateways", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column("gateways", sa.Column("scope_type", sa.String(50), nullable=False, server_default="global"))
    op.add_column("gateways", sa.Column("scope_team_id", sa.String(), nullable=True))
    op.create_index("idx_gateways_user_id", "gateways", ["user_id"])
    op.create_index("idx_gateways_scope_type", "gateways", ["scope_type"])
    op.create_index("idx_gateways_scope_team_id", "gateways", ["scope_team_id"])

    # A2A Agents table
    op.add_column("a2a_agents", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column("a2a_agents", sa.Column("scope_type", sa.String(50), nullable=False, server_default="global"))
    op.add_column("a2a_agents", sa.Column("scope_team_id", sa.String(), nullable=True))
    op.create_index("idx_a2a_agents_user_id", "a2a_agents", ["user_id"])
    op.create_index("idx_a2a_agents_scope_type", "a2a_agents", ["scope_type"])
    op.create_index("idx_a2a_agents_scope_team_id", "a2a_agents", ["scope_team_id"])


def downgrade() -> None:
    """Downgrade to remove multi-user support."""

    # Remove indexes and columns (no foreign key constraints to remove in SQLite)
    try:
        op.drop_index("idx_a2a_agents_scope_team_id", "a2a_agents")
        op.drop_index("idx_a2a_agents_scope_type", "a2a_agents")
        op.drop_index("idx_a2a_agents_user_id", "a2a_agents")
        op.drop_column("a2a_agents", "scope_team_id")
        op.drop_column("a2a_agents", "scope_type")
        op.drop_column("a2a_agents", "user_id")
    except Exception:
        pass  # Table might not exist

    try:
        op.drop_index("idx_gateways_scope_team_id", "gateways")
        op.drop_index("idx_gateways_scope_type", "gateways")
        op.drop_index("idx_gateways_user_id", "gateways")
        op.drop_column("gateways", "scope_team_id")
        op.drop_column("gateways", "scope_type")
        op.drop_column("gateways", "user_id")
    except Exception:
        pass

    try:
        op.drop_index("idx_servers_scope_team_id", "servers")
        op.drop_index("idx_servers_scope_type", "servers")
        op.drop_index("idx_servers_user_id", "servers")
        op.drop_column("servers", "scope_team_id")
        op.drop_column("servers", "scope_type")
        op.drop_column("servers", "user_id")
    except Exception:
        pass

    try:
        op.drop_index("idx_prompts_scope_team_id", "prompts")
        op.drop_index("idx_prompts_scope_type", "prompts")
        op.drop_index("idx_prompts_user_id", "prompts")
        op.drop_column("prompts", "scope_team_id")
        op.drop_column("prompts", "scope_type")
        op.drop_column("prompts", "user_id")
    except Exception:
        pass

    try:
        op.drop_index("idx_resources_scope_team_id", "resources")
        op.drop_index("idx_resources_scope_type", "resources")
        op.drop_index("idx_resources_user_id", "resources")
        op.drop_column("resources", "scope_team_id")
        op.drop_column("resources", "scope_type")
        op.drop_column("resources", "user_id")
    except Exception:
        pass

    try:
        op.drop_index("idx_tools_scope_team_id", "tools")
        op.drop_index("idx_tools_scope_type", "tools")
        op.drop_index("idx_tools_user_id", "tools")
        op.drop_column("tools", "scope_team_id")
        op.drop_column("tools", "scope_type")
        op.drop_column("tools", "user_id")
    except Exception:
        pass

    # Drop new tables (in reverse order of creation)
    op.drop_table("team_invitations")
    op.drop_table("team_members")
    op.drop_table("teams")
    op.drop_table("auth_events")
    op.drop_table("api_tokens")
    op.drop_table("user_sessions")
    op.drop_table("users")
