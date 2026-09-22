# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/e5f6a7b8c9d0_add_external_group_mappings.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

add_external_group_mappings

Revision ID: e5f6a7b8c9d0
Revises: a824749abd27
Create Date: 2026-09-10 09:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a824749abd27"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# One group maps to exactly one CF team and one role. The unique constraint on
# (issuer, tenant, external_group_id) enforces this. The co-location of cf_role
# in the same row is intentional: a single Entra group can grant both team
# membership and invocation role in one admin operation. If future requirements
# need one group to grant membership in multiple teams, relax the unique
# constraint or add a separate cf_role_overrides table.
TABLE_NAME = "external_group_mappings"
UNIQUE_CONSTRAINT = "uq_external_group_mappings_identity"

_COLUMNS = (
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("issuer", sa.String(length=512), nullable=False),
    sa.Column("tenant", sa.String(length=512), nullable=True),
    sa.Column("external_group_id", sa.String(length=512), nullable=False),
    sa.Column("cf_team_id", sa.String(length=255), nullable=False),
    # cf_role is a plain String with no foreign key: roles.name has only a
    # partial unique index, so name alone cannot be an FK target. Existence is
    # validated at the application level against the roles table.
    sa.Column("cf_role", sa.String(length=255), nullable=True),
    sa.Column("validation_status", sa.String(length=50), server_default="valid", nullable=False),
    sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
)


def upgrade() -> None:
    """Create the external_group_mappings table (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # Skip if the teams table does not exist (fresh DB uses db.py models directly)
    if "email_teams" not in tables:
        return

    if TABLE_NAME not in tables:
        op.create_table(
            TABLE_NAME,
            *_COLUMNS,
            sa.ForeignKeyConstraint(["cf_team_id"], ["email_teams.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("issuer", "tenant", "external_group_id", name=UNIQUE_CONSTRAINT),
        )
        return

    # Partial-apply recovery: add any missing columns to an existing table
    columns = [col["name"] for col in inspector.get_columns(TABLE_NAME)]
    missing = [col for col in _COLUMNS if col.name not in columns]
    if missing:
        with op.batch_alter_table(TABLE_NAME, schema=None) as batch_op:
            for col in missing:
                batch_op.add_column(col)

    constraints = [con["name"] for con in inspector.get_unique_constraints(TABLE_NAME)]
    if UNIQUE_CONSTRAINT not in constraints:
        with op.batch_alter_table(TABLE_NAME, schema=None) as batch_op:
            batch_op.create_unique_constraint(UNIQUE_CONSTRAINT, ["issuer", "tenant", "external_group_id"])


def downgrade() -> None:
    """Drop the external_group_mappings table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if TABLE_NAME not in inspector.get_table_names():
        return

    op.drop_table(TABLE_NAME)
