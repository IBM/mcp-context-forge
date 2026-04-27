"""Add A2A v1 domain models: tasks, server interfaces, agent auth

Revision ID: 3f7e9d1a2b4c
Revises: ff03273d8f93
Create Date: 2026-04-01

Creates tables for A2A task persistence (a2a_tasks), server-to-agent
task mapping (server_task_mappings), multi-protocol server interfaces
(server_interfaces), and extracted agent auth configuration
(a2a_agent_auth).  Also adds tenant and icon_url columns to a2a_agents.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "3f7e9d1a2b4c"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "ff03273d8f93"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create A2A v1 domain tables and backfill agent auth."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()

    # --- a2a_tasks -----------------------------------------------------------
    if "a2a_tasks" not in existing_tables:
        op.create_table(
            "a2a_tasks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "a2a_agent_id",
                sa.String(36),
                sa.ForeignKey("a2a_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("task_id", sa.String(), nullable=False),
            sa.Column("context_id", sa.String(), nullable=True),
            sa.Column("state", sa.String(), nullable=False, server_default="submitted"),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("latest_message", sa.JSON(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("a2a_agent_id", "task_id", name="uq_a2a_tasks_agent_task"),
        )
        op.create_index("ix_a2a_tasks_a2a_agent_id", "a2a_tasks", ["a2a_agent_id"])
        op.create_index("ix_a2a_tasks_task_id", "a2a_tasks", ["task_id"])
        op.create_index("ix_a2a_tasks_state", "a2a_tasks", ["state"])
        op.create_index("ix_a2a_tasks_state_updated", "a2a_tasks", ["state", "updated_at"])

    # --- server_task_mappings ------------------------------------------------
    if "server_task_mappings" not in existing_tables:
        op.create_table(
            "server_task_mappings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "server_id",
                sa.String(36),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("server_task_id", sa.String(), nullable=False),
            sa.Column(
                "agent_id",
                sa.String(36),
                sa.ForeignKey("a2a_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("agent_task_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("server_id", "server_task_id", name="uq_server_task_mappings_server_task"),
        )
        op.create_index("ix_server_task_mappings_server_id", "server_task_mappings", ["server_id"])
        op.create_index("ix_server_task_mappings_agent_id", "server_task_mappings", ["agent_id"])

    # --- server_interfaces ---------------------------------------------------
    if "server_interfaces" not in existing_tables:
        op.create_table(
            "server_interfaces",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "server_id",
                sa.String(36),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("protocol", sa.String(), nullable=False),
            sa.Column("binding", sa.String(), nullable=False),
            sa.Column("version", sa.String(), nullable=True),
            sa.Column("tenant", sa.String(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("server_id", "protocol", "binding", name="uq_server_interfaces_server_protocol_binding"),
        )
        op.create_index("ix_server_interfaces_server_id", "server_interfaces", ["server_id"])

    # --- a2a_agent_auth ------------------------------------------------------
    if "a2a_agent_auth" not in existing_tables:
        op.create_table(
            "a2a_agent_auth",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "a2a_agent_id",
                sa.String(36),
                sa.ForeignKey("a2a_agents.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("auth_type", sa.String(), nullable=True),
            sa.Column("auth_value", sa.Text(), nullable=True),
            sa.Column("auth_query_params", sa.JSON(), nullable=True),
            sa.Column("oauth_config", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    # --- a2a_agents: add tenant and icon_url columns -------------------------
    # Column lengths must match the ORM declarations in mcpgateway/db.py
    # (``tenant=String(255)``, ``icon_url=String(767)``).  Without an
    # explicit length, SQLAlchemy emits ``VARCHAR`` on PostgreSQL (which is
    # unbounded), while fresh installs created from the ORM models get the
    # bounded lengths — a schema drift we want to avoid between upgraded
    # and fresh databases.
    if "a2a_agents" in existing_tables:
        columns = [col["name"] for col in inspector.get_columns("a2a_agents")]
        if "tenant" not in columns:
            op.add_column("a2a_agents", sa.Column("tenant", sa.String(255), nullable=True))
        if "icon_url" not in columns:
            op.add_column("a2a_agents", sa.Column("icon_url", sa.String(767), nullable=True))

    # --- Backfill a2a_agent_auth from existing a2a_agents auth columns -------
    if "a2a_agent_auth" in inspector.get_table_names():
        # Standard
        import json
        import uuid

        conn = op.get_bind()
        agents_with_auth = conn.execute(
            sa.text("SELECT id, auth_type, auth_value, auth_query_params " "FROM a2a_agents " "WHERE auth_type IS NOT NULL " "AND id NOT IN (SELECT a2a_agent_id FROM a2a_agent_auth)")
        ).fetchall()
        for agent in agents_with_auth:
            # auth_query_params may be a Python dict (from a JSON column);
            # serialize it so the untyped text bind works on all drivers.
            raw_params = agent[3]
            params_str = json.dumps(raw_params) if isinstance(raw_params, (dict, list)) else raw_params

            conn.execute(
                sa.text(
                    "INSERT INTO a2a_agent_auth (id, a2a_agent_id, auth_type, auth_value, auth_query_params, created_at, updated_at) "
                    "VALUES (:id, :agent_id, :auth_type, :auth_value, :auth_query_params, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "agent_id": agent[0],
                    "auth_type": agent[1],
                    "auth_value": agent[2],
                    "auth_query_params": params_str,
                },
            )


def downgrade() -> None:
    """Drop A2A v1 domain tables and remove agent columns."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()

    if "a2a_agents" in existing_tables:
        columns = [col["name"] for col in inspector.get_columns("a2a_agents")]
        if "icon_url" in columns:
            op.drop_column("a2a_agents", "icon_url")
        if "tenant" in columns:
            op.drop_column("a2a_agents", "tenant")

    if "a2a_agent_auth" in existing_tables:
        op.drop_table("a2a_agent_auth")
    if "server_interfaces" in existing_tables:
        op.drop_table("server_interfaces")
    if "server_task_mappings" in existing_tables:
        op.drop_table("server_task_mappings")
    if "a2a_tasks" in existing_tables:
        op.drop_table("a2a_tasks")
