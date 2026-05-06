"""merge plugin_bindings and token_revocation heads

Revision ID: 9c45d2e63bc0
Revises: 4842b831d24e, aa1b2c3d4e5f
Create Date: 2026-05-01 00:35:39.894249

"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "9c45d2e63bc0"
down_revision: Union[str, Sequence[str], None] = ("4842b831d24e", "aa1b2c3d4e5f")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
