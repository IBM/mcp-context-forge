"""add_name_uniqueness_constraint_to_resources

Revision ID: 279184dfd71d
Revises: e28566875fa4
Create Date: 2026-06-03 12:39:27.221653

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '279184dfd71d'
down_revision: Union[str, Sequence[str], None] = 'e28566875fa4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "resources" not in inspector.get_table_names():
        return

    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("resources")}
    existing_indexes = {i["name"] for i in inspector.get_indexes("resources")}

    if "uq_team_owner_gateway_name_resource" not in existing_constraints:
        op.create_unique_constraint(
            "uq_team_owner_gateway_name_resource",
            "resources",
            ["team_id", "owner_email", "gateway_id", "name"],
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

    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("resources")}
    if "uq_team_owner_gateway_name_resource" in existing_constraints:
        op.drop_constraint("uq_team_owner_gateway_name_resource", "resources", type_="unique")
