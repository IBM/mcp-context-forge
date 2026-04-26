"""merge token_blocklist (PR #4371) with audit-identity main head

Revision ID: bb43712cae28
Revises: cae28b15a507, b2c3d4e5f6g7
Create Date: 2026-04-26 16:30:00.000000

Resolves the dual-head condition introduced when PR #4371 (#4317) was rebased
onto a main branch that had advanced past d2b501bf4262 (the head referenced by
cae28b15a507_merge_token_revocation_and_uaid_heads.py). After this migration
`alembic heads` returns a single head again.
"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "bb43712cae28"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = ("cae28b15a507", "b2c3d4e5f6g7")  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
