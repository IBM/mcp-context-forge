# -*- coding: utf-8 -*-
# pylint: disable=no-member,not-callable
"""Location: ./mcpgateway/alembic/versions/cfc3d6aa0fb2_consolidated_multiuser_team_rbac_.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

consolidated_multiuser_team_rbac_migration

Revision ID: cfc3d6aa0fb2
Revises: 733159a4fa74
Create Date: 2025-08-29 22:50:14.315471

This migration consolidates all multi-user, team scoping, RBAC, and authentication
features into a single clean DDL-only migration for reliable deployment across
SQLite, PostgreSQL, and MySQL.

Data population (admin users, teams, resource assignment) is handled separately
by bootstrap_db.py to ensure proper transaction management.
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
    """Consolidated upgrade schema for multi-user, team, and RBAC features.

    This migration creates all necessary database tables for the multitenancy system.
    Data population is handled separately by bootstrap_db.py.
    """

    def safe_create_index(index_name: str, table_name: str, columns: list):
        """Helper function to safely create indexes, ignoring if they already exist.

        Args:
            index_name: Name of the index to create
            table_name: Name of the table to create index on
            columns: List of column names for the index
        """
        try:
            bind = op.get_bind()
            inspector = sa.inspect(bind)
            existing_indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]
            if index_name not in existing_indexes:
                op.create_index(index_name, table_name, columns)
        except Exception as e:
            print(f"Warning: Could not create index {index_name} on {table_name}: {e}")

    # Check if this is a fresh database without existing tables
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if not inspector.has_table("gateways"):
        print("Fresh database detected. Creating complete multitenancy schema...")
    else:
        print("Existing database detected. Applying multitenancy schema migration...")

    # ===============================
    # STEP 1: Core User Authentication Tables
    # ===============================

    if "email_users" not in existing_tables:
        print("Creating email_users table...")
        op.create_table(
            "email_users",
            sa.Column("email", sa.String(255), primary_key=True, index=True),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("full_name", sa.String(255), nullable=True),
            sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("auth_provider", sa.String(50), nullable=False, server_default=sa.text("'local'")),
            sa.Column("password_hash_type", sa.String(20), nullable=False, server_default=sa.text("'argon2id'")),
            sa.Column("failed_login_attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        )
        safe_create_index(op.f("ix_email_users_email"), "email_users", ["email"])

    if "email_auth_events" not in existing_tables:
        print("Creating email_auth_events table...")
        op.create_table(
            "email_auth_events",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("user_email", sa.String(255), nullable=True),
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
    # STEP 2: Team Management Tables
    # ===============================

    if "email_teams" not in existing_tables:
        print("Creating email_teams table...")
        op.create_table(
            "email_teams",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("is_personal", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("visibility", sa.String(20), nullable=False, server_default=sa.text("'private'")),
            sa.Column("max_members", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
            sa.CheckConstraint("visibility IN ('private', 'public')", name="ck_email_teams_visibility"),
        )
    else:
        # Add visibility constraint to existing email_teams table if it doesn't exist
        try:
            existing_constraints = [c["name"] for c in inspector.get_check_constraints("email_teams")]
            if "ck_email_teams_visibility" not in existing_constraints:
                print("Adding visibility constraint to existing email_teams table...")
                # Note: Data normalization will be handled by bootstrap_db.py
                # to avoid mixing DML with DDL operations

                # Use batch mode for SQLite compatibility
                with op.batch_alter_table("email_teams", schema=None) as batch_op:
                    batch_op.create_check_constraint("ck_email_teams_visibility", "visibility IN ('private', 'public')")
        except Exception as e:
            print(f"Warning: Could not create visibility constraint on email_teams: {e}")

    if "email_team_members" not in existing_tables:
        print("Creating email_team_members table...")
        op.create_table(
            "email_team_members",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("team_id", sa.String(36), nullable=False),
            sa.Column("user_email", sa.String(255), nullable=False),
            sa.Column("role", sa.String(50), nullable=False, server_default=sa.text("'member'")),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("invited_by", sa.String(255), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("team_id", "user_email", name="uq_team_member"),
        )

    if "email_team_invitations" not in existing_tables:
        print("Creating email_team_invitations table...")
        op.create_table(
            "email_team_invitations",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("team_id", sa.String(36), nullable=False),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("role", sa.String(50), nullable=False, server_default=sa.text("'member'")),
            sa.Column("invited_by", sa.String(255), nullable=False),
            sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("token", sa.String(500), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token"),
        )

    if "email_team_join_requests" not in existing_tables:
        print("Creating email_team_join_requests table...")
        op.create_table(
            "email_team_join_requests",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("team_id", sa.String(36), nullable=False),
            sa.Column("user_email", sa.String(255), nullable=False),
            sa.Column("message", sa.Text, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by", sa.String(255), nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("team_id", "user_email", name="uq_team_join_request"),
        )

    # ===============================
    # STEP 3: JWT Token Management Tables
    # ===============================

    if "email_api_tokens" not in existing_tables:
        print("Creating email_api_tokens table...")
        op.create_table(
            "email_api_tokens",
            sa.Column("id", sa.String(36), nullable=False, comment="Unique token ID"),
            sa.Column("user_email", sa.String(255), nullable=False, comment="Owner email address"),
            sa.Column("name", sa.String(255), nullable=False, comment="Human-readable token name"),
            sa.Column("jti", sa.String(36), nullable=False, comment="JWT ID for revocation tracking"),
            sa.Column("token_hash", sa.String(255), nullable=False, comment="Hashed token value"),
            # Scoping fields - with proper JSON types and defaults
            sa.Column("server_id", sa.String(36), nullable=True, comment="Limited to specific server (NULL = global)"),
            sa.Column("resource_scopes", sa.JSON(), nullable=True, comment="JSON array of resource permissions"),
            sa.Column("ip_restrictions", sa.JSON(), nullable=True, comment="JSON array of allowed IP addresses/CIDR"),
            sa.Column("time_restrictions", sa.JSON(), nullable=True, comment="JSON object of time-based restrictions"),
            sa.Column("usage_limits", sa.JSON(), nullable=True, comment="JSON object of usage limits"),
            # Lifecycle fields
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="Token creation timestamp"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, comment="Token expiry timestamp"),
            sa.Column("last_used", sa.DateTime(timezone=True), nullable=True, comment="Last usage timestamp"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true(), comment="Active status flag"),
            # Metadata fields
            sa.Column("description", sa.Text(), nullable=True, comment="Token description"),
            sa.Column("tags", sa.JSON(), nullable=True, comment="JSON array of tags"),
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
        print("Creating token_revocations table...")
        op.create_table(
            "token_revocations",
            sa.Column("jti", sa.String(36), nullable=False, comment="JWT ID of revoked token"),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="Revocation timestamp"),
            sa.Column("revoked_by", sa.String(255), nullable=False, comment="Email of user who revoked token"),
            sa.Column("reason", sa.String(255), nullable=True, comment="Reason for revocation"),
            # Constraints
            sa.PrimaryKeyConstraint("jti"),
        )

        # Create indexes for token_revocations
        safe_create_index("idx_token_revocations_revoked_at", "token_revocations", ["revoked_at"])
        safe_create_index("idx_token_revocations_revoked_by", "token_revocations", ["revoked_by"])

    if "token_usage_logs" not in existing_tables:
        print("Creating token_usage_logs table...")
        op.create_table(
            "token_usage_logs",
            sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True, comment="Auto-incrementing log ID"),
            sa.Column("token_jti", sa.String(36), nullable=False, comment="Token JWT ID reference"),
            sa.Column("user_email", sa.String(255), nullable=False, comment="Token owner's email"),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="Request timestamp"),
            sa.Column("endpoint", sa.String(255), nullable=True, comment="API endpoint accessed"),
            sa.Column("method", sa.String(10), nullable=True, comment="HTTP method used"),
            sa.Column("ip_address", sa.String(45), nullable=True, comment="Client IP address (IPv6 compatible)"),
            sa.Column("user_agent", sa.Text(), nullable=True, comment="Client user agent"),
            sa.Column("status_code", sa.Integer(), nullable=True, comment="HTTP response status"),
            sa.Column("response_time_ms", sa.Integer(), nullable=True, comment="Response time in milliseconds"),
            sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false(), comment="Whether request was blocked"),
            sa.Column("block_reason", sa.String(255), nullable=True, comment="Reason for blocking if applicable"),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create indexes for token_usage_logs
        safe_create_index("idx_token_usage_logs_token_jti", "token_usage_logs", ["token_jti"])
        safe_create_index("idx_token_usage_logs_user_email", "token_usage_logs", ["user_email"])
        safe_create_index("idx_token_usage_logs_timestamp", "token_usage_logs", ["timestamp"])
        safe_create_index("idx_token_usage_logs_token_jti_timestamp", "token_usage_logs", ["token_jti", "timestamp"])
        safe_create_index("idx_token_usage_logs_user_email_timestamp", "token_usage_logs", ["user_email", "timestamp"])

    # ===============================
    # STEP 4: RBAC System Tables
    # ===============================

    if "roles" not in existing_tables:
        print("Creating roles table...")
        op.create_table(
            "roles",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("scope", sa.String(length=20), nullable=False),
            sa.Column("permissions", sa.JSON(), nullable=False),  # JSON type for proper validation
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
        print("Creating user_roles table...")
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
        print("Creating permission_audit_log table...")
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
            sa.Column("roles_checked", sa.JSON(), nullable=True),  # JSON type for proper validation
            sa.Column("ip_address", sa.String(length=45), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            comment="Permission audit log for RBAC compliance",
        )

        safe_create_index("idx_permission_audit_log_user_email", "permission_audit_log", ["user_email"])
        safe_create_index("idx_permission_audit_log_timestamp", "permission_audit_log", ["timestamp"])
        safe_create_index("idx_permission_audit_log_permission", "permission_audit_log", ["permission"])

    # ===============================
    # STEP 5: SSO Provider Management Tables
    # ===============================

    if "sso_providers" not in existing_tables:
        print("Creating sso_providers table...")
        op.create_table(
            "sso_providers",
            sa.Column("id", sa.String(50), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False, unique=True),
            sa.Column("display_name", sa.String(100), nullable=False),
            sa.Column("provider_type", sa.String(20), nullable=False),
            sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("client_id", sa.String(255), nullable=False),
            sa.Column("client_secret_encrypted", sa.Text, nullable=False),
            sa.Column("authorization_url", sa.String(500), nullable=False),
            sa.Column("token_url", sa.String(500), nullable=False),
            sa.Column("userinfo_url", sa.String(500), nullable=False),
            sa.Column("issuer", sa.String(500), nullable=True),
            sa.Column("trusted_domains", sa.JSON(), nullable=True),  # JSON type for proper validation
            sa.Column("scope", sa.String(200), nullable=False, server_default=sa.text("'openid profile email'")),
            sa.Column("auto_create_users", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("team_mapping", sa.JSON(), nullable=True),  # JSON type for proper validation
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "sso_auth_sessions" not in existing_tables:
        print("Creating sso_auth_sessions table...")
        op.create_table(
            "sso_auth_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("provider_id", sa.String(50), nullable=False),
            sa.Column("state", sa.String(128), nullable=False, unique=True),
            sa.Column("code_verifier", sa.String(128), nullable=True),
            sa.Column("nonce", sa.String(128), nullable=True),
            sa.Column("redirect_uri", sa.String(500), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("user_email", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "pending_user_approvals" not in existing_tables:
        print("Creating pending_user_approvals table...")
        op.create_table(
            "pending_user_approvals",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False, unique=True),
            sa.Column("full_name", sa.String(255), nullable=False),
            sa.Column("auth_provider", sa.String(50), nullable=False),
            sa.Column("sso_metadata", sa.JSON(), nullable=True),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("approved_by", sa.String(255), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("rejection_reason", sa.Text, nullable=True),
            sa.Column("admin_notes", sa.Text, nullable=True),
        )

        # Ensure index on email for quick lookup (safe on both SQLite/PostgreSQL)
        safe_create_index(op.f("ix_pending_user_approvals_email"), "pending_user_approvals", ["email"])

    # ===============================
    # STEP 6: Add Team Scoping to Existing Resource Tables
    # ===============================

    def add_team_columns_if_not_exists(table_name: str):
        """Add team_id, owner_email, and visibility columns to a table if they don't already exist.

        Args:
            table_name: Name of the table to add columns to.
        """
        if table_name not in existing_tables:
            return

        columns = inspector.get_columns(table_name)
        existing_column_names = [col["name"] for col in columns]

        # Use batch mode for SQLite compatibility
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            if "team_id" not in existing_column_names:
                print(f"  Adding team_id column to {table_name}")
                batch_op.add_column(sa.Column("team_id", sa.String(length=36), nullable=True))

            if "owner_email" not in existing_column_names:
                print(f"  Adding owner_email column to {table_name}")
                batch_op.add_column(sa.Column("owner_email", sa.String(length=255), nullable=True))

            if "visibility" not in existing_column_names:
                print(f"  Adding visibility column to {table_name}")
                batch_op.add_column(sa.Column("visibility", sa.String(length=20), nullable=False, server_default=sa.text("'private'")))

    # Add team scoping to existing resource tables if they exist
    resource_tables = ["prompts", "resources", "servers", "tools", "gateways", "a2a_agents"]

    print("Adding team scoping columns to existing resource tables...")
    for table_name in resource_tables:
        if table_name in existing_tables:
            print(f"Processing {table_name}...")
            add_team_columns_if_not_exists(table_name)

    safe_create_index("idx_gateways_team_visibility", "gateways", ["team_id", "visibility"])
    safe_create_index("idx_gateways_owner_visibility", "gateways", ["owner_email", "visibility"])
    safe_create_index("idx_resources_team_visibility", "resources", ["team_id", "visibility"])
    safe_create_index("idx_resources_owner_visibility", "resources", ["owner_email", "visibility"])
    safe_create_index("idx_prompts_team_visibility", "prompts", ["team_id", "visibility"])
    safe_create_index("idx_prompts_owner_visibility", "prompts", ["owner_email", "visibility"])
    safe_create_index("idx_tools_team_visibility", "tools", ["team_id", "visibility"])
    safe_create_index("idx_tools_owner_visibility", "tools", ["owner_email", "visibility"])
    safe_create_index("idx_servers_team_visibility", "servers", ["team_id", "visibility"])
    safe_create_index("idx_servers_owner_visibility", "servers", ["owner_email", "visibility"])

    print("✅ Multitenancy schema migration completed successfully")
    print("📋 Schema changes applied:")
    print("   • Created 15 new multitenancy tables")
    print("   • Added team scoping columns to existing resource tables")
    print("   • Created proper indexes for performance")

    print("\n💡 Next steps:")
    print("   1. Data population handled by bootstrap_db.py during application startup")
    print("   2. Run verification: python3 scripts/verify_multitenancy_0_7_0_migration.py")
    print("   3. Use fix script if needed: python3 scripts/fix_multitenancy_0_7_0_resources.py")

    # Note: Foreign key constraints are intentionally omitted for SQLite compatibility.
    # The ORM models handle the relationships properly.
    # Data population (admin user, teams, resource assignment) is handled by
    # bootstrap_db.py to ensure proper separation of DDL and DML operations.


def downgrade() -> None:
    """Consolidated downgrade schema for multi-user, team, and RBAC features."""

    def safe_drop_index(index_name: str, table_name: str):
        """Helper function to safely drop indexes, ignoring if they don't exist.

        Args:
            index_name: Name of the index to drop
            table_name: Name of the table containing the index
        """
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        existing_tables = inspector.get_table_names()

        if table_name not in existing_tables:
            return
        try:
            existing_indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name)
        except Exception as e:
            print(f"Warning: Could not drop index {index_name} from {table_name}: {e}")

    def safe_drop_table(table_name: str):
        """Helper function to safely drop tables.

        Args:
            table_name: Name of the table to drop
        """
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        existing_tables = inspector.get_table_names()

        if table_name in existing_tables:
            try:
                op.drop_table(table_name)
                print(f"Dropped table {table_name}")
            except Exception as e:
                print(f"Warning: Could not drop table {table_name}: {e}")

    # Get current tables to check what exists
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping downgrade.")
        return

    print("Removing multitenancy schema...")

    # Remove team scoping columns from resource tables
    resource_tables = ["tools", "servers", "resources", "prompts", "gateways", "a2a_agents"]

    print("Removing team scoping columns from resource tables...")
    for table_name in resource_tables:
        if table_name in existing_tables:
            columns = inspector.get_columns(table_name)
            existing_column_names = [col["name"] for col in columns]

            # Use batch mode for SQLite compatibility
            columns_to_drop = []
            if "visibility" in existing_column_names:
                columns_to_drop.append("visibility")
            if "owner_email" in existing_column_names:
                columns_to_drop.append("owner_email")
            if "team_id" in existing_column_names:
                columns_to_drop.append("team_id")

            if columns_to_drop:
                try:
                    print(f"  Dropping columns {columns_to_drop} from {table_name}")
                    with op.batch_alter_table(table_name, schema=None) as batch_op:
                        for col_name in columns_to_drop:
                            batch_op.drop_column(col_name)
                except Exception as e:
                    print(f"Warning: Could not drop columns from {table_name}: {e}")

    # Drop new tables in reverse order
    tables_to_drop = [
        "sso_auth_sessions",
        "sso_providers",
        "email_team_join_requests",
        "pending_user_approvals",
        "permission_audit_log",
        "user_roles",
        "roles",
        "token_usage_logs",
        "token_revocations",
        "email_api_tokens",
        "email_team_invitations",
        "email_team_members",
        "email_teams",
        "email_auth_events",
        "email_users",
    ]

    print("Dropping multitenancy tables...")
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
            elif table_name == "token_usage_logs":
                safe_drop_index("idx_token_usage_logs_user_email_timestamp", table_name)
                safe_drop_index("idx_token_usage_logs_token_jti_timestamp", table_name)
                safe_drop_index("idx_token_usage_logs_timestamp", table_name)
                safe_drop_index("idx_token_usage_logs_user_email", table_name)
                safe_drop_index("idx_token_usage_logs_token_jti", table_name)
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
            elif table_name == "gateways":
                safe_drop_index("idx_gateways_owner_visibility", table_name)
                safe_drop_index("idx_gateways_team_visibility", table_name)
            elif table_name == "resources":
                safe_drop_index("idx_resources_owner_visibility", table_name)
                safe_drop_index("idx_resources_team_visibility", table_name)
            elif table_name == "prompts":
                safe_drop_index("idx_prompts_owner_visibility", table_name)
                safe_drop_index("idx_prompts_team_visibility", table_name)
            elif table_name == "tools":
                safe_drop_index("idx_tools_owner_visibility", table_name)
                safe_drop_index("idx_tools_team_visibility", table_name)
            elif table_name == "servers":
                safe_drop_index("idx_servers_owner_visibility", table_name)
                safe_drop_index("idx_servers_team_visibility", table_name)

            # Drop the table using safe helper
            safe_drop_table(table_name)

    print("✅ Multitenancy schema downgrade completed")
