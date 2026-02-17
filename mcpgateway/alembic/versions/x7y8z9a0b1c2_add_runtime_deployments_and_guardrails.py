# -*- coding: utf-8 -*-
"""Add runtime deployment, approval, and guardrail profile tables.

Revision ID: x7y8z9a0b1c2
Revises: w6g7h8i9j0k1
Create Date: 2026-02-17 10:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "x7y8z9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "w6g7h8i9j0k1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create runtime management tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "runtime_guardrail_profiles" not in tables:
        op.create_table(
            "runtime_guardrail_profiles",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("recommended_backends", sa.JSON(), nullable=False),
            sa.Column("config", sa.JSON(), nullable=False),
            sa.Column("built_in", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )

    profiles_indexes = {idx["name"] for idx in inspector.get_indexes("runtime_guardrail_profiles")} if "runtime_guardrail_profiles" in inspector.get_table_names() else set()
    if "ix_runtime_guardrail_profiles_name" not in profiles_indexes:
        op.create_index("ix_runtime_guardrail_profiles_name", "runtime_guardrail_profiles", ["name"], unique=False)

    tables = inspector.get_table_names()
    if "runtime_deployments" not in tables:
        op.create_table(
            "runtime_deployments",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("slug", sa.String(length=255), nullable=False),
            sa.Column("backend", sa.String(length=50), nullable=False),
            sa.Column("source_type", sa.String(length=30), nullable=False),
            sa.Column("source_config", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("approval_status", sa.String(length=20), nullable=False, server_default="not_required"),
            sa.Column("runtime_ref", sa.String(length=255), nullable=True),
            sa.Column("endpoint_url", sa.String(length=1024), nullable=True),
            sa.Column("image", sa.String(length=512), nullable=True),
            sa.Column("catalog_server_id", sa.String(length=100), nullable=True),
            sa.Column("resource_limits", sa.JSON(), nullable=False),
            sa.Column("environment", sa.JSON(), nullable=False),
            sa.Column("guardrails_profile", sa.String(length=100), nullable=True),
            sa.Column("guardrails_config", sa.JSON(), nullable=False),
            sa.Column("guardrails_warnings", sa.JSON(), nullable=False),
            sa.Column("backend_response", sa.JSON(), nullable=False),
            sa.Column("runtime_metadata", sa.JSON(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("gateway_id", sa.String(length=36), nullable=True),
            sa.Column("team_id", sa.String(length=36), nullable=True),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("approved_by", sa.String(length=255), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_status_check", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["gateway_id"], ["gateways.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    deployment_indexes = {idx["name"] for idx in inspector.get_indexes("runtime_deployments")} if "runtime_deployments" in inspector.get_table_names() else set()
    if "ix_runtime_deployments_slug" not in deployment_indexes:
        op.create_index("ix_runtime_deployments_slug", "runtime_deployments", ["slug"], unique=False)
    if "ix_runtime_deployments_backend" not in deployment_indexes:
        op.create_index("ix_runtime_deployments_backend", "runtime_deployments", ["backend"], unique=False)
    if "ix_runtime_deployments_status" not in deployment_indexes:
        op.create_index("ix_runtime_deployments_status", "runtime_deployments", ["status"], unique=False)
    if "ix_runtime_deployments_approval_status" not in deployment_indexes:
        op.create_index("ix_runtime_deployments_approval_status", "runtime_deployments", ["approval_status"], unique=False)
    if "ix_runtime_deployments_runtime_ref" not in deployment_indexes:
        op.create_index("ix_runtime_deployments_runtime_ref", "runtime_deployments", ["runtime_ref"], unique=False)
    if "ix_runtime_deployments_catalog_server_id" not in deployment_indexes:
        op.create_index("ix_runtime_deployments_catalog_server_id", "runtime_deployments", ["catalog_server_id"], unique=False)
    if "ix_runtime_deployments_gateway_id" not in deployment_indexes:
        op.create_index("ix_runtime_deployments_gateway_id", "runtime_deployments", ["gateway_id"], unique=False)
    if "ix_runtime_deployments_team_id" not in deployment_indexes:
        op.create_index("ix_runtime_deployments_team_id", "runtime_deployments", ["team_id"], unique=False)
    if "idx_runtime_backend_status" not in deployment_indexes:
        op.create_index("idx_runtime_backend_status", "runtime_deployments", ["backend", "status"], unique=False)
    if "idx_runtime_created" not in deployment_indexes:
        op.create_index("idx_runtime_created", "runtime_deployments", ["created_at"], unique=False)

    tables = inspector.get_table_names()
    if "runtime_deployment_approvals" not in tables:
        op.create_table(
            "runtime_deployment_approvals",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("runtime_deployment_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("requested_by", sa.String(length=255), nullable=True),
            sa.Column("reviewed_by", sa.String(length=255), nullable=True),
            sa.Column("requested_reason", sa.Text(), nullable=True),
            sa.Column("decision_reason", sa.Text(), nullable=True),
            sa.Column("approvers", sa.JSON(), nullable=False),
            sa.Column("rule_snapshot", sa.JSON(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["runtime_deployment_id"], ["runtime_deployments.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    approval_indexes = {idx["name"] for idx in inspector.get_indexes("runtime_deployment_approvals")} if "runtime_deployment_approvals" in inspector.get_table_names() else set()
    if "ix_runtime_deployment_approvals_runtime_deployment_id" not in approval_indexes:
        op.create_index("ix_runtime_deployment_approvals_runtime_deployment_id", "runtime_deployment_approvals", ["runtime_deployment_id"], unique=False)
    if "ix_runtime_deployment_approvals_status" not in approval_indexes:
        op.create_index("ix_runtime_deployment_approvals_status", "runtime_deployment_approvals", ["status"], unique=False)
    if "ix_runtime_deployment_approvals_requested_by" not in approval_indexes:
        op.create_index("ix_runtime_deployment_approvals_requested_by", "runtime_deployment_approvals", ["requested_by"], unique=False)
    if "ix_runtime_deployment_approvals_reviewed_by" not in approval_indexes:
        op.create_index("ix_runtime_deployment_approvals_reviewed_by", "runtime_deployment_approvals", ["reviewed_by"], unique=False)
    if "idx_runtime_approval_status_created" not in approval_indexes:
        op.create_index("idx_runtime_approval_status_created", "runtime_deployment_approvals", ["status", "created_at"], unique=False)
    if "idx_runtime_approval_runtime_status" not in approval_indexes:
        op.create_index("idx_runtime_approval_runtime_status", "runtime_deployment_approvals", ["runtime_deployment_id", "status"], unique=False)


def downgrade() -> None:
    """Drop runtime management tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "runtime_deployment_approvals" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("runtime_deployment_approvals")}
        for idx_name in [
            "idx_runtime_approval_runtime_status",
            "idx_runtime_approval_status_created",
            "ix_runtime_deployment_approvals_reviewed_by",
            "ix_runtime_deployment_approvals_requested_by",
            "ix_runtime_deployment_approvals_status",
            "ix_runtime_deployment_approvals_runtime_deployment_id",
        ]:
            if idx_name in indexes:
                op.drop_index(idx_name, table_name="runtime_deployment_approvals")
        op.drop_table("runtime_deployment_approvals")

    if "runtime_deployments" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("runtime_deployments")}
        for idx_name in [
            "idx_runtime_created",
            "idx_runtime_backend_status",
            "ix_runtime_deployments_team_id",
            "ix_runtime_deployments_gateway_id",
            "ix_runtime_deployments_catalog_server_id",
            "ix_runtime_deployments_runtime_ref",
            "ix_runtime_deployments_approval_status",
            "ix_runtime_deployments_status",
            "ix_runtime_deployments_backend",
            "ix_runtime_deployments_slug",
        ]:
            if idx_name in indexes:
                op.drop_index(idx_name, table_name="runtime_deployments")
        op.drop_table("runtime_deployments")

    if "runtime_guardrail_profiles" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("runtime_guardrail_profiles")}
        if "ix_runtime_guardrail_profiles_name" in indexes:
            op.drop_index("ix_runtime_guardrail_profiles_name", table_name="runtime_guardrail_profiles")
        op.drop_table("runtime_guardrail_profiles")
