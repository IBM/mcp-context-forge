# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/0a089912b5f0_add_numeric_id_to_email_users.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

add_uuid_id_to_email_users

Revision ID: 0a089912b5f0
Revises: e28566875fa4
Create Date: 2026-05-25 16:28:22.159471
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision: str = "0a089912b5f0"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e28566875fa4"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add UUID id column to email_users table for Phase 1 token migration.

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
    op.add_column(
        "email_users",
        sa.Column("id", sa.String(36), nullable=True),
    )

    # Backfill existing rows with UUIDs
    if bind.dialect.name == "postgresql":
        bind.execute(text("UPDATE email_users SET id = gen_random_uuid()::text WHERE id IS NULL"))
    else:
        # SQLite: use Python-generated UUIDs via a subquery isn't possible,
        # so we use a single UPDATE with a hex() + randomblob() approach.
        bind.execute(text("""
            UPDATE email_users
            SET id = lower(hex(randomblob(4))) || '-'
                  || lower(hex(randomblob(2))) || '-'
                  || '4' || substr(lower(hex(randomblob(2))), 2) || '-'
                  || substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))), 2) || '-'
                  || lower(hex(randomblob(6)))
            WHERE id IS NULL
        """))

    # Promote id to primary key and demote email to unique (SQLite requires batch mode)
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("email_users", recreate="always") as batch_op:
            batch_op.alter_column(
                "id",
                existing_type=sa.String(36),
                nullable=False,
            )
            batch_op.create_primary_key("pk_email_users", ["id"])
            batch_op.create_unique_constraint("uq_email_users_email", ["email"])
    else:
        op.alter_column(
            "email_users",
            "id",
            existing_type=sa.String(36),
            nullable=False,
        )
        # Drop ALL FK constraints that reference email_users (referencing email as the old PK).
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
    """Remove UUID id column from email_users table."""
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
