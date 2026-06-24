# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/a54288286395_repair_sqlite_tools_grpc_service_fk.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan Catanus

repair_sqlite_tools_grpc_service_fk

Revision ID: a54288286395
Revises: 6c0e5f8a9b1d
Create Date: 2026-06-19 13:05:04.090092

Repairs SQLite databases upgraded through revision w7x8y9z0a1b2 that have the
tools.grpc_service_id column but lack the corresponding foreign key constraint.

This is a forward-only repair migration that is:
- Idempotent: safe to run multiple times
- Database-aware: only operates on SQLite databases
- Constraint-aware: no-op if FK already exists
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "a54288286395"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "6c0e5f8a9b1d"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = "fk_tools_grpc_service_id"


def _has_foreign_key(inspector: sa.Inspector, table_name: str, fk_name: str) -> bool:
    """Check if a foreign key constraint exists on a table.

    Args:
        inspector: SQLAlchemy inspector instance
        table_name: Name of the table to check
        fk_name: Name of the foreign key constraint

    Returns:
        bool: True if the foreign key exists, False otherwise
    """
    for fk in inspector.get_foreign_keys(table_name):
        if fk.get("name") == fk_name:
            return True
    return False


def upgrade() -> None:
    """Repair missing tools.grpc_service_id FK on SQLite databases.

    This migration:
    1. Only operates on SQLite (PostgreSQL already has correct FK from w7x8y9z0a1b2)
    2. Checks if tools table and grpc_service_id column exist
    3. Checks if FK already exists (idempotent)
    4. Uses batch_alter_table to rebuild the table with the FK constraint
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    # Only operate on SQLite databases
    if bind.dialect.name != "sqlite":
        return

    # Skip if tables don't exist (fresh DB uses db.py models directly)
    if "tools" not in inspector.get_table_names():
        return
    if "grpc_services" not in inspector.get_table_names():
        return

    # Skip if column doesn't exist (shouldn't happen if w7x8y9z0a1b2 was applied)
    columns = {col["name"] for col in inspector.get_columns("tools")}
    if "grpc_service_id" not in columns:
        return

    # Skip if FK already exists (migration already ran or fresh install)
    if _has_foreign_key(inspector, "tools", FK_NAME):
        return

    # Repair: rebuild the tools table with the missing FK constraint
    # SQLite requires batch mode with recreate="always" to add FK to existing table
    with op.batch_alter_table("tools", recreate="always") as batch_op:
        batch_op.create_foreign_key(
            FK_NAME,
            "grpc_services",
            ["grpc_service_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """Remove the repaired FK constraint on SQLite.

    This is defensive: in practice, downgrading past w7x8y9z0a1b2 should use
    that migration's downgrade logic. This handles the case where a database
    has been repaired by this migration and needs to be rolled back.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    # Only operate on SQLite databases
    if bind.dialect.name != "sqlite":
        return

    # Skip if table doesn't exist
    if "tools" not in inspector.get_table_names():
        return

    # Skip if FK doesn't exist
    if not _has_foreign_key(inspector, "tools", FK_NAME):
        return

    # Remove FK constraint (requires table rebuild on SQLite)
    with op.batch_alter_table("tools", recreate="always") as batch_op:
        batch_op.drop_constraint(FK_NAME, type_="foreignkey")
