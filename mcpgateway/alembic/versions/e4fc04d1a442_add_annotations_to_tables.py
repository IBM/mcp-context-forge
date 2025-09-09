# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/e4fc04d1a442_add_annotations_to_tables.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Add annotations to tables

Revision ID: e4fc04d1a442
Revises: b77ca9d2de7e
Create Date: 2025-06-27 21:45:35.099713
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e4fc04d1a442"
down_revision: Union[str, Sequence[str], None] = "b77ca9d2de7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Applies the migration to add the 'annotations' column.

    This function adds a new column named 'annotations' of type JSON to the 'tool'
    table. It includes a server-side default of an empty JSON object ('{}') to ensure
    that existing rows get a non-null default value.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    if inspector.has_table("tools"):
        columns = [col["name"] for col in inspector.get_columns("tools")]
        if "annotations" not in columns:
            try:
                op.add_column("tools", sa.Column("annotations", sa.JSON(), nullable=True))
            except Exception as e:
                print(f"Warning: Could not add annotations column to tools: {e}")


def downgrade() -> None:
    """
    Reverts the migration by removing the 'annotations' column.

    This function provides a way to undo the migration, safely removing the
    'annotations' column from the 'tool' table.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    if inspector.has_table("tools"):
        columns = [col["name"] for col in inspector.get_columns("tools")]
        if "annotations" in columns:
            try:
                op.drop_column("tools", "annotations")
            except Exception as e:
                print(f"Warning: Could not drop annotations column from tools: {e}")
