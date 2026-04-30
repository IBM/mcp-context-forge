# -*- coding: utf-8 -*-
# pylint: disable=no-member
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/a3c38b6c2437_fix_a2a_agents_auth_value.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

fix_a2a_agents_auth_value

Revision ID: a3c38b6c2437
Revises: e1f2a3b4c5d6
Create Date: 2026-02-25 13:27:40.837193

Fix auth_value column type in a2a_agents table from JSON to TEXT.

Background:
The auth_value column was originally typed as JSON (Dict[str, str]) in the ORM model,
but the actual stored values were always plain strings (e.g., API tokens, bearer tokens).
This type mismatch caused issues with retrieval.

This migration:
1. Converts the column from JSON to TEXT type
2. Cleans up empty/null JSON values before type change
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3c38b6c2437"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Change auth_value column from JSON to TEXT.

    PostgreSQL:
        Alters the column type from JSON to TEXT.

    SQLite:
        No-op, because SQLite does not enforce JSON type
        and stores it as TEXT internally.
    """
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)

    if "a2a_agents" not in inspector.get_table_names():
        return

    columns = {col["name"]: col for col in inspector.get_columns("a2a_agents")}

    if "auth_value" not in columns:
        return

    current_type = columns["auth_value"]["type"]

    if isinstance(current_type, sa.Text):
        return

    if dialect == "postgresql":
        # Null out empty JSON string values ('""') and JSON null ('null') before
        # converting the column type so the USING clause does not fail on them.
        # PostgreSQL-specific cast is required here; parameterized DML cannot
        # express the ::text cast needed to compare a JSON column to a string.
        op.execute(sa.text("UPDATE a2a_agents SET auth_value = NULL WHERE auth_value::text IN ('\"\"', 'null')"))
        op.alter_column(
            "a2a_agents",
            "auth_value",
            type_=sa.Text(),
            postgresql_using="auth_value#>>'{}'",
        )


def downgrade() -> None:
    """
    Revert auth_value column from TEXT back to JSON.

    PostgreSQL:
        Alters the column type from TEXT to JSON.

    SQLite:
        No-op, because SQLite stores JSON as TEXT and does
        not enforce a separate JSON type.
    """
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)

    if "a2a_agents" not in inspector.get_table_names():
        return

    columns = {col["name"]: col for col in inspector.get_columns("a2a_agents")}

    if "auth_value" not in columns:
        return

    current_type = columns["auth_value"]["type"]

    if not isinstance(current_type, sa.Text):
        return

    if dialect == "postgresql":
        op.alter_column(
            "a2a_agents",
            "auth_value",
            type_=postgresql.JSON(astext_type=sa.Text()),
            postgresql_using="to_jsonb(auth_value)",
        )
