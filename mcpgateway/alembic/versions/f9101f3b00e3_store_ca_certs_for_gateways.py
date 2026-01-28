# -*- coding: utf-8 -*-
"""store ca-certs for gateways

Revision ID: f9101f3b00e3
Revises: a706a3320c56
Create Date: 2025-11-05 15:18:16.659224

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f9101f3b00e3"
down_revision: Union[str, Sequence[str], None] = "a706a3320c56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database (tables created via create_all + stamp)
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    columns = [col["name"] for col in inspector.get_columns("gateways")]
    if "ca_certificate" not in columns:
        op.add_column("gateways", sa.Column("ca_certificate", sa.Text(), nullable=True))
    if "ca_certificate_sig" not in columns:
        op.add_column("gateways", sa.Column("ca_certificate_sig", sa.String(length=64), nullable=True))
    if "signing_algorithm" not in columns:
        op.add_column("gateways", sa.Column("signing_algorithm", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if fresh database
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    columns = [col["name"] for col in inspector.get_columns("gateways")]
    if "signing_algorithm" in columns:
        op.drop_column("gateways", "signing_algorithm")
    if "ca_certificate_sig" in columns:
        op.drop_column("gateways", "ca_certificate_sig")
    if "ca_certificate" in columns:
        op.drop_column("gateways", "ca_certificate")
