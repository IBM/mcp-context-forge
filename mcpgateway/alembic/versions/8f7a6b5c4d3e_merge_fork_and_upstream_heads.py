# -*- coding: utf-8 -*-
"""Merge the fork and upstream migration heads.

Revision ID: 8f7a6b5c4d3e
Revises: 12d4a0c7789c, s1a2b3c4d5e6
Create Date: 2026-09-02 00:00:00.000000

Empty merge revision joining the upstream 1.0.9 head (12d4a0c7789c) with the
fork intranet head (s1a2b3c4d5e6) so the upgrade graph has a single head.
"""

from typing import Sequence, Union

revision: str = "8f7a6b5c4d3e"
down_revision: Union[str, Sequence[str], None] = ("12d4a0c7789c", "s1a2b3c4d5e6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op merge upgrade."""
    pass


def downgrade() -> None:
    """No-op merge downgrade."""
    pass
