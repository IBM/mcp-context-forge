# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/u5f6g7h8i9j0_add_provider_metadata_to_sso_providers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Add provider_metadata column to sso_providers table.

This column stores provider-specific configuration such as:
- Role mappings (group ID -> role name)
- Groups claim configuration
- Other provider-specific settings

Revision ID: u5f6g7h8i9j0
Revises: 5f3c681b05e1
Create Date: 2025-01-16
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision: str = "u5f6g7h8i9j0"
down_revision: Union[str, Sequence[str], None] = "5f3c681b05e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add provider_metadata JSON column to sso_providers table.

    Note: MySQL/MariaDB do not support server_default for JSON columns,
    so we add as nullable, backfill, then alter to NOT NULL for those dialects.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("sso_providers"):
        print("sso_providers table not found. Skipping migration.")
        return

    # Check if column already exists
    columns = [col["name"] for col in inspector.get_columns("sso_providers")]
    if "provider_metadata" in columns:
        print("provider_metadata column already exists. Skipping migration.")
        return

    # Add provider_metadata column with appropriate type and default for database
    if dialect == "postgresql":
        # PostgreSQL: JSONB with server_default works
        op.add_column(
            "sso_providers",
            sa.Column(
                "provider_metadata",
                pg.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
    elif dialect in ("mysql", "mariadb"):
        # MySQL/MariaDB: JSON columns cannot have server_default
        # Add as nullable, backfill, then alter to NOT NULL
        op.add_column(
            "sso_providers",
            sa.Column("provider_metadata", sa.JSON(), nullable=True),
        )
        # Backfill existing rows with empty JSON object
        bind.execute(sa.text("UPDATE sso_providers SET provider_metadata = '{}' WHERE provider_metadata IS NULL"))
        # Alter to NOT NULL
        op.alter_column("sso_providers", "provider_metadata", nullable=False)
    else:
        # SQLite and others: JSON stored as TEXT, server_default works
        op.add_column(
            "sso_providers",
            sa.Column(
                "provider_metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )


def downgrade() -> None:
    """Remove provider_metadata column from sso_providers table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("sso_providers"):
        columns = [col["name"] for col in inspector.get_columns("sso_providers")]
        if "provider_metadata" in columns:
            op.drop_column("sso_providers", "provider_metadata")
