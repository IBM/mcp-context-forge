# -*- coding: utf-8 -*-
"""Add UAID field to a2a_agents

Revision ID: d2b501bf4262
Revises: ffe4494639d3
Create Date: 2026-04-14 17:22:03.808082

Adds HCS-14 Universal Agent ID (UAID) support to enable zero-config cross-gateway
routing. Stores UAID in a separate field from the UUID primary key for optimal
database performance and clean URL routing.

Changes:
- Add uaid (String(2048), nullable, unique): Full UAID string for cross-gateway routing
- Add uaid_registry (String(255), nullable): Registry name extracted from UAID
- Add uaid_proto (String(50), nullable): Protocol from UAID (a2a, mcp, rest, grpc)
- Add uaid_native_id (String(767), nullable): Native endpoint URL for routing

The id field remains String(36) UUID for optimal indexing and URL compatibility.
UAID agents store UUID in id and UAID in uaid field for dual lookup support.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d2b501bf4262"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "ffe4494639d3"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add UAID field and metadata columns to a2a_agents table.

    Idempotent: skips if table doesn't exist (fresh DB) or columns already exist.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "a2a_agents" not in inspector.get_table_names():
        return

    # Get existing columns
    existing_columns = {col["name"] for col in inspector.get_columns("a2a_agents")}

    # Add uaid column if it doesn't exist
    if "uaid" not in existing_columns:
        op.add_column("a2a_agents", sa.Column("uaid", sa.String(2048), nullable=True, comment="Full UAID string for UAID-based agents (max 2048 chars)"))
        # Create unique index on uaid
        op.create_index("ix_a2a_agents_uaid", "a2a_agents", ["uaid"], unique=True)

    # Add uaid_registry column if it doesn't exist
    if "uaid_registry" not in existing_columns:
        op.add_column("a2a_agents", sa.Column("uaid_registry", sa.String(255), nullable=True, comment="Registry name extracted from UAID"))

    # Add uaid_proto column if it doesn't exist
    if "uaid_proto" not in existing_columns:
        op.add_column("a2a_agents", sa.Column("uaid_proto", sa.String(50), nullable=True, comment="Protocol from UAID (a2a, mcp, rest, grpc)"))

    # Add uaid_native_id column if it doesn't exist
    if "uaid_native_id" not in existing_columns:
        op.add_column("a2a_agents", sa.Column("uaid_native_id", sa.String(767), nullable=True, comment="Native endpoint URL for cross-gateway routing"))


def downgrade() -> None:
    """Remove UAID field and metadata columns from a2a_agents table.

    Idempotent: skips if table doesn't exist or columns don't exist.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if table doesn't exist
    if "a2a_agents" not in inspector.get_table_names():
        return

    # Get existing columns
    existing_columns = {col["name"] for col in inspector.get_columns("a2a_agents")}

    # Get existing indexes
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("a2a_agents")}

    # Drop uaid_native_id column if it exists
    if "uaid_native_id" in existing_columns:
        op.drop_column("a2a_agents", "uaid_native_id")

    # Drop uaid_proto column if it exists
    if "uaid_proto" in existing_columns:
        op.drop_column("a2a_agents", "uaid_proto")

    # Drop uaid_registry column if it exists
    if "uaid_registry" in existing_columns:
        op.drop_column("a2a_agents", "uaid_registry")

    # Drop uaid index if it exists
    if "ix_a2a_agents_uaid" in existing_indexes:
        op.drop_index("ix_a2a_agents_uaid", table_name="a2a_agents")

    # Drop uaid column if it exists
    if "uaid" in existing_columns:
        op.drop_column("a2a_agents", "uaid")
