# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/a7c3e9d1b5f2_add_ca_certificate_to_sso_providers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add ca_certificate column to sso_providers.

Stores an optional PEM CA bundle that the gateway trusts, in addition to the
system trust store, for TLS connections to one SSO/OIDC provider (discovery,
token exchange, userinfo, JWKS).

Revision ID: a7c3e9d1b5f2
Revises: 7ac83e50bd12
Create Date: 2026-11-16
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a7c3e9d1b5f2"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "7ac83e50bd12"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable ca_certificate column to sso_providers."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("sso_providers"):
        return
    if "ca_certificate" in [col["name"] for col in inspector.get_columns("sso_providers")]:
        return
    op.add_column("sso_providers", sa.Column("ca_certificate", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the ca_certificate column from sso_providers."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("sso_providers"):
        return
    if "ca_certificate" not in [col["name"] for col in inspector.get_columns("sso_providers")]:
        return
    op.drop_column("sso_providers", "ca_certificate")
