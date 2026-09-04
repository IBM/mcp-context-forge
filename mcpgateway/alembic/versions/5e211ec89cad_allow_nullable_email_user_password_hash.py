# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/5e211ec89cad_allow_nullable_email_user_password_hash.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Allow email users without local password hashes.

Revision ID: 5e211ec89cad
Revises: 12d4a0c7789c
Create Date: 2026-09-04 09:37:21.131648
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5e211ec89cad"
down_revision: Union[str, Sequence[str], None] = "12d4a0c7789c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _email_users_columns() -> dict[str, dict]:
    """Return reflected email_users columns keyed by name."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "email_users" not in inspector.get_table_names():
        return {}
    return {column["name"]: column for column in inspector.get_columns("email_users")}


def upgrade() -> None:
    """Allow passwordless SSO-only users to store NULL password_hash."""
    columns = _email_users_columns()
    password_hash = columns.get("password_hash")
    if password_hash is None or password_hash.get("nullable"):
        return

    with op.batch_alter_table("email_users", schema=None) as batch_op:
        batch_op.alter_column("password_hash", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    """Restore NOT NULL password_hash after disabling passwordless rows."""
    columns = _email_users_columns()
    password_hash = columns.get("password_hash")
    if password_hash is None:
        return

    bind = op.get_bind()
    password_hash_type = columns.get("password_hash_type")

    bind.execute(
        sa.text("UPDATE email_users SET password_hash = :disabled_hash WHERE password_hash IS NULL"),
        {"disabled_hash": "!disabled"},
    )

    if password_hash_type is not None:
        bind.execute(
            sa.text("UPDATE email_users SET password_hash_type = :hash_type WHERE password_hash_type = :passwordless_hash_type"),
            {"hash_type": "argon2id", "passwordless_hash_type": "none"},
        )

    if not password_hash.get("nullable"):
        return

    with op.batch_alter_table("email_users", schema=None) as batch_op:
        batch_op.alter_column("password_hash", existing_type=sa.String(length=255), nullable=False)
