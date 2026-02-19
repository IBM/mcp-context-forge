# -*- coding: utf-8 -*-
"""Add code_execution virtual server mode (servers columns + skills/runs tables)

Revision ID: y8i9j0k1l2m3
Revises: w6g7h8i9j0k1
Create Date: 2026-02-16 01:20:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "y8i9j0k1l2m3"
down_revision: Union[str, Sequence[str], None] = "x7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add code_execution server settings and create skills/run history tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "servers" not in tables:
        return

    # -------------------------
    # servers: add new columns
    # -------------------------
    server_columns = {col["name"] for col in inspector.get_columns("servers")}

    # Phase 1: Add columns as nullable to avoid table rewrites on MySQL/MariaDB.
    # PostgreSQL 11+ handles NOT NULL + DEFAULT as metadata-only, but MySQL may
    # require a full table copy.  The phased approach is safe on all backends.
    if "server_type" not in server_columns:
        op.add_column(
            "servers",
            sa.Column("server_type", sa.String(length=32), nullable=True, server_default="standard"),
        )
        # Phase 2: Backfill existing rows
        op.execute("UPDATE servers SET server_type = 'standard' WHERE server_type IS NULL")
        # Phase 3: Apply NOT NULL constraint
        op.alter_column("servers", "server_type", nullable=False)
    if "stub_language" not in server_columns:
        op.add_column("servers", sa.Column("stub_language", sa.String(length=32), nullable=True))
    if "mount_rules" not in server_columns:
        op.add_column("servers", sa.Column("mount_rules", sa.JSON(), nullable=True))
    if "sandbox_policy" not in server_columns:
        op.add_column("servers", sa.Column("sandbox_policy", sa.JSON(), nullable=True))
    if "tokenization" not in server_columns:
        op.add_column("servers", sa.Column("tokenization", sa.JSON(), nullable=True))
    if "skills_scope" not in server_columns:
        op.add_column("servers", sa.Column("skills_scope", sa.String(length=255), nullable=True))
    if "skills_require_approval" not in server_columns:
        op.add_column(
            "servers",
            sa.Column("skills_require_approval", sa.Boolean(), nullable=True, server_default=sa.false()),
        )
        op.execute("UPDATE servers SET skills_require_approval = 0 WHERE skills_require_approval IS NULL")
        op.alter_column("servers", "skills_require_approval", nullable=False)

    server_indexes = {idx["name"] for idx in inspector.get_indexes("servers")}
    if "ix_servers_server_type" not in server_indexes and "server_type" in {c["name"] for c in inspector.get_columns("servers")}:
        op.create_index("ix_servers_server_type", "servers", ["server_type"], unique=False)

    # --------------------------------
    # code_execution_skills table
    # --------------------------------
    tables = inspector.get_table_names()
    if "code_execution_skills" not in tables:
        op.create_table(
            "code_execution_skills",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("server_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("language", sa.String(length=32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("source_code", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("team_id", sa.String(length=36), nullable=True),
            sa.Column("owner_email", sa.String(length=255), nullable=True),
            sa.Column("approved_by", sa.String(length=255), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("created_from_ip", sa.String(length=45), nullable=True),
            sa.Column("created_via", sa.String(length=100), nullable=True),
            sa.Column("created_user_agent", sa.Text(), nullable=True),
            sa.Column("modified_by", sa.String(length=255), nullable=True),
            sa.Column("modified_from_ip", sa.String(length=45), nullable=True),
            sa.Column("modified_via", sa.String(length=100), nullable=True),
            sa.Column("modified_user_agent", sa.Text(), nullable=True),
            sa.Column("version_counter", sa.Integer(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(["approved_by"], ["email_users.email"]),
            sa.ForeignKeyConstraint(["owner_email"], ["email_users.email"], use_alter=True, name="fk_code_execution_skills_owner_email_email_users"),
            sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["team_id"], ["email_teams.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("server_id", "name", "version", name="uq_code_execution_skill_server_name_version"),
        )

    skill_indexes = {idx["name"] for idx in inspector.get_indexes("code_execution_skills")}
    if "idx_code_execution_skills_server_status" not in skill_indexes:
        op.create_index("idx_code_execution_skills_server_status", "code_execution_skills", ["server_id", "status"], unique=False)
    if "ix_code_execution_skills_server_id" not in skill_indexes:
        op.create_index("ix_code_execution_skills_server_id", "code_execution_skills", ["server_id"], unique=False)
    if "ix_code_execution_skills_name" not in skill_indexes:
        op.create_index("ix_code_execution_skills_name", "code_execution_skills", ["name"], unique=False)
    if "ix_code_execution_skills_team_id" not in skill_indexes:
        op.create_index("ix_code_execution_skills_team_id", "code_execution_skills", ["team_id"], unique=False)
    if "ix_code_execution_skills_owner_email" not in skill_indexes:
        op.create_index("ix_code_execution_skills_owner_email", "code_execution_skills", ["owner_email"], unique=False)

    # --------------------------------
    # skill_approvals table
    # --------------------------------
    tables = inspector.get_table_names()
    if "skill_approvals" not in tables:
        op.create_table(
            "skill_approvals",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("skill_id", sa.String(length=36), nullable=False),
            sa.Column("requested_by", sa.String(length=255), nullable=True),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("reviewed_by", sa.String(length=255), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("admin_notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["requested_by"], ["email_users.email"]),
            sa.ForeignKeyConstraint(["reviewed_by"], ["email_users.email"]),
            sa.ForeignKeyConstraint(["skill_id"], ["code_execution_skills.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    approval_indexes = {idx["name"] for idx in inspector.get_indexes("skill_approvals")}
    if "idx_skill_approvals_status_requested_at" not in approval_indexes:
        op.create_index("idx_skill_approvals_status_requested_at", "skill_approvals", ["status", "requested_at"], unique=False)
    if "idx_skill_approvals_expires_at" not in approval_indexes:
        op.create_index("idx_skill_approvals_expires_at", "skill_approvals", ["expires_at"], unique=False)
    if "ix_skill_approvals_skill_id" not in approval_indexes:
        op.create_index("ix_skill_approvals_skill_id", "skill_approvals", ["skill_id"], unique=False)

    # --------------------------------
    # code_execution_runs table
    # --------------------------------
    tables = inspector.get_table_names()
    if "code_execution_runs" not in tables:
        op.create_table(
            "code_execution_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("server_id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=64), nullable=False),
            sa.Column("user_email", sa.String(length=255), nullable=True),
            sa.Column("language", sa.String(length=32), nullable=False),
            sa.Column("code_hash", sa.String(length=64), nullable=False),
            sa.Column("code_body", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("output", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("metrics", sa.JSON(), nullable=True),
            sa.Column("tool_calls_made", sa.JSON(), nullable=True),
            sa.Column("security_events", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("team_id", sa.String(length=36), nullable=True),
            sa.Column("token_teams", sa.JSON(), nullable=True),
            sa.Column("runtime", sa.String(length=64), nullable=True),
            sa.Column("code_size_bytes", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    run_indexes = {idx["name"] for idx in inspector.get_indexes("code_execution_runs")}
    if "idx_code_execution_runs_server_created" not in run_indexes:
        op.create_index("idx_code_execution_runs_server_created", "code_execution_runs", ["server_id", "created_at"], unique=False)
    if "idx_code_execution_runs_user_created" not in run_indexes:
        op.create_index("idx_code_execution_runs_user_created", "code_execution_runs", ["user_email", "created_at"], unique=False)
    if "ix_code_execution_runs_server_id" not in run_indexes:
        op.create_index("ix_code_execution_runs_server_id", "code_execution_runs", ["server_id"], unique=False)
    if "ix_code_execution_runs_session_id" not in run_indexes:
        op.create_index("ix_code_execution_runs_session_id", "code_execution_runs", ["session_id"], unique=False)
    if "ix_code_execution_runs_user_email" not in run_indexes:
        op.create_index("ix_code_execution_runs_user_email", "code_execution_runs", ["user_email"], unique=False)
    if "ix_code_execution_runs_code_hash" not in run_indexes:
        op.create_index("ix_code_execution_runs_code_hash", "code_execution_runs", ["code_hash"], unique=False)
    if "ix_code_execution_runs_team_id" not in run_indexes:
        op.create_index("ix_code_execution_runs_team_id", "code_execution_runs", ["team_id"], unique=False)


def downgrade() -> None:
    """Drop code_execution mode tables and servers columns."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "code_execution_runs" in tables:
        run_indexes = {idx["name"] for idx in inspector.get_indexes("code_execution_runs")}
        for idx in (
            "ix_code_execution_runs_team_id",
            "ix_code_execution_runs_code_hash",
            "ix_code_execution_runs_user_email",
            "ix_code_execution_runs_session_id",
            "ix_code_execution_runs_server_id",
            "idx_code_execution_runs_user_created",
            "idx_code_execution_runs_server_created",
        ):
            if idx in run_indexes:
                op.drop_index(idx, table_name="code_execution_runs")
        op.drop_table("code_execution_runs")

    tables = inspector.get_table_names()
    if "skill_approvals" in tables:
        approval_indexes = {idx["name"] for idx in inspector.get_indexes("skill_approvals")}
        for idx in ("ix_skill_approvals_skill_id", "idx_skill_approvals_expires_at", "idx_skill_approvals_status_requested_at"):
            if idx in approval_indexes:
                op.drop_index(idx, table_name="skill_approvals")
        op.drop_table("skill_approvals")

    tables = inspector.get_table_names()
    if "code_execution_skills" in tables:
        skill_indexes = {idx["name"] for idx in inspector.get_indexes("code_execution_skills")}
        for idx in (
            "ix_code_execution_skills_owner_email",
            "ix_code_execution_skills_team_id",
            "ix_code_execution_skills_name",
            "ix_code_execution_skills_server_id",
            "idx_code_execution_skills_server_status",
        ):
            if idx in skill_indexes:
                op.drop_index(idx, table_name="code_execution_skills")
        op.drop_table("code_execution_skills")

    if "servers" not in tables:
        return

    server_indexes = {idx["name"] for idx in inspector.get_indexes("servers")}
    if "ix_servers_server_type" in server_indexes:
        op.drop_index("ix_servers_server_type", table_name="servers")

    server_columns = {col["name"] for col in inspector.get_columns("servers")}
    for col in ("skills_require_approval", "skills_scope", "tokenization", "sandbox_policy", "mount_rules", "stub_language", "server_type"):
        if col in server_columns:
            op.drop_column("servers", col)
