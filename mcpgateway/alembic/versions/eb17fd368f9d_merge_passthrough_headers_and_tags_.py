# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/eb17fd368f9d_merge_passthrough_headers_and_tags_.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

merge passthrough headers and tags support

Revision ID: eb17fd368f9d
Revises: 3b17fdc40a8d, cc7b95fec5d9
Create Date: 2025-08-08 05:31:10.857718
"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "eb17fd368f9d"
down_revision: Union[str, Sequence[str], None] = ("3b17fdc40a8d", "cc7b95fec5d9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
