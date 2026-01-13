"""Create index on user name

Revision ID: c96c11c111b4
Revises: 77243f5bfce5
Create Date: 2026-01-13 19:23:33.138318

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c96c11c111b4'
down_revision: Union[str, Sequence[str], None] = '77243f5bfce5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create index on email_users.full_name to speed up search queries
    op.create_index(
        'ix_email_users_full_name',
        'email_users',
        ['full_name'],
        unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index on email_users.full_name
    op.drop_index('ix_email_users_full_name', table_name='email_users')
