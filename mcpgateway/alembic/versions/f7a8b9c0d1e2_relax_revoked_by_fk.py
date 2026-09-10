# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/f7a8b9c0d1e2_relax_revoked_by_fk.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

relax_revoked_by_fk

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-09-10 10:00:00.000000

Make ``token_revocations.revoked_by`` nullable and drop the foreign key
to ``email_users.email``. Trust-mode principals have no local user row,
so the old FK rejected every revocation they wrote; the idle-timeout
path then swallowed the error and the revocation never landed. The
column now stores the canonical user_id or a system sentinel string
(``system:idle-timeout``, ``system:logout``, ``system:admin-logout``).

SQLite has no ALTER COLUMN / DROP CONSTRAINT, so both changes run inside
``batch_alter_table`` (table rebuild). All operations are guarded by
inspector checks so the migration is idempotent and safe to re-run.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "token_revocations"
COLUMN_NAME = "revoked_by"
FK_NAME = "token_revocations_revoked_by_fkey"


def _revoked_by_fk_names(inspector: sa.engine.reflection.Inspector) -> list:
    """Return the names of every FK that constrains token_revocations.revoked_by.

    The name depends on how the schema was created: alembic-managed
    databases predate the FK (none exists), ``create_all`` databases use
    the model naming convention, and PostgreSQL default naming produces
    ``token_revocations_revoked_by_fkey``. Read the real names from the
    inspector instead of assuming one.
    """
    names = []
    for fk in inspector.get_foreign_keys(TABLE_NAME):
        if fk.get("constrained_columns") == [COLUMN_NAME] and fk.get("name"):
            names.append(fk["name"])
    return names


def upgrade() -> None:
    """Drop the revoked_by FK and make the column nullable (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if TABLE_NAME not in inspector.get_table_names():
        return

    fk_names = _revoked_by_fk_names(inspector)
    columns = {column["name"]: column for column in inspector.get_columns(TABLE_NAME)}
    needs_nullable = COLUMN_NAME in columns and not columns[COLUMN_NAME]["nullable"]

    if not fk_names and not needs_nullable:
        return

    # batch_alter_table rebuilds the table on SQLite; op.drop_constraint
    # outside batch mode fails there. Both changes share one rebuild.
    with op.batch_alter_table(TABLE_NAME, schema=None) as batch_op:
        for fk_name in fk_names:
            batch_op.drop_constraint(fk_name, type_="foreignkey")
        if needs_nullable:
            batch_op.alter_column(COLUMN_NAME, existing_type=sa.String(255), nullable=True)


def downgrade() -> None:
    """Restore the revoked_by FK and the NOT NULL constraint (idempotent).

    Rows that the relaxed schema allows (NULL or non-email revoked_by)
    block the restore; delete or re-key them before downgrading.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if TABLE_NAME not in inspector.get_table_names():
        return

    fk_names = _revoked_by_fk_names(inspector)
    columns = {column["name"]: column for column in inspector.get_columns(TABLE_NAME)}
    needs_not_null = COLUMN_NAME in columns and columns[COLUMN_NAME]["nullable"]

    if fk_names and not needs_not_null:
        return

    with op.batch_alter_table(TABLE_NAME, schema=None) as batch_op:
        if needs_not_null:
            batch_op.alter_column(COLUMN_NAME, existing_type=sa.String(255), nullable=False)
        if not fk_names:
            batch_op.create_foreign_key(FK_NAME, "email_users", [COLUMN_NAME], ["email"])
