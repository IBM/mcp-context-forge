"""uuid-pk_and_slug_refactor

Revision ID: b77ca9d2de7e
Revises: 
Create Date: 2025-06-26 21:29:59.117140

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.orm import Session

from alembic import op
from mcpgateway.config import settings
from mcpgateway.utils.create_slug import slugify as _slugify

# revision identifiers, used by Alembic.
revision: str = 'b77ca9d2de7e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _use_batch() -> bool:
    return op.get_bind().dialect.name == "sqlite"


# ──────────────────────────────────────────────────────────────────────────────
# Upgrade
# ──────────────────────────────────────────────────────────────────────────────
def upgrade() -> None:
    bind = op.get_bind()
    sess = Session(bind=bind)
    inspector = sa.inspect(bind)

    # ── STAGE 0: CHECK FOR EXISTING gateways table ─────────────────
    # Only run the migration if the old 'gateways' table exists.
    if not inspector.has_table("gateways"):
        return

    # ── STAGE 1: ADD NEW NULLABLE COLUMNS AS PLACEHOLDERS ─────────────────
    # We add all new columns, including temporary ones, allowing NULLs
    # so the operation succeeds on tables with existing data.

    op.add_column("gateways", sa.Column("slug", sa.String(), nullable=True))
    op.add_column("gateways", sa.Column("id_new", sa.String(36), nullable=True))

    op.add_column("tools", sa.Column("id_new", sa.String(36), nullable=True))
    op.add_column("tools", sa.Column("original_name", sa.String(), nullable=True))
    op.add_column("tools", sa.Column("original_name_slug", sa.String(), nullable=True))
    op.add_column("tools", sa.Column("name_new", sa.String(), nullable=True)) # The temporary holding column for the new name
    op.add_column("tools", sa.Column("gateway_id_new", sa.String(36), nullable=True))

    op.add_column("servers", sa.Column("id_new", sa.String(36), nullable=True))

    op.add_column("server_tool_association", sa.Column("server_id_new", sa.String(36), nullable=True))
    op.add_column("server_tool_association", sa.Column("tool_id_new", sa.String(36), nullable=True))

    # ── STAGE 2: POPULATE THE NEW COLUMNS (DATA MIGRATION) ───────────────
    # This entire block is treated as a single transaction.
    # We use raw, parameterized SQL for portability and clarity.

    gateways = sess.execute(sa.select(sa.text("id, name")).select_from(sa.text("gateways"))).all()
    for gid, gname in gateways:
        g_uuid = uuid.uuid4().hex
        sess.execute(
            sa.text("UPDATE gateways SET id_new=:u, slug=:s WHERE id=:i"),
            {"u": g_uuid, "s": _slugify(gname), "i": gid},
        )

    tools = sess.execute(
        sa.select(sa.text("id, name, gateway_id")).select_from(sa.text("tools"))
    ).all()
    for tid, tname, g_old in tools:
        t_uuid = uuid.uuid4().hex
        tool_slug = _slugify(tname)
        sess.execute(
            sa.text(
                """
                UPDATE tools
                SET id_new=:u,
                    original_name=:on,
                    original_name_slug=:ons,
                    -- THE FIX: Populate the 'name_new' temporary column --
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

    sta = sess.execute(
        sa.select(sa.text("server_id, tool_id")).select_from(sa.text("server_tool_association"))
    ).all()
    for s_old, t_old in sta:
        sess.execute(
            sa.text(
                """
                UPDATE server_tool_association
                SET server_id_new=(SELECT id_new FROM servers WHERE id=:s),
                    tool_id_new=(SELECT id_new FROM tools WHERE id=:t)
                WHERE server_id=:s AND tool_id=:t
                """
            ),
            {"s": s_old, "t": t_old},
        )

    sess.commit()

    # ── STAGE 3: FINALIZE SCHEMA (DROP OLD COLS, RENAME NEW, ADD CONSTRAINTS) ──
    # Using batch mode ensures this is portable.

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

    with op.batch_alter_table("tools") as batch_op:
        # THE FIX: Implement the full drop/rename pattern for all columns
        batch_op.drop_column("id")
        batch_op.alter_column("id_new", new_column_name="id", nullable=False)
        batch_op.create_primary_key("pk_tools", ["id"])

        batch_op.drop_column("gateway_id")
        batch_op.alter_column("gateway_id_new", new_column_name="gateway_id", nullable=True) # Or False if it's required

        # This is the corrected logic for the name column
        batch_op.drop_column("name")
        batch_op.alter_column("name_new", new_column_name="name", nullable=False)

        # Apply final constraints
        batch_op.alter_column("original_name", nullable=False)
        batch_op.alter_column("original_name_slug", nullable=False)
        batch_op.create_unique_constraint("uq_tools_name", ["name"])
        batch_op.create_unique_constraint("uq_gateway_id__original_name", ["gateway_id", "original_name"])
        batch_op.create_foreign_key("fk_tools_gateway_id", "gateways", ["gateway_id"], ["id"])

    with op.batch_alter_table("server_tool_association") as batch_op:
        batch_op.drop_column("server_id")
        batch_op.drop_column("tool_id")
        batch_op.alter_column("server_id_new", new_column_name="server_id", nullable=False)
        batch_op.alter_column("tool_id_new", new_column_name="tool_id", nullable=False)
        batch_op.create_primary_key("pk_server_tool_association", ["server_id", "tool_id"])
        batch_op.create_foreign_key("fk_server_tool_association_servers", "servers", ["server_id"], ["id"])
        batch_op.create_foreign_key("fk_server_tool_association_tools", "tools", ["tool_id"], ["id"])


def downgrade() -> None:
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
        batch_op.add_column(sa.Column("name", sa.String(), nullable=True))

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