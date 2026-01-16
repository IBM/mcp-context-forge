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
    """Add provider_metadata JSON column to sso_providers table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if this is a fresh database without existing tables
    if not inspector.has_table("sso_providers"):
        print("sso_providers table not found. Skipping migration.")
        return

    # Check if column already exists
    columns = [col["name"] for col in inspector.get_columns("sso_providers")]
    if "provider_metadata" in columns:
        print("provider_metadata column already exists. Skipping migration.")
        return

    # Add provider_metadata column with appropriate type for database
    is_postgresql = bind.dialect.name == "postgresql"
    col_type = pg.JSONB() if is_postgresql else sa.JSON()
    default = sa.text("'{}'::jsonb") if is_postgresql else sa.text("'{}'")

    op.add_column(
        "sso_providers",
        sa.Column("provider_metadata", col_type, nullable=False, server_default=default),
    )


def downgrade() -> None:
    """Remove provider_metadata column from sso_providers table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("sso_providers"):
        columns = [col["name"] for col in inspector.get_columns("sso_providers")]
        if "provider_metadata" in columns:
            op.drop_column("sso_providers", "provider_metadata")
