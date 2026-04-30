# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/225bde88217e_add_grant_source_to_team_members.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add_grant_source_to_team_members

Revision ID: 225bde88217e
Revises: 615af4ab94b4
Create Date: 2026-03-25 12:51:19.526274
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "225bde88217e"
down_revision: Union[str, Sequence[str], None] = "615af4ab94b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add grant_source column to email_team_members table."""
    inspector = sa.inspect(op.get_bind())

    if "email_team_members" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("email_team_members")]
    if "grant_source" in columns:
        return

    op.add_column("email_team_members", sa.Column("grant_source", sa.String(50), nullable=True))


def downgrade() -> None:
    """Remove grant_source column from email_team_members table."""
    inspector = sa.inspect(op.get_bind())

    if "email_team_members" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("email_team_members")]
    if "grant_source" not in columns:
        return

    op.drop_column("email_team_members", "grant_source")
