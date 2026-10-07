# -*- coding: utf-8 -*-
"""Add gateway per-user credential policy.

Revision ID: 8f6b2c4d9a10
Revises: c7e91a2b4d60
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "8f6b2c4d9a10"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "c7e91a2b4d60"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the opt-in per-user credential policy."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("gateways"):
        return
    columns = {column["name"] for column in inspector.get_columns("gateways")}
    if "requires_user_credentials" in columns:
        return

    op.add_column("gateways", sa.Column("requires_user_credentials", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Remove the gateway per-user credential policy."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("gateways"):
        return
    columns = {column["name"] for column in inspector.get_columns("gateways")}
    if "requires_user_credentials" not in columns:
        return
    with op.batch_alter_table("gateways") as batch:
        batch.drop_column("requires_user_credentials")
