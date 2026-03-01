# -*- coding: utf-8 -*-
"""a2a_v1_protocol_migration

Revision ID: 86d15e51b773
Revises: d9e0f1a2b3c4
Create Date: 2026-03-01 12:00:00.000000

Add A2A v1.0 RC1 protocol support:
- Add tenant, icon_url to a2a_agents table
- Create server_interfaces table (protocol-specific config per server)
- Create a2a_agent_auth table (extracted auth config from a2a_agents)
- Create server_task_mappings table for federated task ID persistence
- Migrate existing a2a_agents auth data into a2a_agent_auth
- Normalize cancelled -> canceled in task state values

Note: The old auth columns on a2a_agents are NOT dropped in this migration.
They are kept for backward compatibility during the transition. A future
migration will drop them after the service layer fully adopts a2a_agent_auth.
"""

# Standard
import uuid
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "86d15e51b773"
down_revision: Union[str, Sequence[str], None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    # --- A2A Agents: add tenant and icon_url ---
    if _table_exists("a2a_agents"):
        if not _column_exists("a2a_agents", "tenant"):
            op.add_column("a2a_agents", sa.Column("tenant", sa.String(255), nullable=True))
        if not _column_exists("a2a_agents", "icon_url"):
            op.add_column("a2a_agents", sa.Column("icon_url", sa.String(767), nullable=True))

    # --- Server Interfaces table ---
    if not _table_exists("server_interfaces"):
        op.create_table(
            "server_interfaces",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("server_id", sa.String(36), sa.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("protocol", sa.String(20), nullable=False),
            sa.Column("binding", sa.String(30), nullable=False),
            sa.Column("version", sa.String(10), nullable=False, server_default="1.0"),
            sa.Column("tenant", sa.String(255), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("server_id", "protocol", "binding", name="uq_server_interface"),
        )
        op.create_index("ix_server_interfaces_server_id", "server_interfaces", ["server_id"])

    # --- A2A Agent Auth table ---
    if not _table_exists("a2a_agent_auth"):
        op.create_table(
            "a2a_agent_auth",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("a2a_agent_id", sa.String(36), sa.ForeignKey("a2a_agents.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("auth_type", sa.String(20), nullable=True),
            sa.Column("auth_value", sa.JSON(), nullable=True),
            sa.Column("auth_query_params", sa.JSON(), nullable=True),
            sa.Column("oauth_config", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_a2a_agent_auth_agent_id", "a2a_agent_auth", ["a2a_agent_id"])

    # --- Migrate existing auth data from a2a_agents to a2a_agent_auth ---
    if _table_exists("a2a_agents") and _table_exists("a2a_agent_auth") and _column_exists("a2a_agents", "auth_type"):
        bind = op.get_bind()
        # Select agents that have any auth configuration
        agents = bind.execute(
            sa.text(
                "SELECT id, auth_type, auth_value, auth_query_params, oauth_config "
                "FROM a2a_agents "
                "WHERE auth_type IS NOT NULL"
            )
        ).fetchall()
        for agent in agents:
            # Check if auth config already exists (idempotent)
            existing = bind.execute(
                sa.text("SELECT id FROM a2a_agent_auth WHERE a2a_agent_id = :agent_id"),
                {"agent_id": agent[0]},
            ).fetchone()
            if existing is None:
                bind.execute(
                    sa.text(
                        "INSERT INTO a2a_agent_auth (id, a2a_agent_id, auth_type, auth_value, auth_query_params, oauth_config) "
                        "VALUES (:id, :agent_id, :auth_type, :auth_value, :auth_query_params, :oauth_config)"
                    ),
                    {
                        "id": uuid.uuid4().hex,
                        "agent_id": agent[0],
                        "auth_type": agent[1],
                        "auth_value": agent[2],
                        "auth_query_params": agent[3],
                        "oauth_config": agent[4],
                    },
                )

    # --- ServerTaskMapping table ---
    if not _table_exists("server_task_mappings"):
        op.create_table(
            "server_task_mappings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("server_id", sa.String(36), sa.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("server_task_id", sa.String(255), nullable=False),
            sa.Column("agent_name", sa.String(255), nullable=False),
            sa.Column("agent_task_id", sa.String(255), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("server_id", "server_task_id", name="uq_server_task_mapping"),
        )
        op.create_index("ix_server_task_mappings_agent", "server_task_mappings", ["agent_name", "agent_task_id"])

    # --- Normalize cancelled -> canceled in a2a_tasks ---
    if _table_exists("a2a_tasks"):
        bind = op.get_bind()
        bind.execute(
            sa.text("UPDATE a2a_tasks SET state = 'canceled' WHERE state = 'cancelled'")
        )


def downgrade() -> None:
    # --- Revert cancelled spelling ---
    if _table_exists("a2a_tasks"):
        bind = op.get_bind()
        bind.execute(
            sa.text("UPDATE a2a_tasks SET state = 'cancelled' WHERE state = 'canceled'")
        )

    # --- Drop ServerTaskMapping table ---
    if _table_exists("server_task_mappings"):
        op.drop_index("ix_server_task_mappings_agent", table_name="server_task_mappings")
        op.drop_table("server_task_mappings")

    # --- Drop A2A Agent Auth table ---
    # Note: data migration back to a2a_agents columns is NOT performed here
    # because the old columns are preserved during upgrade.
    if _table_exists("a2a_agent_auth"):
        op.drop_index("ix_a2a_agent_auth_agent_id", table_name="a2a_agent_auth")
        op.drop_table("a2a_agent_auth")

    # --- Drop Server Interfaces table ---
    if _table_exists("server_interfaces"):
        op.drop_index("ix_server_interfaces_server_id", table_name="server_interfaces")
        op.drop_table("server_interfaces")

    # --- Remove A2A agent fields ---
    if _table_exists("a2a_agents"):
        for col in ("icon_url", "tenant"):
            if _column_exists("a2a_agents", col):
                op.drop_column("a2a_agents", col)
