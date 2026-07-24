# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/c9f8e7d6a4b3_add_learned_aud_and_iss_to_oauth_tokens.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add_learned_aud_and_iss_to_oauth_tokens

Per-user OAuth learned audience and issuer, replacing the earlier design that
persisted the callback-learned aud on gateway.oauth_config.resource. The
per-user storage prevents (a) cross-tenant DoS when a single gateway serves
multiple IdP tenants with per-tenant aud values, and (b) users without
gateways.update mutating shared gateway config via the OAuth callback path.

Revision ID: c9f8e7d6a4b3
Revises: d21698ae4a19
Create Date: 2026-07-15 11:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c9f8e7d6a4b3"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d21698ae4a19"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add learned_aud (JSON) and learned_iss (String) to oauth_tokens.

    Both columns are nullable; existing rows are left with NULL and the
    validator falls back to gateway.oauth_config.resource / origin as before.
    New rows populated by TokenStorageService.store_tokens carry the
    per-user learned aud/iss.
    """
    inspector = sa.inspect(op.get_bind())

    if "oauth_tokens" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("oauth_tokens")}

    if "learned_aud" not in columns:
        op.add_column("oauth_tokens", sa.Column("learned_aud", sa.JSON(), nullable=True))

    if "learned_iss" not in columns:
        op.add_column("oauth_tokens", sa.Column("learned_iss", sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Drop the per-user learned_aud and learned_iss columns from oauth_tokens.

    This is a **schema rollback only**. It removes the columns but does not
    restore the pre-redesign callback-driven writes to
    ``gateway.oauth_config.resource`` (that code was removed from
    ``mcpgateway/routers/oauth_router.py`` in the same PR that added these
    columns). To fully revert learned-audience behavior to the pre-redesign
    model, roll back the application image as well as run this downgrade.

    Any per-user learned values in the dropped columns are lost. After a full
    rollback (schema + code), those values will re-populate on each user's
    next OAuth flow via the restored callback path.
    """
    inspector = sa.inspect(op.get_bind())

    if "oauth_tokens" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("oauth_tokens")}
    bind = op.get_bind()
    dialect_name = bind.dialect.name.lower()

    if dialect_name == "sqlite":
        with op.batch_alter_table("oauth_tokens") as batch_op:
            if "learned_iss" in columns:
                batch_op.drop_column("learned_iss")
            if "learned_aud" in columns:
                batch_op.drop_column("learned_aud")
    else:
        if "learned_iss" in columns:
            op.drop_column("oauth_tokens", "learned_iss")
        if "learned_aud" in columns:
            op.drop_column("oauth_tokens", "learned_aud")
