# -*- coding: utf-8 -*-
"""add pagination indexes

Revision ID: g1a2b3c4d5e6
Revises: e5a59c16e041
Create Date: 2025-10-13 10:00:00.000000

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e5a59c16e041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add pagination indexes for efficient querying."""
    # Tools table indexes
    op.create_index(
        "ix_tools_created_at_id",
        "tools",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_tools_team_id_created_at",
        "tools",
        ["team_id", "created_at"],
        unique=False,
    )

    # Resources table indexes
    op.create_index(
        "ix_resources_created_at_uri",
        "resources",
        ["created_at", "uri"],
        unique=False,
    )
    op.create_index(
        "ix_resources_team_id_created_at",
        "resources",
        ["team_id", "created_at"],
        unique=False,
    )

    # Prompts table indexes
    op.create_index(
        "ix_prompts_created_at_name",
        "prompts",
        ["created_at", "name"],
        unique=False,
    )
    op.create_index(
        "ix_prompts_team_id_created_at",
        "prompts",
        ["team_id", "created_at"],
        unique=False,
    )

    # Servers table indexes
    op.create_index(
        "ix_servers_created_at_id",
        "servers",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_servers_team_id_created_at",
        "servers",
        ["team_id", "created_at"],
        unique=False,
    )

    # Gateways table indexes
    op.create_index(
        "ix_gateways_created_at_id",
        "gateways",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_gateways_team_id_created_at",
        "gateways",
        ["team_id", "created_at"],
        unique=False,
    )

    # Users table indexes
    op.create_index(
        "ix_email_users_created_at_email",
        "email_users",
        ["created_at", "email"],
        unique=False,
    )

    # Teams table indexes
    op.create_index(
        "ix_email_teams_created_at_id",
        "email_teams",
        ["created_at", "id"],
        unique=False,
    )

    # API Tokens table indexes
    op.create_index(
        "ix_email_api_tokens_created_at_id",
        "email_api_tokens",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_email_api_tokens_user_email_created_at",
        "email_api_tokens",
        ["user_email", "created_at"],
        unique=False,
    )

    # Auth Events table indexes
    op.create_index(
        "ix_email_auth_events_timestamp_id",
        "email_auth_events",
        ["timestamp", "id"],
        unique=False,
    )
    op.create_index(
        "ix_email_auth_events_user_email_timestamp",
        "email_auth_events",
        ["user_email", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    """Remove pagination indexes."""
    # Drop indexes in reverse order
    op.drop_index("ix_email_auth_events_user_email_timestamp", table_name="email_auth_events")
    op.drop_index("ix_email_auth_events_timestamp_id", table_name="email_auth_events")
    op.drop_index("ix_email_api_tokens_user_email_created_at", table_name="email_api_tokens")
    op.drop_index("ix_email_api_tokens_created_at_id", table_name="email_api_tokens")
    op.drop_index("ix_email_teams_created_at_id", table_name="email_teams")
    op.drop_index("ix_email_users_created_at_email", table_name="email_users")
    op.drop_index("ix_gateways_team_id_created_at", table_name="gateways")
    op.drop_index("ix_gateways_created_at_id", table_name="gateways")
    op.drop_index("ix_servers_team_id_created_at", table_name="servers")
    op.drop_index("ix_servers_created_at_id", table_name="servers")
    op.drop_index("ix_prompts_team_id_created_at", table_name="prompts")
    op.drop_index("ix_prompts_created_at_name", table_name="prompts")
    op.drop_index("ix_resources_team_id_created_at", table_name="resources")
    op.drop_index("ix_resources_created_at_uri", table_name="resources")
    op.drop_index("ix_tools_team_id_created_at", table_name="tools")
    op.drop_index("ix_tools_created_at_id", table_name="tools")
