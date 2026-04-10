# -*- coding: utf-8 -*-
"""Add UAID (Universal Agent ID) support to a2a_agents

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-04-10 00:00:00.000000

Adds HCS-14 Universal Agent ID (UAID) support to enable zero-config cross-gateway
routing. Extends id column to accommodate UAID format and adds metadata fields for
self-describing agent identifiers.

Changes:
- Extend a2a_agents.id column: String(36) → String(512) for UAID format
- Add uaid (String(512), nullable): Full UAID string
- Add uaid_registry (String(255), nullable): Registry name from UAID
- Add uaid_proto (String(50), nullable): Protocol from UAID (a2a, mcp, rest, grpc)
- Add uaid_native_id (String(767), nullable): Native endpoint URL for routing

Backward compatible: Existing UUID-based agents continue to work unchanged.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add UAID support.

    Supports both PostgreSQL and SQLite databases.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect_name = bind.dialect.name.lower()

    # Skip if fresh database (tables created via create_all + stamp)
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Skip if a2a_agents table doesn't exist
    if not inspector.has_table("a2a_agents"):
        print("a2a_agents table not found. Skipping migration.")
        return

    # Check current state
    columns = {col["name"]: col for col in inspector.get_columns("a2a_agents")}

    # Check if columns need to be added
    need_uaid = "uaid" not in columns
    need_uaid_registry = "uaid_registry" not in columns
    need_uaid_proto = "uaid_proto" not in columns
    need_uaid_native_id = "uaid_native_id" not in columns

    # Check if id column needs to be extended
    need_id_resize = False
    if "id" in columns:
        id_type_str = str(columns["id"].get("type", "")).upper()
        # Check if it's VARCHAR/STRING with length 36
        if ("VARCHAR" in id_type_str or "STRING" in id_type_str) and "36" in id_type_str:
            need_id_resize = True

    # Nothing to do if everything is already migrated
    if not (need_id_resize or need_uaid or need_uaid_registry or need_uaid_proto or need_uaid_native_id):
        print("UAID columns already exist and id column is correct size. Skipping migration.")
        return

    print(f"Applying UAID migration for {dialect_name} database...")

    # SQLite requires batch mode for all ALTER TABLE operations
    # PostgreSQL can use direct ops but batch mode also works
    if dialect_name == "sqlite":
        # Use batch mode for SQLite (recreates table)
        with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
            # Extend id column to accommodate UAID format
            if need_id_resize:
                batch_op.alter_column(
                    "id",
                    type_=sa.String(512),
                    existing_type=sa.String(36),
                    existing_nullable=False
                )
                print("  - Extended id column from VARCHAR(36) to VARCHAR(512)")

            # Add UAID metadata columns
            if need_uaid:
                batch_op.add_column(sa.Column("uaid", sa.String(512), nullable=True))
                print("  - Added uaid column (VARCHAR(512), nullable)")
            if need_uaid_registry:
                batch_op.add_column(sa.Column("uaid_registry", sa.String(255), nullable=True))
                print("  - Added uaid_registry column (VARCHAR(255), nullable)")
            if need_uaid_proto:
                batch_op.add_column(sa.Column("uaid_proto", sa.String(50), nullable=True))
                print("  - Added uaid_proto column (VARCHAR(50), nullable)")
            if need_uaid_native_id:
                batch_op.add_column(sa.Column("uaid_native_id", sa.String(767), nullable=True))
                print("  - Added uaid_native_id column (VARCHAR(767), nullable)")
    else:
        # PostgreSQL: Use direct operations (more efficient than batch mode)
        if need_id_resize:
            op.alter_column(
                "a2a_agents",
                "id",
                type_=sa.String(512),
                existing_type=sa.String(36),
                existing_nullable=False
            )
            print("  - Extended id column from VARCHAR(36) to VARCHAR(512)")

        # Add UAID metadata columns
        if need_uaid:
            op.add_column("a2a_agents", sa.Column("uaid", sa.String(512), nullable=True))
            print("  - Added uaid column (VARCHAR(512), nullable)")
        if need_uaid_registry:
            op.add_column("a2a_agents", sa.Column("uaid_registry", sa.String(255), nullable=True))
            print("  - Added uaid_registry column (VARCHAR(255), nullable)")
        if need_uaid_proto:
            op.add_column("a2a_agents", sa.Column("uaid_proto", sa.String(50), nullable=True))
            print("  - Added uaid_proto column (VARCHAR(50), nullable)")
        if need_uaid_native_id:
            op.add_column("a2a_agents", sa.Column("uaid_native_id", sa.String(767), nullable=True))
            print("  - Added uaid_native_id column (VARCHAR(767), nullable)")

    print("✅ UAID support added to a2a_agents table.")


def downgrade() -> None:
    """Downgrade schema to remove UAID support.

    WARNING: This will truncate any UAID-based agent IDs back to 36 characters!

    Supports both PostgreSQL and SQLite databases.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect_name = bind.dialect.name.lower()

    # Skip if fresh database
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Skip if a2a_agents table doesn't exist
    if not inspector.has_table("a2a_agents"):
        print("a2a_agents table not found. Skipping migration.")
        return

    # Check which columns exist
    columns = {col["name"] for col in inspector.get_columns("a2a_agents")}

    print(f"Reverting UAID migration for {dialect_name} database...")

    # SQLite requires batch mode for all ALTER TABLE operations
    if dialect_name == "sqlite":
        with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
            # Remove UAID columns if they exist (reverse order)
            if "uaid_native_id" in columns:
                batch_op.drop_column("uaid_native_id")
                print("  - Dropped uaid_native_id column")
            if "uaid_proto" in columns:
                batch_op.drop_column("uaid_proto")
                print("  - Dropped uaid_proto column")
            if "uaid_registry" in columns:
                batch_op.drop_column("uaid_registry")
                print("  - Dropped uaid_registry column")
            if "uaid" in columns:
                batch_op.drop_column("uaid")
                print("  - Dropped uaid column")

            # Shrink id column back to String(36)
            # WARNING: This will truncate any UAID-based agent IDs!
            if "id" in columns:
                batch_op.alter_column(
                    "id",
                    type_=sa.String(36),
                    existing_type=sa.String(512),
                    existing_nullable=False
                )
                print("  - ⚠️  Shrunk id column from VARCHAR(512) to VARCHAR(36) (data may be truncated!)")
    else:
        # PostgreSQL: Use direct operations
        # Remove UAID columns if they exist (reverse order)
        if "uaid_native_id" in columns:
            op.drop_column("a2a_agents", "uaid_native_id")
            print("  - Dropped uaid_native_id column")
        if "uaid_proto" in columns:
            op.drop_column("a2a_agents", "uaid_proto")
            print("  - Dropped uaid_proto column")
        if "uaid_registry" in columns:
            op.drop_column("a2a_agents", "uaid_registry")
            print("  - Dropped uaid_registry column")
        if "uaid" in columns:
            op.drop_column("a2a_agents", "uaid")
            print("  - Dropped uaid column")

        # Shrink id column back to String(36)
        # WARNING: This will truncate any UAID-based agent IDs!
        if "id" in columns:
            op.alter_column(
                "a2a_agents",
                "id",
                type_=sa.String(36),
                existing_type=sa.String(512),
                existing_nullable=False
            )
            print("  - ⚠️  Shrunk id column from VARCHAR(512) to VARCHAR(36) (data may be truncated!)")

    print("✅ UAID support removed from a2a_agents table.")
