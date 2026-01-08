# -*- coding: utf-8 -*-
"""add prompt namespacing fields

Revision ID: r2b3c4d5e6f7
Revises: k5e6f7g8h9i0, 4f07c116f917, z1a2b3c4d5e6
Create Date: 2025-12-19 00:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.create_slug import slugify

# revision identifiers, used by Alembic.
revision: str = "r2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = ("k5e6f7g8h9i0", "4f07c116f917", "z1a2b3c4d5e6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add prompt name fields and backfill namespaced values."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("prompts"):
        print("Prompts table not found. Skipping prompt namespacing migration.")
        return

    columns = [col["name"] for col in inspector.get_columns("prompts")]

    with op.batch_alter_table("prompts") as batch_op:
        if "original_name" not in columns:
            batch_op.add_column(sa.Column("original_name", sa.String(255), nullable=True))
        if "custom_name" not in columns:
            batch_op.add_column(sa.Column("custom_name", sa.String(255), nullable=True))
        if "custom_name_slug" not in columns:
            batch_op.add_column(sa.Column("custom_name_slug", sa.String(255), nullable=True))
        if "display_name" not in columns:
            batch_op.add_column(sa.Column("display_name", sa.String(255), nullable=True))

    connection = bind
    separator = settings.gateway_tool_name_separator

    rows = (
        connection.execute(
            sa.text(
                """
            SELECT p.id, p.name, p.gateway_id, p.team_id, p.owner_email, g.name AS gateway_name
            FROM prompts p
            LEFT JOIN gateways g ON p.gateway_id = g.id
            """
            )
        )
        .mappings()
        .all()
    )

    seen_gateway_original: dict[tuple[str, str], int] = {}
    seen_scoped_names: set[tuple[Union[str, None], Union[str, None], str]] = set()

    for row in rows:
        base_original = row["name"] or ""
        original_name = base_original

        if row["gateway_id"]:
            key = (row["gateway_id"], base_original)
            count = seen_gateway_original.get(key, 0) + 1
            seen_gateway_original[key] = count
            if count > 1:
                original_name = f"{base_original}-{count}"

        custom_name = original_name
        custom_name_slug = slugify(custom_name)

        gateway_slug = slugify(row["gateway_name"]) if row["gateway_name"] else ""
        if gateway_slug:
            name = f"{gateway_slug}{separator}{custom_name_slug}"
        else:
            name = custom_name_slug

        scope_key = (row["team_id"], row["owner_email"], name)
        if scope_key in seen_scoped_names:
            suffix = 2
            while True:
                candidate_custom_name = f"{custom_name}-{suffix}"
                candidate_slug = slugify(candidate_custom_name)
                if gateway_slug:
                    candidate_name = f"{gateway_slug}{separator}{candidate_slug}"
                else:
                    candidate_name = candidate_slug
                candidate_scope = (row["team_id"], row["owner_email"], candidate_name)
                if candidate_scope not in seen_scoped_names:
                    custom_name = candidate_custom_name
                    custom_name_slug = candidate_slug
                    name = candidate_name
                    scope_key = candidate_scope
                    break
                suffix += 1

        seen_scoped_names.add(scope_key)
        display_name = custom_name

        connection.execute(
            sa.text(
                """
                UPDATE prompts
                SET original_name = :original_name,
                    custom_name = :custom_name,
                    custom_name_slug = :custom_name_slug,
                    display_name = :display_name,
                    name = :name
                WHERE id = :prompt_id
                """
            ),
            {
                "original_name": original_name,
                "custom_name": custom_name,
                "custom_name_slug": custom_name_slug,
                "display_name": display_name,
                "name": name,
                "prompt_id": row["id"],
            },
        )

    connection.commit()

    unique_constraints = {uc["name"] for uc in inspector.get_unique_constraints("prompts")}

    with op.batch_alter_table("prompts") as batch_op:
        batch_op.alter_column("original_name", nullable=False)
        batch_op.alter_column("custom_name", nullable=False)
        batch_op.alter_column("custom_name_slug", nullable=False)
        if "uq_gateway_id__original_name_prompt" not in unique_constraints:
            batch_op.create_unique_constraint("uq_gateway_id__original_name_prompt", ["gateway_id", "original_name"])


def downgrade() -> None:
    """Remove prompt name fields added for namespacing."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("prompts"):
        return

    unique_constraints = {uc["name"] for uc in inspector.get_unique_constraints("prompts")}
    columns = [col["name"] for col in inspector.get_columns("prompts")]

    with op.batch_alter_table("prompts") as batch_op:
        if "uq_gateway_id__original_name_prompt" in unique_constraints:
            batch_op.drop_constraint("uq_gateway_id__original_name_prompt", type_="unique")
        if "display_name" in columns:
            batch_op.drop_column("display_name")
        if "custom_name_slug" in columns:
            batch_op.drop_column("custom_name_slug")
        if "custom_name" in columns:
            batch_op.drop_column("custom_name")
        if "original_name" in columns:
            batch_op.drop_column("original_name")
