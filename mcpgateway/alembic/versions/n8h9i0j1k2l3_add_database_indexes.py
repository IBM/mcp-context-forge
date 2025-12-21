# -*- coding: utf-8 -*-
"""add database indexes

Revision ID: n8h9i0j1k2l3
Revises: m7g8h9i0j1k2
Create Date: 2025-12-18 05:49:00.000000

Complete Database Indexing Optimization (Issue #1353)
This migration adds both foreign key indexes and composite indexes to improve
query performance across the entire application.

Phase 0 - Index Naming Standardization:
Renames all existing 'ix_' prefixed indexes to 'idx_' for consistency.

Phase 0.5 - Duplicate Index Cleanup:
Detects and drops duplicate indexes where the same columns have multiple indexes
and one starts with 'ix_'. This prevents index duplication and saves storage space.

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

Phase 3 - Foreign Key Constraint Fixes:
Adds ON DELETE CASCADE to email_team_member_history.team_member_id foreign key
to fix PostgreSQL constraint violations when deleting users (Issue: user deletion fails).
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "n8h9i0j1k2l3"
down_revision: Union[str, Sequence[str], None] = "m7g8h9i0j1k2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rename_existing_ix_indexes() -> None:
    """Rename all existing indexes with 'ix_' prefix to 'idx_' prefix.

    This ensures consistency with the new naming convention before creating new indexes.
    """
    conn = op.get_bind()
    inspector = inspect(conn)

    # Get all table names
    try:
        table_names = inspector.get_table_names()
    except Exception as e:
        print(f"⚠️  Could not get table names: {e}")
        return

    renamed_count = 0
    for table_name in table_names:
        try:
            existing_indexes = inspector.get_indexes(table_name)

            for idx in existing_indexes:
                index_name = idx["name"]

                # Check if index starts with 'ix_' prefix
                if index_name and index_name.startswith("ix_"):
                    new_index_name = "idx_" + index_name[3:]  # Replace 'ix_' with 'idx_'

                    # Check if the new name already exists
                    if any(i["name"] == new_index_name for i in existing_indexes):
                        print(f"⚠️  Skipping rename of {index_name}: {new_index_name} already exists on {table_name}")
                        continue

                    try:
                        # Rename the index
                        # Note: Different databases have different syntax for renaming indexes
                        # SQLite doesn't support ALTER INDEX RENAME, so we need to recreate
                        dialect_name = conn.dialect.name

                        if dialect_name == "postgresql":
                            op.execute(f"ALTER INDEX {index_name} RENAME TO {new_index_name}")
                            print(f"✓ Renamed index {index_name} → {new_index_name} on {table_name}")
                            renamed_count += 1
                        elif dialect_name == "mysql":
                            op.execute(f"ALTER TABLE {table_name} RENAME INDEX {index_name} TO {new_index_name}")
                            print(f"✓ Renamed index {index_name} → {new_index_name} on {table_name}")
                            renamed_count += 1
                        elif dialect_name == "sqlite":
                            # SQLite requires recreating the index
                            # Get index details
                            columns = idx["column_names"]
                            unique = idx.get("unique", False)

                            # Drop old index and create new one
                            op.drop_index(index_name, table_name=table_name)
                            op.create_index(new_index_name, table_name, columns, unique=unique)
                            print(f"✓ Recreated index {index_name} → {new_index_name} on {table_name}")
                            renamed_count += 1
                        else:
                            print(f"⚠️  Unsupported database dialect '{dialect_name}' for renaming {index_name}")

                    except Exception as e:
                        print(f"⚠️  Failed to rename {index_name} on {table_name}: {e}")

        except Exception as e:
            print(f"⚠️  Could not process table {table_name}: {e}")

    if renamed_count > 0:
        print(f"\n✓ Successfully renamed {renamed_count} indexes from 'ix_' to 'idx_' prefix")
    else:
        print("\n✓ No indexes with 'ix_' prefix found to rename")


def _drop_duplicate_ix_indexes() -> None:
    """Detect and drop duplicate indexes where ix_ prefix exists alongside idx_ prefix.

    When the same columns have multiple indexes and one starts with 'ix_', drop the ix_ one.
    This handles cases where both ix_ and idx_ indexes exist on the same columns.
    """
    conn = op.get_bind()
    inspector = inspect(conn)

    # Get all table names
    try:
        table_names = inspector.get_table_names()
    except Exception as e:
        print(f"⚠️  Could not get table names: {e}")
        return

    dropped_count = 0
    for table_name in table_names:
        try:
            existing_indexes = inspector.get_indexes(table_name)

            # Group indexes by their columns
            column_to_indexes: dict[tuple, list[dict]] = {}
            for idx in existing_indexes:
                columns_tuple = tuple(sorted(idx["column_names"]))
                if columns_tuple not in column_to_indexes:
                    column_to_indexes[columns_tuple] = []
                column_to_indexes[columns_tuple].append(idx)

            # Find duplicates (same columns, multiple indexes)
            for columns, indexes in column_to_indexes.items():
                if len(indexes) > 1:
                    # Check if we have both ix_ and idx_ (or other) indexes
                    ix_indexes = [idx for idx in indexes if idx["name"] and idx["name"].startswith("ix_")]
                    non_ix_indexes = [idx for idx in indexes if idx["name"] and not idx["name"].startswith("ix_")]

                    # Only drop ix_ indexes if there are other indexes on the same columns
                    if ix_indexes and non_ix_indexes:
                        for ix_idx in ix_indexes:
                            try:
                                op.drop_index(ix_idx["name"], table_name=table_name)
                                print(f"✓ Dropped duplicate index {ix_idx['name']} from {table_name} (columns: {', '.join(columns)})")
                                dropped_count += 1
                            except Exception as e:
                                print(f"⚠️  Failed to drop {ix_idx['name']} from {table_name}: {e}")

        except Exception as e:
            print(f"⚠️  Could not process table {table_name}: {e}")

    if dropped_count > 0:
        print(f"\n✓ Successfully dropped {dropped_count} duplicate ix_ indexes")
    else:
        print("\n✓ No duplicate ix_ indexes found to drop")


def _index_exists_on_columns(table_name: str, columns: list[str]) -> tuple[bool, str | None]:
    """Check if an index already exists on the specified columns.

    Args:
        table_name: Name of the table to check
        columns: List of column names to check for existing index

    Returns:
        Tuple of (exists: bool, existing_index_name: str | None)
    """
    conn = op.get_bind()
    inspector = inspect(conn)

    try:
        existing_indexes = inspector.get_indexes(table_name)
    except Exception:
        # Table might not exist yet, or other error
        return False, None

    # Check if any existing index covers these exact columns
    columns_set = set(columns)
    for idx in existing_indexes:
        if set(idx["column_names"]) == columns_set:
            return True, idx["name"]

    return False, None


def _create_index_safe(index_name: str, table_name: str, columns: list[str], unique: bool = False) -> bool:
    """Create an index only if it doesn't already exist on the same columns.

    Args:
        index_name: Name for the new index
        table_name: Table to create index on
        columns: List of column names to index
        unique: Whether the index should be unique

    Returns:
        True if index was created, False if it already existed
    """
    exists, existing_name = _index_exists_on_columns(table_name, columns)

    if exists:
        print(f"⚠️  Skipping {index_name}: Index '{existing_name}' already exists on {table_name}({', '.join(columns)})")
        return False

    op.create_index(index_name, table_name, columns, unique=unique)
    print(f"✓ Created index {index_name} on {table_name}({', '.join(columns)})")
    return True


def _drop_index_safe(index_name: str, table_name: str) -> bool:
    """Drop an index only if it exists.

    Args:
        index_name: Name of the index to drop
        table_name: Table the index is on

    Returns:
        True if index was dropped, False if it didn't exist
    """
    conn = op.get_bind()
    inspector = inspect(conn)

    try:
        existing_indexes = inspector.get_indexes(table_name)
        index_exists = any(idx["name"] == index_name for idx in existing_indexes)

        if not index_exists:
            print(f"⚠️  Skipping drop of {index_name}: Index does not exist on {table_name}")
            return False

        op.drop_index(index_name, table_name=table_name)
        print(f"✓ Dropped index {index_name} from {table_name}")
        return True
    except Exception:
        # Table might not exist, or other error
        return False


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
    # PHASE 0: Rename Existing Indexes (ix_ → idx_)
    # ========================================================================
    print("\n" + "=" * 80)
    print("PHASE 0: Renaming existing indexes from 'ix_' to 'idx_' prefix")
    print("=" * 80)
    _rename_existing_ix_indexes()

    # ========================================================================
    # PHASE 0.5: Drop Duplicate ix_ Indexes
    # ========================================================================
    print("\n" + "=" * 80)
    print("PHASE 0.5: Dropping duplicate ix_ indexes (where idx_ already exists)")
    print("=" * 80)
    _drop_duplicate_ix_indexes()

    # ========================================================================
    # PHASE 1: Foreign Key Indexes
    # ========================================================================
    print("\n" + "=" * 80)
    print("PHASE 1: Creating Foreign Key Indexes")
    print("=" * 80)

    # Role and RBAC foreign keys
    _create_index_safe("idx_roles_inherits_from", "roles", ["inherits_from"])
    _create_index_safe("idx_roles_created_by", "roles", ["created_by"])
    _create_index_safe("idx_user_roles_user_email", "user_roles", ["user_email"])
    _create_index_safe("idx_user_roles_role_id", "user_roles", ["role_id"])
    _create_index_safe("idx_user_roles_granted_by", "user_roles", ["granted_by"])

    # Team management foreign keys
    _create_index_safe("idx_email_teams_created_by", "email_teams", ["created_by"])
    _create_index_safe("idx_email_team_members_team_id", "email_team_members", ["team_id"])
    _create_index_safe("idx_email_team_members_user_email", "email_team_members", ["user_email"])
    _create_index_safe("idx_email_team_members_invited_by", "email_team_members", ["invited_by"])

    # Team member history foreign keys
    _create_index_safe("idx_email_team_member_history_team_member_id", "email_team_member_history", ["team_member_id"])
    _create_index_safe("idx_email_team_member_history_team_id", "email_team_member_history", ["team_id"])
    _create_index_safe("idx_email_team_member_history_user_email", "email_team_member_history", ["user_email"])
    _create_index_safe("idx_email_team_member_history_action_by", "email_team_member_history", ["action_by"])

    # Team invitation foreign keys
    _create_index_safe("idx_email_team_invitations_team_id", "email_team_invitations", ["team_id"])
    _create_index_safe("idx_email_team_invitations_invited_by", "email_team_invitations", ["invited_by"])

    # Team join request foreign keys
    _create_index_safe("idx_email_team_join_requests_team_id", "email_team_join_requests", ["team_id"])
    _create_index_safe("idx_email_team_join_requests_user_email", "email_team_join_requests", ["user_email"])
    _create_index_safe("idx_email_team_join_requests_reviewed_by", "email_team_join_requests", ["reviewed_by"])

    # Pending user approval foreign keys
    _create_index_safe("idx_pending_user_approvals_approved_by", "pending_user_approvals", ["approved_by"])

    # Metrics foreign keys
    _create_index_safe("idx_tool_metrics_tool_id", "tool_metrics", ["tool_id"])
    _create_index_safe("idx_resource_metrics_resource_id", "resource_metrics", ["resource_id"])
    _create_index_safe("idx_server_metrics_server_id", "server_metrics", ["server_id"])
    _create_index_safe("idx_prompt_metrics_prompt_id", "prompt_metrics", ["prompt_id"])
    _create_index_safe("idx_a2a_agent_metrics_a2a_agent_id", "a2a_agent_metrics", ["a2a_agent_id"])

    # Core entity foreign keys (gateway_id, team_id)
    _create_index_safe("idx_tools_gateway_id", "tools", ["gateway_id"])
    _create_index_safe("idx_tools_team_id", "tools", ["team_id"])
    _create_index_safe("idx_resources_gateway_id", "resources", ["gateway_id"])
    _create_index_safe("idx_resources_team_id", "resources", ["team_id"])
    _create_index_safe("idx_prompts_gateway_id", "prompts", ["gateway_id"])
    _create_index_safe("idx_prompts_team_id", "prompts", ["team_id"])
    _create_index_safe("idx_servers_team_id", "servers", ["team_id"])
    _create_index_safe("idx_gateways_team_id", "gateways", ["team_id"])
    _create_index_safe("idx_a2a_agents_team_id", "a2a_agents", ["team_id"])
    _create_index_safe("idx_grpc_services_team_id", "grpc_services", ["team_id"])

    # Resource subscription foreign keys
    _create_index_safe("idx_resource_subscriptions_resource_id", "resource_subscriptions", ["resource_id"])

    # OAuth foreign keys
    _create_index_safe("idx_oauth_tokens_gateway_id", "oauth_tokens", ["gateway_id"])
    _create_index_safe("idx_oauth_tokens_app_user_email", "oauth_tokens", ["app_user_email"])
    _create_index_safe("idx_oauth_states_gateway_id", "oauth_states", ["gateway_id"])

    # API token foreign keys
    _create_index_safe("idx_email_api_tokens_server_id", "email_api_tokens", ["server_id"])

    # Token revocation foreign keys
    _create_index_safe("idx_token_revocations_revoked_by", "token_revocations", ["revoked_by"])

    # SSO foreign keys
    _create_index_safe("idx_sso_auth_sessions_provider_id", "sso_auth_sessions", ["provider_id"])
    _create_index_safe("idx_sso_auth_sessions_user_email", "sso_auth_sessions", ["user_email"])

    # LLM provider foreign keys
    _create_index_safe("idx_llm_models_provider_id", "llm_models", ["provider_id"])

    # Session message foreign keys
    _create_index_safe("idx_mcp_messages_session_id", "mcp_messages", ["session_id"])

    # ------------------------------------------------------------------------
    # Junction Table Foreign Key Indexes
    # ------------------------------------------------------------------------
    # These are many-to-many association tables. While the composite primary key
    # provides an index on (col1, col2), we need separate indexes on each column
    # for efficient lookups when querying from either direction and for CASCADE deletes.

    # server_tool_association
    _create_index_safe("idx_server_tool_association_server_id", "server_tool_association", ["server_id"])
    _create_index_safe("idx_server_tool_association_tool_id", "server_tool_association", ["tool_id"])

    # server_resource_association
    _create_index_safe("idx_server_resource_association_server_id", "server_resource_association", ["server_id"])
    _create_index_safe("idx_server_resource_association_resource_id", "server_resource_association", ["resource_id"])

    # server_prompt_association
    _create_index_safe("idx_server_prompt_association_server_id", "server_prompt_association", ["server_id"])
    _create_index_safe("idx_server_prompt_association_prompt_id", "server_prompt_association", ["prompt_id"])

    # server_a2a_association
    _create_index_safe("idx_server_a2a_association_server_id", "server_a2a_association", ["server_id"])
    _create_index_safe("idx_server_a2a_association_a2a_agent_id", "server_a2a_association", ["a2a_agent_id"])

    # ========================================================================
    # PHASE 2: Composite Indexes
    # ========================================================================
    print("\n" + "=" * 80)
    print("PHASE 2: Creating Composite Indexes")
    print("=" * 80)

    # ------------------------------------------------------------------------
    # Team Management Composite Indexes
    # ------------------------------------------------------------------------
    print("\n--- Team Management Composite Indexes ---")

    # Team membership queries (user + team + active status)
    _create_index_safe(
        "idx_email_team_members_user_team_active",
        "email_team_members",
        ["user_email", "team_id", "is_active"],
    )

    # Team member role queries (team + role + active)
    _create_index_safe(
        "idx_email_team_members_team_role_active",
        "email_team_members",
        ["team_id", "role", "is_active"],
    )

    # Team invitations (team + active + created timestamp)
    _create_index_safe(
        "idx_email_team_invitations_team_active_created",
        "email_team_invitations",
        ["team_id", "is_active", "invited_at"],
    )

    # Team invitations by email (email + active + created)
    _create_index_safe(
        "idx_email_team_invitations_email_active_created",
        "email_team_invitations",
        ["email", "is_active", "invited_at"],
    )

    # Team join requests (team + status + timestamp)
    _create_index_safe(
        "idx_email_team_join_requests_team_status_time",
        "email_team_join_requests",
        ["team_id", "status", "requested_at"],
    )

    # Team join requests by user (user + status + timestamp)
    _create_index_safe(
        "idx_email_team_join_requests_user_status_time",
        "email_team_join_requests",
        ["user_email", "status", "requested_at"],
    )

    # Team listing (visibility + is_active + created)
    _create_index_safe(
        "idx_email_teams_visibility_active_created",
        "email_teams",
        ["visibility", "is_active", "created_at"],
    )

    # Personal team lookup (created_by + is_personal + active)
    _create_index_safe(
        "idx_email_teams_creator_personal_active",
        "email_teams",
        ["created_by", "is_personal", "is_active"],
    )

    # ------------------------------------------------------------------------
    # Core Entity Composite Indexes (Tools, Resources, Prompts, Servers)
    # ------------------------------------------------------------------------

    # Tools: team + visibility + enabled + created (common listing query)
    _create_index_safe(
        "idx_tools_team_visibility_active_created",
        "tools",
        ["team_id", "visibility", "enabled", "created_at"],
    )

    # Tools: visibility + enabled + created (public listing)
    _create_index_safe(
        "idx_tools_visibility_active_created",
        "tools",
        ["visibility", "enabled", "created_at"],
    )

    # Resources: team + visibility + enabled + created
    _create_index_safe(
        "idx_resources_team_visibility_active_created",
        "resources",
        ["team_id", "visibility", "enabled", "created_at"],
    )

    # Resources: visibility + enabled + created
    _create_index_safe(
        "idx_resources_visibility_active_created",
        "resources",
        ["visibility", "enabled", "created_at"],
    )

    # Prompts: team + visibility + enabled + created
    _create_index_safe(
        "idx_prompts_team_visibility_active_created",
        "prompts",
        ["team_id", "visibility", "enabled", "created_at"],
    )

    # Prompts: visibility + enabled + created
    _create_index_safe(
        "idx_prompts_visibility_active_created",
        "prompts",
        ["visibility", "enabled", "created_at"],
    )

    # Servers: team + visibility + enabled + created
    _create_index_safe(
        "idx_servers_team_visibility_active_created",
        "servers",
        ["team_id", "visibility", "enabled", "created_at"],
    )

    # Servers: visibility + enabled + created
    _create_index_safe(
        "idx_servers_visibility_active_created",
        "servers",
        ["visibility", "enabled", "created_at"],
    )

    # Gateways: team + visibility + enabled + created
    _create_index_safe(
        "idx_gateways_team_visibility_active_created",
        "gateways",
        ["team_id", "visibility", "enabled", "created_at"],
    )

    # Gateways: visibility + enabled + created
    _create_index_safe(
        "idx_gateways_visibility_active_created",
        "gateways",
        ["visibility", "enabled", "created_at"],
    )

    # A2A Agents: team + visibility + enabled + created
    _create_index_safe(
        "idx_a2a_agents_team_visibility_active_created",
        "a2a_agents",
        ["team_id", "visibility", "enabled", "created_at"],
    )

    # A2A Agents: visibility + enabled + created
    _create_index_safe(
        "idx_a2a_agents_visibility_active_created",
        "a2a_agents",
        ["visibility", "enabled", "created_at"],
    )

    # ------------------------------------------------------------------------
    # Observability Composite Indexes
    # ------------------------------------------------------------------------

    # Traces: user + status + time (user activity queries)
    _create_index_safe(
        "idx_observability_traces_user_status_time",
        "observability_traces",
        ["user_email", "status", "start_time"],
    )

    # Traces: status + http_method + time (error analysis)
    _create_index_safe(
        "idx_observability_traces_status_method_time",
        "observability_traces",
        ["status", "http_method", "start_time"],
    )

    # Spans: trace + resource_type + time (trace analysis)
    _create_index_safe(
        "idx_observability_spans_trace_resource_time",
        "observability_spans",
        ["trace_id", "resource_type", "start_time"],
    )

    # Spans: resource_type + status + time (resource monitoring)
    _create_index_safe(
        "idx_observability_spans_resource_status_time",
        "observability_spans",
        ["resource_type", "status", "start_time"],
    )

    # ------------------------------------------------------------------------
    # Authentication & Token Composite Indexes
    # ------------------------------------------------------------------------

    # API Tokens: user + active + created (user token listing)
    _create_index_safe(
        "idx_email_api_tokens_user_active_created",
        "email_api_tokens",
        ["user_email", "is_active", "created_at"],
    )

    # API Tokens: team + active + created (team token listing)
    _create_index_safe(
        "idx_email_api_tokens_team_active_created",
        "email_api_tokens",
        ["team_id", "is_active", "created_at"],
    )

    # Auth Events: user + event_type + timestamp (user activity audit)
    _create_index_safe(
        "idx_email_auth_events_user_type_time",
        "email_auth_events",
        ["user_email", "event_type", "timestamp"],
    )

    # SSO Sessions: provider + user + created (session lookup)
    _create_index_safe(
        "idx_sso_auth_sessions_provider_user_created",
        "sso_auth_sessions",
        ["provider_id", "user_email", "created_at"],
    )

    # OAuth Tokens: gateway + user + created (token lookup)
    _create_index_safe(
        "idx_oauth_tokens_gateway_user_created",
        "oauth_tokens",
        ["gateway_id", "app_user_email", "created_at"],
    )

    # ------------------------------------------------------------------------
    # Metrics Composite Indexes
    # ------------------------------------------------------------------------

    # Tool Metrics: tool + timestamp (time-series queries)
    _create_index_safe(
        "idx_tool_metrics_tool_timestamp",
        "tool_metrics",
        ["tool_id", "timestamp"],
    )

    # Resource Metrics: resource + timestamp
    _create_index_safe(
        "idx_resource_metrics_resource_timestamp",
        "resource_metrics",
        ["resource_id", "timestamp"],
    )

    # Server Metrics: server + timestamp
    _create_index_safe(
        "idx_server_metrics_server_timestamp",
        "server_metrics",
        ["server_id", "timestamp"],
    )

    # Prompt Metrics: prompt + timestamp
    _create_index_safe(
        "idx_prompt_metrics_prompt_timestamp",
        "prompt_metrics",
        ["prompt_id", "timestamp"],
    )

    # ------------------------------------------------------------------------
    # RBAC Composite Indexes
    # ------------------------------------------------------------------------

    # User Roles: user + scope + active (permission checks)
    _create_index_safe(
        "idx_user_roles_user_scope_active",
        "user_roles",
        ["user_email", "scope", "is_active"],
    )

    # User Roles: role + scope + active (role membership queries)
    _create_index_safe(
        "idx_user_roles_role_scope_active",
        "user_roles",
        ["role_id", "scope", "is_active"],
    )

    # ------------------------------------------------------------------------
    # Permission Audit Log Indexes
    # ------------------------------------------------------------------------
    print("\n--- Permission Audit Log Indexes ---")

    # Single-column indexes for common filters
    _create_index_safe("idx_permission_audit_log_timestamp", "permission_audit_log", ["timestamp"])
    _create_index_safe("idx_permission_audit_log_user_email", "permission_audit_log", ["user_email"])
    _create_index_safe("idx_permission_audit_log_granted", "permission_audit_log", ["granted"])
    _create_index_safe("idx_permission_audit_log_resource_type", "permission_audit_log", ["resource_type"])
    _create_index_safe("idx_permission_audit_log_team_id", "permission_audit_log", ["team_id"])

    # Composite indexes for common query patterns
    _create_index_safe(
        "idx_permission_audit_log_user_time",
        "permission_audit_log",
        ["user_email", "timestamp"],
    )
    _create_index_safe(
        "idx_permission_audit_log_resource_granted_time",
        "permission_audit_log",
        ["resource_type", "granted", "timestamp"],
    )
    _create_index_safe(
        "idx_permission_audit_log_team_time",
        "permission_audit_log",
        ["team_id", "timestamp"],
    )

    # ------------------------------------------------------------------------
    # Email Auth Events Additional Indexes
    # ------------------------------------------------------------------------
    print("\n--- Email Auth Events Additional Indexes ---")

    # Single-column indexes for common filters
    _create_index_safe("idx_email_auth_events_timestamp", "email_auth_events", ["timestamp"])
    _create_index_safe("idx_email_auth_events_event_type", "email_auth_events", ["event_type"])
    _create_index_safe("idx_email_auth_events_success", "email_auth_events", ["success"])
    _create_index_safe("idx_email_auth_events_ip_address", "email_auth_events", ["ip_address"])

    # Composite indexes for security analysis
    _create_index_safe(
        "idx_email_auth_events_success_time",
        "email_auth_events",
        ["success", "timestamp"],
    )
    _create_index_safe(
        "idx_email_auth_events_ip_time",
        "email_auth_events",
        ["ip_address", "timestamp"],
    )
    _create_index_safe(
        "idx_email_auth_events_type_success_time",
        "email_auth_events",
        ["event_type", "success", "timestamp"],
    )

    # ========================================================================
    # PHASE 3: Foreign Key Constraint Fixes
    # ========================================================================
    print("\n" + "=" * 80)
    print("PHASE 3: Fixing Foreign Key Constraints (CASCADE)")
    print("=" * 80)

    # Fix email_team_member_history.team_member_id FK to add CASCADE delete
    # This fixes PostgreSQL constraint violations when deleting users
    conn = op.get_bind()
    dialect_name = conn.dialect.name

    if dialect_name == "postgresql":
        print("\n--- PostgreSQL: Adding CASCADE to team_member_history FK ---")
        try:
            # Drop the existing foreign key constraint (correct name from schema)
            op.drop_constraint("fk_email_team_member_history_team_member_id", "email_team_member_history", type_="foreignkey")
            print("✓ Dropped existing FK constraint: fk_email_team_member_history_team_member_id")

            # Recreate with CASCADE
            op.create_foreign_key("fk_email_team_member_history_team_member_id", "email_team_member_history", "email_team_members", ["team_member_id"], ["id"], ondelete="CASCADE")
            print("✓ Created FK constraint with CASCADE: fk_email_team_member_history_team_member_id")
        except Exception as e:
            print(f"⚠️  Could not update FK constraint: {e}")
            print("   This is expected if the constraint already has CASCADE")
    elif dialect_name == "mysql":
        print("\n--- MySQL: Adding CASCADE to team_member_history FK ---")
        try:
            # MySQL may use a different constraint name
            op.drop_constraint("email_team_member_history_ibfk_1", "email_team_member_history", type_="foreignkey")
            print("✓ Dropped existing FK constraint: email_team_member_history_ibfk_1")

            op.create_foreign_key("email_team_member_history_ibfk_1", "email_team_member_history", "email_team_members", ["team_member_id"], ["id"], ondelete="CASCADE")
            print("✓ Created FK constraint with CASCADE: email_team_member_history_ibfk_1")
        except Exception as e:
            print(f"⚠️  Could not update FK constraint: {e}")
    else:
        print(f"\n--- {dialect_name}: Skipping FK CASCADE update (not required) ---")


def downgrade() -> None:
    """Remove all foreign key and composite indexes."""

    # ========================================================================
    # PHASE 3 DOWNGRADE: Revert Foreign Key Constraint Fixes
    # ========================================================================
    print("\n" + "=" * 80)
    print("PHASE 3 DOWNGRADE: Reverting Foreign Key Constraints (removing CASCADE)")
    print("=" * 80)

    conn = op.get_bind()
    dialect_name = conn.dialect.name

    if dialect_name == "postgresql":
        print("\n--- PostgreSQL: Removing CASCADE from team_member_history FK ---")
        try:
            # Drop the CASCADE constraint
            op.drop_constraint("fk_email_team_member_history_team_member_id", "email_team_member_history", type_="foreignkey")
            print("✓ Dropped FK constraint with CASCADE")

            # Recreate without CASCADE
            op.create_foreign_key("fk_email_team_member_history_team_member_id", "email_team_member_history", "email_team_members", ["team_member_id"], ["id"])
            print("✓ Recreated FK constraint without CASCADE")
        except Exception as e:
            print(f"⚠️  Could not revert FK constraint: {e}")
    elif dialect_name == "mysql":
        print("\n--- MySQL: Removing CASCADE from team_member_history FK ---")
        try:
            op.drop_constraint("email_team_member_history_ibfk_1", "email_team_member_history", type_="foreignkey")
            print("✓ Dropped FK constraint with CASCADE")

            op.create_foreign_key("email_team_member_history_ibfk_1", "email_team_member_history", "email_team_members", ["team_member_id"], ["id"])
            print("✓ Recreated FK constraint without CASCADE")
        except Exception as e:
            print(f"⚠️  Could not revert FK constraint: {e}")
    else:
        print(f"\n--- {dialect_name}: Skipping FK CASCADE revert (not required) ---")

    # ========================================================================
    # Remove Composite Indexes (Phase 2) - in reverse order
    # ========================================================================

    # Email Auth Events Additional Indexes
    _drop_index_safe("idx_email_auth_events_type_success_time", "email_auth_events")
    _drop_index_safe("idx_email_auth_events_ip_time", "email_auth_events")
    _drop_index_safe("idx_email_auth_events_success_time", "email_auth_events")
    _drop_index_safe("idx_email_auth_events_ip_address", "email_auth_events")
    _drop_index_safe("idx_email_auth_events_success", "email_auth_events")
    _drop_index_safe("idx_email_auth_events_event_type", "email_auth_events")
    _drop_index_safe("idx_email_auth_events_timestamp", "email_auth_events")

    # Permission Audit Log Indexes
    _drop_index_safe("idx_permission_audit_log_team_time", "permission_audit_log")
    _drop_index_safe("idx_permission_audit_log_resource_granted_time", "permission_audit_log")
    _drop_index_safe("idx_permission_audit_log_user_time", "permission_audit_log")
    _drop_index_safe("idx_permission_audit_log_team_id", "permission_audit_log")
    _drop_index_safe("idx_permission_audit_log_resource_type", "permission_audit_log")
    _drop_index_safe("idx_permission_audit_log_granted", "permission_audit_log")
    _drop_index_safe("idx_permission_audit_log_user_email", "permission_audit_log")
    _drop_index_safe("idx_permission_audit_log_timestamp", "permission_audit_log")

    # RBAC
    _drop_index_safe("idx_user_roles_role_scope_active", "user_roles")
    _drop_index_safe("idx_user_roles_user_scope_active", "user_roles")

    # Metrics
    _drop_index_safe("idx_prompt_metrics_prompt_timestamp", "prompt_metrics")
    _drop_index_safe("idx_server_metrics_server_timestamp", "server_metrics")
    _drop_index_safe("idx_resource_metrics_resource_timestamp", "resource_metrics")
    _drop_index_safe("idx_tool_metrics_tool_timestamp", "tool_metrics")

    # Authentication & Tokens
    _drop_index_safe("idx_oauth_tokens_gateway_user_created", "oauth_tokens")
    _drop_index_safe("idx_sso_auth_sessions_provider_user_created", "sso_auth_sessions")
    _drop_index_safe("idx_email_auth_events_user_type_time", "email_auth_events")
    _drop_index_safe("idx_email_api_tokens_team_active_created", "email_api_tokens")
    _drop_index_safe("idx_email_api_tokens_user_active_created", "email_api_tokens")

    # Observability
    _drop_index_safe("idx_observability_spans_resource_status_time", "observability_spans")
    _drop_index_safe("idx_observability_spans_trace_resource_time", "observability_spans")
    _drop_index_safe("idx_observability_traces_status_method_time", "observability_traces")
    _drop_index_safe("idx_observability_traces_user_status_time", "observability_traces")

    # Core Entities
    _drop_index_safe("idx_a2a_agents_visibility_active_created", "a2a_agents")
    _drop_index_safe("idx_a2a_agents_team_visibility_active_created", "a2a_agents")
    _drop_index_safe("idx_gateways_visibility_active_created", "gateways")
    _drop_index_safe("idx_gateways_team_visibility_active_created", "gateways")
    _drop_index_safe("idx_servers_visibility_active_created", "servers")
    _drop_index_safe("idx_servers_team_visibility_active_created", "servers")
    _drop_index_safe("idx_prompts_visibility_active_created", "prompts")
    _drop_index_safe("idx_prompts_team_visibility_active_created", "prompts")
    _drop_index_safe("idx_resources_visibility_active_created", "resources")
    _drop_index_safe("idx_resources_team_visibility_active_created", "resources")
    _drop_index_safe("idx_tools_visibility_active_created", "tools")
    _drop_index_safe("idx_tools_team_visibility_active_created", "tools")

    # Team Management
    _drop_index_safe("idx_email_teams_creator_personal_active", "email_teams")
    _drop_index_safe("idx_email_teams_visibility_active_created", "email_teams")
    _drop_index_safe("idx_email_team_join_requests_user_status_time", "email_team_join_requests")
    _drop_index_safe("idx_email_team_join_requests_team_status_time", "email_team_join_requests")
    _drop_index_safe("idx_email_team_invitations_email_active_created", "email_team_invitations")
    _drop_index_safe("idx_email_team_invitations_team_active_created", "email_team_invitations")
    _drop_index_safe("idx_email_team_members_team_role_active", "email_team_members")
    _drop_index_safe("idx_email_team_members_user_team_active", "email_team_members")

    # ========================================================================
    # Remove Foreign Key Indexes (Phase 1) - in reverse order
    # ========================================================================

    # Junction Table Indexes
    _drop_index_safe("idx_server_a2a_association_a2a_agent_id", "server_a2a_association")
    _drop_index_safe("idx_server_a2a_association_server_id", "server_a2a_association")
    _drop_index_safe("idx_server_prompt_association_prompt_id", "server_prompt_association")
    _drop_index_safe("idx_server_prompt_association_server_id", "server_prompt_association")
    _drop_index_safe("idx_server_resource_association_resource_id", "server_resource_association")
    _drop_index_safe("idx_server_resource_association_server_id", "server_resource_association")
    _drop_index_safe("idx_server_tool_association_tool_id", "server_tool_association")
    _drop_index_safe("idx_server_tool_association_server_id", "server_tool_association")

    _drop_index_safe("idx_mcp_messages_session_id", "mcp_messages")
    _drop_index_safe("idx_llm_models_provider_id", "llm_models")
    _drop_index_safe("idx_sso_auth_sessions_user_email", "sso_auth_sessions")
    _drop_index_safe("idx_sso_auth_sessions_provider_id", "sso_auth_sessions")
    _drop_index_safe("idx_token_revocations_revoked_by", "token_revocations")
    _drop_index_safe("idx_email_api_tokens_server_id", "email_api_tokens")
    _drop_index_safe("idx_oauth_states_gateway_id", "oauth_states")
    _drop_index_safe("idx_oauth_tokens_app_user_email", "oauth_tokens")
    _drop_index_safe("idx_oauth_tokens_gateway_id", "oauth_tokens")
    _drop_index_safe("idx_resource_subscriptions_resource_id", "resource_subscriptions")
    _drop_index_safe("idx_grpc_services_team_id", "grpc_services")
    _drop_index_safe("idx_a2a_agents_team_id", "a2a_agents")
    _drop_index_safe("idx_gateways_team_id", "gateways")
    _drop_index_safe("idx_servers_team_id", "servers")
    _drop_index_safe("idx_prompts_team_id", "prompts")
    _drop_index_safe("idx_prompts_gateway_id", "prompts")
    _drop_index_safe("idx_resources_team_id", "resources")
    _drop_index_safe("idx_resources_gateway_id", "resources")
    _drop_index_safe("idx_tools_team_id", "tools")
    _drop_index_safe("idx_tools_gateway_id", "tools")
    _drop_index_safe("idx_a2a_agent_metrics_a2a_agent_id", "a2a_agent_metrics")
    _drop_index_safe("idx_prompt_metrics_prompt_id", "prompt_metrics")
    _drop_index_safe("idx_server_metrics_server_id", "server_metrics")
    _drop_index_safe("idx_resource_metrics_resource_id", "resource_metrics")
    _drop_index_safe("idx_tool_metrics_tool_id", "tool_metrics")
    _drop_index_safe("idx_pending_user_approvals_approved_by", "pending_user_approvals")
    _drop_index_safe("idx_email_team_join_requests_reviewed_by", "email_team_join_requests")
    _drop_index_safe("idx_email_team_join_requests_user_email", "email_team_join_requests")
    _drop_index_safe("idx_email_team_join_requests_team_id", "email_team_join_requests")
    _drop_index_safe("idx_email_team_invitations_invited_by", "email_team_invitations")
    _drop_index_safe("idx_email_team_invitations_team_id", "email_team_invitations")
    _drop_index_safe("idx_email_team_member_history_action_by", "email_team_member_history")
    _drop_index_safe("idx_email_team_member_history_user_email", "email_team_member_history")
    _drop_index_safe("idx_email_team_member_history_team_id", "email_team_member_history")
    _drop_index_safe("idx_email_team_member_history_team_member_id", "email_team_member_history")
    _drop_index_safe("idx_email_team_members_invited_by", "email_team_members")
    _drop_index_safe("idx_email_team_members_user_email", "email_team_members")
    _drop_index_safe("idx_email_team_members_team_id", "email_team_members")
    _drop_index_safe("idx_email_teams_created_by", "email_teams")
    _drop_index_safe("idx_user_roles_granted_by", "user_roles")
    _drop_index_safe("idx_user_roles_role_id", "user_roles")
    _drop_index_safe("idx_user_roles_user_email", "user_roles")
    _drop_index_safe("idx_roles_created_by", "roles")
    _drop_index_safe("idx_roles_inherits_from", "roles")
