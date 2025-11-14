"""Add password expiration fields to EmailUser

Revision ID: f1822fcc2ca2
Revises: aac21d6f9522
Create Date: 2025-11-12 17:12:47.420982

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f1822fcc2ca2"
down_revision: Union[str, Sequence[str], None] = "aac21d6f9522"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add password expiration fields to email_users table
    try:
        op.add_column("email_users", sa.Column("password_expires_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column("email_users", sa.Column("password_change_required", sa.Boolean(), nullable=False, default=False))
    except Exception as e:
        print(f"Migration skipped (table may already have columns or not exist): {e}")


def downgrade() -> None:
    """Downgrade schema."""
    # Remove password expiration fields from email_users table
    try:
        op.drop_column("email_users", "password_change_required")
        op.drop_column("email_users", "password_expires_at")
    except Exception as e:
        print(f"Downgrade skipped (columns may not exist): {e}")
