"""UUID Change for Prompt and Resources

Revision ID: 356a2d4eed6f
Revises: z1a2b3c4d5e6
Create Date: 2025-12-01 14:52:01.957105

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import uuid
import logging

from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '356a2d4eed6f'
down_revision: Union[str, Sequence[str], None] = '9e028ecf59c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # 1) Add temporary id_new column to prompts and populate with uuid.hex
    op.add_column("prompts", sa.Column("id_new", sa.String(36), nullable=True))

    rows = conn.execute(text("SELECT id FROM prompts")).fetchall()
    for (old_id,) in rows:
        new_id = uuid.uuid4().hex
        conn.execute(text("UPDATE prompts SET id_new = :new WHERE id = :old"), {"new": new_id, "old": old_id})

    # 2) Create new prompts table (temporary) with varchar(36) id
    op.create_table(
        "prompts_tmp",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("template", sa.Text, nullable=True),
        sa.Column("argument_schema", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=True),
        sa.Column("tags", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_from_ip", sa.String(45), nullable=True),
        sa.Column("created_via", sa.String(100), nullable=True),
        sa.Column("created_user_agent", sa.Text, nullable=True),
        sa.Column("modified_by", sa.String(255), nullable=True),
        sa.Column("modified_from_ip", sa.String(45), nullable=True),
        sa.Column("modified_via", sa.String(100), nullable=True),
        sa.Column("modified_user_agent", sa.Text, nullable=True),
        sa.Column("import_batch_id", sa.String(36), nullable=True),
        sa.Column("federation_source", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("gateway_id", sa.String(36), nullable=True),
        sa.Column("team_id", sa.String(36), nullable=True),
        sa.Column("owner_email", sa.String(255), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.UniqueConstraint("team_id", "owner_email", "name", name="uq_team_owner_name_prompt"),
        sa.PrimaryKeyConstraint("id", name="pk_prompts"),
    )

    # 3) Copy data from prompts into prompts_tmp using id_new as id
    copy_cols = (
        "id, name, description, template, argument_schema, created_at, updated_at, is_active, tags,"
        " created_by, created_from_ip, created_via, created_user_agent, modified_by, modified_from_ip,"
        " modified_via, modified_user_agent, import_batch_id, federation_source, version, gateway_id, team_id, owner_email, visibility"
    )
    conn.execute(text(f"INSERT INTO prompts_tmp ({copy_cols}) SELECT id_new, name, description, template, argument_schema, created_at, updated_at, is_active, tags, created_by, created_from_ip, created_via, created_user_agent, modified_by, modified_from_ip, modified_via, modified_user_agent, import_batch_id, federation_source, version, gateway_id, team_id, owner_email, visibility FROM prompts"))

    # 4) Create new prompt_metrics table with prompt_id varchar(36)
    op.create_table(
        "prompt_metrics_tmp",
        sa.Column("id", sa.Integer, primary_key=True, nullable=False),
        sa.Column("prompt_id", sa.String(36), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_time", sa.Float, nullable=False),
        sa.Column("is_success", sa.Boolean, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts_tmp.id"], name="fk_prompt_metrics_prompt_id"),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_metrics"),
    )

    # 5) Copy prompt_metrics mapping old integer prompt_id -> new uuid via join
    conn.execute(text("INSERT INTO prompt_metrics_tmp (id, prompt_id, timestamp, response_time, is_success, error_message) SELECT pm.id, p.id_new, pm.timestamp, pm.response_time, pm.is_success, pm.error_message FROM prompt_metrics pm JOIN prompts p ON pm.prompt_id = p.id"))

    # 6) Create new server_prompt_association table with prompt_id varchar(36)
    op.create_table(
        "server_prompt_association_tmp",
        sa.Column("server_id", sa.String(36), nullable=False),
        sa.Column("prompt_id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("server_id", "prompt_id", name="pk_server_prompt_assoc"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], name="fk_server_prompt_server_id"),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts_tmp.id"], name="fk_server_prompt_prompt_id"),
    )

    conn.execute(text("INSERT INTO server_prompt_association_tmp (server_id, prompt_id) SELECT spa.server_id, p.id_new FROM server_prompt_association spa JOIN prompts p ON spa.prompt_id = p.id"))

    # 7) Drop old tables and rename tmp tables into place
    op.drop_table("prompt_metrics")
    op.drop_table("server_prompt_association")
    op.drop_table("prompts")

    op.rename_table("prompts_tmp", "prompts")
    op.rename_table("prompt_metrics_tmp", "prompt_metrics")
    op.rename_table("server_prompt_association_tmp", "server_prompt_association")
    

def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()

    # Best-effort: rebuild integer prompt ids and remap dependent FK columns.
    # 1) Create old-style prompts table with integer id (autoincrement)
    op.create_table(
        "prompts_old",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("template", sa.Text, nullable=True),
        sa.Column("argument_schema", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=True),
        sa.Column("tags", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_from_ip", sa.String(45), nullable=True),
        sa.Column("created_via", sa.String(100), nullable=True),
        sa.Column("created_user_agent", sa.Text, nullable=True),
        sa.Column("modified_by", sa.String(255), nullable=True),
        sa.Column("modified_from_ip", sa.String(45), nullable=True),
        sa.Column("modified_via", sa.String(100), nullable=True),
        sa.Column("modified_user_agent", sa.Text, nullable=True),
        sa.Column("import_batch_id", sa.String(36), nullable=True),
        sa.Column("federation_source", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("gateway_id", sa.String(36), nullable=True),
        sa.Column("team_id", sa.String(36), nullable=True),
        sa.Column("owner_email", sa.String(255), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.UniqueConstraint("team_id", "owner_email", "name", name="uq_team_owner_name_prompt"),
        sa.PrimaryKeyConstraint("id", name="pk_prompts"),
    )

    # 2) Insert rows from current prompts into prompts_old letting id autoincrement.
    # We'll preserve uniqueness by using the team_id/owner_email/name triple to later remap.
    conn.execute(text("INSERT INTO prompts_old (name, description, template, argument_schema, created_at, updated_at, is_active, tags, created_by, created_from_ip, created_via, created_user_agent, modified_by, modified_from_ip, modified_via, modified_user_agent, import_batch_id, federation_source, version, gateway_id, team_id, owner_email, visibility) SELECT name, description, template, argument_schema, created_at, updated_at, is_active, tags, created_by, created_from_ip, created_via, created_user_agent, modified_by, modified_from_ip, modified_via, modified_user_agent, import_batch_id, federation_source, version, gateway_id, team_id, owner_email, visibility FROM prompts"))

    # 3) Build mapping from new uuid -> new integer id using the unique key (team_id, owner_email, name)
    mapping = {}
    res = conn.execute(text("SELECT p.id as uuid_id, p.team_id, p.owner_email, p.name, old.id as int_id FROM prompts p JOIN prompts_old old ON COALESCE(p.team_id, '') = COALESCE(old.team_id, '') AND COALESCE(p.owner_email, '') = COALESCE(old.owner_email, '') AND p.name = old.name"))
    for row in res:
        mapping[row[0]] = row[4]

    # 4) Recreate prompt_metrics_old and remap prompt_id
    op.create_table(
        "prompt_metrics_old",
        sa.Column("id", sa.Integer, primary_key=True, nullable=False),
        sa.Column("prompt_id", sa.Integer, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_time", sa.Float, nullable=False),
        sa.Column("is_success", sa.Boolean, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts_old.id"], name="fk_prompt_metrics_prompt_id"),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_metric"),
    )

    # Copy metrics mapping prompt_id via Python mapping
    rows = conn.execute(text("SELECT id, prompt_id, timestamp, response_time, is_success, error_message FROM prompt_metrics")).fetchall()
    for r in rows:
        old_uuid = r[1]
        int_id = mapping.get(old_uuid)
        if int_id is None:
            # skip orphaned metric
            continue
        conn.execute(text("INSERT INTO prompt_metrics_old (id, prompt_id, timestamp, response_time, is_success, error_message) VALUES (:id, :pid, :ts, :rt, :is_s, :err)"), {"id": r[0], "pid": int_id, "ts": r[2], "rt": r[3], "is_s": r[4], "err": r[5]})

    # 5) Recreate server_prompt_association_old and remap prompt_id
    op.create_table(
        "server_prompt_association_old",
        sa.Column("server_id", sa.String(36), nullable=False),
        sa.Column("prompt_id", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("server_id", "prompt_id", name="pk_server_prompt_assoc"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], name="fk_server_prompt_server_id"),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts_old.id"], name="fk_server_prompt_prompt_id"),
    )

    rows = conn.execute(text("SELECT server_id, prompt_id FROM server_prompt_association")).fetchall()
    for server_id, prompt_uuid in rows:
        int_id = mapping.get(prompt_uuid)
        if int_id is None:
            continue
        conn.execute(text("INSERT INTO server_prompt_association_old (server_id, prompt_id) VALUES (:sid, :pid)"), {"sid": server_id, "pid": int_id})

    # 6) Drop current tables and rename old ones back
    op.drop_table("prompt_metrics")
    op.drop_table("server_prompt_association")
    op.drop_table("prompts")

    op.rename_table("prompts_old", "prompts")
    op.rename_table("prompt_metrics_old", "prompt_metrics")
    op.rename_table("server_prompt_association_old", "server_prompt_association")
