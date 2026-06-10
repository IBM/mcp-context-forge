"""add_name_uniqueness_constraint_to_resources

Revision ID: 279184dfd71d
Revises: e28566875fa4
Create Date: 2026-06-03 12:39:27.221653

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "279184dfd71d"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "0a089912b5f0"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "resources" not in inspector.get_table_names():
        return

    # Pre-flight: fail early with a clear message if duplicate names already exist under the
    # same ownership scope. Without this check the constraint creation below raises a raw
    # IntegrityError that is hard to diagnose.
    dupes = bind.execute(text("SELECT name, team_id, owner_email, gateway_id, COUNT(*) AS cnt " "FROM resources " "GROUP BY name, team_id, owner_email, gateway_id " "HAVING COUNT(*) > 1")).fetchall()
    if dupes:
        dupe_list = ", ".join(f"'{r[0]}'" for r in dupes[:5])
        raise RuntimeError(
            f"Cannot add resource name uniqueness constraint: {len(dupes)} duplicate name(s) "
            f"exist under the same (team_id, owner_email, gateway_id) scope "
            f"(e.g. {dupe_list}). Resolve duplicates before migrating."
        )

    existing_indexes = {i["name"] for i in inspector.get_indexes("resources")}

    # Use create_index(unique=True) instead of create_unique_constraint: SQLite does not
    # support ALTER TABLE ADD CONSTRAINT, but it does support CREATE UNIQUE INDEX.
    if "uq_team_owner_gateway_name_resource" not in existing_indexes:
        op.create_index(
            "uq_team_owner_gateway_name_resource",
            "resources",
            ["team_id", "owner_email", "gateway_id", "name"],
            unique=True,
        )

    if "uq_team_owner_name_resource_local" not in existing_indexes:
        op.create_index(
            "uq_team_owner_name_resource_local",
            "resources",
            ["team_id", "owner_email", "name"],
            unique=True,
            postgresql_where=sa.text("gateway_id IS NULL"),
            sqlite_where=sa.text("gateway_id IS NULL"),
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "resources" not in inspector.get_table_names():
        return

    existing_indexes = {i["name"] for i in inspector.get_indexes("resources")}
    if "uq_team_owner_name_resource_local" in existing_indexes:
        op.drop_index("uq_team_owner_name_resource_local", table_name="resources")

    if "uq_team_owner_gateway_name_resource" in existing_indexes:
        op.drop_index("uq_team_owner_gateway_name_resource", table_name="resources")
