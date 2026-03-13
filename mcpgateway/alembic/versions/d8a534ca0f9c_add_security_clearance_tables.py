# -*- coding: utf-8 -*-
"""Add Bell-LaPadula security clearance tables (Phase 2)

Revision ID: d8a534ca0f9c
Revises: z1a2b3c4d5e6
Create Date: 2026-03-13
"""
from alembic import op
import sqlalchemy as sa

revision = "d8a534ca0f9c"
down_revision = "z1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sc_levels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("numeric_value", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sc_levels_tenant_id", "sc_levels", ["tenant_id"])

    op.create_table(
        "sc_user_clearances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("clearance_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("granted_by", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sc_user_clearances_user_tenant", "sc_user_clearances", ["user_id", "tenant_id"])

    op.create_table(
        "sc_team_clearances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("team_id", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("clearance_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("granted_by", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sc_team_clearances_team_tenant", "sc_team_clearances", ["team_id", "tenant_id"])

    op.create_table(
        "sc_tool_classifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("server_name", sa.String(255), nullable=True),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("classification_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sc_tool_classifications_tool_server", "sc_tool_classifications", ["tool_name", "server_name"])
    op.create_index("ix_sc_tool_classifications_tenant_id", "sc_tool_classifications", ["tenant_id"])

    op.create_table(
        "sc_server_classifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("server_name", sa.String(255), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("classification_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sc_server_classifications_tenant_id", "sc_server_classifications", ["tenant_id"])

    op.create_table(
        "sc_clearance_audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("user_clearance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_name", sa.String(255), nullable=True),
        sa.Column("resource_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("violation_type", sa.String(64), nullable=True),
        sa.Column("hook", sa.String(64), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
    )
    op.create_index("ix_sc_audit_user_ts", "sc_clearance_audit_log", ["user_id", "timestamp"])
    op.create_index("ix_sc_audit_tenant_ts", "sc_clearance_audit_log", ["tenant_id", "timestamp"])
    op.create_index("ix_sc_clearance_audit_log_timestamp", "sc_clearance_audit_log", ["timestamp"])

    op.create_table(
        "sc_dynamic_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("rule_type", sa.String(32), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(255), nullable=False),
        sa.Column("resource_pattern", sa.String(255), nullable=False),
        sa.Column("clearance_override", sa.Integer(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sc_dynamic_rules_tenant_id", "sc_dynamic_rules", ["tenant_id"])


def downgrade():
    op.drop_table("sc_dynamic_rules")
    op.drop_table("sc_clearance_audit_log")
    op.drop_table("sc_server_classifications")
    op.drop_table("sc_tool_classifications")
    op.drop_table("sc_team_clearances")
    op.drop_table("sc_user_clearances")
    op.drop_table("sc_levels")