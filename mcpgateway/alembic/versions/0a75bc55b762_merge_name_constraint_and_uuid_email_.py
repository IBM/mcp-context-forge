"""merge_name_constraint_and_uuid_email_heads

Revision ID: 0a75bc55b762
Revises: 0a089912b5f0, 279184dfd71d
Create Date: 2026-06-09 17:58:27.933008

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a75bc55b762'
down_revision: Union[str, Sequence[str], None] = ('0a089912b5f0', '279184dfd71d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
