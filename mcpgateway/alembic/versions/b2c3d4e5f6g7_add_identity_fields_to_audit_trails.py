"""add identity fields to audit_trails

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-17

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if "audit_trails" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("audit_trails")]

    if "auth_method" not in columns:
        op.add_column("audit_trails", sa.Column("auth_method", sa.String(50), nullable=True))
    if "acting_as" not in columns:
        op.add_column("audit_trails", sa.Column("acting_as", sa.String(255), nullable=True))
    if "delegation_chain" not in columns:
        op.add_column("audit_trails", sa.Column("delegation_chain", sa.JSON(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if "audit_trails" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("audit_trails")]

    if "delegation_chain" in columns:
        op.drop_column("audit_trails", "delegation_chain")
    if "acting_as" in columns:
        op.drop_column("audit_trails", "acting_as")
    if "auth_method" in columns:
        op.drop_column("audit_trails", "auth_method")
