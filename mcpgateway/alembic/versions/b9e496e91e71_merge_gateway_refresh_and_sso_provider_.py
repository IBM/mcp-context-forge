# -*- coding: utf-8 -*-
"""Merge gateway_refresh and sso_provider_metadata heads.

Revision ID: b9e496e91e71
Revises: a8f3b2c1d4e5, u5f6g7h8i9j0
Create Date: 2026-01-17
"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "b9e496e91e71"
down_revision: Union[str, Sequence[str], None] = ("a8f3b2c1d4e5", "u5f6g7h8i9j0")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge migration - no schema changes needed."""


def downgrade() -> None:
    """Merge migration - no schema changes needed."""
