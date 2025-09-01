# -*- coding: utf-8 -*-
# pylint: disable=no-member,not-callable
"""consolidated_multiuser_team_rbac_migration

Revision ID: cfc3d6aa0fb2
Revises: 733159a4fa74
Create Date: 2025-08-29 22:50:14.315471

This migration consolidates all multi-user, team scoping, RBAC, and authentication
features into a single migration for clean deployment.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "cfc3d6aa0fb2"
down_revision: Union[str, Sequence[str], None] = "733159a4fa74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Consolidated upgrade schema for multi-user, team, and RBAC features."""

    def safe_create_index(index_name: str, table_name: str, columns: list):
        """Helper function to safely create indexes, ignoring if they already exist.

        Args:
            index_name: Name of the index to create
            table_name: Name of the table to create index on
            columns: List of column names for the index
        """
        try:
            op.create_index(index_name, table_name, columns)
        except Exception:
            pass  # Index might already exist

    # ===============================
    # STEP 1: Core User Authentication
    # ===============================

    # Check if email_users table exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "email_users" not in existing_tables:
        # Create email_users table
        op.create_table(
            "email_users",
            sa.Column("email", sa.String(255), primary_key=True, index=True),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("full_name", sa.String(255), nullable=True),
            sa.Column("is_admin", sa.Boolean, default=False, nullable=False),
            sa.Column("is_active", sa.Boolean, default=True, nullable=False),
            sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("auth_provider", sa.String(50), default="local", nullable=False),
            sa.Column("password_hash_type", sa.String(20), default="argon2id", nullable=False),
            sa.Column("failed_login_attempts", sa.Integer, default=0, nullable=False),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        )

        safe_create_index(op.f("ix_email_users_email"), "email_users", ["email"])

    if "email_auth_events" not in existing_tables:
        # Create email_auth_events table
        op.create_table(
            "email_auth_events",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("user_email", sa.String(255), nullable=True, index=True),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("success", sa.Boolean, nullable=False),
            sa.Column("ip_address", sa.String(45), nullable=True),  # IPv6 compatible
            sa.Column("user_agent", sa.Text, nullable=True),
            sa.Column("failure_reason", sa.String(255), nullable=True),
            sa.Column("details", sa.Text, nullable=True),  # JSON string
        )
        safe_create_index(op.f("ix_email_auth_events_user_email"), "email_auth_events", ["user_email"])
        safe_create_index(op.f("ix_email_auth_events_timestamp"), "email_auth_events", ["timestamp"])

    # ===============================
    # STEP 2: Team Management
    # ===============================

    if "email_teams" not in existing_tables:
        # Create email_teams table
        op.create_table(
            "email_teams",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("is_personal", sa.Boolean(), nullable=False, default=False),
            sa.Column("visibility", sa.String(20), nullable=False, default="private"),
            sa.Column("max_members", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
            sa.CheckConstraint("visibility IN ('private', 'public')", name="ck_email_teams_visibility"),
        )
    else:
        # Add visibility constraint to existing email_teams table if it doesn't exist
        try:
            # Use batch mode for SQLite compatibility
            with op.batch_alter_table("email_teams", schema=None) as batch_op:
                batch_op.create_check_constraint("ck_email_teams_visibility", "visibility IN ('private', 'public')")
        except Exception:
            # Constraint might already exist, ignore
            pass

    if "email_team_members" not in existing_tables:
        # Create email_team_members table
        op.create_table(
            "email_team_members",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("team_id", sa.String(36), nullable=False),
            sa.Column("user_email", sa.String(255), nullable=False),
            sa.Column("role", sa.String(50), nullable=False, default="member"),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("invited_by", sa.String(255), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("team_id", "user_email", name="uq_team_member"),
        )

    if "email_team_invitations" not in existing_tables:
        # Create email_team_invitations table
        op.create_table(
            "email_team_invitations",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("team_id", sa.String(36), nullable=False),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("role", sa.String(50), nullable=False, default="member"),
            sa.Column("invited_by", sa.String(255), nullable=False),
            sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("token", sa.String(500), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token"),
        )

    # ===============================
    # STEP 3: JWT Token Management
    # ===============================

    if "email_api_tokens" not in existing_tables:
        # Create email_api_tokens table
        op.create_table(
            "email_api_tokens",
            sa.Column("id", sa.String(36), nullable=False, comment="Unique token ID"),
            sa.Column("user_email", sa.String(255), nullable=False, comment="Owner email address"),
            sa.Column("name", sa.String(255), nullable=False, comment="Human-readable token name"),
            sa.Column("jti", sa.String(36), nullable=False, comment="JWT ID for revocation tracking"),
            sa.Column("token_hash", sa.String(255), nullable=False, comment="Hashed token value"),
            # Scoping fields
            sa.Column("server_id", sa.String(36), nullable=True, comment="Limited to specific server (NULL = global)"),
            sa.Column("resource_scopes", sa.Text(), nullable=True, comment="JSON array of resource permissions"),
            sa.Column("ip_restrictions", sa.Text(), nullable=True, comment="JSON array of allowed IP addresses/CIDR"),
            sa.Column("time_restrictions", sa.Text(), nullable=True, comment="JSON object of time-based restrictions"),
            sa.Column("usage_limits", sa.Text(), nullable=True, comment="JSON object of usage limits"),
            # Lifecycle fields
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="Token creation timestamp"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, comment="Token expiry timestamp"),
            sa.Column("last_used", sa.DateTime(timezone=True), nullable=True, comment="Last usage timestamp"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"), comment="Active status flag"),
            # Metadata fields
            sa.Column("description", sa.Text(), nullable=True, comment="Token description"),
            sa.Column("tags", sa.Text(), nullable=True, comment="JSON array of tags"),
            sa.Column("team_id", sa.String(length=36), nullable=True),  # Team scoping
            # Constraints
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("jti", name="uq_email_api_tokens_jti"),
            sa.UniqueConstraint("user_email", "name", name="uq_email_api_tokens_user_email_name"),
        )

        # Create indexes for email_api_tokens
        safe_create_index("idx_email_api_tokens_user_email", "email_api_tokens", ["user_email"])
        safe_create_index("idx_email_api_tokens_server_id", "email_api_tokens", ["server_id"])
        safe_create_index("idx_email_api_tokens_is_active", "email_api_tokens", ["is_active"])
        safe_create_index("idx_email_api_tokens_expires_at", "email_api_tokens", ["expires_at"])
        safe_create_index("idx_email_api_tokens_last_used", "email_api_tokens", ["last_used"])
        safe_create_index(op.f("ix_email_api_tokens_team_id"), "email_api_tokens", ["team_id"])

    if "token_revocations" not in existing_tables:
        # Create token_revocations table (blacklist)
        op.create_table(
            "token_revocations",
            sa.Column("jti", sa.String(36), nullable=False, comment="JWT ID of revoked token"),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="Revocation timestamp"),
            sa.Column("revoked_by", sa.String(255), nullable=True, comment="Email of user who revoked token"),
            sa.Column("reason", sa.String(255), nullable=True, comment="Reason for revocation"),
            # Constraints
            sa.PrimaryKeyConstraint("jti"),
        )

        # Create indexes for token_revocations
        safe_create_index("idx_token_revocations_revoked_at", "token_revocations", ["revoked_at"])
        safe_create_index("idx_token_revocations_revoked_by", "token_revocations", ["revoked_by"])

    # ===============================
    # STEP 4: RBAC System
    # ===============================

    if "roles" not in existing_tables:
        # Create RBAC roles table
        op.create_table(
            "roles",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("scope", sa.String(length=20), nullable=False),
            sa.Column("permissions", sa.JSON(), nullable=False),
            sa.Column("inherits_from", sa.String(length=36), nullable=True),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("is_system_role", sa.Boolean(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            comment="Roles for RBAC permission system",
        )

    if "user_roles" not in existing_tables:
        # Create RBAC user_roles table
        op.create_table(
            "user_roles",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_email", sa.String(length=255), nullable=False),
            sa.Column("role_id", sa.String(length=36), nullable=False),
            sa.Column("scope", sa.String(length=20), nullable=False),
            sa.Column("scope_id", sa.String(length=36), nullable=True),
            sa.Column("granted_by", sa.String(length=255), nullable=False),
            sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            comment="User role assignments for RBAC system",
        )

        # Create indexes for performance
        safe_create_index("idx_user_roles_user_email", "user_roles", ["user_email"])
        safe_create_index("idx_user_roles_role_id", "user_roles", ["role_id"])
        safe_create_index("idx_user_roles_scope", "user_roles", ["scope"])
        safe_create_index("idx_user_roles_scope_id", "user_roles", ["scope_id"])

    if "permission_audit_log" not in existing_tables:
        # Create RBAC permission_audit_log table
        op.create_table(
            "permission_audit_log",
            sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("user_email", sa.String(length=255), nullable=True),
            sa.Column("permission", sa.String(length=100), nullable=False),
            sa.Column("resource_type", sa.String(length=50), nullable=True),
            sa.Column("resource_id", sa.String(length=255), nullable=True),
            sa.Column("team_id", sa.String(length=36), nullable=True),
            sa.Column("granted", sa.Boolean(), nullable=False),
            sa.Column("roles_checked", sa.JSON(), nullable=True),
            sa.Column("ip_address", sa.String(length=45), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            comment="Permission audit log for RBAC compliance",
        )

        safe_create_index("idx_permission_audit_log_user_email", "permission_audit_log", ["user_email"])
        safe_create_index("idx_permission_audit_log_timestamp", "permission_audit_log", ["timestamp"])
        safe_create_index("idx_permission_audit_log_permission", "permission_audit_log", ["permission"])

    # ===============================
    # STEP 5: User Approval System
    # ===============================

    if "pending_user_approvals" not in existing_tables:
        op.create_table(
            "pending_user_approvals",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("full_name", sa.String(length=255), nullable=False),
            sa.Column("auth_provider", sa.String(length=50), nullable=False),
            sa.Column("sso_metadata", sa.JSON(), nullable=True),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("approved_by", sa.String(length=255), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("admin_notes", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )

    # ===============================
    # STEP 6: Add Team Scoping to Existing Tables
    # ===============================

    # Check which columns already exist before adding them
    def add_team_columns_if_not_exists(table_name: str):
        """Add team_id and owner_email columns to a table if they don't already exist.

        Args:
            table_name: Name of the table to add columns to.
        """
        columns = inspector.get_columns(table_name)
        existing_column_names = [col["name"] for col in columns]

        if "team_id" not in existing_column_names:
            op.add_column(table_name, sa.Column("team_id", sa.String(length=36), nullable=True))

        if "owner_email" not in existing_column_names:
            op.add_column(table_name, sa.Column("owner_email", sa.String(length=255), nullable=True))

        if "visibility" not in existing_column_names:
            op.add_column(table_name, sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"))

    # Add team scoping to existing resource tables if they exist
    resource_tables = ["prompts", "resources", "servers", "tools", "gateways", "a2a_agents"]

    for table_name in resource_tables:
        if table_name in existing_tables:
            add_team_columns_if_not_exists(table_name)

    # ===============================
    # STEP 8: SSO Provider Management
    # ===============================

    if "sso_providers" not in existing_tables:
        # Create sso_providers table
        op.create_table(
            "sso_providers",
            sa.Column("id", sa.String(50), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False, unique=True),
            sa.Column("display_name", sa.String(100), nullable=False),
            sa.Column("provider_type", sa.String(20), nullable=False),
            sa.Column("is_enabled", sa.Boolean, nullable=False, default=True),
            sa.Column("client_id", sa.String(255), nullable=False),
            sa.Column("client_secret_encrypted", sa.Text, nullable=False),
            sa.Column("authorization_url", sa.String(500), nullable=False),
            sa.Column("token_url", sa.String(500), nullable=False),
            sa.Column("userinfo_url", sa.String(500), nullable=False),
            sa.Column("issuer", sa.String(500), nullable=True),
            sa.Column("trusted_domains", sa.JSON, nullable=False, default="[]"),
            sa.Column("scope", sa.String(200), nullable=False, default="openid profile email"),
            sa.Column("auto_create_users", sa.Boolean, nullable=False, default=True),
            sa.Column("team_mapping", sa.JSON, nullable=False, default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "email_team_join_requests" not in existing_tables:
        # Create email_team_join_requests table
        op.create_table(
            "email_team_join_requests",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("team_id", sa.String(36), nullable=False),
            sa.Column("user_email", sa.String(255), nullable=False),
            sa.Column("message", sa.Text, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, default="pending"),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by", sa.String(255), nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("team_id", "user_email", name="uq_team_join_request"),
        )

    if "sso_auth_sessions" not in existing_tables:
        # Create sso_auth_sessions table
        op.create_table(
            "sso_auth_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("provider_id", sa.String(50), nullable=False),
            sa.Column("state", sa.String(255), nullable=False, unique=True),
            sa.Column("code_verifier", sa.String(255), nullable=True),
            sa.Column("nonce", sa.String(255), nullable=True),
            sa.Column("redirect_uri", sa.String(500), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("user_email", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "pending_user_approvals" not in existing_tables:
        # Create pending_user_approvals table
        op.create_table(
            "pending_user_approvals",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False, index=True),
            sa.Column("provider_id", sa.String(50), nullable=False),
            sa.Column("provider_user_id", sa.String(255), nullable=True),
            sa.Column("full_name", sa.String(255), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, default="pending"),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by", sa.String(255), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.Text, nullable=True),
            sa.UniqueConstraint("email", "provider_id", name="uq_pending_approval"),
        )

    # Note: Foreign key constraints are intentionally omitted for SQLite compatibility
    # The ORM models handle the relationships properly


def downgrade() -> None:
    """Consolidated downgrade schema for multi-user, team, and RBAC features."""

    def safe_drop_index(index_name: str, table_name: str):
        """Helper function to safely drop indexes, ignoring if they don't exist.

        Args:
            index_name: Name of the index to drop
            table_name: Name of the table containing the index
        """
        try:
            op.drop_index(index_name, table_name)
        except Exception:
            pass  # Index might not exist

    # Get current tables to check what exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Remove team scoping columns from resource tables
    resource_tables = ["tools", "servers", "resources", "prompts", "gateways", "a2a_agents"]

    for table_name in resource_tables:
        if table_name in existing_tables:
            columns = inspector.get_columns(table_name)
            existing_column_names = [col["name"] for col in columns]

            # SQLite has issues dropping columns with foreign key constraints
            # Use safe column dropping that ignores errors
            if "visibility" in existing_column_names:
                try:
                    op.drop_column(table_name, "visibility")
                except Exception:
                    pass  # SQLite constraint issues
            if "owner_email" in existing_column_names:
                try:
                    op.drop_column(table_name, "owner_email")
                except Exception:
                    pass  # SQLite constraint issues
            if "team_id" in existing_column_names:
                try:
                    op.drop_column(table_name, "team_id")
                except Exception:
                    pass  # SQLite constraint issues

    # Drop new tables in reverse order
    tables_to_drop = [
        "sso_auth_sessions",
        "sso_providers",
        "email_team_join_requests",
        "pending_user_approvals",
        "permission_audit_log",
        "user_roles",
        "roles",
        "token_revocations",
        "email_api_tokens",
        "email_team_invitations",
        "email_team_members",
        "email_teams",
        "email_auth_events",
        "email_users",
    ]

    for table_name in tables_to_drop:
        if table_name in existing_tables:
            # Drop indexes first if they exist
            if table_name == "email_api_tokens":
                safe_drop_index("ix_email_api_tokens_team_id", table_name)
                safe_drop_index("idx_email_api_tokens_last_used", table_name)
                safe_drop_index("idx_email_api_tokens_expires_at", table_name)
                safe_drop_index("idx_email_api_tokens_is_active", table_name)
                safe_drop_index("idx_email_api_tokens_server_id", table_name)
                safe_drop_index("idx_email_api_tokens_user_email", table_name)
            elif table_name == "token_revocations":
                safe_drop_index("idx_token_revocations_revoked_by", table_name)
                safe_drop_index("idx_token_revocations_revoked_at", table_name)
            elif table_name == "user_roles":
                safe_drop_index("idx_user_roles_scope_id", table_name)
                safe_drop_index("idx_user_roles_scope", table_name)
                safe_drop_index("idx_user_roles_role_id", table_name)
                safe_drop_index("idx_user_roles_user_email", table_name)
            elif table_name == "permission_audit_log":
                safe_drop_index("idx_permission_audit_log_permission", table_name)
                safe_drop_index("idx_permission_audit_log_timestamp", table_name)
                safe_drop_index("idx_permission_audit_log_user_email", table_name)
            elif table_name == "email_auth_events":
                safe_drop_index(op.f("ix_email_auth_events_timestamp"), table_name)
                safe_drop_index(op.f("ix_email_auth_events_user_email"), table_name)
            elif table_name == "email_users":
                safe_drop_index(op.f("ix_email_users_email"), table_name)

            # Drop the table
            op.drop_table(table_name)
