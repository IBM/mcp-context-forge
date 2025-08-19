# -*- coding: utf-8 -*-
"""add oauth config to gateways

Revision ID: f8c9d3e2a1b4
Revises: eb17fd368f9d
Create Date: 2024-12-20 10:00:00.000000

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f8c9d3e2a1b4"
down_revision: Union[str, Sequence[str], None] = "34492f99a0c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add oauth_config column to gateways table."""
    # Check if we're dealing with a fresh database
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if "gateways" not in tables:
        print("Fresh database detected. Skipping migration.")
        return

    # Add oauth_config column
    with op.batch_alter_table("gateways", schema=None) as batch_op:
        batch_op.add_column(sa.Column("oauth_config", sa.JSON(), nullable=True, comment="OAuth 2.0 configuration including grant_type, client_id, encrypted client_secret, URLs, and scopes"))

    print("Successfully added oauth_config column to gateways table.")


def downgrade() -> None:
    """Remove oauth_config column from gateways table."""
    # Check if we're dealing with a fresh database
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if "gateways" not in tables:
        print("Fresh database detected. Skipping migration.")
        return

    # Remove oauth_config column
    with op.batch_alter_table("gateways", schema=None) as batch_op:
        batch_op.drop_column("oauth_config")

    print("Successfully removed oauth_config column from gateways table.")
