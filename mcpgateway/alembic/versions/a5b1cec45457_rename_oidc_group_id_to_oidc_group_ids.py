# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
"""Rename oidc_group_id to oidc_group_ids (JSON list)

Revision ID: a5b1cec45457
Revises: f7a2b1c3d4e5
Create Date: 2026-04-15 12:00:00.000000

Migrate the single ``oidc_group_id`` (String) column to ``oidc_group_ids``
(JSON list) so that multiple OIDC groups can be linked to a single team.
Existing single-value data is migrated into a one-element JSON array.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision: str = "a5b1cec45457"
down_revision: Union[str, Sequence[str], None] = "f7a2b1c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace oidc_group_id (String) with oidc_group_ids (JSON list)."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if "email_teams" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("email_teams")}

    if "oidc_group_ids" in existing_columns:
        # Already migrated (fresh DB or re-run)
        if "oidc_group_id" in existing_columns:
            op.drop_column("email_teams", "oidc_group_id")
        return

    # Add the new JSON column
    op.add_column("email_teams", sa.Column("oidc_group_ids", sa.JSON(), nullable=True))

    # Migrate existing data: wrap single value in a JSON array
    if "oidc_group_id" in existing_columns:
        dialect = conn.dialect.name
        if dialect == "postgresql":
            op.execute(
                text(
                    "UPDATE email_teams SET oidc_group_ids = jsonb_build_array(oidc_group_id) "
                    "WHERE oidc_group_id IS NOT NULL AND oidc_group_id != ''"
                )
            )
        else:
            # SQLite fallback
            op.execute(
                text(
                    "UPDATE email_teams SET oidc_group_ids = json_array(oidc_group_id) "
                    "WHERE oidc_group_id IS NOT NULL AND oidc_group_id != ''"
                )
            )
        op.drop_column("email_teams", "oidc_group_id")


def downgrade() -> None:
    """Revert oidc_group_ids (JSON) back to oidc_group_id (String)."""
    conn = op.get_bind()
    inspector = inspect(conn)

    if "email_teams" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("email_teams")}

    if "oidc_group_id" in existing_columns:
        if "oidc_group_ids" in existing_columns:
            op.drop_column("email_teams", "oidc_group_ids")
        return

    # Add the old String column back
    op.add_column("email_teams", sa.Column("oidc_group_id", sa.String(255), nullable=True))

    # Migrate data: take the first element of the JSON array
    if "oidc_group_ids" in existing_columns:
        dialect = conn.dialect.name
        if dialect == "postgresql":
            op.execute(
                text(
                    "UPDATE email_teams SET oidc_group_id = oidc_group_ids->>0 "
                    "WHERE oidc_group_ids IS NOT NULL"
                )
            )
        else:
            op.execute(
                text(
                    "UPDATE email_teams SET oidc_group_id = json_extract(oidc_group_ids, '$[0]') "
                    "WHERE oidc_group_ids IS NOT NULL"
                )
            )
        op.drop_column("email_teams", "oidc_group_ids")
