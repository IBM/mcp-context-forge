# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/b8d4e1f0c2a3_add_gateway_refresh_mode.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add refresh_mode to the gateways table.

Per-gateway auto-refresh mode (off, auto, or quarantine). NULL uses the
global AUTO_REFRESH_SERVERS setting. quarantine still refreshes; holding
material catalog changes for approval is tracked in issue #7021.

Revision ID: b8d4e1f0c2a3
Revises: a7c3e9d1b5f2
Create Date: 2026-11-19
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b8d4e1f0c2a3"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a7c3e9d1b5f2"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check whether a column exists in a given database table.

    Args:
        table_name: Name of the database table to inspect.
        column_name: Name of the column to check for existence.

    Returns:
        True if the column exists in the table, False otherwise.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    columns = inspector.get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def _table_exists(table_name: str) -> bool:
    """Check whether a table exists in the current database.

    Args:
        table_name: Name of the database table to check.

    Returns:
        True if the table exists, False otherwise.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Add refresh_mode to the gateways table if it is missing.

    The column is added only if it does not already exist, so the migration
    can be re-run or applied to a partially migrated schema.
    """
    if not _table_exists("gateways"):
        return

    if not _column_exists("gateways", "refresh_mode"):
        op.add_column(
            "gateways",
            sa.Column(
                "refresh_mode",
                sa.String(length=16),
                nullable=True,
                comment="Per-gateway auto-refresh mode: off, auto, or quarantine; NULL uses AUTO_REFRESH_SERVERS",
            ),
        )


def downgrade() -> None:
    """Remove refresh_mode from the gateways table if present."""
    if not _table_exists("gateways"):
        return

    if _column_exists("gateways", "refresh_mode"):
        op.drop_column("gateways", "refresh_mode")
