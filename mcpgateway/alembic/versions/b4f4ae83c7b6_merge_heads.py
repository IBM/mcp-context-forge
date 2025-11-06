"""merge heads

Revision ID: b4f4ae83c7b6
Revises: 3c89a45f32e5, add_toolops_test_cases_table
Create Date: 2025-11-06 19:19:25.161135

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4f4ae83c7b6'
down_revision: Union[str, Sequence[str], None] = ('3c89a45f32e5', 'add_toolops_test_cases_table')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
