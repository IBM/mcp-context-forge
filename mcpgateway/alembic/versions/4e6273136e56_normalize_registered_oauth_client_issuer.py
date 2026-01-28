# -*- coding: utf-8 -*-
"""normalize_registered_oauth_client_issuer

Revision ID: 4e6273136e56
Revises: f1a2b3c4d5e6
Create Date: 2026-01-25 01:32:38.987891

This migration normalizes the `issuer` column in `registered_oauth_clients` table
by stripping trailing slashes. This ensures consistent lookup and prevents duplicate
registrations when the MCP SDK adds trailing slashes via Pydantic's AnyHttpUrl.

See: https://github.com/modelcontextprotocol/python-sdk/issues/1919
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4e6273136e56"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Normalize issuer URLs by stripping trailing slashes.

    This is idempotent - running multiple times has no effect on already-normalized values.
    Works with both SQLite and PostgreSQL.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if table doesn't exist (fresh DB uses models.py directly)
    if "registered_oauth_clients" not in inspector.get_table_names():
        return

    # Use raw SQL for cross-database compatibility
    # SQLite and PostgreSQL both support RTRIM for removing trailing characters
    # We use CASE to only update rows that actually have trailing slashes
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # PostgreSQL: Use RTRIM to remove trailing slashes
        op.execute(
            sa.text(
                """
                UPDATE registered_oauth_clients
                SET issuer = RTRIM(issuer, '/')
                WHERE issuer LIKE '%/'
                """
            )
        )
    else:
        # SQLite: RTRIM works the same way
        op.execute(
            sa.text(
                """
                UPDATE registered_oauth_clients
                SET issuer = RTRIM(issuer, '/')
                WHERE issuer LIKE '%/'
                """
            )
        )


def downgrade() -> None:
    """Downgrade is a no-op.

    We cannot restore trailing slashes since we don't know which rows originally had them.
    The normalized form is canonical and safe to keep.
    """
