# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/b3e9f1a7c2d5_drop_stale_oauth_tokens_unique_gateway_user.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

drop stale unique_gateway_user constraint on oauth_tokens (issue #5538)

Revision ID: b3e9f1a7c2d5
Revises: e198602c3c1e
Create Date: 2026-07-09
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "b3e9f1a7c2d5"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e198602c3c1e"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the stale unique_gateway_user (gateway_id, user_id) constraint on oauth_tokens.

    Per-user token scope is enforced by uq_oauth_gateway_user (gateway_id,
    app_user_email). The older gateway_id + user_id constraint predates the
    app_user_email column and blocks a second user from authorizing the same
    gateway, because user_id holds the shared OAuth client_id (issue #5538).
    """
    inspector = sa.inspect(op.get_bind())
    if "oauth_tokens" not in inspector.get_table_names():
        return
    constraint_names = {uc["name"] for uc in inspector.get_unique_constraints("oauth_tokens")}
    if "unique_gateway_user" in constraint_names:
        with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
            batch_op.drop_constraint("unique_gateway_user", type_="unique")


def downgrade() -> None:
    """Restore the unique_gateway_user (gateway_id, user_id) constraint on oauth_tokens."""
    inspector = sa.inspect(op.get_bind())
    if "oauth_tokens" not in inspector.get_table_names():
        return
    constraint_names = {uc["name"] for uc in inspector.get_unique_constraints("oauth_tokens")}
    if "unique_gateway_user" not in constraint_names:
        with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
            batch_op.create_unique_constraint("unique_gateway_user", ["gateway_id", "user_id"])
