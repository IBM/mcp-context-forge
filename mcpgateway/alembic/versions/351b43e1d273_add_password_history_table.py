"""add_password_history_table

Revision ID: 351b43e1d273
Revises: w7x8y9z0a1b2
Create Date: 2026-04-23 12:25:15.946938

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "351b43e1d273"
down_revision: Union[str, Sequence[str], None] = "w7x8y9z0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create password_history table for tracking password reuse."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # Skip if email_users table doesn't exist (fresh DB uses db.py models directly)
    if "email_users" not in tables:
        return

    # Skip if password_history table already exists
    if "password_history" in tables:
        return

    # Create password_history table
    op.create_table(
        "password_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_email"], ["email_users.email"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes
    indexes = {idx["name"] for idx in inspector.get_indexes("password_history")} if "password_history" in inspector.get_table_names() else set()

    if "ix_password_history_user_email" not in indexes:
        op.create_index("ix_password_history_user_email", "password_history", ["user_email"], unique=False)

    if "ix_password_history_user_email_changed_at" not in indexes:
        op.create_index("ix_password_history_user_email_changed_at", "password_history", ["user_email", "changed_at"], unique=False)


def downgrade() -> None:
    """Drop password_history table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "password_history" not in tables:
        return

    # Drop indexes first
    indexes = {idx["name"] for idx in inspector.get_indexes("password_history")}

    if "ix_password_history_user_email_changed_at" in indexes:
        op.drop_index("ix_password_history_user_email_changed_at", table_name="password_history")

    if "ix_password_history_user_email" in indexes:
        op.drop_index("ix_password_history_user_email", table_name="password_history")

    # Drop table
    op.drop_table("password_history")
