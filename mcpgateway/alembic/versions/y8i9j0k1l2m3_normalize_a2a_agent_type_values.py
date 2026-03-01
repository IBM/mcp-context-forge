# -*- coding: utf-8 -*-
"""Normalize legacy A2A agent_type values to canonical transport names.

Revision ID: y8i9j0k1l2m3
Revises: 2af2fa379eb9
Create Date: 2026-02-16 00:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "y8i9j0k1l2m3"
down_revision: Union[str, Sequence[str], None] = "2af2fa379eb9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Map legacy agent_type values (generic/jsonrpc/etc) to canonical names."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "a2a_agents" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("a2a_agents")}
    if "agent_type" not in columns:
        return

    # Ensure empty/null values get a safe default.
    op.execute(sa.text("UPDATE a2a_agents SET agent_type = 'a2a-jsonrpc' WHERE agent_type IS NULL OR TRIM(agent_type) = ''"))

    # Canonicalize common aliases. Use LOWER() to handle historical capitalization differences.
    op.execute(sa.text("UPDATE a2a_agents SET agent_type = 'a2a-jsonrpc' WHERE LOWER(agent_type) IN ('a2a', 'generic', 'jsonrpc', 'a2a_jsonrpc')"))
    op.execute(sa.text("UPDATE a2a_agents SET agent_type = 'a2a-rest' WHERE LOWER(agent_type) IN ('rest', 'a2a_rest')"))
    op.execute(sa.text("UPDATE a2a_agents SET agent_type = 'a2a-grpc' WHERE LOWER(agent_type) IN ('grpc', 'a2a_grpc')"))
    op.execute(sa.text("UPDATE a2a_agents SET agent_type = 'rest-passthrough' WHERE LOWER(agent_type) IN ('passthrough', 'rest_passthrough', 'openai', 'anthropic')"))


def downgrade() -> None:
    """No-op downgrade.

    This migration is intentionally one-way: multiple legacy values map into the
    same canonical transport name, so downgrading would be lossy and unsafe.
    """
    return
