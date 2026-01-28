# -*- coding: utf-8 -*-
"""Add grpc_services table

Revision ID: 3c89a45f32e5
Revises: g1a2b3c4d5e6
Create Date: 2025-10-05 12:00:00.000000

"""
# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "3c89a45f32e5"
down_revision: Union[str, Sequence[str], None] = "g1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create grpc_services table for gRPC service management
    op.create_table(
        "grpc_services",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("slug", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("target", sa.String(767), nullable=False),
        # Configuration
        sa.Column("reflection_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("tls_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("tls_cert_path", sa.String(767), nullable=True),
        sa.Column("tls_key_path", sa.String(767), nullable=True),
        sa.Column("grpc_metadata", sa.JSON, nullable=True),
        # Status
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("reachable", sa.Boolean, nullable=False, server_default=sa.false()),
        # Discovery
        sa.Column("service_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("method_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("discovered_services", sa.JSON, nullable=True),
        sa.Column("last_reflection", sa.DateTime(timezone=True), nullable=True),
        # Tags
        sa.Column("tags", sa.JSON, nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Audit metadata
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_from_ip", sa.String(45), nullable=True),
        sa.Column("created_via", sa.String(100), nullable=True),
        sa.Column("created_user_agent", sa.Text, nullable=True),
        sa.Column("modified_by", sa.String(255), nullable=True),
        sa.Column("modified_from_ip", sa.String(45), nullable=True),
        sa.Column("modified_via", sa.String(100), nullable=True),
        sa.Column("modified_user_agent", sa.Text, nullable=True),
        sa.Column("import_batch_id", sa.String(36), nullable=True),
        sa.Column("federation_source", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        # Team scoping
        sa.Column("team_id", sa.String(36), sa.ForeignKey("email_teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_email", sa.String(255), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("grpc_services")
