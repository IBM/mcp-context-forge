# -*- coding: utf-8 -*-
"""resource_rename_template_to_uri_template

Revision ID: 191a2def08d7
Revises: f3a3a3d901b8
Create Date: 2025-11-17 21:20:05.223248
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "191a2def08d7"
down_revision: Union[str, Sequence[str], None] = "f3a3a3d901b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    columns = [c["name"] for c in inspector.get_columns("resources")]

    # Only rename if old column exists
    if "template" in columns and "uri_template" not in columns:
        with op.batch_alter_table("resources") as batch_op:
            batch_op.alter_column("template", new_column_name="uri_template")


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    columns = [c["name"] for c in inspector.get_columns("resources")]

    # Only rename back if current column exists
    if "uri_template" in columns and "template" not in columns:
        with op.batch_alter_table("resources") as batch_op:
            batch_op.alter_column("uri_template", new_column_name="template")
