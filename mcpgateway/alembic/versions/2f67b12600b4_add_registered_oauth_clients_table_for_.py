# -*- coding: utf-8 -*-
"""Add registered_oauth_clients table for DCR

Revision ID: 2f67b12600b4
Revises: 61ee11c482d6
Create Date: 2025-09-30 15:51:10.600647

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "2f67b12600b4"
down_revision: Union[str, Sequence[str], None] = "61ee11c482d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create registered_oauth_clients table for DCR (RFC 7591)
    op.create_table(
        "registered_oauth_clients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("gateway_id", sa.String(36), sa.ForeignKey("gateways.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("issuer", sa.String(500), nullable=False),
        sa.Column("client_id", sa.String(500), nullable=False),
        sa.Column("client_secret_encrypted", sa.Text, nullable=True),
        sa.Column("redirect_uris", sa.Text, nullable=False),
        sa.Column("grant_types", sa.Text, nullable=False),
        sa.Column("response_types", sa.Text, nullable=True),
        sa.Column("scope", sa.String(1000), nullable=True),
        sa.Column("token_endpoint_auth_method", sa.String(50), server_default="client_secret_basic"),
        sa.Column("registration_client_uri", sa.String(500), nullable=True),
        sa.Column("registration_access_token_encrypted", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
    )

    # Create unique index on (gateway_id, issuer)
    op.create_index("idx_gateway_issuer", "registered_oauth_clients", ["gateway_id", "issuer"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index and table
    op.drop_index("idx_gateway_issuer", table_name="registered_oauth_clients")
    op.drop_table("registered_oauth_clients")
