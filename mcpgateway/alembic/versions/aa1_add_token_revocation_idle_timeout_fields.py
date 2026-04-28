"""add_token_revocation_idle_timeout_fields

Revision ID: aa1b2c3d4e5f
Revises: z1a2b3c4d5e6
Create Date: 2026-04-21 12:58:00.000000

"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "aa1b2c3d4e5f"  # pragma: allowlist secret
down_revision = "z1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add token_expiry and last_activity fields to token_revocations table for idle timeout tracking."""

    # Check if table exists
    inspector = sa.inspect(op.get_bind())
    if "token_revocations" not in inspector.get_table_names():
        return

    # Check if columns already exist
    columns = [col["name"] for col in inspector.get_columns("token_revocations")]

    if "token_expiry" not in columns:
        op.add_column("token_revocations", sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=True))
        op.create_index("idx_token_revocations_expiry_cleanup", "token_revocations", ["token_expiry"], unique=False)

    if "last_activity" not in columns:
        op.add_column("token_revocations", sa.Column("last_activity", sa.DateTime(timezone=True), nullable=True))

    # Add index on revoked_at if it doesn't exist
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("token_revocations")]
    if "idx_token_revocations_revoked_at" not in existing_indexes:
        op.create_index("idx_token_revocations_revoked_at", "token_revocations", ["revoked_at"], unique=False)


def downgrade() -> None:
    """Remove token_expiry and last_activity fields from token_revocations table."""

    # Check if table exists
    inspector = sa.inspect(op.get_bind())
    if "token_revocations" not in inspector.get_table_names():
        return

    # Drop indexes
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("token_revocations")]

    if "idx_token_revocations_expiry_cleanup" in existing_indexes:
        op.drop_index("idx_token_revocations_expiry_cleanup", table_name="token_revocations")

    if "idx_token_revocations_revoked_at" in existing_indexes:
        op.drop_index("idx_token_revocations_revoked_at", table_name="token_revocations")

    # Drop columns
    columns = [col["name"] for col in inspector.get_columns("token_revocations")]

    if "last_activity" in columns:
        op.drop_column("token_revocations", "last_activity")

    if "token_expiry" in columns:
        op.drop_column("token_revocations", "token_expiry")
