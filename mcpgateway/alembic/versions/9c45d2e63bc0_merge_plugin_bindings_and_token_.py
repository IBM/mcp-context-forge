# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/9c45d2e63bc0_merge_plugin_bindings_and_token_.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

merge plugin_bindings and token_revocation heads

Revision ID: 9c45d2e63bc0
Revises: aa1b2c3d4e5f
Create Date: 2026-05-01 00:35:39.894249
"""

# Standard
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "9c45d2e63bc0"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "aa1b2c3d4e5f"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
