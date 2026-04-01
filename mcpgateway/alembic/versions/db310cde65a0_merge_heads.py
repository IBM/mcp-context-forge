"""merge heads

Revision ID: db310cde65a0
Revises: 225bde88217e, a2ee97cdc336
Create Date: 2026-04-01 14:36:52.002002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db310cde65a0'
down_revision: Union[str, Sequence[str], None] = ('225bde88217e', 'a2ee97cdc336')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
