# -*- coding: utf-8 -*-
"""add_tags_support_to_all_entities

Revision ID: cc7b95fec5d9
Revises: e75490e949b1
Create Date: 2025-08-06 22:27:08.682814

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "cc7b95fec5d9"
down_revision: Union[str, Sequence[str], None] = "e75490e949b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add tags JSON column to all entity tables."""
    # Add tags column to tools table
    op.add_column("tools", sa.Column("tags", sa.JSON(), nullable=True, server_default="[]"))

    # Add tags column to resources table
    op.add_column("resources", sa.Column("tags", sa.JSON(), nullable=True, server_default="[]"))

    # Add tags column to prompts table
    op.add_column("prompts", sa.Column("tags", sa.JSON(), nullable=True, server_default="[]"))

    # Add tags column to servers table
    op.add_column("servers", sa.Column("tags", sa.JSON(), nullable=True, server_default="[]"))

    # Add tags column to gateways table
    op.add_column("gateways", sa.Column("tags", sa.JSON(), nullable=True, server_default="[]"))

    # Create indexes for PostgreSQL (GIN indexes for JSON)
    # These will be ignored on SQLite but work on PostgreSQL
    try:
        op.create_index("idx_tools_tags", "tools", ["tags"], postgresql_using="gin")
        op.create_index("idx_resources_tags", "resources", ["tags"], postgresql_using="gin")
        op.create_index("idx_prompts_tags", "prompts", ["tags"], postgresql_using="gin")
        op.create_index("idx_servers_tags", "servers", ["tags"], postgresql_using="gin")
        op.create_index("idx_gateways_tags", "gateways", ["tags"], postgresql_using="gin")
    except Exception:
        # SQLite doesn't support GIN indexes, skip silently
        pass


def downgrade() -> None:
    """Downgrade schema - Remove tags columns from all entity tables."""
    # Drop indexes first (if they exist)
    try:
        op.drop_index("idx_tools_tags", "tools")
        op.drop_index("idx_resources_tags", "resources")
        op.drop_index("idx_prompts_tags", "prompts")
        op.drop_index("idx_servers_tags", "servers")
        op.drop_index("idx_gateways_tags", "gateways")
    except Exception:
        # Indexes might not exist on SQLite
        pass

    # Drop tags columns
    op.drop_column("gateways", "tags")
    op.drop_column("servers", "tags")
    op.drop_column("prompts", "tags")
    op.drop_column("resources", "tags")
    op.drop_column("tools", "tags")
