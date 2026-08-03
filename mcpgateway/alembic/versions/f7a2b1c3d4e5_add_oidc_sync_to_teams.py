# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
"""Add OIDC group sync fields to email_teams

Revision ID: f7a2b1c3d4e5
Revises: 5126ced48fd0
Create Date: 2026-03-17 10:00:00.000000

Add oidc_sync_enabled, oidc_group_id, and oidc_sync_role columns to
email_teams so administrators can link a team to an OIDC group directly
from the Teams admin UI instead of configuring team_mapping on the SSO
provider record.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "f7a2b1c3d4e5"
down_revision: Union[str, Sequence[str], None] = "5126ced48fd0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add OIDC sync columns to email_teams."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if "email_teams" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("email_teams")}

    if "oidc_sync_enabled" not in existing_columns:
        op.add_column("email_teams", sa.Column("oidc_sync_enabled", sa.Boolean(), nullable=False, server_default="0"))

    if "oidc_group_id" not in existing_columns:
        op.add_column("email_teams", sa.Column("oidc_group_id", sa.String(255), nullable=True))

    if "oidc_sync_role" not in existing_columns:
        op.add_column("email_teams", sa.Column("oidc_sync_role", sa.String(50), nullable=False, server_default="member"))


def downgrade() -> None:
    """Remove OIDC sync columns from email_teams."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if "email_teams" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("email_teams")}

    if "oidc_sync_role" in existing_columns:
        op.drop_column("email_teams", "oidc_sync_role")
    if "oidc_group_id" in existing_columns:
        op.drop_column("email_teams", "oidc_group_id")
    if "oidc_sync_enabled" in existing_columns:
        op.drop_column("email_teams", "oidc_sync_enabled")
