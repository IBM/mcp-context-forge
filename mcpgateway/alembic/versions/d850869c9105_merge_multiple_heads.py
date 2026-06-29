"""merge multiple heads

Revision ID: d850869c9105
Revises: 0a089912b5f0, 8129322c68e5
Create Date: 2026-06-15 15:59:57.255176

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'd850869c9105'
down_revision: Union[str, Sequence[str], None] = ('0a089912b5f0', '8129322c68e5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
