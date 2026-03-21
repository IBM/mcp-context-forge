# -*- coding: utf-8 -*-
"""Add dynamic_servers and dynamic_rules tables

Revision ID: d4e5f6a7b8c9
Revises: 5126ced48fd0
Create Date: 2026-02-25 14:00:00.000000

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "5126ced48fd0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create dynamic_servers and dynamic_rules tables (idempotent).

    Skips table creation if a table already exists so that the migration is
    safe to run on both fresh databases and databases that were created from
    the ORM models directly (e.g. in tests).
    """
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Dialect-aware server_default for datetime columns
    now_sql = sa.text("now()") if dialect_name == "postgresql" else sa.text("(datetime('now'))")

    # ------------------------------------------------------------------
    # 1. dynamic_servers
    # ------------------------------------------------------------------
    if "dynamic_servers" not in existing_tables:
        op.create_table(
            "dynamic_servers",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("refresh_interval", sa.Integer(), nullable=True),
            sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
            sa.Column("team_id", sa.String(36), nullable=True),
            sa.Column("owner_email", sa.String(255), nullable=True),
            # Audit fields
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now_sql),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now_sql),
            sa.Column("created_by", sa.String(255), nullable=True),
            sa.Column("modified_by", sa.String(255), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            # Constraints
            sa.PrimaryKeyConstraint("id", name="pk_dynamic_servers"),
            sa.ForeignKeyConstraint(
                ["team_id"],
                ["email_teams.id"],
                name="fk_dynamic_servers_team_id",
                ondelete="SET NULL",
            ),
            sa.UniqueConstraint(
                "team_id", "owner_email", "name",
                name="uq_dynamic_servers_team_owner_name",
            ),
        )

        op.create_index(
            "idx_dynamic_servers_created_at_id",
            "dynamic_servers",
            ["created_at", "id"],
        )
        op.create_index(
            "idx_dynamic_servers_team_id",
            "dynamic_servers",
            ["team_id"],
        )

    # ------------------------------------------------------------------
    # 2. dynamic_rules
    # ------------------------------------------------------------------
    if "dynamic_rules" not in existing_tables:
        op.create_table(
            "dynamic_rules",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("dynamic_server_id", sa.String(36), nullable=False),
            sa.Column("rule_type", sa.String(20), nullable=False),
            sa.Column("entity_type", sa.String(20), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now_sql),
            # Constraints
            sa.PrimaryKeyConstraint("id", name="pk_dynamic_rules"),
            sa.ForeignKeyConstraint(
                ["dynamic_server_id"],
                ["dynamic_servers.id"],
                name="fk_dynamic_rules_dynamic_server_id",
                ondelete="CASCADE",
            ),
        )

        op.create_index(
            "idx_dynamic_rules_dynamic_server_id",
            "dynamic_rules",
            ["dynamic_server_id"],
        )


def downgrade() -> None:
    """Drop dynamic_rules and dynamic_servers tables (idempotent).

    Drops child table first to respect the FK constraint, then the parent.
    """
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()

    # Drop dynamic_rules first (child)
    if "dynamic_rules" in existing_tables:
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("dynamic_rules")}
        if "idx_dynamic_rules_dynamic_server_id" in existing_indexes:
            op.drop_index("idx_dynamic_rules_dynamic_server_id", table_name="dynamic_rules")
        op.drop_table("dynamic_rules")

    # Drop dynamic_servers second (parent)
    if "dynamic_servers" in existing_tables:
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("dynamic_servers")}
        if "idx_dynamic_servers_created_at_id" in existing_indexes:
            op.drop_index("idx_dynamic_servers_created_at_id", table_name="dynamic_servers")
        if "idx_dynamic_servers_team_id" in existing_indexes:
            op.drop_index("idx_dynamic_servers_team_id", table_name="dynamic_servers")
        op.drop_table("dynamic_servers")
