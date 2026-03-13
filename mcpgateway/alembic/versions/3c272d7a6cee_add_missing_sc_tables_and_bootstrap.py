# -*- coding: utf-8 -*-
"""Add missing sc_ tables and bootstrap default clearance levels

Revision ID: 3c272d7a6cee
Revises: d8a534ca0f9c
Create Date: 2026-03-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone
import uuid

revision = "3c272d7a6cee"
down_revision = "d8a534ca0f9c"
branch_labels = None
depends_on = None


def upgrade():
    # --- sc_resource_classifications ---
    op.create_table(
        "sc_resource_classifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resource_uri", sa.String(512), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("classification_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sc_resource_classifications_tenant_id", "sc_resource_classifications", ["tenant_id"])
    op.create_index("ix_sc_resource_classifications_uri", "sc_resource_classifications", ["resource_uri"])

    # --- sc_a2a_agent_clearances ---
    op.create_table(
        "sc_a2a_agent_clearances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(255), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("clearance_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("granted_by", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sc_a2a_agent_clearances_tenant_id", "sc_a2a_agent_clearances", ["tenant_id"])

    # --- Bootstrap default clearance levels (0-5) ---
    now = datetime.now(timezone.utc)
    default_levels = [
        {"id": str(uuid.uuid4()), "name": "PUBLIC",           "numeric_value": 0, "description": "Publicly accessible data",            "is_active": True, "created_at": now, "updated_at": now},
        {"id": str(uuid.uuid4()), "name": "INTERNAL",         "numeric_value": 1, "description": "Internal use only",                   "is_active": True, "created_at": now, "updated_at": now},
        {"id": str(uuid.uuid4()), "name": "CONFIDENTIAL",     "numeric_value": 2, "description": "Confidential business data",          "is_active": True, "created_at": now, "updated_at": now},
        {"id": str(uuid.uuid4()), "name": "SECRET",           "numeric_value": 3, "description": "Secret - restricted access",          "is_active": True, "created_at": now, "updated_at": now},
        {"id": str(uuid.uuid4()), "name": "TOP_SECRET",       "numeric_value": 4, "description": "Top secret - highly restricted",      "is_active": True, "created_at": now, "updated_at": now},
        {"id": str(uuid.uuid4()), "name": "COMPARTMENTALIZED","numeric_value": 5, "description": "Compartmentalized - need to know only","is_active": True, "created_at": now, "updated_at": now},
    ]
    op.bulk_insert(
        sa.table(
            "sc_levels",
            sa.column("id", sa.String),
            sa.column("name", sa.String),
            sa.column("numeric_value", sa.Integer),
            sa.column("description", sa.String),
            sa.column("is_active", sa.Boolean),
            sa.column("created_at", sa.DateTime),
            sa.column("updated_at", sa.DateTime),
        ),
        default_levels,
    )


def downgrade():
    # Remove bootstrap data
    op.execute("DELETE FROM sc_levels WHERE name IN ('PUBLIC','INTERNAL','CONFIDENTIAL','SECRET','TOP_SECRET','COMPARTMENTALIZED')")
    op.drop_table("sc_a2a_agent_clearances")
    op.drop_table("sc_resource_classifications")