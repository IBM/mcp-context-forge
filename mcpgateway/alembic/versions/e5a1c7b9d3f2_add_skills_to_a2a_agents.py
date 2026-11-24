# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/e5a1c7b9d3f2_add_skills_to_a2a_agents.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add skills column to a2a_agents table.

Revision ID: e5a1c7b9d3f2
Revises: e5c2a7b91f4d
Create Date: 2026-11-03

Moves agent skills out of the free-form capabilities JSON. Existing rows keep
skills in capabilities and are read through a fallback.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5a1c7b9d3f2"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e5c2a7b91f4d"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add skills column to a2a_agents table."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agents" not in inspector.get_table_names():
        return
    if "skills" in [col["name"] for col in inspector.get_columns("a2a_agents")]:
        return
    with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("skills", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove skills column from a2a_agents table."""
    inspector = sa.inspect(op.get_bind())
    if "a2a_agents" not in inspector.get_table_names():
        return
    if "skills" not in [col["name"] for col in inspector.get_columns("a2a_agents")]:
        return
    with op.batch_alter_table("a2a_agents", schema=None) as batch_op:
        batch_op.drop_column("skills")
