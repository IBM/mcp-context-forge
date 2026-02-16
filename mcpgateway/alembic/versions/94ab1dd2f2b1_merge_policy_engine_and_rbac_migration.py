"""merge policy engine and rbac migration

Revision ID: 94ab1dd2f2b1
Revises: ea9fc597042e, v1a2b3c4d5e6
Create Date: 2026-02-10 19:42:34.680264
"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "94ab1dd2f2b1"
down_revision: Union[str, Sequence[str], None] = ("ea9fc597042e", "v1a2b3c4d5e6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
