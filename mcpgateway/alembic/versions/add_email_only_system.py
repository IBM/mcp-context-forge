# -*- coding: utf-8 -*-
"""Add email-only authentication system

Revision ID: email_only_001
Revises: multi_user_001
Create Date: 2025-01-24 10:00:00.000000

"""
# Standard
import uuid

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "email_only_001"
down_revision = "multi_user_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade to add email-only authentication system."""

    # Create email_users table
    op.create_table(
        "email_users",
        sa.Column("email", sa.String(255), nullable=False, primary_key=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, default=False),
        # Status fields
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        # Authentication and security
        sa.Column("auth_provider", sa.String(50), nullable=False, default="local"),
        sa.Column("password_hash_type", sa.String(20), nullable=False, default="argon2id"),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, default=0),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        # Personal team reference
        sa.Column("personal_team_id", sa.String(), nullable=True),
        sa.UniqueConstraint("email"),
    )

    # Create indexes for email_users
    op.create_index("idx_email_users_email", "email_users", ["email"])
    op.create_index("idx_email_users_auth_provider", "email_users", ["auth_provider"])
    op.create_index("idx_email_users_active", "email_users", ["is_active"])

    # Create email_teams table
    op.create_table(
        "email_teams",
        sa.Column("id", sa.String(), nullable=False, primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        # Team settings
        sa.Column("is_personal", sa.Boolean(), nullable=False, default=False),
        sa.Column("visibility", sa.String(20), nullable=False, default="private"),
        sa.Column("auto_join", sa.Boolean(), nullable=False, default=False),
        sa.Column("max_members", sa.Integer(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.UniqueConstraint("slug"),
        sa.ForeignKeyConstraint(["created_by"], ["email_users.email"], ondelete="CASCADE"),
    )

    # Create indexes for email_teams
    op.create_index("idx_email_teams_created_by", "email_teams", ["created_by"])
    op.create_index("idx_email_teams_is_personal", "email_teams", ["is_personal"])
    op.create_index("idx_email_teams_visibility", "email_teams", ["visibility"])

    # Create email_team_members table
    op.create_table(
        "email_team_members",
        sa.Column("id", sa.String(), nullable=False, primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("user_email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("invited_by", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["email_teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_email"], ["email_users.email"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["email_users.email"]),
        sa.UniqueConstraint("team_id", "user_email", name="uq_email_team_user_membership"),
    )

    # Create indexes for email_team_members
    op.create_index("idx_email_team_members_team_id", "email_team_members", ["team_id"])
    op.create_index("idx_email_team_members_user_email", "email_team_members", ["user_email"])
    op.create_index("idx_email_team_members_role", "email_team_members", ["role"])

    # Create email_team_invitations table
    op.create_table(
        "email_team_invitations",
        sa.Column("id", sa.String(), nullable=False, primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, default="member"),
        sa.Column("invited_by", sa.String(255), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(255), nullable=True),
        sa.Column("token", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.ForeignKeyConstraint(["team_id"], ["email_teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["email_users.email"]),
        sa.ForeignKeyConstraint(["accepted_by"], ["email_users.email"]),
        sa.UniqueConstraint("team_id", "email", name="uq_email_team_invitation"),
        sa.UniqueConstraint("token"),
    )

    # Create email_api_tokens table with scoping
    op.create_table(
        "email_api_tokens",
        sa.Column("id", sa.String(), nullable=False, primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("user_email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("jti", sa.String(), nullable=False),
        # Scoping fields (#282)
        sa.Column("server_id", sa.String(), nullable=True),
        sa.Column("resource_scopes", sa.JSON(), nullable=True),
        sa.Column("ip_restrictions", sa.JSON(), nullable=True),
        sa.Column("time_restrictions", sa.JSON(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
        # Status
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["user_email"], ["email_users.email"], ondelete="CASCADE"),
        sa.UniqueConstraint("jti"),
        sa.UniqueConstraint("user_email", "name", name="uq_email_user_token_name"),
    )

    # Create email_auth_events table
    op.create_table(
        "email_auth_events",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["user_email"], ["email_users.email"], ondelete="SET NULL"),
    )

    # Create trusted_domains table
    op.create_table(
        "trusted_domains",
        sa.Column("id", sa.String(), nullable=False, primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("auto_approve", sa.Boolean(), nullable=False, default=True),
        sa.Column("sso_provider", sa.String(50), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.UniqueConstraint("domain"),
        sa.ForeignKeyConstraint(["created_by"], ["email_users.email"]),
    )

    # Create user_registrations table
    op.create_table(
        "user_registrations",
        sa.Column("id", sa.String(), nullable=False, primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("auth_provider", sa.String(50), nullable=False, default="local"),
        sa.Column("status", sa.String(20), nullable=False, default="pending_approval"),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(255), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("external_profile", sa.JSON(), nullable=True),
        sa.UniqueConstraint("email"),
        sa.ForeignKeyConstraint(["approved_by"], ["email_users.email"]),
    )

    # Create email_verifications table
    op.create_table(
        "email_verifications",
        sa.Column("id", sa.String(), nullable=False, primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("verification_token", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("verification_token"),
    )

    # Create password_resets table
    op.create_table(
        "password_resets",
        sa.Column("id", sa.String(), nullable=False, primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("user_email", sa.String(255), nullable=False),
        sa.Column("reset_token", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("reset_token"),
        sa.ForeignKeyConstraint(["user_email"], ["email_users.email"], ondelete="CASCADE"),
    )

    # Create sso_providers table
    op.create_table(
        "sso_providers",
        sa.Column("id", sa.String(), nullable=False, primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("provider_type", sa.String(50), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, default=False),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("client_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("authorization_url", sa.String(500), nullable=True),
        sa.Column("token_url", sa.String(500), nullable=True),
        sa.Column("userinfo_url", sa.String(500), nullable=True),
        sa.Column("issuer", sa.String(255), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=True),
        sa.Column("attribute_mapping", sa.JSON(), nullable=True),
        sa.Column("trusted_domains", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("name"),
    )

    # Create user_external_profiles table
    op.create_table(
        "user_external_profiles",
        sa.Column("id", sa.String(), nullable=False, primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("user_email", sa.String(255), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("external_username", sa.String(255), nullable=True),
        sa.Column("profile_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_sync", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_email"], ["email_users.email"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["sso_providers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("provider_id", "external_id"),
    )


def downgrade() -> None:
    """Downgrade to remove email-only authentication system."""

    # Drop tables in reverse order
    op.drop_table("user_external_profiles")
    op.drop_table("sso_providers")
    op.drop_table("password_resets")
    op.drop_table("email_verifications")
    op.drop_table("user_registrations")
    op.drop_table("trusted_domains")
    op.drop_table("email_auth_events")
    op.drop_table("email_api_tokens")
    op.drop_table("email_team_invitations")
    op.drop_table("email_team_members")
    op.drop_table("email_teams")
    op.drop_table("email_users")
