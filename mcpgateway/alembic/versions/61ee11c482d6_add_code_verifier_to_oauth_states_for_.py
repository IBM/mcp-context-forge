# -*- coding: utf-8 -*-
"""Add code_verifier to oauth_states for PKCE support

Revision ID: 61ee11c482d6
Revises: 0f81d4a5efe0
Create Date: 2025-09-30 15:45:43.895080

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "61ee11c482d6"
down_revision: Union[str, Sequence[str], None] = "0f81d4a5efe0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Check if oauth_states table exists before adding column
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "oauth_states" not in inspector.get_table_names():
        print("oauth_states table not found. Skipping PKCE code_verifier migration.")
        return

    # Add code_verifier column to oauth_states for PKCE support (RFC 7636)
    op.add_column("oauth_states", sa.Column("code_verifier", sa.String(128), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Check if oauth_states table exists before dropping column
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "oauth_states" not in inspector.get_table_names():
        print("oauth_states table not found. Skipping PKCE code_verifier downgrade.")
        return

    # Remove code_verifier column from oauth_states
    op.drop_column("oauth_states", "code_verifier")
