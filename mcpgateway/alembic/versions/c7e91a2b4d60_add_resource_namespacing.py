# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/c7e91a2b4d60_add_resource_namespacing.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add persisted resource namespacing.

Revision ID: c7e91a2b4d60
Revises: 5e211ec89cad

Downgrade restores federated upstream names and discards manual base overrides.
It uses stored values only, independently of the current separator configuration.
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.create_slug import slugify

revision: str = "c7e91a2b4d60"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "5e211ec89cad"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Initialize naming state once and prefix federated resources."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("resources"):
        return
    columns = {column["name"] for column in inspector.get_columns("resources")}
    for name in ("original_name", "custom_name_slug"):
        if name not in columns:
            op.add_column("resources", sa.Column(name, sa.Text(), nullable=True))

    rows = (
        bind.execute(sa.text("SELECT r.id, r.name, r.gateway_id, g.name AS gateway_name " "FROM resources r LEFT JOIN gateways g ON r.gateway_id = g.id " "WHERE r.original_name IS NULL"))
        .mappings()
        .all()
    )
    for row in rows:
        base = slugify(row["name"])
        gateway_slug = slugify(row["gateway_name"]) if row["gateway_id"] and row["gateway_name"] else ""
        name = row["name"]
        if gateway_slug:
            name = (f"{gateway_slug}{settings.gateway_tool_name_separator}{base}" if base else gateway_slug)[:255]
        bind.execute(
            sa.text("UPDATE resources SET original_name = :original, custom_name_slug = :base, name = :name WHERE id = :id"),
            {"id": row["id"], "original": row["name"], "base": base, "name": name},
        )


def downgrade() -> None:
    """Restore upstream names, leaving local names unchanged, then drop naming state."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("resources"):
        return
    columns = {column["name"] for column in inspector.get_columns("resources")}
    if "original_name" in columns:
        bind.execute(sa.text("UPDATE resources SET name = original_name WHERE gateway_id IS NOT NULL AND original_name IS NOT NULL"))
    with op.batch_alter_table("resources") as batch:
        for name in ("custom_name_slug", "original_name"):
            if name in columns:
                batch.drop_column(name)
