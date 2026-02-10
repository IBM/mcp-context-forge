"""merge main and policy engine phase1

Revision ID: ea9fc597042e
Revises: 04cda6733305, policy_engine_phase1
Create Date: 2026-02-10 16:45:07.519489

"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "ea9fc597042e"
down_revision: Union[str, Sequence[str], None] = ("04cda6733305", "policy_engine_phase1")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
