"""merge meta_server_fields and tool_embedding heads

Revision ID: merge_two_heads
Revises: 5126ced48fd0, bab4694b3e90
Create Date: 2026-02-13

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "merge_two_heads"
down_revision: Union[str, Sequence[str], None] = ("5126ced48fd0", "bab4694b3e90")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
