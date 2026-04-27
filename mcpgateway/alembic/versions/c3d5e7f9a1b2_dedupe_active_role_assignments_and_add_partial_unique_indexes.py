# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/c3d5e7f9a1b2_dedupe_active_role_assignments_and_add_partial_unique_indexes.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Dedupe active rows in ``roles`` / ``user_roles`` and add partial unique indexes.

Revision ID: c3d5e7f9a1b2
Revises: b2c3d4e5f6g7
Create Date: 2026-04-27 18:00:00.000000

The bootstrap-time SELECT-then-INSERT pattern in ``bootstrap_default_roles``
and ``assign_role_to_user`` was historically serialized by the migration
advisory lock — when the in-pod bootstrap fast-path skips the lock (replicas
2..N on transaction-pool PgBouncer deployments), N concurrent seeders can all
miss the same row and all insert. ``Role.id`` and ``UserRole.id`` are
client-generated UUIDs so the PK never saves us.

This migration enforces the invariant at the DB tier:

  * exactly one ACTIVE row per ``(roles.name, roles.scope)``;
  * exactly one ACTIVE row per
    ``(user_roles.user_email, user_roles.role_id, user_roles.scope,
       user_roles.scope_id)`` — split into two partial indexes because
    ``scope_id`` is nullable and both Postgres and SQLite treat NULLs as
    distinct in ordinary unique indexes.

If the DB already contains duplicate active rows from before this migration
shipped, we soft-delete losers (``is_active = false``) deterministically by
``created_at`` (oldest wins) so the partial indexes can be added without
violation. Audit history is preserved.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d5e7f9a1b2"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ROLES_INDEX = "uq_roles_name_scope_active"
_USER_ROLES_INDEX_NO_SCOPE_ID = "uq_user_roles_assignment_active_no_scope_id"
_USER_ROLES_INDEX_WITH_SCOPE_ID = "uq_user_roles_assignment_active_with_scope_id"


def _is_active_true_literal(dialect_name: str) -> str:
    """Return the boolean-true literal that matches each dialect's storage.

    Args:
        dialect_name: SQLAlchemy dialect name (e.g., ``postgresql``, ``sqlite``).

    Returns:
        The dialect-appropriate literal for ``is_active = TRUE``.
    """
    if dialect_name == "sqlite":
        return "1"
    return "true"


def _index_exists(inspector: sa.engine.reflection.Inspector, table_name: str, index_name: str) -> bool:
    """Return True if the named index exists on ``table_name``.

    Args:
        inspector: SQLAlchemy inspector for the active connection.
        table_name: Table to inspect.
        index_name: Index name to look for.

    Returns:
        True if the index exists; False otherwise (including missing table).
    """
    if table_name not in inspector.get_table_names():
        return False
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _dedupe_roles(conn: sa.engine.Connection) -> int:
    """Soft-delete duplicate active rows in ``roles``, keeping the oldest.

    Args:
        conn: Active SQLAlchemy connection bound to the migration transaction.

    Returns:
        Count of rows soft-deleted (``is_active`` flipped to false).
    """
    true_lit = _is_active_true_literal(conn.dialect.name)
    # Keep the oldest active row per (name, scope); flip the rest to inactive.
    sql = sa.text(
        f"""
        UPDATE roles
        SET is_active = {('0' if conn.dialect.name == 'sqlite' else 'false')}
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY name, scope
                           ORDER BY created_at ASC, id ASC
                       ) AS rn
                FROM roles
                WHERE is_active = {true_lit}
            ) ranked
            WHERE rn > 1
        )
        """
    )
    result = conn.execute(sql)
    return result.rowcount or 0


def _dedupe_user_roles(conn: sa.engine.Connection) -> int:
    """Soft-delete duplicate active rows in ``user_roles``, keeping the oldest.

    Args:
        conn: Active SQLAlchemy connection bound to the migration transaction.

    Returns:
        Count of rows soft-deleted (``is_active`` flipped to false).
    """
    true_lit = _is_active_true_literal(conn.dialect.name)
    # COALESCE flattens NULL scope_id into the partition key so global/personal
    # assignments (scope_id IS NULL) are deduped alongside team assignments.
    sql = sa.text(
        f"""
        UPDATE user_roles
        SET is_active = {('0' if conn.dialect.name == 'sqlite' else 'false')}
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY user_email, role_id, scope, COALESCE(scope_id, '')
                           ORDER BY granted_at ASC, id ASC
                       ) AS rn
                FROM user_roles
                WHERE is_active = {true_lit}
            ) ranked
            WHERE rn > 1
        )
        """
    )
    result = conn.execute(sql)
    return result.rowcount or 0


def upgrade() -> None:
    """Dedupe active duplicates and create the partial unique indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "roles" in inspector.get_table_names():
        _dedupe_roles(bind)
        if not _index_exists(inspector, "roles", _ROLES_INDEX):
            op.create_index(
                _ROLES_INDEX,
                "roles",
                ["name", "scope"],
                unique=True,
                postgresql_where=sa.text("is_active = true"),
                sqlite_where=sa.text("is_active = 1"),
            )

    if "user_roles" in inspector.get_table_names():
        _dedupe_user_roles(bind)
        if not _index_exists(inspector, "user_roles", _USER_ROLES_INDEX_NO_SCOPE_ID):
            op.create_index(
                _USER_ROLES_INDEX_NO_SCOPE_ID,
                "user_roles",
                ["user_email", "role_id", "scope"],
                unique=True,
                postgresql_where=sa.text("is_active = true AND scope_id IS NULL"),
                sqlite_where=sa.text("is_active = 1 AND scope_id IS NULL"),
            )
        if not _index_exists(inspector, "user_roles", _USER_ROLES_INDEX_WITH_SCOPE_ID):
            op.create_index(
                _USER_ROLES_INDEX_WITH_SCOPE_ID,
                "user_roles",
                ["user_email", "role_id", "scope", "scope_id"],
                unique=True,
                postgresql_where=sa.text("is_active = true AND scope_id IS NOT NULL"),
                sqlite_where=sa.text("is_active = 1 AND scope_id IS NOT NULL"),
            )


def downgrade() -> None:
    """Drop the partial unique indexes; the soft-delete dedupe is not reversed."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _index_exists(inspector, "user_roles", _USER_ROLES_INDEX_WITH_SCOPE_ID):
        op.drop_index(_USER_ROLES_INDEX_WITH_SCOPE_ID, table_name="user_roles")
    if _index_exists(inspector, "user_roles", _USER_ROLES_INDEX_NO_SCOPE_ID):
        op.drop_index(_USER_ROLES_INDEX_NO_SCOPE_ID, table_name="user_roles")
    if _index_exists(inspector, "roles", _ROLES_INDEX):
        op.drop_index(_ROLES_INDEX, table_name="roles")
