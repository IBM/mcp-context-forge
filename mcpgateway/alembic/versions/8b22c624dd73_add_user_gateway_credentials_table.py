# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
"""Add user_gateway_credentials table for per-user personal credentials

Revision ID: 8b22c624dd73
Revises: z1a2b3c4d5e6
Create Date: 2026-04-02 10:00:00.000000

"""

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "8b22c624dd73"
down_revision = "z1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the user_gateway_credentials table and its indexes."""
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if "user_gateway_credentials" not in existing_tables:
        op.create_table(
            "user_gateway_credentials",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("gateway_id", sa.String(36), sa.ForeignKey("gateways.id", ondelete="CASCADE"), nullable=False),
            sa.Column("app_user_email", sa.String(255), sa.ForeignKey("email_users.email", ondelete="CASCADE"), nullable=False),
            sa.Column("credential_type", sa.String(50), nullable=False),
            sa.Column("credential_value", sa.Text(), nullable=False),
            sa.Column("label", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
            sa.UniqueConstraint("gateway_id", "app_user_email", name="uq_credential_gateway_user"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("user_gateway_credentials")}
    if "idx_user_credentials_gateway" not in existing_indexes:
        op.create_index("idx_user_credentials_gateway", "user_gateway_credentials", ["gateway_id"])
    if "idx_user_credentials_email" not in existing_indexes:
        op.create_index("idx_user_credentials_email", "user_gateway_credentials", ["app_user_email"])


def downgrade() -> None:
    """Drop the user_gateway_credentials table and its indexes."""
    op.drop_index("idx_user_credentials_email", table_name="user_gateway_credentials")
    op.drop_index("idx_user_credentials_gateway", table_name="user_gateway_credentials")
    op.drop_table("user_gateway_credentials")
