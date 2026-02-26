# -*- coding: utf-8 -*-
"""Add jit_grants table for Just-in-Time access management

Revision ID: a1b2c3d4e5f6
Revises: z1a2b3c4d5e6
Create Date: 2026-02-26 12:00:00.000000
"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "z1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    """Create jit_grants table for JIT access management."""
    op.create_table(
        "jit_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("requester_email", sa.String(255), sa.ForeignKey("email_users.email"), nullable=False),
        sa.Column("requested_role", sa.String(255), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("duration_hours", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("ticket_url", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("approved_by", sa.String(255), sa.ForeignKey("email_users.email"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(255), sa.ForeignKey("email_users.email"), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_jit_requester_status", "jit_grants", ["requester_email", "status"])
    op.create_index("idx_jit_expires", "jit_grants", ["expires_at", "status"])
    op.create_index("ix_jit_grants_requester_email", "jit_grants", ["requester_email"])
    op.create_index("ix_jit_grants_status", "jit_grants", ["status"])
    op.create_index("ix_jit_grants_created_at", "jit_grants", ["created_at"])
    op.create_index("ix_jit_grants_expires_at", "jit_grants", ["expires_at"])


def downgrade():
    """Drop jit_grants table."""
    op.drop_index("ix_jit_grants_expires_at", table_name="jit_grants")
    op.drop_index("ix_jit_grants_created_at", table_name="jit_grants")
    op.drop_index("ix_jit_grants_status", table_name="jit_grants")
    op.drop_index("ix_jit_grants_requester_email", table_name="jit_grants")
    op.drop_index("idx_jit_expires", table_name="jit_grants")
    op.drop_index("idx_jit_requester_status", table_name="jit_grants")
    op.drop_table("jit_grants")
