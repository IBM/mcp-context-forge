# -*- coding: utf-8 -*-
"""Add password_reset_tokens table

Revision ID: w6g7h8i9j0k1
Revises: ba202ac1665f
Create Date: 2026-02-15 12:30:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "w6g7h8i9j0k1"
down_revision: Union[str, Sequence[str], None] = "ba202ac1665f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create password reset tokens table and indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "email_users" not in tables:
        return

    if "password_reset_tokens" not in tables:
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_email", sa.String(length=255), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ip_address", sa.String(length=45), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["user_email"], ["email_users.email"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )

    indexes = {idx["name"] for idx in inspector.get_indexes("password_reset_tokens")}
    if "ix_password_reset_tokens_user_email" not in indexes:
        op.create_index("ix_password_reset_tokens_user_email", "password_reset_tokens", ["user_email"], unique=False)
    if "ix_password_reset_tokens_token_hash" not in indexes:
        op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"], unique=True)
    if "ix_password_reset_tokens_expires_at" not in indexes:
        op.create_index("ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at"], unique=False)


def downgrade() -> None:
    """Drop password reset token storage."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "password_reset_tokens" not in tables:
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("password_reset_tokens")}
    if "ix_password_reset_tokens_expires_at" in indexes:
        op.drop_index("ix_password_reset_tokens_expires_at", table_name="password_reset_tokens")
    if "ix_password_reset_tokens_token_hash" in indexes:
        op.drop_index("ix_password_reset_tokens_token_hash", table_name="password_reset_tokens")
    if "ix_password_reset_tokens_user_email" in indexes:
        op.drop_index("ix_password_reset_tokens_user_email", table_name="password_reset_tokens")

    op.drop_table("password_reset_tokens")
