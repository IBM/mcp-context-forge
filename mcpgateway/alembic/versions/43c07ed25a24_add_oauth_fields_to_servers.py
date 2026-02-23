# -*- coding: utf-8 -*-
"""add_oauth_fields_to_servers

Revision ID: 43c07ed25a24
Revises: b9e496e91e71
Create Date: 2026-01-11 10:30:26.832065

Add OAuth 2.0 configuration fields to the servers table for RFC 9728
Protected Resource Metadata support. This enables MCP clients to authenticate
to virtual servers using browser-based OAuth/SSO.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "43c07ed25a24"
down_revision: Union[str, Sequence[str], None] = "b9e496e91e71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    """Check whether a table exists.

    Args:
        table_name: Name of table to inspect.

    Returns:
        True if table exists, False otherwise.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check whether a column exists in a table.

    Args:
        table_name: Name of table to inspect.
        column_name: Name of column to inspect.

    Returns:
        True if column exists, False otherwise.
    """
    if not _table_exists(table_name):
        return False
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    """Add OAuth configuration fields to servers table."""
    if not _table_exists("servers"):
        return

    # Add oauth_enabled column with default False
    # Use sa.false() for cross-database compatibility (SQLite, PostgreSQL)
    if not _column_exists("servers", "oauth_enabled"):
        op.add_column("servers", sa.Column("oauth_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))

    # Add oauth_config column for storing OAuth configuration as JSON
    if not _column_exists("servers", "oauth_config"):
        op.add_column("servers", sa.Column("oauth_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove OAuth configuration fields from servers table."""
    if not _table_exists("servers"):
        return

    if _column_exists("servers", "oauth_config"):
        op.drop_column("servers", "oauth_config")
    if _column_exists("servers", "oauth_enabled"):
        op.drop_column("servers", "oauth_enabled")
