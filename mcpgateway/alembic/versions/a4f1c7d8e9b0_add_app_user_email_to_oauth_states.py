# -*- coding: utf-8 -*-
"""Add app_user_email column to oauth_states.

Revision ID: a4f1c7d8e9b0
Revises: 9f5d93ced2b3
Create Date: 2026-02-23 18:35:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a4f1c7d8e9b0"
down_revision: Union[str, Sequence[str], None] = "9f5d93ced2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add app_user_email to oauth_states when missing."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "oauth_states" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("oauth_states")}
    if "app_user_email" in columns:
        return

    op.add_column("oauth_states", sa.Column("app_user_email", sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Drop app_user_email from oauth_states when present."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "oauth_states" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("oauth_states")}
    if "app_user_email" not in columns:
        return

    op.drop_column("oauth_states", "app_user_email")
