# -*- coding: utf-8 -*-
"""Add password_changed_at field to EmailUser

Revision ID: t4d5e6f7g8h9
Revises: c96c11c111b4
Create Date: 2026-01-14

This migration adds a password_changed_at timestamp column to the email_users
table to track when passwords were last changed. This supports password expiry
enforcement based on password_max_age_days configuration.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "t4d5e6f7g8h9"
down_revision: Union[str, Sequence[str], None] = "c96c11c111b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column already exists.

    Args:
        table_name: Name of the table to check
        column_name: Name of the column to look for

    Returns:
        True if the column exists, False otherwise
    """
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        columns = inspector.get_columns(table_name)
        return any(col["name"] == column_name for col in columns)
    except Exception:
        return False


def upgrade() -> None:
    """Add password_changed_at field to email_users table and backfill existing users."""
    if not _column_exists("email_users", "password_changed_at"):
        op.add_column(
            "email_users",
            sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        )

    # Backfill existing users: set password_changed_at = created_at for rows where it's NULL
    # This ensures existing users are subject to password expiry enforcement
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE email_users SET password_changed_at = created_at WHERE password_changed_at IS NULL"))


def downgrade() -> None:
    """Remove password_changed_at field from email_users table."""
    if _column_exists("email_users", "password_changed_at"):
        op.drop_column("email_users", "password_changed_at")
