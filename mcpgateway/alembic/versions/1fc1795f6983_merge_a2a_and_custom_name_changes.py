"""merge_a2a_and_custom_name_changes

Revision ID: 1fc1795f6983
Revises: add_a2a_agents_and_metrics, c9dd86c0aac9
Create Date: 2025-08-20 19:04:40.589538

"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "1fc1795f6983"
down_revision: Union[str, Sequence[str], None] = ("add_a2a_agents_and_metrics", "c9dd86c0aac9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
