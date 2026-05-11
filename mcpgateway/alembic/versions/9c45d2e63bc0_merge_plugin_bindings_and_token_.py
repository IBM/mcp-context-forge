"""merge plugin_bindings and token_revocation heads

Revision ID: 9c45d2e63bc0
Revises: 4842b831d24e, c3c3b7f9b014
Create Date: 2026-05-01 00:35:39.894249

"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "9c45d2e63bc0"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = ("4842b831d24e", "c3c3b7f9b014")  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
