# -*- coding: utf-8 -*-
"""Add jwks_uri column to sso_providers

Revision ID: x7h8i9j0k1l2
Revises: w6g7h8i9j0k1
Create Date: 2026-02-18 10:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "x7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "w6g7h8i9j0k1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add jwks_uri column to sso_providers table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "sso_providers" not in tables:
        return

    columns = [col["name"] for col in inspector.get_columns("sso_providers")]
    if "jwks_uri" in columns:
        return

    op.add_column("sso_providers", sa.Column("jwks_uri", sa.String(500), nullable=True))


def downgrade() -> None:
    """Remove jwks_uri column from sso_providers table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "sso_providers" not in tables:
        return

    columns = [col["name"] for col in inspector.get_columns("sso_providers")]
    if "jwks_uri" not in columns:
        return

    op.drop_column("sso_providers", "jwks_uri")
