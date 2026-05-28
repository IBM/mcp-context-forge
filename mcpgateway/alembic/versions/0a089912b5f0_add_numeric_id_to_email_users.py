# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/0a089912b5f0_add_numeric_id_to_email_users.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Gabriel Costa

add_numeric_id_to_email_users

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
    """Make id the primary key of email_users and email a unique non-PK column.

    For existing databases this migration:
    1. Adds the id column (nullable) if absent
    2. Populates sequential ids for existing rows
    3. Recreates the table with id as INTEGER PRIMARY KEY and email as UNIQUE

    Fresh databases skip this migration entirely (db.py models apply directly).
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "email_users" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("email_users")}

    # Step 1: add id column if absent
    if "id" not in columns:
        op.add_column("email_users", sa.Column("id", sa.Integer(), nullable=True))

        # Step 2: populate sequential ids ordered by (created_at, email)
        if bind.dialect.name == "postgresql":
            bind.execute(
                text(
                    "UPDATE email_users SET id = subquery.row_num "
                    "FROM (SELECT email, ROW_NUMBER() OVER (ORDER BY created_at, email) AS row_num FROM email_users) AS subquery "
                    "WHERE email_users.email = subquery.email"
                )
            )
        else:  # sqlite
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

    # Step 3: restructure table so id is PK, email is UNIQUE NOT NULL
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("email_users", recreate="always") as batch_op:
            batch_op.alter_column("id", existing_type=sa.Integer(), nullable=False)
            batch_op.create_primary_key("pk_email_users", ["id"])
            batch_op.create_unique_constraint("uq_email_users_email", ["email"])
    else:
        # PostgreSQL: set up sequence, make id PK, demote email to UNIQUE
        max_id_result = bind.execute(text("SELECT COALESCE(MAX(id), 0) FROM email_users"))
        max_id = max_id_result.scalar()

        bind.execute(text(f"CREATE SEQUENCE IF NOT EXISTS email_users_id_seq START WITH {max_id + 1}"))

        op.alter_column(
            "email_users",
            "id",
            existing_type=sa.Integer(),
            nullable=False,
            server_default=text("nextval('email_users_id_seq')"),
        )
        bind.execute(text("ALTER SEQUENCE email_users_id_seq OWNED BY email_users.id"))

        # Drop email primary key, promote id to PK, keep email unique
        bind.execute(text("ALTER TABLE email_users DROP CONSTRAINT email_users_pkey"))
        bind.execute(text("ALTER TABLE email_users ADD PRIMARY KEY (id)"))
        bind.execute(text("ALTER TABLE email_users ADD CONSTRAINT uq_email_users_email UNIQUE (email)"))


def downgrade() -> None:
    """Restore email as primary key and remove the id column."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if "email_users" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("email_users")}
    if "id" not in columns:
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("email_users", recreate="always") as batch_op:
            batch_op.drop_column("id")
            batch_op.create_primary_key("pk_email_users_email", ["email"])
    else:
        bind.execute(text("ALTER TABLE email_users DROP CONSTRAINT email_users_pkey"))
        bind.execute(text("ALTER TABLE email_users DROP CONSTRAINT IF EXISTS uq_email_users_email"))
        op.drop_column("email_users", "id")
        bind.execute(text("DROP SEQUENCE IF EXISTS email_users_id_seq"))
        bind.execute(text("ALTER TABLE email_users ADD PRIMARY KEY (email)"))
