# -*- coding: utf-8 -*-
"""add api token auth columns to sso_providers (issue #3567)

Revision ID: e198602c3c1e
Revises: 0a089912b5f0
Create Date: 2026-06-11

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e198602c3c1e"
down_revision: Union[str, Sequence[str], None] = "0a089912b5f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "sso_providers" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("sso_providers")]
    if "trusted_for_api_auth" not in columns:
        op.add_column("sso_providers", sa.Column("trusted_for_api_auth", sa.Boolean(), nullable=True, server_default=sa.false()))
    if "api_audience" not in columns:
        op.add_column("sso_providers", sa.Column("api_audience", sa.String(length=500), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "sso_providers" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("sso_providers")]
    if "api_audience" in columns:
        op.drop_column("sso_providers", "api_audience")
    if "trusted_for_api_auth" in columns:
        op.drop_column("sso_providers", "trusted_for_api_auth")
