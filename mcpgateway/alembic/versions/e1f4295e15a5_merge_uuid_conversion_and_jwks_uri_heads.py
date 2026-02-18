"""merge_uuid_conversion_and_jwks_uri_heads

Revision ID: e1f4295e15a5
Revises: 71e35d2065b6, x7h8i9j0k1l2
Create Date: 2026-02-18 15:55:17.190512

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f4295e15a5'
down_revision: Union[str, Sequence[str], None] = ('71e35d2065b6', 'x7h8i9j0k1l2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
