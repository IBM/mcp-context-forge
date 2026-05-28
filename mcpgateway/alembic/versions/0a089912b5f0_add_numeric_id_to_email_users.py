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

    # Add id column as nullable first (for existing rows).
    # For PostgreSQL, create a named sequence so that new INSERTs without an
    # explicit id auto-generate a value (avoids NotNullViolation on bootstrap).
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS email_users_id_seq"))
        op.add_column(
            "email_users",
            sa.Column(
                "id",
                sa.Integer(),
                server_default=sa.text("nextval('email_users_id_seq')"),
                nullable=True,
            ),
        )
    else:
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
        # Advance the sequence past any IDs assigned by the backfill above so
        # future auto-generated values don't collide with existing rows.
        bind.execute(text("SELECT setval('email_users_id_seq', " "COALESCE((SELECT MAX(id) FROM email_users), 0) + 1, false)"))
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

    # Promote id to primary key and demote email to unique (SQLite requires batch mode)
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("email_users", recreate="always") as batch_op:
            batch_op.alter_column(
                "id",
                existing_type=sa.Integer(),
                nullable=False,
            )
            batch_op.create_primary_key("pk_email_users", ["id"])
            batch_op.create_unique_constraint("uq_email_users_email", ["email"])
    else:
        op.alter_column(
            "email_users",
            "id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        # Drop ALL FK constraints that reference email_users (referencing email as the old PK).
        # We need to do this before dropping the PK constraint.
        fks_to_recreate = []
        for table_name in inspector.get_table_names():
            if table_name == "email_users":
                continue
            for fk in inspector.get_foreign_keys(table_name):
                if fk.get("referred_table") == "email_users":
                    fks_to_recreate.append((table_name, fk))
                    op.drop_constraint(fk["name"], table_name, type_="foreignkey")

        # Use introspection to get the actual PK name (avoids hard-coding naming convention)
        pk_info = inspector.get_pk_constraint("email_users")
        pk_name = pk_info.get("name")
        if pk_name:
            op.drop_constraint(pk_name, "email_users", type_="primary")

        op.create_primary_key("pk_email_users", "email_users", ["id"])
        op.create_unique_constraint("uq_email_users_email", "email_users", ["email"])

        # Recreate all dropped FKs (they still reference email, which is now UNIQUE)
        for table_name, fk in fks_to_recreate:
            options = fk.get("options", {})
            op.create_foreign_key(
                fk["name"],
                table_name,
                "email_users",
                fk["constrained_columns"],
                fk["referred_columns"],
                ondelete=options.get("ondelete"),
                onupdate=options.get("onupdate"),
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
        # Drop ALL FK constraints that reference email_users before touching its constraints
        fks_to_recreate = []
        for table_name in inspector.get_table_names():
            if table_name == "email_users":
                continue
            for fk in inspector.get_foreign_keys(table_name):
                if fk.get("referred_table") == "email_users":
                    fks_to_recreate.append((table_name, fk))
                    op.drop_constraint(fk["name"], table_name, type_="foreignkey")

        op.drop_constraint("uq_email_users_email", "email_users", type_="unique")
        op.drop_constraint("pk_email_users", "email_users", type_="primary")
        op.create_primary_key("pk_email_users", "email_users", ["email"])
        op.drop_column("email_users", "id")
        op.execute(sa.text("DROP SEQUENCE IF EXISTS email_users_id_seq"))

        # Recreate all dropped FKs (they reference email, which is now the PK again)
        for table_name, fk in fks_to_recreate:
            options = fk.get("options", {})
            op.create_foreign_key(
                fk["name"],
                table_name,
                "email_users",
                fk["constrained_columns"],
                fk["referred_columns"],
                ondelete=options.get("ondelete"),
                onupdate=options.get("onupdate"),
            )

    elif bind.dialect.name == "sqlite":
        with op.batch_alter_table("email_users", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_email_users_email", type_="unique")
            batch_op.create_primary_key("pk_email_users", ["email"])
            batch_op.drop_column("id")
