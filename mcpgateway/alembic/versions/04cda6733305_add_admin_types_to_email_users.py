"""Add admin types to email_users

Revision ID: 04cda6733305
Revises: b1b2b3b4b5b6
Create Date: 2026-02-03 09:27:35.836551

Add admin_origin column to track how admin status was granted:
- "sso": Granted via SSO group sync (can be demoted on login)
- "manual": Granted via Admin UI (never auto-demoted)
- "api": Granted via API (never auto-demoted)
- None: Legacy state (treated as manual, never auto-demoted)

This enables proper bidirectional sync for SSO-granted admins while
preserving manual grants from being auto-revoked.

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "04cda6733305"
down_revision: Union[str, Sequence[str], None] = "b1b2b3b4b5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add admin_origin column."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check if table exists
    if "email_users" not in inspector.get_table_names():
        return

    # Check if column already exists
    columns = [col["name"] for col in inspector.get_columns("email_users")]
    if "admin_origin" in columns:
        return

    op.add_column("email_users", sa.Column("admin_origin", sa.String(20), nullable=True))


def downgrade() -> None:
    """Downgrade schema - remove admin_origin column."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check if table exists
    if "email_users" not in inspector.get_table_names():
        return

    # Check if column exists
    columns = [col["name"] for col in inspector.get_columns("email_users")]
    if "admin_origin" not in columns:
        return

    op.drop_column("email_users", "admin_origin")
