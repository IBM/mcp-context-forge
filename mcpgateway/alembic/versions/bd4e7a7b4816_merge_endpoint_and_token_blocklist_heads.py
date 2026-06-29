"""merge_endpoint_and_token_blocklist_heads

Revision ID: bd4e7a7b4816
Revises: 93529b1429b4, bb43712cae28
Create Date: 2026-04-29 22:45:40.725259

"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "bd4e7a7b4816"
down_revision: Union[str, Sequence[str], None] = ("93529b1429b4", "bb43712cae28")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
