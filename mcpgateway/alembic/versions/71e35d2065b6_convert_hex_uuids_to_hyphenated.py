# -*- coding: utf-8 -*-
"""convert_hex_uuids_to_hyphenated

Revision ID: 71e35d2065b6
Revises: c1c2c3c4c5c6
Create Date: 2026-02-13 13:40:21.370714

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "71e35d2065b6"
down_revision: Union[str, Sequence[str], None] = "c1c2c3c4c5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert hex UUIDs (32 chars) to hyphenated format (36 chars) for consistency.

    This migration converts both primary key IDs and all foreign key references
    to ensure referential integrity is maintained using batch updates for performance.
    """
    inspector = sa.inspect(op.get_bind())
    connection = op.get_bind()
    dialect = connection.dialect.name

    # Tables with UUID primary keys that need conversion
    tables_with_uuid_pk = [
        "gateways",
        "servers",
        "tools",
        "resources",
        "prompts",
        "rate_limits",
        "api_keys",
        "audit_logs",
        "plugin_executions",
        "plugin_violations",
        "oauth_tokens",
        "oauth_clients",
        "a2a_agents",
        "email_teams",
        "roles",
        "email_users",
        "email_team_members",
        "email_team_invitations",
        "email_team_join_requests",
        "observability_traces",
        "observability_spans",
        "sso_providers",
        "llm_providers",
    ]

    # Mapping of tables to their foreign key columns that reference UUID PKs
    # Format: {table_name: [(fk_column, referenced_table), ...]}
    fk_mappings = {
        "tools": [("gateway_id", "gateways"), ("team_id", "email_teams")],
        "resources": [("gateway_id", "gateways"), ("team_id", "email_teams")],
        "prompts": [("gateway_id", "gateways"), ("team_id", "email_teams")],
        "servers": [("team_id", "email_teams")],
        "gateways": [("team_id", "email_teams")],
        "a2a_agents": [("team_id", "email_teams"), ("tool_id", "tools")],
        "server_tool_association": [("server_id", "servers"), ("tool_id", "tools")],
        "server_resource_association": [("server_id", "servers"), ("resource_id", "resources")],
        "server_prompt_association": [("server_id", "servers"), ("prompt_id", "prompts")],
        "server_a2a_association": [("server_id", "servers"), ("a2a_agent_id", "a2a_agents")],
        "tool_metrics": [("tool_id", "tools")],
        "resource_metrics": [("resource_id", "resources")],
        "prompt_metrics": [("prompt_id", "prompts")],
        "server_metrics": [("server_id", "servers")],
        "a2a_agent_metrics": [("a2a_agent_id", "a2a_agents")],
        "tool_metrics_hourly": [("tool_id", "tools")],
        "resource_metrics_hourly": [("resource_id", "resources")],
        "prompt_metrics_hourly": [("prompt_id", "prompts")],
        "server_metrics_hourly": [("server_id", "servers")],
        "a2a_agent_metrics_hourly": [("a2a_agent_id", "a2a_agents")],
        "observability_spans": [("trace_id", "observability_traces"), ("parent_span_id", "observability_spans")],
        "observability_events": [("span_id", "observability_spans"), ("trace_id", "observability_traces")],
        "api_keys": [("team_id", "email_teams"), ("server_id", "servers")],
        "oauth_tokens": [("gateway_id", "gateways")],
        "oauth_state": [("gateway_id", "gateways")],
        "oauth_clients": [("gateway_id", "gateways")],
        "email_team_members": [("team_id", "email_teams")],
        "email_team_member_history": [("team_member_id", "email_team_members"), ("team_id", "email_teams")],
        "email_team_invitations": [("team_id", "email_teams")],
        "email_team_join_requests": [("team_id", "email_teams")],
        "role_assignments": [("role_id", "roles")],
        "roles": [("inherits_from", "roles")],
        "resource_subscriptions": [("resource_id", "resources"), ("team_id", "email_teams")],
        "mcp_sessions": [("gateway_id", "gateways")],
        "llm_chat_sessions": [("provider_id", "llm_providers")],
    }

    # Helper function to build UUID hyphenation SQL based on database dialect
    def build_hyphenate_uuid_sql(column_name: str) -> str:
        """Build database-agnostic SQL to convert hex UUID to hyphenated format.

        Args:
            column_name: The name of the column containing the UUID to hyphenate.

        Returns:
            SQL expression string that converts a 32-char hex UUID to hyphenated format.
        """
        if dialect == "postgresql":
            # PostgreSQL: substring() and ||
            return (
                f"substring({column_name}, 1, 8) || '-' || "
                f"substring({column_name}, 9, 4) || '-' || "
                f"substring({column_name}, 13, 4) || '-' || "
                f"substring({column_name}, 17, 4) || '-' || "
                f"substring({column_name}, 21)"
            )
        else:
            # SQLite: substr() and ||
            return (
                f"substr({column_name}, 1, 8) || '-' || "
                f"substr({column_name}, 9, 4) || '-' || "
                f"substr({column_name}, 13, 4) || '-' || "
                f"substr({column_name}, 17, 4) || '-' || "
                f"substr({column_name}, 21)"
            )

    # Step 1: Convert primary key IDs in all tables using batch updates for performance
    for table_name in tables_with_uuid_pk:
        if table_name not in inspector.get_table_names():
            continue

        columns = {col["name"]: col for col in inspector.get_columns(table_name)}
        if "id" not in columns:
            continue

        # Batch update: convert all hex UUIDs to hyphenated format in a single statement
        hyphenate_sql = build_hyphenate_uuid_sql("id")
        update_sql = f"UPDATE {table_name} SET id = {hyphenate_sql} WHERE LENGTH(id) = 32 AND id NOT LIKE '%-%'"  # nosec: B608

        try:
            connection.execute(sa.text(update_sql))
            connection.commit()
        except Exception as e:
            # Log error but continue with next table
            print(f"Warning: Failed to batch update {table_name}: {e}")
            connection.rollback()

    # Step 2: Convert foreign key references in batch
    for table_name, fk_columns in fk_mappings.items():
        if table_name not in inspector.get_table_names():
            continue

        table_columns = {col["name"]: col for col in inspector.get_columns(table_name)}

        for fk_column, referenced_table in fk_columns:
            # Skip if FK column doesn't exist
            if fk_column not in table_columns:
                continue

            # Batch update: convert all hex UUID foreign keys to hyphenated format
            hyphenate_sql = build_hyphenate_uuid_sql(fk_column)
            update_sql = f"UPDATE {table_name} SET {fk_column} = {hyphenate_sql} " f"WHERE {fk_column} IS NOT NULL AND LENGTH({fk_column}) = 32 AND {fk_column} NOT LIKE '%-%'"  # nosec: B608

            try:
                connection.execute(sa.text(update_sql))
                connection.commit()
            except Exception as e:
                # Log error but continue with next FK
                print(f"Warning: Failed to batch update {table_name}.{fk_column}: {e}")
                connection.rollback()


def downgrade() -> None:
    """Convert hyphenated UUIDs back to hex format using batch updates for performance.

    This downgrade reverses both primary key IDs and all foreign key references
    to restore the original hex format.
    """
    inspector = sa.inspect(op.get_bind())
    connection = op.get_bind()
    dialect = connection.dialect.name

    # Tables with UUID primary keys that need conversion
    tables_with_uuid_pk = [
        "gateways",
        "servers",
        "tools",
        "resources",
        "prompts",
        "rate_limits",
        "api_keys",
        "audit_logs",
        "plugin_executions",
        "plugin_violations",
        "oauth_tokens",
        "oauth_clients",
        "a2a_agents",
        "email_teams",
        "roles",
        "email_users",
        "email_team_members",
        "email_team_invitations",
        "email_team_join_requests",
        "observability_traces",
        "observability_spans",
        "sso_providers",
        "llm_providers",
    ]

    # Mapping of tables to their foreign key columns (same as upgrade)
    fk_mappings = {
        "tools": [("gateway_id", "gateways"), ("team_id", "email_teams")],
        "resources": [("gateway_id", "gateways"), ("team_id", "email_teams")],
        "prompts": [("gateway_id", "gateways"), ("team_id", "email_teams")],
        "servers": [("team_id", "email_teams")],
        "gateways": [("team_id", "email_teams")],
        "a2a_agents": [("team_id", "email_teams"), ("tool_id", "tools")],
        "server_tool_association": [("server_id", "servers"), ("tool_id", "tools")],
        "server_resource_association": [("server_id", "servers"), ("resource_id", "resources")],
        "server_prompt_association": [("server_id", "servers"), ("prompt_id", "prompts")],
        "server_a2a_association": [("server_id", "servers"), ("a2a_agent_id", "a2a_agents")],
        "tool_metrics": [("tool_id", "tools")],
        "resource_metrics": [("resource_id", "resources")],
        "prompt_metrics": [("prompt_id", "prompts")],
        "server_metrics": [("server_id", "servers")],
        "a2a_agent_metrics": [("a2a_agent_id", "a2a_agents")],
        "tool_metrics_hourly": [("tool_id", "tools")],
        "resource_metrics_hourly": [("resource_id", "resources")],
        "prompt_metrics_hourly": [("prompt_id", "prompts")],
        "server_metrics_hourly": [("server_id", "servers")],
        "a2a_agent_metrics_hourly": [("a2a_agent_id", "a2a_agents")],
        "observability_spans": [("trace_id", "observability_traces"), ("parent_span_id", "observability_spans")],
        "observability_events": [("span_id", "observability_spans"), ("trace_id", "observability_traces")],
        "api_keys": [("team_id", "email_teams"), ("server_id", "servers")],
        "oauth_tokens": [("gateway_id", "gateways")],
        "oauth_state": [("gateway_id", "gateways")],
        "oauth_clients": [("gateway_id", "gateways")],
        "email_team_members": [("team_id", "email_teams")],
        "email_team_member_history": [("team_member_id", "email_team_members"), ("team_id", "email_teams")],
        "email_team_invitations": [("team_id", "email_teams")],
        "email_team_join_requests": [("team_id", "email_teams")],
        "role_assignments": [("role_id", "roles")],
        "roles": [("inherits_from", "roles")],
        "resource_subscriptions": [("resource_id", "resources"), ("team_id", "email_teams")],
        "mcp_sessions": [("gateway_id", "gateways")],
        "llm_chat_sessions": [("provider_id", "llm_providers")],
    }

    # Step 1: Batch convert foreign key references back to hex format first
    # (reverse order from upgrade to avoid FK constraint violations)
    for table_name, fk_columns in fk_mappings.items():
        if table_name not in inspector.get_table_names():
            continue

        table_columns = {col["name"]: col for col in inspector.get_columns(table_name)}

        for fk_column, referenced_table in fk_columns:
            # Skip if FK column doesn't exist
            if fk_column not in table_columns:
                continue

            # Batch update: remove hyphens to convert back to hex format (using REPLACE/SUBSTITUTE)
            if dialect == "postgresql":
                unhyphenate_sql = f"REPLACE({fk_column}, '-', '')"
            else:
                # SQLite
                unhyphenate_sql = f"REPLACE({fk_column}, '-', '')"

            update_sql = f"UPDATE {table_name} SET {fk_column} = {unhyphenate_sql} " f"WHERE {fk_column} IS NOT NULL AND LENGTH({fk_column}) = 36 AND {fk_column} LIKE '%-%'"  # nosec: B608

            try:
                connection.execute(sa.text(update_sql))
                connection.commit()
            except Exception as e:
                print(f"Warning: Failed to batch downgrade {table_name}.{fk_column}: {e}")
                connection.rollback()

    # Step 2: Batch convert primary key IDs back to hex format
    for table_name in tables_with_uuid_pk:
        if table_name not in inspector.get_table_names():
            continue

        columns = {col["name"]: col for col in inspector.get_columns(table_name)}
        if "id" not in columns:
            continue

        # Batch update: remove hyphens to convert back to hex format
        update_sql = f"UPDATE {table_name} SET id = REPLACE(id, '-', '') " f"WHERE LENGTH(id) = 36 AND id LIKE '%-%'"  # nosec: B608

        try:
            connection.execute(sa.text(update_sql))
            connection.commit()
        except Exception as e:
            print(f"Warning: Failed to batch downgrade {table_name}: {e}")
            connection.rollback()
