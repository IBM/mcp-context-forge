# -*- coding: utf-8 -*-
"""add_comprehensive_metadata_to_all_entities

Revision ID: 34492f99a0c4
Revises: eb17fd368f9d
Create Date: 2025-08-18 08:06:17.141169

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "34492f99a0c4"
down_revision: Union[str, Sequence[str], None] = "eb17fd368f9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add comprehensive metadata columns to all entity tables for audit tracking."""
    tables = ["tools", "resources", "prompts", "servers", "gateways"]

    for table in tables:
        # Creation metadata (nullable=True for backwards compatibility)
        op.add_column(table, sa.Column("created_by", sa.String(), nullable=True))
        op.add_column(table, sa.Column("created_from_ip", sa.String(), nullable=True))
        op.add_column(table, sa.Column("created_via", sa.String(), nullable=True))
        op.add_column(table, sa.Column("created_user_agent", sa.Text(), nullable=True))

        # Modification metadata (nullable=True for backwards compatibility)
        op.add_column(table, sa.Column("modified_by", sa.String(), nullable=True))
        op.add_column(table, sa.Column("modified_from_ip", sa.String(), nullable=True))
        op.add_column(table, sa.Column("modified_via", sa.String(), nullable=True))
        op.add_column(table, sa.Column("modified_user_agent", sa.Text(), nullable=True))

        # Source tracking (nullable=True for backwards compatibility)
        op.add_column(table, sa.Column("import_batch_id", sa.String(), nullable=True))
        op.add_column(table, sa.Column("federation_source", sa.String(), nullable=True))
        op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

        # Create indexes for query performance (PostgreSQL compatible, SQLite ignores)
        try:
            op.create_index(f"idx_{table}_created_by", table, ["created_by"])
            op.create_index(f"idx_{table}_created_at", table, ["created_at"])
            op.create_index(f"idx_{table}_modified_at", table, ["modified_at"])
            op.create_index(f"idx_{table}_created_via", table, ["created_via"])
        except Exception:  # nosec B110 - database compatibility
            # SQLite doesn't support all index types, skip silently
            pass


def downgrade() -> None:
    """Remove comprehensive metadata columns from all entity tables."""
    tables = ["tools", "resources", "prompts", "servers", "gateways"]

    for table in tables:
        # Drop indexes first (if they exist)
        try:
            op.drop_index(f"idx_{table}_created_by", table)
            op.drop_index(f"idx_{table}_created_at", table)
            op.drop_index(f"idx_{table}_modified_at", table)
            op.drop_index(f"idx_{table}_created_via", table)
        except Exception:  # nosec B110 - database compatibility
            # Indexes might not exist on SQLite
            pass

        # Drop metadata columns
        op.drop_column(table, "version")
        op.drop_column(table, "federation_source")
        op.drop_column(table, "import_batch_id")
        op.drop_column(table, "modified_user_agent")
        op.drop_column(table, "modified_via")
        op.drop_column(table, "modified_from_ip")
        op.drop_column(table, "modified_by")
        op.drop_column(table, "created_user_agent")
        op.drop_column(table, "created_via")
        op.drop_column(table, "created_from_ip")
        op.drop_column(table, "created_by")
