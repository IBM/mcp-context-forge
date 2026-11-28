# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/2769fb2d2344_add_access_token_marker_claim_to_sso_providers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add access_token_marker_claim column to sso_providers (issue #7706)

Revision ID: 2769fb2d2344
Revises: b9d2f4a6c8e1
Create Date: 2026-11-28
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "2769fb2d2344"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b9d2f4a6c8e1"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the access_token_marker_claim column to sso_providers."""
    inspector = sa.inspect(op.get_bind())
    if "sso_providers" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("sso_providers")]
    if "access_token_marker_claim" not in columns:
        op.add_column("sso_providers", sa.Column("access_token_marker_claim", sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Drop the access_token_marker_claim column from sso_providers."""
    inspector = sa.inspect(op.get_bind())
    if "sso_providers" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("sso_providers")]
    if "access_token_marker_claim" in columns:
        op.drop_column("sso_providers", "access_token_marker_claim")
