"""merge_migration_heads

Revision ID: e796bd5e97c2
Revises: 43c07ed25a24, a8f3b2c1d4e5
Create Date: 2026-01-17 10:26:41.805772

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "e796bd5e97c2"
down_revision: Union[str, Sequence[str], None] = ("43c07ed25a24", "a8f3b2c1d4e5")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
