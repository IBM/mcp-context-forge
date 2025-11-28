# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/b77ca9d2de7e_uuid_pk_and_slug_refactor.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

uuid-pk_and_slug_refactor

Revision ID: b77ca9d2de7e
Revises:
Create Date: 2025-06-26 21:29:59.117140
"""

# Standard
from typing import Sequence, Union
import uuid

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.create_slug import slugify

# revision identifiers, used by Alembic.
revision: str = "b77ca9d2de7e"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _use_batch() -> bool:
    """Determine if batch operations are required for the current database.

    SQLite requires batch mode for certain ALTER TABLE operations like dropping
    columns or altering column types. This helper checks the database dialect
    to determine if batch operations should be used.

    Returns:
        bool: True if the database is SQLite (requires batch mode), False otherwise.

    Examples:
        >>> # In a SQLite context
        >>> _use_batch()  # doctest: +SKIP
        True
        >>> # In a PostgreSQL context
        >>> _use_batch()  # doctest: +SKIP
        False
    """
    return op.get_bind().dialect.name == "sqlite"


def column_exists(table, column, conn):
    """
    Check whether a given column exists in a database table.

    Args:
        table (str): Name of the database table to inspect.
        column (str): Name of the column to check for.
        conn (Connection): SQLAlchemy connection object used for inspection.

    Returns:
        bool: True if the column exists in the table, otherwise False.
    """
    insp = inspect(conn)
    return column in [col["name"] for col in insp.get_columns(table)]


# ──────────────────────────────────────────────────────────────────────────────
# Upgrade
# ──────────────────────────────────────────────────────────────────────────────
def upgrade() -> None:
    """Migrate database schema from integer to UUID primary keys with slugs.

    This migration performs a comprehensive schema transformation in three stages:

    Stage 1 - Add placeholder columns:
        - Adds UUID columns (id_new) to gateways, tools, and servers
        - Adds slug columns for human-readable identifiers
        - Adds columns to preserve original tool names before prefixing

    Stage 2 - Data migration:
        - Generates UUIDs for all primary keys
        - Creates slugs from names (e.g., "My Gateway" -> "my-gateway")
        - Prefixes tool names with gateway slugs (e.g., "my-tool" -> "gateway-slug-my-tool")
        - Updates all foreign key references to use new UUIDs

    Stage 3 - Schema finalization:
        - Drops old integer columns
        - Renames new UUID columns to replace old ones
        - Recreates primary keys and foreign key constraints
        - Adds unique constraints on slugs and URLs

    The migration is designed to work with both SQLite (using batch operations)
    and other databases. It preserves all existing data relationships while
    transforming the schema.

    Note:
        - Skips migration if database is fresh (no gateways table)
        - Uses batch operations for SQLite compatibility
        - Commits data changes before schema alterations

    Examples:
        >>> # Running the migration
        >>> upgrade()  # doctest: +SKIP
        Fresh database detected. Skipping migration.
        >>> # Or for existing database
        >>> upgrade()  # doctest: +SKIP
        Existing installation detected. Starting data and schema migration...
    """
    bind = op.get_bind()
    sess = Session(bind=bind)
    inspector = sa.inspect(bind)

    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    print("Existing installation detected. Starting data and schema migration...")

    # ── STAGE 1: ADD NEW NULLABLE COLUMNS AS PLACEHOLDERS ─────────────────
    if not column_exists("gateways", "slug", bind):
        op.add_column("gateways", sa.Column("slug", sa.String(255), nullable=True))
    op.add_column("gateways", sa.Column("id_new", sa.String(36), nullable=True))

    op.add_column("tools", sa.Column("id_new", sa.String(36), nullable=True))
    op.add_column("tools", sa.Column("original_name", sa.String(255), nullable=True))
    op.add_column("tools", sa.Column("original_name_slug", sa.String(255), nullable=True))
    op.add_column("tools", sa.Column("name_new", sa.String(255), nullable=True))
    op.add_column("tools", sa.Column("gateway_id_new", sa.String(36), nullable=True))

    op.add_column("resources", sa.Column("gateway_id_new", sa.String(36), nullable=True))
    op.add_column("prompts", sa.Column("gateway_id_new", sa.String(36), nullable=True))

    op.add_column("servers", sa.Column("id_new", sa.String(36), nullable=True))

    op.add_column("server_tool_association", sa.Column("server_id_new", sa.String(36), nullable=True))
    op.add_column("server_tool_association", sa.Column("tool_id_new", sa.String(36), nullable=True))

    op.add_column("tool_metrics", sa.Column("tool_id_new", sa.String(36), nullable=True))
    op.add_column("server_metrics", sa.Column("server_id_new", sa.String(36), nullable=True))
    op.add_column("server_resource_association", sa.Column("server_id_new", sa.String(36), nullable=True))
    op.add_column("server_prompt_association", sa.Column("server_id_new", sa.String(36), nullable=True))

    # ── STAGE 2: POPULATE THE NEW COLUMNS (DATA MIGRATION) ───────────────
    gateways = sess.execute(sa.select(sa.text("id, name")).select_from(sa.text("gateways"))).all()
    for gid, gname in gateways:
        g_uuid = uuid.uuid4().hex
        sess.execute(
            sa.text("UPDATE gateways SET id_new=:u, slug=:s WHERE id=:i"),
            {"u": g_uuid, "s": slugify(gname), "i": gid},
        )

    tools = sess.execute(sa.select(sa.text("id, name, gateway_id")).select_from(sa.text("tools"))).all()
    for tid, tname, g_old in tools:
        t_uuid = uuid.uuid4().hex
        tool_slug = slugify(tname)
        sess.execute(
            sa.text(
                """
                UPDATE tools
                SET id_new=:u,
                    original_name=:on,
                    original_name_slug=:ons,
                    name_new = CASE
                        WHEN :g IS NOT NULL THEN (SELECT slug FROM gateways WHERE id = :g) || :sep || :ons
                        ELSE :ons
                    END,
                    gateway_id_new=(SELECT id_new FROM gateways WHERE id=:g)
                WHERE id=:i
                """
            ),
            {
                "u": t_uuid,
                "on": tname,
                "ons": tool_slug,
                "sep": settings.gateway_tool_name_separator,
                "g": g_old,
                "i": tid,
            },
        )

    servers = sess.execute(sa.select(sa.text("id")).select_from(sa.text("servers"))).all()
    for (sid,) in servers:
        sess.execute(
            sa.text("UPDATE servers SET id_new=:u WHERE id=:i"),
            {"u": uuid.uuid4().hex, "i": sid},
        )

    # Populate all dependent tables
    resources = sess.execute(sa.select(sa.text("id, gateway_id")).select_from(sa.text("resources"))).all()
    for rid, g_old in resources:
        sess.execute(sa.text("UPDATE resources SET gateway_id_new=(SELECT id_new FROM gateways WHERE id=:g) WHERE id=:i"), {"g": g_old, "i": rid})
    prompts = sess.execute(sa.select(sa.text("id, gateway_id")).select_from(sa.text("prompts"))).all()
    for pid, g_old in prompts:
        sess.execute(sa.text("UPDATE prompts SET gateway_id_new=(SELECT id_new FROM gateways WHERE id=:g) WHERE id=:i"), {"g": g_old, "i": pid})
    sta = sess.execute(sa.select(sa.text("server_id, tool_id")).select_from(sa.text("server_tool_association"))).all()
    for s_old, t_old in sta:
        sess.execute(
            sa.text("UPDATE server_tool_association SET server_id_new=(SELECT id_new FROM servers WHERE id=:s), tool_id_new=(SELECT id_new FROM tools WHERE id=:t) WHERE server_id=:s AND tool_id=:t"),
            {"s": s_old, "t": t_old},
        )
    tool_metrics = sess.execute(sa.select(sa.text("id, tool_id")).select_from(sa.text("tool_metrics"))).all()
    for tmid, t_old in tool_metrics:
        sess.execute(sa.text("UPDATE tool_metrics SET tool_id_new=(SELECT id_new FROM tools WHERE id=:t) WHERE id=:i"), {"t": t_old, "i": tmid})
    server_metrics = sess.execute(sa.select(sa.text("id, server_id")).select_from(sa.text("server_metrics"))).all()
    for smid, s_old in server_metrics:
        sess.execute(sa.text("UPDATE server_metrics SET server_id_new=(SELECT id_new FROM servers WHERE id=:s) WHERE id=:i"), {"s": s_old, "i": smid})
    server_resource_assoc = sess.execute(sa.select(sa.text("server_id, resource_id")).select_from(sa.text("server_resource_association"))).all()
    for s_old, r_id in server_resource_assoc:
        sess.execute(sa.text("UPDATE server_resource_association SET server_id_new=(SELECT id_new FROM servers WHERE id=:s) WHERE server_id=:s AND resource_id=:r"), {"s": s_old, "r": r_id})
    server_prompt_assoc = sess.execute(sa.select(sa.text("server_id, prompt_id")).select_from(sa.text("server_prompt_association"))).all()
    for s_old, p_id in server_prompt_assoc:
        sess.execute(sa.text("UPDATE server_prompt_association SET server_id_new=(SELECT id_new FROM servers WHERE id=:s) WHERE server_id=:s AND prompt_id=:p"), {"s": s_old, "p": p_id})

    sess.commit()

    # ── STAGE 3: FINALIZE SCHEMA (CORRECTED ORDER) ───────────────────────
    # First, rebuild all tables that depend on `servers` and `gateways`.
    # This implicitly drops their old foreign key constraints.
    with op.batch_alter_table("server_tool_association") as batch_op:
        batch_op.drop_column("server_id")
        batch_op.drop_column("tool_id")
        batch_op.alter_column("server_id_new", new_column_name="server_id", nullable=False)
        batch_op.alter_column("tool_id_new", new_column_name="tool_id", nullable=False)
        batch_op.create_primary_key("pk_server_tool_association", ["server_id", "tool_id"])

    with op.batch_alter_table("server_resource_association") as batch_op:
        batch_op.drop_column("server_id")
        batch_op.alter_column("server_id_new", new_column_name="server_id", nullable=False)

    with op.batch_alter_table("server_prompt_association") as batch_op:
        batch_op.drop_column("server_id")
        batch_op.alter_column("server_id_new", new_column_name="server_id", nullable=False)

    with op.batch_alter_table("server_metrics") as batch_op:
        batch_op.drop_column("server_id")
        batch_op.alter_column("server_id_new", new_column_name="server_id", nullable=False)

    with op.batch_alter_table("tool_metrics") as batch_op:
        batch_op.drop_column("tool_id")
        batch_op.alter_column("tool_id_new", new_column_name="tool_id", nullable=False)

    with op.batch_alter_table("tools") as batch_op:
        batch_op.drop_column("id")
        batch_op.alter_column("id_new", new_column_name="id", nullable=False)
        batch_op.create_primary_key("pk_tools", ["id"])
        batch_op.drop_column("gateway_id")
        batch_op.alter_column("gateway_id_new", new_column_name="gateway_id", nullable=True)
        batch_op.drop_column("name")
        batch_op.alter_column("name_new", new_column_name="name", nullable=True)
        batch_op.alter_column("original_name", nullable=False)
        batch_op.alter_column("original_name_slug", nullable=False)
        batch_op.create_unique_constraint("uq_tools_name", ["name"])
        batch_op.create_unique_constraint("uq_gateway_id__original_name", ["gateway_id", "original_name"])

    with op.batch_alter_table("resources") as batch_op:
        batch_op.drop_column("gateway_id")
        batch_op.alter_column("gateway_id_new", new_column_name="gateway_id", nullable=True)

    with op.batch_alter_table("prompts") as batch_op:
        batch_op.drop_column("gateway_id")
        batch_op.alter_column("gateway_id_new", new_column_name="gateway_id", nullable=True)

    # Second, now that no tables point to their old IDs, rebuild `gateways` and `servers`.
    with op.batch_alter_table("gateways") as batch_op:
        batch_op.drop_column("id")
        batch_op.alter_column("id_new", new_column_name="id", nullable=False)
        batch_op.create_primary_key("pk_gateways", ["id"])
        batch_op.alter_column("slug", nullable=False)
        batch_op.create_unique_constraint("uq_gateways_slug", ["slug"])
        batch_op.create_unique_constraint("uq_gateways_url", ["url"])

    with op.batch_alter_table("servers") as batch_op:
        batch_op.drop_column("id")
        batch_op.alter_column("id_new", new_column_name="id", nullable=False)
        batch_op.create_primary_key("pk_servers", ["id"])

    # Finally, recreate all the foreign key constraints in batch mode for SQLite compatibility.
    # The redundant `source_table` argument has been removed from each call.
    with op.batch_alter_table("tools") as batch_op:
        batch_op.create_foreign_key("fk_tools_gateway_id", "gateways", ["gateway_id"], ["id"])
    with op.batch_alter_table("resources") as batch_op:
        batch_op.create_foreign_key("fk_resources_gateway_id", "gateways", ["gateway_id"], ["id"])
    with op.batch_alter_table("prompts") as batch_op:
        batch_op.create_foreign_key("fk_prompts_gateway_id", "gateways", ["gateway_id"], ["id"])
    with op.batch_alter_table("server_tool_association") as batch_op:
        batch_op.create_foreign_key("fk_server_tool_association_servers", "servers", ["server_id"], ["id"])
        batch_op.create_foreign_key("fk_server_tool_association_tools", "tools", ["tool_id"], ["id"])
    with op.batch_alter_table("tool_metrics") as batch_op:
        batch_op.create_foreign_key("fk_tool_metrics_tool_id", "tools", ["tool_id"], ["id"])
    with op.batch_alter_table("server_metrics") as batch_op:
        batch_op.create_foreign_key("fk_server_metrics_server_id", "servers", ["server_id"], ["id"])
    with op.batch_alter_table("server_resource_association") as batch_op:
        batch_op.create_foreign_key("fk_server_resource_association_server_id", "servers", ["server_id"], ["id"])
    with op.batch_alter_table("server_prompt_association") as batch_op:
        batch_op.create_foreign_key("fk_server_prompt_association_server_id", "servers", ["server_id"], ["id"])


# def upgrade() -> None:
#     bind = op.get_bind()
#     sess = Session(bind=bind)
#     inspector = sa.inspect(bind)

#     if not inspector.has_table("gateways"):
#         print("Fresh database detected. Skipping migration.")
#         return

#     print("Existing installation detected. Starting data and schema migration...")

#     # ── STAGE 1: ADD NEW NULLABLE COLUMNS AS PLACEHOLDERS ─────────────────
#     op.add_column("gateways", sa.Column("slug", sa.String(), nullable=True))
#     op.add_column("gateways", sa.Column("id_new", sa.String(36), nullable=True))

#     op.add_column("tools", sa.Column("id_new", sa.String(36), nullable=True))
#     op.add_column("tools", sa.Column("original_name", sa.String(), nullable=True))
#     op.add_column("tools", sa.Column("original_name_slug", sa.String(), nullable=True))
#     op.add_column("tools", sa.Column("name_new", sa.String(), nullable=True))
#     op.add_column("tools", sa.Column("gateway_id_new", sa.String(36), nullable=True))

#     op.add_column("resources", sa.Column("gateway_id_new", sa.String(36), nullable=True))
#     op.add_column("prompts", sa.Column("gateway_id_new", sa.String(36), nullable=True))

#     op.add_column("servers", sa.Column("id_new", sa.String(36), nullable=True))

#     op.add_column("server_tool_association", sa.Column("server_id_new", sa.String(36), nullable=True))
#     op.add_column("server_tool_association", sa.Column("tool_id_new", sa.String(36), nullable=True))

#     op.add_column("tool_metrics", sa.Column("tool_id_new", sa.String(36), nullable=True))

#     # Add columns for the new server dependencies
#     op.add_column("server_metrics", sa.Column("server_id_new", sa.String(36), nullable=True))
#     op.add_column("server_resource_association", sa.Column("server_id_new", sa.String(36), nullable=True))
#     op.add_column("server_prompt_association", sa.Column("server_id_new", sa.String(36), nullable=True))


#     # ── STAGE 2: POPULATE THE NEW COLUMNS (DATA MIGRATION) ───────────────
#     gateways = sess.execute(sa.select(sa.text("id, name")).select_from(sa.text("gateways"))).all()
#     for gid, gname in gateways:
#         g_uuid = uuid.uuid4().hex
#         sess.execute(
#             sa.text("UPDATE gateways SET id_new=:u, slug=:s WHERE id=:i"),
#             {"u": g_uuid, "s": slugify(gname), "i": gid},
#         )

#     tools = sess.execute(
#         sa.select(sa.text("id, name, gateway_id")).select_from(sa.text("tools"))
#     ).all()
#     for tid, tname, g_old in tools:
#         t_uuid = uuid.uuid4().hex
#         tool_slug = slugify(tname)
#         sess.execute(
#             sa.text(
#                 """
#                 UPDATE tools
#                 SET id_new=:u,
#                     original_name=:on,
#                     original_name_slug=:ons,
#                     name_new = CASE
#                         WHEN :g IS NOT NULL THEN (SELECT slug FROM gateways WHERE id = :g) || :sep || :ons
#                         ELSE :ons
#                     END,
#                     gateway_id_new=(SELECT id_new FROM gateways WHERE id=:g)
#                 WHERE id=:i
#                 """
#             ),
#             {
#                 "u": t_uuid, "on": tname, "ons": tool_slug,
#                 "sep": settings.gateway_tool_name_separator, "g": g_old, "i": tid,
#             },
#         )

#     servers = sess.execute(sa.select(sa.text("id")).select_from(sa.text("servers"))).all()
#     for (sid,) in servers:
#         sess.execute(
#             sa.text("UPDATE servers SET id_new=:u WHERE id=:i"),
#             {"u": uuid.uuid4().hex, "i": sid},
#         )

#     # Populate all dependent tables
#     resources = sess.execute(sa.select(sa.text("id, gateway_id")).select_from(sa.text("resources"))).all()
#     for rid, g_old in resources:
#         sess.execute(sa.text("UPDATE resources SET gateway_id_new=(SELECT id_new FROM gateways WHERE id=:g) WHERE id=:i"), {"g": g_old, "i": rid})
#     prompts = sess.execute(sa.select(sa.text("id, gateway_id")).select_from(sa.text("prompts"))).all()
#     for pid, g_old in prompts:
#         sess.execute(sa.text("UPDATE prompts SET gateway_id_new=(SELECT id_new FROM gateways WHERE id=:g) WHERE id=:i"), {"g": g_old, "i": pid})
#     sta = sess.execute(sa.select(sa.text("server_id, tool_id")).select_from(sa.text("server_tool_association"))).all()
#     for s_old, t_old in sta:
#         sess.execute(sa.text("UPDATE server_tool_association SET server_id_new=(SELECT id_new FROM servers WHERE id=:s), tool_id_new=(SELECT id_new FROM tools WHERE id=:t) WHERE server_id=:s AND tool_id=:t"), {"s": s_old, "t": t_old})
#     tool_metrics = sess.execute(sa.select(sa.text("id, tool_id")).select_from(sa.text("tool_metrics"))).all()
#     for tmid, t_old in tool_metrics:
#         sess.execute(sa.text("UPDATE tool_metrics SET tool_id_new=(SELECT id_new FROM tools WHERE id=:t) WHERE id=:i"), {"t": t_old, "i": tmid})
#     server_metrics = sess.execute(sa.select(sa.text("id, server_id")).select_from(sa.text("server_metrics"))).all()
#     for smid, s_old in server_metrics:
#         sess.execute(sa.text("UPDATE server_metrics SET server_id_new=(SELECT id_new FROM servers WHERE id=:s) WHERE id=:i"), {"s": s_old, "i": smid})
#     server_resource_assoc = sess.execute(sa.select(sa.text("server_id, resource_id")).select_from(sa.text("server_resource_association"))).all()
#     for s_old, r_id in server_resource_assoc:
#         sess.execute(sa.text("UPDATE server_resource_association SET server_id_new=(SELECT id_new FROM servers WHERE id=:s) WHERE server_id=:s AND resource_id=:r"), {"s": s_old, "r": r_id})
#     server_prompt_assoc = sess.execute(sa.select(sa.text("server_id, prompt_id")).select_from(sa.text("server_prompt_association"))).all()
#     for s_old, p_id in server_prompt_assoc:
#         sess.execute(sa.text("UPDATE server_prompt_association SET server_id_new=(SELECT id_new FROM servers WHERE id=:s) WHERE server_id=:s AND prompt_id=:p"), {"s": s_old, "p": p_id})

#     sess.commit()

#     # ── STAGE 3: FINALIZE SCHEMA (CORRECTED ORDER) ───────────────────────
#     with op.batch_alter_table("server_tool_association") as batch_op:
#         batch_op.drop_column("server_id")
#         batch_op.drop_column("tool_id")
#         batch_op.alter_column("server_id_new", new_column_name="server_id", nullable=False)
#         batch_op.alter_column("tool_id_new", new_column_name="tool_id", nullable=False)
#         batch_op.create_primary_key("pk_server_tool_association", ["server_id", "tool_id"])

#     with op.batch_alter_table("server_resource_association") as batch_op:
#         batch_op.drop_column("server_id")
#         batch_op.alter_column("server_id_new", new_column_name="server_id", nullable=False)

#     with op.batch_alter_table("server_prompt_association") as batch_op:
#         batch_op.drop_column("server_id")
#         batch_op.alter_column("server_id_new", new_column_name="server_id", nullable=False)

#     with op.batch_alter_table("server_metrics") as batch_op:
#         batch_op.drop_column("server_id")
#         batch_op.alter_column("server_id_new", new_column_name="server_id", nullable=False)

#     with op.batch_alter_table("tool_metrics") as batch_op:
#         batch_op.drop_column("tool_id")
#         batch_op.alter_column("tool_id_new", new_column_name="tool_id", nullable=False)

#     with op.batch_alter_table("tools") as batch_op:
#         batch_op.drop_column("id")
#         batch_op.alter_column("id_new", new_column_name="id", nullable=False)
#         batch_op.create_primary_key("pk_tools", ["id"])
#         batch_op.drop_column("gateway_id")
#         batch_op.alter_column("gateway_id_new", new_column_name="gateway_id", nullable=True)
#         batch_op.drop_column("name")
#         batch_op.alter_column("name_new", new_column_name="name", nullable=False)
#         batch_op.alter_column("original_name", nullable=False)
#         batch_op.alter_column("original_name_slug", nullable=False)
#         batch_op.create_unique_constraint("uq_tools_name", ["name"])
#         batch_op.create_unique_constraint("uq_gateway_id__original_name", ["gateway_id", "original_name"])

#     with op.batch_alter_table("resources") as batch_op:
#         batch_op.drop_column("gateway_id")
#         batch_op.alter_column("gateway_id_new", new_column_name="gateway_id", nullable=True)

#     with op.batch_alter_table("prompts") as batch_op:
#         batch_op.drop_column("gateway_id")
#         batch_op.alter_column("gateway_id_new", new_column_name="gateway_id", nullable=True)

#     with op.batch_alter_table("gateways") as batch_op:
#         batch_op.drop_column("id")
#         batch_op.alter_column("id_new", new_column_name="id", nullable=False)
#         batch_op.create_primary_key("pk_gateways", ["id"])
#         batch_op.alter_column("slug", nullable=False)
#         batch_op.create_unique_constraint("uq_gateways_slug", ["slug"])
#         batch_op.create_unique_constraint("uq_gateways_url", ["url"])

#     with op.batch_alter_table("servers") as batch_op:
#         batch_op.drop_column("id")
#         batch_op.alter_column("id_new", new_column_name="id", nullable=False)
#         batch_op.create_primary_key("pk_servers", ["id"])

#     # Finally, recreate all the foreign key constraints
#     op.create_foreign_key("fk_tools_gateway_id", "tools", "gateways", ["gateway_id"], ["id"])
#     op.create_foreign_key("fk_resources_gateway_id", "resources", "gateways", ["gateway_id"], ["id"])
#     op.create_foreign_key("fk_prompts_gateway_id", "prompts", "gateways", ["gateway_id"], ["id"])
#     op.create_foreign_key("fk_server_tool_association_servers", "server_tool_association", "servers", ["server_id"], ["id"])
#     op.create_foreign_key("fk_server_tool_association_tools", "server_tool_association", "tools", ["tool_id"], ["id"])
#     op.create_foreign_key("fk_tool_metrics_tool_id", "tool_metrics", "tools", ["tool_id"], ["id"])
#     op.create_foreign_key("fk_server_metrics_server_id", "server_metrics", "servers", ["server_id"], ["id"])
#     op.create_foreign_key("fk_server_resource_association_server_id", "server_resource_association", "servers", ["server_id"], ["id"])
#     op.create_foreign_key("fk_server_prompt_association_server_id", "server_prompt_association", "servers", ["server_id"], ["id"])


def downgrade() -> None:
    """Revert database schema from UUID primary keys back to integers.

    This downgrade reverses the UUID migration but with significant limitations:
    - Schema structure is restored but data is NOT preserved
    - All UUID values and slug fields are lost
    - Foreign key relationships are broken (columns will be NULL)
    - Original integer IDs cannot be recovered

    The downgrade operates in reverse order of the upgrade:

    Stage 1 - Revert schema changes:
        - Drops UUID-based constraints and keys
        - Renames UUID columns back to temporary names
        - Re-adds integer columns (empty/NULL)

    Stage 2 - Data migration (skipped):
        - Original integer IDs cannot be restored from UUIDs
        - Relationships cannot be reconstructed

    Stage 3 - Remove temporary columns:
        - Drops all UUID and slug columns
        - Leaves database with original schema but no data

    Warning:
        This downgrade is destructive and should only be used if you need
        to revert the schema structure. All data in affected tables will
        need to be manually restored from backups.

    Examples:
        >>> # Running the downgrade
        >>> downgrade()  # doctest: +SKIP
        # Schema reverted but data is lost
    """
    # ── STAGE 1 (REVERSE): Revert Schema to original state ─────────────────
    # This reverses the operations from STAGE 3 of the upgrade.
    # Data from the new columns will be lost, which is expected.

    with op.batch_alter_table("server_tool_association") as batch_op:
        # Drop new constraints
        batch_op.drop_constraint("fk_server_tool_association_tools", type_="foreignkey")
        batch_op.drop_constraint("fk_server_tool_association_servers", type_="foreignkey")
        batch_op.drop_constraint("pk_server_tool_association", type_="primarykey")
        # Rename final columns back to temporary names
        batch_op.alter_column("server_id", new_column_name="server_id_new")
        batch_op.alter_column("tool_id", new_column_name="tool_id_new")
        # Add back old integer columns (data is not restored)
        batch_op.add_column(sa.Column("server_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tool_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("tools") as batch_op:
        # Drop new constraints
        batch_op.drop_constraint("fk_tools_gateway_id", type_="foreignkey")
        batch_op.drop_constraint("uq_gateway_id__original_name", type_="unique")
        batch_op.drop_constraint("uq_tools_name", type_="unique")
        batch_op.drop_constraint("pk_tools", type_="primarykey")
        # Rename final columns back to temporary names
        batch_op.alter_column("id", new_column_name="id_new")
        batch_op.alter_column("gateway_id", new_column_name="gateway_id_new")
        batch_op.alter_column("name", new_column_name="name_new")
        # Add back old columns
        batch_op.add_column(sa.Column("id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("gateway_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("name", sa.String(255), nullable=True))

    with op.batch_alter_table("servers") as batch_op:
        batch_op.drop_constraint("pk_servers", type_="primarykey")
        batch_op.alter_column("id", new_column_name="id_new")
        batch_op.add_column(sa.Column("id", sa.Integer(), nullable=True))

    with op.batch_alter_table("gateways") as batch_op:
        batch_op.drop_constraint("uq_gateways_url", type_="unique")
        batch_op.drop_constraint("uq_gateways_slug", type_="unique")
        batch_op.drop_constraint("pk_gateways", type_="primarykey")
        batch_op.alter_column("id", new_column_name="id_new")
        batch_op.add_column(sa.Column("id", sa.Integer(), nullable=True))

    # ── STAGE 2 (REVERSE): Reverse Data Migration (No-Op for Schema) ──────
    # Reversing the data population (e.g., creating integer PKs from UUIDs)
    # is a complex, stateful operation and is omitted here. At this point,
    # the original columns exist but are empty (NULL).

    # ── STAGE 3 (REVERSE): Drop the temporary/new columns ────────────────
    # This reverses the operations from STAGE 1 of the upgrade.
    op.drop_column("server_tool_association", "tool_id_new")
    op.drop_column("server_tool_association", "server_id_new")
    op.drop_column("servers", "id_new")
    op.drop_column("tools", "gateway_id_new")
    op.drop_column("tools", "name_new")
    op.drop_column("tools", "original_name_slug")
    op.drop_column("tools", "original_name")
    op.drop_column("tools", "id_new")
    op.drop_column("gateways", "id_new")
    op.drop_column("gateways", "slug")
