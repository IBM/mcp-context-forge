# pylint: disable=no-member
"""change token uniqueness constraint to per-team scope

Revision ID: d9e0f1a2b3c4
Revises: b2d9c6e4f1a7
Create Date: 2026-02-27

Replaces the global (user_email, name) unique constraint on email_api_tokens
with a per-team (user_email, name, team_id) constraint so that the same token
name can be reused across different teams (e.g. agent studio workflows).

Because SQL NULL != NULL semantics mean the composite constraint cannot protect
global-scope tokens (team_id IS NULL), we also add a partial unique index for
that case.

Old constraint: uq_email_api_tokens_user_name        -> (user_email, name)
New constraint: uq_email_api_tokens_user_name_team   -> (user_email, name, team_id)
New index:      uq_email_api_tokens_user_name_global  -> (user_email, name) WHERE team_id IS NULL
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "b2d9c6e4f1a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace global (user_email, name) unique constraint with per-team (user_email, name, team_id) constraint."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if the table doesn't exist yet (fresh DB is created directly from db.py models)
    if "email_api_tokens" not in inspector.get_table_names():
        return

    # Clean up orphaned temp table from a previously failed batch_alter_table run.
    # On SQLite, DDL is non-transactional so the temp table persists after a rollback.
    if "_alembic_tmp_email_api_tokens" in inspector.get_table_names():
        op.drop_table("_alembic_tmp_email_api_tokens")

    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("email_api_tokens")}
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("email_api_tokens")}

    # batch_alter_table is required for SQLite compatibility (SQLite cannot DROP CONSTRAINT
    # directly; Alembic reconstructs the table internally under a batch context).
    with op.batch_alter_table("email_api_tokens") as batch_op:
        # Drop the old global (user_email, name) constraint variants if present
        for old_name in ("uq_email_api_tokens_user_name", "uq_email_api_tokens_user_email_name"):
            if old_name in existing_constraints:
                batch_op.drop_constraint(old_name, type_="unique")

        # Add the new per-team (user_email, name, team_id) constraint if not already present
        if "uq_email_api_tokens_user_name_team" not in existing_constraints:
            batch_op.create_unique_constraint(
                "uq_email_api_tokens_user_name_team",
                ["user_email", "name", "team_id"],
            )

    # Partial unique index for global-scope tokens (team_id IS NULL).
    # SQL NULL != NULL means the composite constraint above cannot protect this case.
    if "uq_email_api_tokens_user_name_global" not in existing_indexes:
        op.create_index(
            "uq_email_api_tokens_user_name_global",
            "email_api_tokens",
            ["user_email", "name"],
            unique=True,
            postgresql_where=sa.text("team_id IS NULL"),
            sqlite_where=sa.text("team_id IS NULL"),
        )


def downgrade() -> None:
    """Restore the original global (user_email, name) unique constraint."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "email_api_tokens" not in inspector.get_table_names():
        return

    # Clean up orphaned temp table from a previously failed batch_alter_table run.
    if "_alembic_tmp_email_api_tokens" in inspector.get_table_names():
        op.drop_table("_alembic_tmp_email_api_tokens")

    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("email_api_tokens")}
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("email_api_tokens")}

    # Drop the partial unique index for global-scope tokens
    if "uq_email_api_tokens_user_name_global" in existing_indexes:
        op.drop_index("uq_email_api_tokens_user_name_global", table_name="email_api_tokens")

    with op.batch_alter_table("email_api_tokens") as batch_op:
        # Remove the per-team constraint
        if "uq_email_api_tokens_user_name_team" in existing_constraints:
            batch_op.drop_constraint("uq_email_api_tokens_user_name_team", type_="unique")

        # Restore the original global constraint
        if "uq_email_api_tokens_user_name" not in existing_constraints:
            batch_op.create_unique_constraint(
                "uq_email_api_tokens_user_name",
                ["user_email", "name"],
            )
