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
from sqlalchemy import text

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
            existing_indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]
            if index_name not in existing_indexes:
                op.create_index(index_name, table_name, columns)
        except Exception as e:
            print(f"Warning: Could not create index {index_name} on {table_name}: {e}")

    def safe_add_column_if_not_exists(table_name: str, column: sa.Column):
        """Add column to table if it doesn't already exist.

        Args:
            table_name: Name of the table
            column: SQLAlchemy Column object to add
        """
        if table_name in existing_tables:
            columns = [col["name"] for col in inspector.get_columns(table_name)]
            if column.name not in columns:
                op.add_column(table_name, column)

    # ===============================
    # STEP 1: Core User Authentication
    # ===============================

    # Check if email_users table exists
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    if "email_users" not in existing_tables:
        # Create email_users table
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
        # Create email_auth_events table
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
            # Check if constraint already exists by looking at existing constraints
            existing_constraints = [c["name"] for c in inspector.get_check_constraints("email_teams")]
            if "ck_email_teams_visibility" not in existing_constraints:
                # Normalize existing data to satisfy the constraint before adding it
                try:
                    op.execute(
                        sa.text(
                            """
                            UPDATE email_teams
                            SET visibility = 'private'
                            WHERE visibility IS NULL
                               OR visibility NOT IN ('private', 'public')
                            """
                        )
                    )
                except Exception as e:
                    print(f"Warning: Could not normalize email_teams.visibility values: {e}")

                # Use batch mode for SQLite compatibility
                with op.batch_alter_table("email_teams", schema=None) as batch_op:
                    batch_op.create_check_constraint("ck_email_teams_visibility", "visibility IN ('private', 'public')")
        except Exception as e:
            print(f"Warning: Could not create visibility constraint on email_teams: {e}")

    if "email_team_members" not in existing_tables:
        # Create email_team_members table
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
        # Create email_team_invitations table
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
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="Token creation timestamp"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, comment="Token expiry timestamp"),
            sa.Column("last_used", sa.DateTime(timezone=True), nullable=True, comment="Last usage timestamp"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true(), comment="Active status flag"),
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
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="Revocation timestamp"),
            sa.Column("revoked_by", sa.String(255), nullable=True, comment="Email of user who revoked token"),
            sa.Column("reason", sa.String(255), nullable=True, comment="Reason for revocation"),
            # Constraints
            sa.PrimaryKeyConstraint("jti"),
        )

        # Create indexes for token_revocations
        safe_create_index("idx_token_revocations_revoked_at", "token_revocations", ["revoked_at"])
        safe_create_index("idx_token_revocations_revoked_by", "token_revocations", ["revoked_by"])

    if "token_usage_logs" not in existing_tables:
        # Create token_usage_logs table
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
            sa.Column("permissions", sa.Text(), nullable=False),  # JSON as text for cross-DB compatibility
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
            sa.Column("roles_checked", sa.Text(), nullable=True),  # JSON as text for cross-DB compatibility
            sa.Column("ip_address", sa.String(length=45), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            comment="Permission audit log for RBAC compliance",
        )

        safe_create_index("idx_permission_audit_log_user_email", "permission_audit_log", ["user_email"])
        safe_create_index("idx_permission_audit_log_timestamp", "permission_audit_log", ["timestamp"])
        safe_create_index("idx_permission_audit_log_permission", "permission_audit_log", ["permission"])

    # ===============================
    # STEP 5: User Approval System (handled in SSO section)
    # ===============================

    # ===============================
    # STEP 6: Add Team Scoping to Existing Tables
    # ===============================

    # Check which columns already exist before adding them
    def add_team_columns_if_not_exists(table_name: str):
        """Add team_id and owner_email columns to a table if they don't already exist.

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
                batch_op.add_column(sa.Column("team_id", sa.String(length=36), nullable=True))

            if "owner_email" not in existing_column_names:
                batch_op.add_column(sa.Column("owner_email", sa.String(length=255), nullable=True))

            if "visibility" not in existing_column_names:
                batch_op.add_column(sa.Column("visibility", sa.String(length=20), nullable=False, server_default=sa.text("'private'")))

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
            sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("client_id", sa.String(255), nullable=False),
            sa.Column("client_secret_encrypted", sa.Text, nullable=False),
            sa.Column("authorization_url", sa.String(500), nullable=False),
            sa.Column("token_url", sa.String(500), nullable=False),
            sa.Column("userinfo_url", sa.String(500), nullable=False),
            sa.Column("issuer", sa.String(500), nullable=True),
            sa.Column("trusted_domains", sa.Text, nullable=False, server_default=sa.text("'[]'")),  # JSON as text for cross-DB compatibility
            sa.Column("scope", sa.String(200), nullable=False, server_default=sa.text("'openid profile email'")),
            sa.Column("auto_create_users", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("team_mapping", sa.Text, nullable=False, server_default=sa.text("'{}'")),  # JSON as text for cross-DB compatibility
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
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
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
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("provider_id", sa.String(50), nullable=False),
            sa.Column("provider_user_id", sa.String(255), nullable=True),
            sa.Column("full_name", sa.String(255), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by", sa.String(255), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.Text, nullable=True),
            sa.UniqueConstraint("email", "provider_id", name="uq_pending_approval"),
        )

        # Ensure index on email for quick lookup (safe on both SQLite/PostgreSQL)
        safe_create_index(op.f("ix_pending_user_approvals_email"), "pending_user_approvals", ["email"])

    # ===============================
    # STEP 9: Populate Team Data for Existing Resources
    # ===============================

    # This step ensures old resources (created before multitenancy) get assigned
    # to the platform admin's personal team, making them visible in the UI

    # ===============================
    # VALIDATION & CONFIGURATION
    # ===============================

    print("🔧 Starting team data population for existing resources...")

    # Get platform admin configuration from settings (consistent with bootstrap_db.py)
    try:
        # First-Party
        from mcpgateway.config import settings

        platform_admin_email = settings.platform_admin_email
        platform_admin_password = settings.platform_admin_password
        platform_admin_full_name = settings.platform_admin_full_name
        print(f"📧 Using platform admin email from settings: {platform_admin_email}")
    except Exception as e:
        print(f"⚠️  Warning: Could not load settings: {e}")
        print("🔄 Falling back to environment variables...")

        # Fallback to direct environment reading
        # Standard
        import os

        platform_admin_email = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
        platform_admin_password = os.getenv("PLATFORM_ADMIN_PASSWORD", "changeme")
        platform_admin_full_name = os.getenv("PLATFORM_ADMIN_FULL_NAME", "Platform Administrator")
        print(f"📧 Using platform admin email from environment: {platform_admin_email}")

    # Validate admin email format
    # Standard
    import re

    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_pattern, platform_admin_email):
        print(f"❌ ERROR: Invalid admin email format: {platform_admin_email}")
        print("⚠️  Skipping team data population - please fix PLATFORM_ADMIN_EMAIL")
        return

    # Validate password strength
    if len(platform_admin_password) < 8:
        print(f"⚠️  Warning: Admin password is short ({len(platform_admin_password)} chars). Consider using a stronger password.")

    # Get current timestamp for database operations
    # Standard
    from datetime import datetime, timezone

    current_timestamp = datetime.now(timezone.utc)
    print(f"⏰ Migration timestamp: {current_timestamp.isoformat()}")

    # Database connection validation
    try:
        # Test database connection
        db_type = str(bind.engine.url).split(":")[0].lower()
        print(f"🗄️  Database type detected: {db_type}")

        # Test basic query
        test_result = bind.execute(text("SELECT 1")).scalar()
        if test_result != 1:
            raise Exception("Database test query failed")
        print("✅ Database connection verified")
    except Exception as e:
        print(f"❌ ERROR: Database connection test failed: {e}")
        print("⚠️  Aborting team data population")
        return

    # ===============================
    # ADMIN USER CREATION
    # ===============================

    print("👤 Checking platform admin user...")

    if "email_users" not in existing_tables:
        print("⚠️  Warning: email_users table not found - multitenancy tables may not be created yet")
        print("🔄 This is normal for fresh installations")
    else:
        try:
            # Check if admin user exists
            result = bind.execute(
                text("SELECT email, is_admin, is_active FROM email_users WHERE email = :email"),
                {"email": platform_admin_email},
            ).fetchone()

            if result:
                email, is_admin, is_active = result
                print(f"✅ Admin user found: {email}")
                print(f"   - Is admin: {is_admin}")
                print(f"   - Is active: {is_active}")

                if not is_admin:
                    print("⚠️  Warning: User exists but is not admin - updating admin status")
                    bind.execute(text("UPDATE email_users SET is_admin = :is_admin WHERE email = :email"), {"is_admin": True, "email": platform_admin_email})
                    print("✅ Admin status updated")
            else:
                print(f"👤 Creating platform admin user: {platform_admin_email}")

                # Hash password using the same method as the application
                password_hash_type = "argon2id"
                try:
                    # First-Party
                    from mcpgateway.services.argon2_service import Argon2PasswordService

                    password_service = Argon2PasswordService()
                    password_hash = password_service.hash_password(platform_admin_password)
                    print("🔐 Using Argon2 password hashing")
                except ImportError as e:
                    # Fallback to a basic hash if the service is not available
                    # Standard
                    import hashlib

                    password_hash = hashlib.sha256(platform_admin_password.encode()).hexdigest()
                    password_hash_type = "sha256"
                    print(f"⚠️  Warning: Argon2 not available ({e}), using SHA256 fallback")

                # Validate password hash was created
                if not password_hash or len(password_hash) < 20:
                    print("❌ ERROR: Password hashing failed - aborting admin user creation")
                    print("⚠️  Please check password service configuration")
                    return

                bind.execute(
                    text(
                        """
                        INSERT INTO email_users (
                            email, password_hash, full_name, is_admin, is_active,
                            auth_provider, password_hash_type, failed_login_attempts,
                            created_at, updated_at, email_verified_at
                        ) VALUES (
                            :email, :password_hash, :full_name, :is_admin, :is_active,
                            :auth_provider, :password_hash_type, :failed_login_attempts,
                            :created_at, :updated_at, :email_verified_at
                        )
                    """
                    ),
                    {
                        "email": platform_admin_email,
                        "password_hash": password_hash,
                        "full_name": platform_admin_full_name,
                        "is_admin": True,
                        "is_active": True,
                        "auth_provider": "local",
                        "password_hash_type": password_hash_type,
                        "failed_login_attempts": 0,
                        "created_at": current_timestamp,
                        "updated_at": current_timestamp,
                        "email_verified_at": current_timestamp,
                    },
                )

                # Verify user was created
                verify_result = bind.execute(text("SELECT email FROM email_users WHERE email = :email"), {"email": platform_admin_email}).fetchone()

                if verify_result:
                    print("✅ Admin user created successfully")
                else:
                    print("❌ ERROR: Admin user creation failed - user not found after INSERT")
                    return

        except Exception as e:
            print(f"❌ ERROR: Admin user creation failed: {e}")
            print("⚠️  Continuing with migration, but admin user may not be available")
            # Standard
            import traceback

            traceback.print_exc()

    # ===============================
    # ADMIN PERSONAL TEAM CREATION
    # ===============================

    print("🏢 Checking admin personal team...")
    admin_team_id = None

    if "email_teams" not in existing_tables:
        print("⚠️  Warning: email_teams table not found - multitenancy tables may not be created yet")
    else:
        try:
            # Check if admin has a personal team
            result = bind.execute(
                text(
                    """
                    SELECT id, name, slug, visibility, is_active FROM email_teams
                    WHERE created_by = :email AND is_personal = true AND is_active = true
                """
                ),
                {"email": platform_admin_email},
            ).fetchone()

            if result:
                admin_team_id, team_name, team_slug, visibility, is_active = result
                print("✅ Found existing admin personal team:")
                print(f"   - ID: {admin_team_id}")
                print(f"   - Name: {team_name}")
                print(f"   - Slug: {team_slug}")
                print(f"   - Visibility: {visibility}")
                print(f"   - Active: {is_active}")
            else:
                print("👥 Creating personal team for admin user...")

                # Generate a unique team ID and slug
                # Standard
                import uuid

                admin_team_id = str(uuid.uuid4())

                # Create safe slug from email
                safe_email = platform_admin_email.replace("@", "-").replace(".", "-").lower()
                # Remove any potentially problematic characters
                safe_email = re.sub(r"[^a-z0-9-]", "-", safe_email)
                team_slug = f"personal-{safe_email}"

                # Ensure slug is not too long (database constraint)
                if len(team_slug) > 255:
                    team_slug = team_slug[:255]
                    print(f"⚠️  Team slug truncated to fit database constraint: {len(team_slug)} chars")

                team_name = f"{platform_admin_full_name}'s Team"
                if len(team_name) > 255:
                    team_name = team_name[:252] + "..."
                    print("⚠️  Team name truncated to fit database constraint")

                print(f"   - Team ID: {admin_team_id}")
                print(f"   - Team name: {team_name}")
                print(f"   - Team slug: {team_slug}")

                # Check for slug conflicts (though unlikely)
                conflict_check = bind.execute(text("SELECT id FROM email_teams WHERE slug = :slug"), {"slug": team_slug}).fetchone()

                if conflict_check:
                    # Add timestamp suffix to make unique
                    # Standard
                    import time

                    team_slug = f"{team_slug}-{int(time.time())}"
                    print(f"⚠️  Slug conflict detected, using: {team_slug}")

                bind.execute(
                    text(
                        """
                        INSERT INTO email_teams (
                            id, name, slug, description, created_by, is_personal,
                            visibility, is_active, created_at, updated_at
                        ) VALUES (
                            :id, :name, :slug, :description, :created_by, :is_personal,
                            :visibility, :is_active, :created_at, :updated_at
                        )
                    """
                    ),
                    {
                        "id": admin_team_id,
                        "name": team_name,
                        "slug": team_slug,
                        "description": "Personal team for platform administrator",
                        "created_by": platform_admin_email,
                        "is_personal": True,
                        "visibility": "private",
                        "is_active": True,
                        "created_at": current_timestamp,
                        "updated_at": current_timestamp,
                    },
                )

                # Verify team was created
                verify_team = bind.execute(text("SELECT id, name FROM email_teams WHERE id = :team_id"), {"team_id": admin_team_id}).fetchone()

                if not verify_team:
                    print("❌ ERROR: Team creation failed - team not found after INSERT")
                    return

                print("✅ Admin personal team created successfully")

                # Add admin as owner of the personal team
                if "email_team_members" in existing_tables:
                    print("👥 Adding admin as team owner...")
                    member_id = str(uuid.uuid4())

                    bind.execute(
                        text(
                            """
                            INSERT INTO email_team_members (
                                id, team_id, user_email, role, joined_at, is_active
                            ) VALUES (
                                :id, :team_id, :user_email, :role, :joined_at, :is_active
                            )
                        """
                        ),
                        {"id": member_id, "team_id": admin_team_id, "user_email": platform_admin_email, "role": "owner", "joined_at": current_timestamp, "is_active": True},
                    )

                    # Verify membership was created
                    verify_member = bind.execute(
                        text("SELECT role FROM email_team_members WHERE team_id = :team_id AND user_email = :email"), {"team_id": admin_team_id, "email": platform_admin_email}
                    ).fetchone()

                    if verify_member:
                        print(f"✅ Admin added as team {verify_member[0]}")
                    else:
                        print("❌ ERROR: Team membership creation failed")
                        # Continue anyway, team exists
                else:
                    print("⚠️  email_team_members table not found - membership not created")

        except Exception as e:
            print(f"❌ ERROR: Personal team creation failed: {e}")
            print("⚠️  Continuing with migration, but team assignments may not work")
            # Standard
            import traceback

            traceback.print_exc()

    # ===============================
    # RESOURCE TEAM ASSIGNMENT
    # ===============================

    if not admin_team_id:
        print("❌ ERROR: No admin team available - cannot assign resources")
        print("⚠️  Old resources will remain unassigned and may not be visible")
        print("💡 Run the fix script after migration to resolve this")
        return

    print("📦 Starting resource team assignment...")
    print(f"🎯 Target team: {admin_team_id}")

    # Track migration statistics
    migration_stats = {"tables_processed": 0, "resources_found": 0, "resources_migrated": 0, "errors": 0}

    # Validate resource tables exist and have required columns
    valid_tables = []
    for table_name in resource_tables:
        if table_name in existing_tables:
            # Validate table name to prevent SQL injection (whitelist approach)
            if table_name not in ["prompts", "resources", "servers", "tools", "gateways", "a2a_agents"]:
                print(f"⚠️  Skipping unknown table: {table_name}")
                continue

            # Check if table has the multitenancy columns
            try:
                columns = [col["name"] for col in inspector.get_columns(table_name)]
                if "team_id" in columns and "owner_email" in columns and "visibility" in columns:
                    valid_tables.append(table_name)
                    print(f"✅ {table_name}: multitenancy columns present")
                else:
                    missing_cols = []
                    for col in ["team_id", "owner_email", "visibility"]:
                        if col not in columns:
                            missing_cols.append(col)
                    print(f"⚠️  {table_name}: missing columns {missing_cols} - skipping")
            except Exception as e:
                print(f"❌ {table_name}: column inspection failed - {e}")
                migration_stats["errors"] += 1
        else:
            print(f"⚠️  {table_name}: table not found - skipping")

    if not valid_tables:
        print("⚠️  No valid resource tables found for migration")
        return

    print(f"📋 Processing {len(valid_tables)} resource tables: {', '.join(valid_tables)}")

    # Process each resource table
    for table_name in valid_tables:
        try:
            print(f"\\n🔄 Processing {table_name}...")
            migration_stats["tables_processed"] += 1

            # Count total resources in table
            total_count = bind.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
            print(f"   📊 Total {table_name}: {total_count}")

            # Find resources needing migration
            select_sql = f"SELECT id, name FROM {table_name} WHERE team_id IS NULL OR owner_email IS NULL OR visibility IS NULL"
            old_resources = bind.execute(text(select_sql)).fetchall()

            if not old_resources:
                print(f"   ✅ {table_name}: all resources already have team assignments")
                continue

            migration_stats["resources_found"] += len(old_resources)
            print(f"   🔧 Found {len(old_resources)} {table_name} needing migration")

            # Show sample of resources being migrated (first 3)
            for i, (resource_id, resource_name) in enumerate(old_resources[:3]):
                name_display = resource_name[:50] + "..." if len(resource_name) > 50 else resource_name
                print(f"      • {name_display} (ID: {resource_id})")

            if len(old_resources) > 3:
                print(f"      • ... and {len(old_resources) - 3} more")

            # Perform the migration
            update_sql = f"""
                UPDATE {table_name}
                SET team_id = :team_id,
                    owner_email = :owner_email,
                    visibility = :visibility
                WHERE team_id IS NULL OR owner_email IS NULL OR visibility IS NULL
            """

            result = bind.execute(text(update_sql), {"team_id": admin_team_id, "owner_email": platform_admin_email, "visibility": "public"})  # Make visible to all users initially

            rows_updated = result.rowcount
            migration_stats["resources_migrated"] += rows_updated

            if rows_updated == len(old_resources):
                print(f"   ✅ Successfully migrated {rows_updated} {table_name}")
            else:
                print(f"   ⚠️  Expected {len(old_resources)}, updated {rows_updated} {table_name}")

            # Verify migration
            remaining = bind.execute(text(select_sql)).fetchall()
            if remaining:
                print(f"   ⚠️  {len(remaining)} {table_name} still need migration")
            else:
                print(f"   ✅ All {table_name} successfully migrated")

        except Exception as e:
            print(f"   ❌ ERROR migrating {table_name}: {e}")
            migration_stats["errors"] += 1
            # Standard
            import traceback

            traceback.print_exc()
            continue

    # ===============================
    # MIGRATION SUMMARY
    # ===============================

    print("\\n" + "=" * 60)
    print("📊 TEAM DATA POPULATION SUMMARY")
    print("=" * 60)
    print(f"✅ Tables processed: {migration_stats['tables_processed']}")
    print(f"🔍 Resources found: {migration_stats['resources_found']}")
    print(f"📦 Resources migrated: {migration_stats['resources_migrated']}")
    print(f"❌ Errors encountered: {migration_stats['errors']}")

    if migration_stats["errors"] == 0:
        print("🎉 Team data population completed successfully!")
    else:
        print("⚠️  Team data population completed with errors")

    print(f"👤 All migrated resources assigned to: {platform_admin_email}")
    print(f"🏢 Target team: {admin_team_id}")
    print("👁️  Default visibility: public")
    print("=" * 60)

    if migration_stats["resources_migrated"] > 0:
        print("💡 Next steps:")
        print("   1. Run verification: python3 scripts/verify_multitenancy_0_7_0_migration.py")
        print("   2. Check admin UI: /admin to see your resources")
        print("   3. Adjust visibility settings as needed")

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

    # Remove team scoping columns from resource tables
    resource_tables = ["tools", "servers", "resources", "prompts", "gateways", "a2a_agents"]

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
                    with op.batch_alter_table(table_name, schema=None) as batch_op:
                        for col_name in columns_to_drop:
                            batch_op.drop_column(col_name)
                    print(f"Dropped columns {columns_to_drop} from {table_name}")
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

            # Drop the table using safe helper
            safe_drop_table(table_name)
