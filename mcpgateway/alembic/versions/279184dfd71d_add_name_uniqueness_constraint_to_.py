# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/279184dfd71d_add_name_uniqueness_constraint_to_.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

add_name_uniqueness_constraint_to_resources

Revision ID: 279184dfd71d
Revises: e198602c3c1e
Create Date: 2026-06-03 12:39:27.221653
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "279184dfd71d"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e198602c3c1e"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_index_names(bind) -> set:
    """Return index names on the resources table via the DB catalog directly.

    SQLAlchemy's Inspector.get_indexes() silently drops expression-based indexes on both
    SQLite and Postgres ("Skipped unsupported reflection of expression-based index"), which
    would make the COALESCE(...)-based indexes below always look absent and break the
    idempotent create-if-missing / drop-if-present checks in upgrade()/downgrade().
    """
    dialect_name = bind.dialect.name
    if dialect_name == "sqlite":
        rows = bind.execute(text("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'resources'")).fetchall()
    else:
        rows = bind.execute(text("SELECT indexname AS name FROM pg_indexes WHERE tablename = 'resources'")).fetchall()
    return {r[0] for r in rows}


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "resources" not in inspector.get_table_names():
        return

    # Pre-flight: fail early with a clear message if duplicate names already exist under the
    # same ownership scope. Without this check the constraint creation below raises a raw
    # IntegrityError that is hard to diagnose.
    # NOTE: grouping uses COALESCE(team_id, '') to match the index expression below - team_id is
    # NULL for public/private resources, and SQL treats NULLs as distinct, so grouping on the raw
    # column would miss duplicates the new index is about to enforce.
    dupes = bind.execute(
        text("SELECT name, COALESCE(team_id, '') AS team_scope, owner_email, gateway_id, COUNT(*) AS cnt FROM resources GROUP BY name, team_scope, owner_email, gateway_id HAVING COUNT(*) > 1")
    ).fetchall()
    if dupes:
        dupe_list = ", ".join(f"'{r[0]}'" for r in dupes[:5])
        raise RuntimeError(
            f"Cannot add resource name uniqueness constraint: {len(dupes)} duplicate name(s) "
            f"exist under the same (team_id, owner_email, gateway_id) scope "
            f"(e.g. {dupe_list}). Resolve duplicates before migrating."
        )

    existing_indexes = _existing_index_names(bind)

    # Use raw CREATE UNIQUE INDEX (not op.create_index) so we can index COALESCE(team_id, '')
    # instead of the bare column. team_id is NULL for public/private resources, and both SQLite
    # and Postgres treat NULLs as distinct in unique indexes, so indexing the raw column would
    # let unlimited duplicate names through for those two visibilities - only team-scoped rows
    # would ever be blocked. Wrapping team_id in COALESCE collapses NULL to a single comparable
    # value so the constraint actually enforces uniqueness for public/private resources too.
    if "uq_team_owner_gateway_name_resource" not in existing_indexes:
        op.execute(text("CREATE UNIQUE INDEX uq_team_owner_gateway_name_resource ON resources (COALESCE(team_id, ''), owner_email, gateway_id, name)"))

    if "uq_team_owner_name_resource_local" not in existing_indexes:
        op.execute(text("CREATE UNIQUE INDEX uq_team_owner_name_resource_local ON resources (COALESCE(team_id, ''), owner_email, name) WHERE gateway_id IS NULL"))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "resources" not in inspector.get_table_names():
        return

    existing_indexes = _existing_index_names(bind)
    if "uq_team_owner_name_resource_local" in existing_indexes:
        op.drop_index("uq_team_owner_name_resource_local", table_name="resources")

    if "uq_team_owner_gateway_name_resource" in existing_indexes:
        op.drop_index("uq_team_owner_gateway_name_resource", table_name="resources")
