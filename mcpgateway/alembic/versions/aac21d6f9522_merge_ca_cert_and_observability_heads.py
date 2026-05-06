# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/aac21d6f9522_merge_ca_cert_and_observability_heads.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

merge ca cert and observability heads

Revision ID: aac21d6f9522
Revises: f9101f3b00e3, j4d5e6f7g8h9
Create Date: 2025-11-08 21:43:56.381588
"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "aac21d6f9522"
down_revision: Union[str, Sequence[str], None] = ("f9101f3b00e3", "j4d5e6f7g8h9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
