# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/c8a1b2d3e4f5_add_catalog_stale_to_tools.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Track tools deprecated by catalog reconciliation.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c8a1b2d3e4f5"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "c7e91a2b4d60"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the internal catalog-stale marker to tools."""
    op.add_column("tools", sa.Column("catalog_stale", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    """Remove the internal catalog-stale marker from tools."""
    op.drop_column("tools", "catalog_stale")
