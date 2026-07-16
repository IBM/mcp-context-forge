"""add_name_uniqueness_constraint_to_resources

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

    # The name-uniqueness indexes originally added here were found to violate the MCP spec:
    # resources are uniquely identified by URI, not by name. Name is a human-readable display
    # label and may legitimately repeat across multiple task-specific resource instances that
    # share the same resource type name but have distinct URIs (e.g. grid-entities://{taskId}.json).
    # Drop the indexes if they were created by an earlier build of this migration.
    existing_indexes = _existing_index_names(bind)
    if "uq_team_owner_gateway_name_resource" in existing_indexes:
        op.execute(text("DROP INDEX uq_team_owner_gateway_name_resource"))
    if "uq_team_owner_name_resource_local" in existing_indexes:
        op.execute(text("DROP INDEX uq_team_owner_name_resource_local"))


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
