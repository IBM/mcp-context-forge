# -*- coding: utf-8 -*-
"""add sandbox tables for policy testing

Revision ID: d2d3d4d5d6d7
Revises: c1c2c3c4c5c6
Create Date: 2026-02-12 22:00:00.000000

"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d2d3d4d5d6d7"
down_revision: str = "c1c2c3c4c5c6"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create policy_drafts and sandbox_test_suites tables.

    Both operations are idempotent: they skip if the tables already exist
    (e.g. fresh databases that were created from the ORM models directly).
    """
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()

    # --- policy_drafts ---
    if "policy_drafts" not in existing_tables:
        op.create_table(
            "policy_drafts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False, index=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("config", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(50), nullable=False, server_default="draft", index=True),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    # --- sandbox_test_suites ---
    if "sandbox_test_suites" not in existing_tables:
        op.create_table(
            "sandbox_test_suites",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False, index=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("test_cases", sa.JSON(), nullable=False),
            sa.Column("tags", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    """Drop sandbox tables."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()

    if "sandbox_test_suites" in existing_tables:
        op.drop_table("sandbox_test_suites")
    if "policy_drafts" in existing_tables:
        op.drop_table("policy_drafts")
