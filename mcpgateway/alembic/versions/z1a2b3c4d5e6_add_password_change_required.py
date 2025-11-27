# -*- coding: utf-8 -*-
"""Add password_change_required field to EmailUser

Revision ID: z1a2b3c4d5e6
Revises: 191a2def08d7
Create Date: 2025-11-21 14:16:30.000000

"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "z1a2b3c4d5e6"
down_revision = "191a2def08d7"
branch_labels = None
depends_on = None


def upgrade():
    """Add password_change_required field to email_users table."""
    op.add_column("email_users", sa.Column("password_change_required", sa.Boolean(), nullable=False, server_default="false"))


def downgrade():
    """Remove password_change_required field from email_users table."""
    op.drop_column("email_users", "password_change_required")
