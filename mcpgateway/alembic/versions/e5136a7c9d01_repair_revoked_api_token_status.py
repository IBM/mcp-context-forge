# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/e5136a7c9d01_repair_revoked_api_token_status.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Repair active API-token rows that already have revocation records.

Revision ID: e5136a7c9d01
Revises: d21698ae4a19
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5136a7c9d01"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d21698ae4a19"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Mark previously revoked API tokens inactive."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "email_api_tokens" not in tables or "token_revocations" not in tables:
        return

    email_api_token_columns = {column["name"] for column in inspector.get_columns("email_api_tokens")}
    token_revocation_columns = {column["name"] for column in inspector.get_columns("token_revocations")}
    if not {"jti", "is_active"}.issubset(email_api_token_columns) or "jti" not in token_revocation_columns:
        return

    bind.execute(
        sa.text(
            "UPDATE email_api_tokens SET is_active = false "
            "WHERE is_active = true AND jti IN (SELECT jti FROM token_revocations)"
        )
    )


def downgrade() -> None:
    """Keep revoked tokens inactive because this data repair is not reversible."""
