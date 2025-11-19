"""empty message

Revision ID: 0a142ad09274
Revises: b4f4ae83c7b6, f3a3a3d901b8
Create Date: 2025-11-18 17:42:33.602124

"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0a142ad09274"
down_revision: Union[str, Sequence[str], None] = ("b4f4ae83c7b6", "f3a3a3d901b8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
