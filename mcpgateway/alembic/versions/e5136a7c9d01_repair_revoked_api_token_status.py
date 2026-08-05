# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/e5136a7c9d01_repair_revoked_api_token_status.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Repair active API-token rows that already have revocation records.

Revision ID: e5136a7c9d01
Revises: e4f5a6b7c8d9
Create Date: 2026-07-27
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "e5136a7c9d01"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d9"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _repair_statement() -> sa.Update:
    """Build a database-portable update for revoked API-token rows."""
    email_api_tokens = sa.table(
        "email_api_tokens",
        sa.column("jti", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    token_revocations = sa.table(
        "token_revocations",
        sa.column("jti", sa.String()),
    )

    return (
        sa.update(email_api_tokens)
        .where(email_api_tokens.c.is_active.is_(sa.true()))
        .where(email_api_tokens.c.jti.in_(sa.select(token_revocations.c.jti)))
        .values(is_active=sa.false())
    )


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

    bind.execute(_repair_statement())


def downgrade() -> None:
    """Keep revoked tokens inactive because this data repair is not reversible."""
    pass  # Data repair is intentionally irreversible: revoked tokens must remain inactive.
