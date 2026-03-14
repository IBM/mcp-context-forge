# -*- coding: utf-8 -*-
"""Add ip_rules and ip_blocks tables for IP-based access control.

Revision ID: 1d27bc0a81f5
Revises: b2d9c6e4f1a7
Create Date: 2026-02-26 13:33:43.653087
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "1d27bc0a81f5"
down_revision: Union[str, Sequence[str], None] = "b2d9c6e4f1a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ip_rules and ip_blocks tables."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()

    if "ip_rules" not in existing_tables:
        op.create_table(
            "ip_rules",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("ip_pattern", sa.String(45), nullable=False),
            sa.Column("rule_type", sa.String(10), nullable=False),
            sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
            sa.Column("path_pattern", sa.String(500), nullable=True),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
            sa.Column("created_by", sa.String(255), nullable=True),
            sa.Column("updated_by", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hit_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata_json", sa.JSON, nullable=True),
        )
        op.create_index("idx_ip_rules_active_priority", "ip_rules", ["is_active", "priority"])

    if "ip_blocks" not in existing_tables:
        op.create_table(
            "ip_blocks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("ip_address", sa.String(45), nullable=False),
            sa.Column("reason", sa.Text, nullable=False),
            sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("blocked_by", sa.String(255), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
            sa.Column("unblocked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("unblocked_by", sa.String(255), nullable=True),
        )
        op.create_index("idx_ip_blocks_active_expires", "ip_blocks", ["is_active", "expires_at"])
        op.create_index("idx_ip_blocks_ip_active", "ip_blocks", ["ip_address", "is_active"])


def downgrade() -> None:
    """Drop ip_rules and ip_blocks tables."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = inspector.get_table_names()

    if "ip_blocks" in existing_tables:
        op.drop_index("idx_ip_blocks_ip_active", table_name="ip_blocks")
        op.drop_index("idx_ip_blocks_active_expires", table_name="ip_blocks")
        op.drop_table("ip_blocks")

    if "ip_rules" in existing_tables:
        op.drop_index("idx_ip_rules_active_priority", table_name="ip_rules")
        op.drop_table("ip_rules")
