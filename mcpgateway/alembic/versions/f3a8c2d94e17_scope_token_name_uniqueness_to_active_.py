# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/f3a8c2d94e17_scope_token_name_uniqueness_to_active_.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

scope token name uniqueness to active tokens

Revision ID: f3a8c2d94e17
Revises: d21698ae4a19
Create Date: 2026-07-27

Token revocation is a soft delete (is_active = false), but the uniqueness rule on
email_api_tokens (user_email, name, team_id) applied to ALL rows.  Once a token was
revoked, its name was blocked forever for that user: creating a new token with the
same name raised "A token with this name already exists" even though the UI showed
no such token.  The service-level duplicate check in TokenCatalogService.create_token()
already filters on is_active, so the DB constraint contradicted the intended semantics.

This migration replaces the uniqueness rule with partial unique indexes that only
cover active tokens — the same pattern migration d21698ae4a19 applied to the roles
and user_roles tables:

Old constraint: uq_email_api_tokens_user_name_team   -> (user_email, name, team_id)
Old index:      uq_email_api_tokens_user_name_global -> (user_email, name) WHERE team_id IS NULL
New index:      uq_email_api_tokens_user_name_team   -> (user_email, name, team_id) WHERE team_id IS NOT NULL AND is_active
New index:      uq_email_api_tokens_user_name_global -> (user_email, name) WHERE team_id IS NULL AND is_active

Index names are kept identical to the old constraint/index names so the IntegrityError
handlers in routers/tokens.py and utils/error_formatter.py keep matching.

No deduplication step is needed: the old (stricter) rule guarantees existing rows
also satisfy the new (active-only) rule.

Supports PostgreSQL and SQLite.  On other dialects partial indexes are unavailable,
so the previous full-row uniqueness behavior is kept (with a warning), matching the
fallback strategy of migration d21698ae4a19.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f3a8c2d94e17"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d21698ae4a19"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace all-rows token name uniqueness with active-only partial unique indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # Skip if the table doesn't exist yet (fresh DB is created directly from db.py models)
    if "email_api_tokens" not in inspector.get_table_names():
        return

    # Clean up orphaned temp table from a previously failed batch_alter_table run.
    # On SQLite, DDL is non-transactional so the temp table persists after a rollback.
    if "_alembic_tmp_email_api_tokens" in inspector.get_table_names():
        op.drop_table("_alembic_tmp_email_api_tokens")

    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("email_api_tokens")}
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("email_api_tokens")}

    # Drop the old (user_email, name, team_id) all-rows unique constraint.
    # batch_alter_table is required for SQLite compatibility (SQLite cannot DROP
    # CONSTRAINT directly; Alembic reconstructs the table under a batch context).
    if "uq_email_api_tokens_user_name_team" in existing_constraints:
        with op.batch_alter_table("email_api_tokens") as batch_op:
            batch_op.drop_constraint("uq_email_api_tokens_user_name_team", type_="unique")

    # Drop the old global-scope partial index (no is_active filter)
    if "uq_email_api_tokens_user_name_global" in existing_indexes:
        op.drop_index("uq_email_api_tokens_user_name_global", table_name="email_api_tokens")

    # Recompute after the DDL above (batch_alter_table rebuilds the table on SQLite)
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("email_api_tokens")}

    if dialect in ("postgresql", "sqlite"):
        is_active_true = "is_active = true" if dialect == "postgresql" else "is_active = 1"
        if "uq_email_api_tokens_user_name_team" not in existing_indexes:
            op.create_index(
                "uq_email_api_tokens_user_name_team",
                "email_api_tokens",
                ["user_email", "name", "team_id"],
                unique=True,
                postgresql_where=sa.text(f"team_id IS NOT NULL AND {is_active_true}"),
                sqlite_where=sa.text(f"team_id IS NOT NULL AND {is_active_true}"),
            )
        if "uq_email_api_tokens_user_name_global" not in existing_indexes:
            op.create_index(
                "uq_email_api_tokens_user_name_global",
                "email_api_tokens",
                ["user_email", "name"],
                unique=True,
                postgresql_where=sa.text(f"team_id IS NULL AND {is_active_true}"),
                sqlite_where=sa.text(f"team_id IS NULL AND {is_active_true}"),
            )
    else:
        # Partial indexes are not supported (e.g. MySQL): keep the previous all-rows
        # uniqueness behavior so nothing regresses, even though revoked names stay blocked.
        print(f"WARNING: Dialect '{dialect}' does not support partial indexes. " "Recreating full unique indexes; revoked token names remain reserved on this dialect.")
        if "uq_email_api_tokens_user_name_team" not in existing_indexes:
            op.create_index(
                "uq_email_api_tokens_user_name_team",
                "email_api_tokens",
                ["user_email", "name", "team_id"],
                unique=True,
            )
        if "uq_email_api_tokens_user_name_global" not in existing_indexes:
            op.create_index(
                "uq_email_api_tokens_user_name_global",
                "email_api_tokens",
                ["user_email", "name"],
                unique=True,
            )


def downgrade() -> None:
    """Restore all-rows uniqueness (constraint + partial index without is_active filter)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "email_api_tokens" not in inspector.get_table_names():
        return

    # Clean up orphaned temp table from a previously failed batch_alter_table run.
    if "_alembic_tmp_email_api_tokens" in inspector.get_table_names():
        op.drop_table("_alembic_tmp_email_api_tokens")

    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("email_api_tokens")}
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("email_api_tokens")}

    # Drop the active-only partial indexes
    if "uq_email_api_tokens_user_name_team" in existing_indexes:
        op.drop_index("uq_email_api_tokens_user_name_team", table_name="email_api_tokens")
    if "uq_email_api_tokens_user_name_global" in existing_indexes:
        op.drop_index("uq_email_api_tokens_user_name_global", table_name="email_api_tokens")

    # Restore the original all-rows constraint and global partial index.
    # NOTE: this can fail if revoked tokens now share a name with an active one;
    # such rows must be renamed or deleted before downgrading.
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("email_api_tokens")}

    if "uq_email_api_tokens_user_name_team" not in existing_constraints:
        with op.batch_alter_table("email_api_tokens") as batch_op:
            batch_op.create_unique_constraint(
                "uq_email_api_tokens_user_name_team",
                ["user_email", "name", "team_id"],
            )

    if "uq_email_api_tokens_user_name_global" not in existing_indexes:
        op.create_index(
            "uq_email_api_tokens_user_name_global",
            "email_api_tokens",
            ["user_email", "name"],
            unique=True,
            postgresql_where=sa.text("team_id IS NULL"),
            sqlite_where=sa.text("team_id IS NULL"),
        )
