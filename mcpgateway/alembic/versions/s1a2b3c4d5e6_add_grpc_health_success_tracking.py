"""add grpc health success tracking

Revision ID: s1a2b3c4d5e6
Revises: r1a2b3c4d5e6
Create Date: 2026-08-11

Add last_health_success column to grpc_services for tracking the most recent
successful health check independently of the general last_health_check timestamp.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "s1a2b3c4d5e6"
down_revision: Union[str, None] = "r1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "grpc_services",
        sa.Column("last_health_success", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("grpc_services", "last_health_success")
