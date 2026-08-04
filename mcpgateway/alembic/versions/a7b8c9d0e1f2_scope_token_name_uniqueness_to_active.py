# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/a7b8c9d0e1f2_scope_token_name_uniqueness_to_active.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

scope token name uniqueness to active tokens

Fixes issue #5931 - a revoked API token permanently blocks its name.

Token revocation is a soft delete (is_active = false, row kept for audit), but
the uniqueness rules on email_api_tokens covered ALL rows, so a revoked token's
name could never be reused. The service-level duplicate check in
TokenCatalogService.create_token() already filters on is_active, so the intended
semantics are "names unique among active tokens". This migration aligns the
database with that intent:

1. Drops the all-rows UniqueConstraint uq_email_api_tokens_user_name_team
   (user_email, name, team_id).
2. Drops the all-rows partial unique index uq_email_api_tokens_user_name_global
   (user_email, name) WHERE team_id IS NULL.
3. Recreates both as partial unique indexes filtered on is_active:
   - uq_email_api_tokens_user_name_team   -> (user_email, name, team_id)
     WHERE team_id IS NOT NULL AND is_active
   - uq_email_api_tokens_user_name_global -> (user_email, name)
     WHERE team_id IS NULL AND is_active

No data deduplication is required: the old all-rows constraint guaranteed at
most one row per (user_email, name, team_id), so the new partial indexes cannot
collide on existing data.

Same class of fix as d21698ae4a19 (roles/user_roles, issue #4482).

NOTE: These indexes are ALSO defined in mcpgateway/db.py (__table_args__) for
fresh databases. This migration only runs on existing databases (if the table
already exists) and is idempotent.

Supports both PostgreSQL and SQLite databases.

Revision ID: a7b8c9d0e1f2
Revises: d21698ae4a19
Create Date: 2026-07-29

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d21698ae4a19"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Scope email_api_tokens name uniqueness to active tokens only."""
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
        # Drop the old all-rows (user_email, name, team_id) constraint if present.
        # Also handle the index form in case a previous run partially applied.
        if "uq_email_api_tokens_user_name_team" in existing_constraints:
            batch_op.drop_constraint("uq_email_api_tokens_user_name_team", type_="unique")

    # Re-inspect after the batch alter: on SQLite the table (and its indexes) was
    # reconstructed, so previously collected index names may be stale.
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("email_api_tokens")}

    # Drop the old all-rows partial index for global-scope tokens if present
    for old_index in ("uq_email_api_tokens_user_name_global", "uq_email_api_tokens_user_name_team"):
        if old_index in existing_indexes:
            op.drop_index(old_index, table_name="email_api_tokens")
            existing_indexes.discard(old_index)

    # Partial unique index for team-scoped ACTIVE tokens.
    if "uq_email_api_tokens_user_name_team" not in existing_indexes:
        op.create_index(
            "uq_email_api_tokens_user_name_team",
            "email_api_tokens",
            ["user_email", "name", "team_id"],
            unique=True,
            postgresql_where=sa.text("team_id IS NOT NULL AND is_active = true"),
            sqlite_where=sa.text("team_id IS NOT NULL AND is_active = 1"),
        )

    # Partial unique index for global-scope ACTIVE tokens (team_id IS NULL).
    if "uq_email_api_tokens_user_name_global" not in existing_indexes:
        op.create_index(
            "uq_email_api_tokens_user_name_global",
            "email_api_tokens",
            ["user_email", "name"],
            unique=True,
            postgresql_where=sa.text("team_id IS NULL AND is_active = true"),
            sqlite_where=sa.text("team_id IS NULL AND is_active = 1"),
        )


def downgrade() -> None:
    """Restore the all-rows uniqueness rules on email_api_tokens.

    Note: if token names were reused after revocations while this migration was
    applied, restoring the all-rows constraint can fail on the duplicated
    inactive rows. Those rows must be removed (or renamed) manually first.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "email_api_tokens" not in inspector.get_table_names():
        return

    # Clean up orphaned temp table from a previously failed batch_alter_table run.
    if "_alembic_tmp_email_api_tokens" in inspector.get_table_names():
        op.drop_table("_alembic_tmp_email_api_tokens")

    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("email_api_tokens")}
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("email_api_tokens")}

    # Drop the active-only partial unique indexes
    for index_name in ("uq_email_api_tokens_user_name_team", "uq_email_api_tokens_user_name_global"):
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name="email_api_tokens")
            existing_indexes.discard(index_name)

    with op.batch_alter_table("email_api_tokens") as batch_op:
        # Restore the original all-rows per-team constraint
        if "uq_email_api_tokens_user_name_team" not in existing_constraints:
            batch_op.create_unique_constraint(
                "uq_email_api_tokens_user_name_team",
                ["user_email", "name", "team_id"],
            )

    # Restore the original all-rows partial index for global-scope tokens
    if "uq_email_api_tokens_user_name_global" not in existing_indexes:
        op.create_index(
            "uq_email_api_tokens_user_name_global",
            "email_api_tokens",
            ["user_email", "name"],
            unique=True,
            postgresql_where=sa.text("team_id IS NULL"),
            sqlite_where=sa.text("team_id IS NULL"),
        )
