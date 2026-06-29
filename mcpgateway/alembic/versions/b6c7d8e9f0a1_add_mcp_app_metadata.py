# -*- coding: utf-8 -*-
"""Add MCP App metadata.

Revision ID: b6c7d8e9f0a1
Revises: 6c0e5f8a9b1d
Create Date: 2026-06-02 00:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "b6c7d8e9f0a1"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "6c0e5f8a9b1d"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    """Add MCP Apps metadata and AppBridge sessions."""
    bind = op.get_bind()
    tables = _table_names(bind)

    # Existing tools and resources intentionally keep NULL extension_metadata.
    # NULL means "no extension metadata" and preserves the pre-MCP-Apps behavior:
    # tools remain model-visible by default, and existing resources are not treated
    # as ui:// MCP Apps resources unless metadata is explicitly added later.
    if "tools" in tables and "extension_metadata" not in _column_names(bind, "tools"):
        op.add_column("tools", sa.Column("extension_metadata", sa.JSON(), nullable=True))

    if "resources" in tables and "extension_metadata" not in _column_names(bind, "resources"):
        op.add_column("resources", sa.Column("extension_metadata", sa.JSON(), nullable=True))

    if "mcp_app_sessions" not in tables:
        op.create_table(
            "mcp_app_sessions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("mcp_session_id", sa.String(length=255), nullable=False),
            sa.Column("user_email", sa.String(length=255), nullable=False),
            sa.Column("server_id", sa.String(length=36), nullable=True),
            sa.Column("resource_uri", sa.String(length=767), nullable=False),
            sa.Column("token_teams", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_mcp_app_sessions_lookup", "mcp_app_sessions", ["id", "mcp_session_id", "user_email"])
        op.create_index("idx_mcp_app_sessions_expires_at", "mcp_app_sessions", ["expires_at"])


def downgrade() -> None:
    """Remove MCP App metadata."""
    bind = op.get_bind()
    tables = _table_names(bind)

    if "mcp_app_sessions" in tables:
        op.drop_index("idx_mcp_app_sessions_expires_at", table_name="mcp_app_sessions")
        op.drop_index("idx_mcp_app_sessions_lookup", table_name="mcp_app_sessions")
        op.drop_table("mcp_app_sessions")

    if "resources" in tables and "extension_metadata" in _column_names(bind, "resources"):
        op.drop_column("resources", "extension_metadata")

    if "tools" in tables and "extension_metadata" in _column_names(bind, "tools"):
        op.drop_column("tools", "extension_metadata")
