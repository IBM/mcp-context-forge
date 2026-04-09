"""add http_auth_sessions table for enhanced session management

Revision ID: a1b2c3d4e5f6
Revises: 225bde88217e
Create Date: 2026-04-02 10:25:00.000000

Issue #541: Enhanced session management for admin UI
Adds http_auth_sessions table to track HTTP authentication sessions
with enhanced security features including timeouts, client binding,
and audit trails.
"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "cbedf4e580e0"  # Verified via 'alembic heads' - current head before this migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create http_auth_sessions table."""
    # Check if table already exists (idempotent migration)
    inspector = sa.inspect(op.get_bind())
    if "http_auth_sessions" in inspector.get_table_names():
        return

    op.create_table(
        "http_auth_sessions",
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("user_email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("device_info", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["email_users.email"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )

    # Create indexes for efficient queries
    op.create_index("idx_http_auth_sessions_user_activity", "http_auth_sessions", ["user_id", "last_activity"], unique=False)
    op.create_index(op.f("ix_http_auth_sessions_user_id"), "http_auth_sessions", ["user_id"], unique=False)
    op.create_index(op.f("ix_http_auth_sessions_user_email"), "http_auth_sessions", ["user_email"], unique=False)
    op.create_index(op.f("ix_http_auth_sessions_last_activity"), "http_auth_sessions", ["last_activity"], unique=False)


def downgrade() -> None:
    """Drop http_auth_sessions table."""
    # Check if table exists before dropping (idempotent migration)
    inspector = sa.inspect(op.get_bind())
    if "http_auth_sessions" not in inspector.get_table_names():
        return

    op.drop_index(op.f("ix_http_auth_sessions_last_activity"), table_name="http_auth_sessions")
    op.drop_index(op.f("ix_http_auth_sessions_user_email"), table_name="http_auth_sessions")
    op.drop_index(op.f("ix_http_auth_sessions_user_id"), table_name="http_auth_sessions")
    op.drop_index("idx_http_auth_sessions_user_activity", table_name="http_auth_sessions")
    op.drop_table("http_auth_sessions")
