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
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "g1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e5a59c16e041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _safe_create_index(index_name: str, table_name: str, columns: list, inspector) -> None:
    """Create index only if the table exists and index doesn't already exist.

    Args:
        index_name: Name of the index to create.
        table_name: Name of the table to create the index on.
        columns: List of column names to include in the index.
        inspector: SQLAlchemy inspector instance.
    """
    if not inspector.has_table(table_name):
        return
    existing_indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]
    if index_name in existing_indexes:
        return
    op.create_index(index_name, table_name, columns, unique=False)


def _safe_drop_index(index_name: str, table_name: str, inspector) -> None:
    """Drop index only if the table and index exist.

    Args:
        index_name: Name of the index to drop.
        table_name: Name of the table the index belongs to.
        inspector: SQLAlchemy inspector instance.
    """
    if not inspector.has_table(table_name):
        return
    existing_indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]
    if index_name not in existing_indexes:
        return
    op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    """Add pagination indexes for efficient querying."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database (tables created via create_all + stamp)
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Tools table indexes
    _safe_create_index("ix_tools_created_at_id", "tools", ["created_at", "id"], inspector)
    _safe_create_index("ix_tools_team_id_created_at", "tools", ["team_id", "created_at"], inspector)

    # Resources table indexes
    _safe_create_index("ix_resources_created_at_uri", "resources", ["created_at", "uri"], inspector)
    _safe_create_index("ix_resources_team_id_created_at", "resources", ["team_id", "created_at"], inspector)

    # Prompts table indexes
    _safe_create_index("ix_prompts_created_at_name", "prompts", ["created_at", "name"], inspector)
    _safe_create_index("ix_prompts_team_id_created_at", "prompts", ["team_id", "created_at"], inspector)

    # Servers table indexes
    _safe_create_index("ix_servers_created_at_id", "servers", ["created_at", "id"], inspector)
    _safe_create_index("ix_servers_team_id_created_at", "servers", ["team_id", "created_at"], inspector)

    # Gateways table indexes
    _safe_create_index("ix_gateways_created_at_id", "gateways", ["created_at", "id"], inspector)
    _safe_create_index("ix_gateways_team_id_created_at", "gateways", ["team_id", "created_at"], inspector)

    # Users table indexes
    _safe_create_index("ix_email_users_created_at_email", "email_users", ["created_at", "email"], inspector)

    # Teams table indexes
    _safe_create_index("ix_email_teams_created_at_id", "email_teams", ["created_at", "id"], inspector)

    # API Tokens table indexes
    _safe_create_index("ix_email_api_tokens_created_at_id", "email_api_tokens", ["created_at", "id"], inspector)
    _safe_create_index("ix_email_api_tokens_user_email_created_at", "email_api_tokens", ["user_email", "created_at"], inspector)

    # Auth Events table indexes
    _safe_create_index("ix_email_auth_events_timestamp_id", "email_auth_events", ["timestamp", "id"], inspector)
    _safe_create_index("ix_email_auth_events_user_email_timestamp", "email_auth_events", ["user_email", "timestamp"], inspector)


def downgrade() -> None:
    """Remove pagination indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Drop indexes in reverse order
    _safe_drop_index("ix_email_auth_events_user_email_timestamp", "email_auth_events", inspector)
    _safe_drop_index("ix_email_auth_events_timestamp_id", "email_auth_events", inspector)
    _safe_drop_index("ix_email_api_tokens_user_email_created_at", "email_api_tokens", inspector)
    _safe_drop_index("ix_email_api_tokens_created_at_id", "email_api_tokens", inspector)
    _safe_drop_index("ix_email_teams_created_at_id", "email_teams", inspector)
    _safe_drop_index("ix_email_users_created_at_email", "email_users", inspector)
    _safe_drop_index("ix_gateways_team_id_created_at", "gateways", inspector)
    _safe_drop_index("ix_gateways_created_at_id", "gateways", inspector)
    _safe_drop_index("ix_servers_team_id_created_at", "servers", inspector)
    _safe_drop_index("ix_servers_created_at_id", "servers", inspector)
    _safe_drop_index("ix_prompts_team_id_created_at", "prompts", inspector)
    _safe_drop_index("ix_prompts_created_at_name", "prompts", inspector)
    _safe_drop_index("ix_resources_team_id_created_at", "resources", inspector)
    _safe_drop_index("ix_resources_created_at_uri", "resources", inspector)
    _safe_drop_index("ix_tools_team_id_created_at", "tools", inspector)
    _safe_drop_index("ix_tools_created_at_id", "tools", inspector)
