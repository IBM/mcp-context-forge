# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/e1f2a3b4c5d6_add_grant_source_to_user_roles.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add grant_source to user_roles

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-03-05

Adds a grant_source column to user_roles to track the origin of role
assignments (e.g. 'sso', 'manual', 'bootstrap', 'auto').  This replaces
the previous pattern of using granted_by='sso_system' which violated the
FK constraint on granted_by -> email_users.email.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add grant_source column to user_roles table."""
    inspector = sa.inspect(op.get_bind())

    if "user_roles" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("user_roles")]
    if "grant_source" in columns:
        return

    op.add_column("user_roles", sa.Column("grant_source", sa.String(50), nullable=True))


def downgrade() -> None:
    """Remove grant_source column from user_roles table."""
    inspector = sa.inspect(op.get_bind())

    if "user_roles" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("user_roles")]
    if "grant_source" not in columns:
        return

    op.drop_column("user_roles", "grant_source")
