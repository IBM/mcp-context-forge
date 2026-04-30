# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/a7f3c9e1b2d4_add_title_to_tools_resources_prompts.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Add title column to tools, resources, and prompts

Revision ID: a7f3c9e1b2d4
Revises: 225bde88217e
Create Date: 2026-02-23 11:20:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a7f3c9e1b2d4"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "225bde88217e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add title column to tools, resources, and prompts tables."""
    inspector = sa.inspect(op.get_bind())

    for table_name in ("tools", "resources", "prompts"):
        if table_name not in inspector.get_table_names():
            continue
        columns = [col["name"] for col in inspector.get_columns(table_name)]
        if "title" not in columns:
            op.add_column(table_name, sa.Column("title", sa.String(255), nullable=True))


def downgrade() -> None:
    """Remove title column from tools, resources, and prompts tables."""
    inspector = sa.inspect(op.get_bind())

    for table_name in ("tools", "resources", "prompts"):
        if table_name not in inspector.get_table_names():
            continue
        columns = [col["name"] for col in inspector.get_columns(table_name)]
        if "title" in columns:
            op.drop_column(table_name, "title")
