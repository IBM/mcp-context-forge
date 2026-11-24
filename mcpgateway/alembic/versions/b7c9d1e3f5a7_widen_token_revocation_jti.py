#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/b7c9d1e3f5a7_widen_token_revocation_jti.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Widen token revocation JTIs for external identity providers.

Revision ID: b7c9d1e3f5a7
Revises: f2c3d4e5a6b7
Create Date: 2026-11-24 00:00:00.000000
"""

# Standard
from typing import Any, Optional, Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b7c9d1e3f5a7"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "f2c3d4e5a6b7"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jti_column() -> Optional[dict[str, Any]]:
    """Return the reflected JTI column when the revocation table exists.

    Returns:
        The column metadata, or None when the table or column is absent.
    """
    inspector = sa.inspect(op.get_bind())
    if "token_revocations" not in inspector.get_table_names():
        return None
    return next((column for column in inspector.get_columns("token_revocations") if column["name"] == "jti"), None)


def upgrade() -> None:
    """Widen the JTI column to hold external identity provider token IDs."""
    column = _jti_column()
    if column is None:
        return

    current_type = column["type"]
    current_length = getattr(current_type, "length", None)
    if current_length is None or current_length >= 255:
        return

    with op.batch_alter_table("token_revocations") as batch_op:
        batch_op.alter_column("jti", existing_type=current_type, existing_nullable=column["nullable"], type_=sa.String(255))


def downgrade() -> None:
    """Narrow the JTI column only when every stored value fits 36 characters."""
    column = _jti_column()
    if column is None:
        return

    current_type = column["type"]
    current_length = getattr(current_type, "length", None)
    if current_length is not None and current_length <= 36:
        return

    long_jti = op.get_bind().execute(sa.text("SELECT jti FROM token_revocations WHERE length(jti) > 36 LIMIT 1")).scalar_one_or_none()
    if long_jti is not None:
        raise RuntimeError("Cannot downgrade token_revocations.jti: an existing JTI exceeds 36 characters")

    with op.batch_alter_table("token_revocations") as batch_op:
        batch_op.alter_column("jti", existing_type=current_type, existing_nullable=column["nullable"], type_=sa.String(36))
