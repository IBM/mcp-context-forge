"""add_numeric_id_to_email_users

Revision ID: 0a089912b5f0
Revises: e28566875fa4
Create Date: 2026-05-25 16:28:22.159471

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision: str = "0a089912b5f0"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e28566875fa4"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add numeric id column to email_users table for Phase 1 token migration.

    This enables future migration from email-based to user-ID-based JWT tokens
    while maintaining backward compatibility with email as primary key.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "email_users" not in inspector.get_table_names():
        return

    # Skip if column already exists
    columns = [col["name"] for col in inspector.get_columns("email_users")]
    if "id" in columns:
        return

    # Add id column as nullable first (for existing rows)
    op.add_column("email_users", sa.Column("id", sa.Integer(), nullable=True))

    # Populate id for existing users with sequential values
    # Use a window function to assign sequential IDs based on created_at
    if bind.dialect.name == "postgresql":
        bind.execute(
            text(
                "UPDATE email_users SET id = subquery.row_num "
                "FROM (SELECT email, ROW_NUMBER() OVER (ORDER BY created_at, email) as row_num FROM email_users) AS subquery "
                "WHERE email_users.email = subquery.email"
            )
        )
    elif bind.dialect.name == "sqlite":
        bind.execute(text("""
            UPDATE email_users
            SET id = (
                SELECT COUNT(*)
                FROM email_users AS e2
                WHERE e2.created_at < email_users.created_at
                   OR (
                       e2.created_at = email_users.created_at
                       AND e2.email <= email_users.email
                   )
            )
        """))

    # Make column non-nullable (SQLite requires batch mode)
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("email_users", recreate="always") as batch_op:
            batch_op.alter_column(
                "id",
                existing_type=sa.Integer(),
                nullable=False,
            )
            batch_op.create_unique_constraint(
                "uq_email_users_id",
                ["id"],
            )
    else:
        op.alter_column(
            "email_users",
            "id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        op.create_unique_constraint(
            "uq_email_users_id",
            "email_users",
            ["id"],
        )


def downgrade() -> None:
    """Remove numeric id column from email_users table."""
    bind = op.get_bind()
    inspector = inspect(bind)

    # Skip if table doesn't exist
    if "email_users" not in inspector.get_table_names():
        return

    # Skip if column doesn't exist
    columns = [col["name"] for col in inspector.get_columns("email_users")]
    if "id" not in columns:
        return

    if bind.dialect.name == "postgresql":
        op.drop_constraint("uq_email_users_id", "email_users", type_="unique")
        op.drop_column("email_users", "id")

    elif bind.dialect.name == "sqlite":
        with op.batch_alter_table("email_users", recreate="always") as batch_op:
            batch_op.drop_column("id")