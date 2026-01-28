# -*- coding: utf-8 -*-
"""UUID Change for Prompt and Resources

Revision ID: 356a2d4eed6f
Revises: z1a2b3c4d5e6
Create Date: 2025-12-01 14:52:01.957105

"""

# Standard
from typing import Sequence, Union
import uuid

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "356a2d4eed6f"
down_revision: Union[str, Sequence[str], None] = "9e028ecf59c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Raises:
        RuntimeError: If partial or inconsistent migration state is detected.
    """
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    dialect = conn.dialect.name if hasattr(conn, "dialect") else None

    # Skip if fresh database (tables created via create_all + stamp)
    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping migration.")
        return

    # Skip if prompts table doesn't exist (fresh database)
    if not inspector.has_table("prompts"):
        print("prompts table not found. Skipping migration.")
        return

    # Analyze current state of both tables
    # Check if id is integer type (needs migration) vs non-integer (already migrated)
    # Non-integer includes: VARCHAR, STRING, TEXT, UUID, CHAR, etc.
    # Use exact matching to avoid false positives (e.g., POINT, INTERVAL contain "INT")
    integer_type_names = {
        "INTEGER",
        "INT",
        "BIGINT",
        "SMALLINT",
        "TINYINT",
        "MEDIUMINT",  # Standard SQL
        "SERIAL",
        "BIGSERIAL",
        "SMALLSERIAL",  # PostgreSQL auto-increment
    }

    def is_integer_type(type_str: str) -> bool:
        """Check if type string represents an integer type using exact word matching.

        Args:
            type_str: The database column type as a string (e.g., "INTEGER", "VARCHAR(36)").

        Returns:
            True if the type is a known integer type, False otherwise.
        """
        # Extract base type name (first word only), handling:
        # - "INTEGER(11)" -> "INTEGER"
        # - "BIGINT UNSIGNED" -> "BIGINT"
        # - "INT UNSIGNED ZEROFILL" -> "INT"
        base_type = type_str.upper().split("(")[0].split()[0].strip()
        return base_type in integer_type_names

    prompts_columns = {col["name"]: col for col in inspector.get_columns("prompts")}
    prompts_id_type = str(prompts_columns.get("id", {}).get("type", ""))
    prompts_is_integer = is_integer_type(prompts_id_type)
    prompts_has_id_new = "id_new" in prompts_columns

    # Check resources table existence explicitly - both tables are required
    if not inspector.has_table("resources"):
        raise RuntimeError(
            f"Cannot proceed: resources table is missing. "
            f"prompts.id type is {prompts_id_type} ({'needs migration' if prompts_is_integer else 'possibly already migrated'}). "
            "This migration requires both prompts and resources tables to exist. "
            "Please verify your database schema."
        )

    resources_columns = {col["name"]: col for col in inspector.get_columns("resources")}
    resources_id_type = str(resources_columns.get("id", {}).get("type", ""))
    resources_is_integer = is_integer_type(resources_id_type)
    resources_has_id_new = "id_new" in resources_columns

    # Check for partial migration states that require manual intervention
    if prompts_has_id_new or resources_has_id_new:
        raise RuntimeError(
            "Partial migration detected: id_new column exists in prompts or resources. "
            "This indicates a previous migration attempt failed midway. "
            "Manual cleanup required: DROP the id_new column and verify data integrity, "
            "or restore from backup before retrying."
        )

    # Check for inconsistent states - this migration must convert both tables atomically
    if prompts_is_integer != resources_is_integer:
        raise RuntimeError(
            f"Inconsistent migration state: prompts.id is {prompts_id_type}, "
            f"resources.id is {resources_id_type}. "
            "This migration converts both tables atomically and cannot auto-repair partial states. "
            "Manual intervention required to align the schemas before retrying."
        )

    # If both are already non-integer (string/uuid/text), migration is complete
    if not prompts_is_integer and not resources_is_integer:
        print(f"prompts.id ({prompts_id_type}) and resources.id ({resources_id_type}) are non-integer. Skipping migration.")
        return

    # 1) Add temporary id_new column to prompts and populate with uuid.hex
    op.add_column("prompts", sa.Column("id_new", sa.String(36), nullable=True))

    rows = conn.execute(text("SELECT id FROM prompts")).fetchall()
    for (old_id,) in rows:
        new_id = uuid.uuid4().hex
        conn.execute(text("UPDATE prompts SET id_new = :new WHERE id = :old"), {"new": new_id, "old": old_id})

    # 2) Create new prompts table (temporary) with varchar(36) id
    prompts_pk_name = "pk_prompts" if dialect == "sqlite" else "pk_prompts_tmp"
    prompts_uq_name = "uq_team_owner_name_prompt" if dialect == "sqlite" else "uq_team_owner_name_prompt_tmp"
    op.create_table(
        "prompts_tmp",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("template", sa.Text, nullable=True),
        sa.Column("argument_schema", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=True),
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
        sa.UniqueConstraint("team_id", "owner_email", "name", name=prompts_uq_name),
        sa.PrimaryKeyConstraint("id", name=prompts_pk_name),
    )

    # 3) Copy data from prompts into prompts_tmp using id_new as id
    # Use SQLAlchemy Core to move rows from `prompts` -> `prompts_tmp` without
    # composing SQL text. This avoids dynamic string concat while keeping the
    # same column mapping (id_new -> id, is_active -> enabled).
    prompts_src = sa.table(
        "prompts",
        sa.column("id_new"),
        sa.column("name"),
        sa.column("description"),
        sa.column("template"),
        sa.column("argument_schema"),
        sa.column("created_at"),
        sa.column("updated_at"),
        sa.column("is_active"),
        sa.column("tags"),
        sa.column("created_by"),
        sa.column("created_from_ip"),
        sa.column("created_via"),
        sa.column("created_user_agent"),
        sa.column("modified_by"),
        sa.column("modified_from_ip"),
        sa.column("modified_via"),
        sa.column("modified_user_agent"),
        sa.column("import_batch_id"),
        sa.column("federation_source"),
        sa.column("version"),
        sa.column("gateway_id"),
        sa.column("team_id"),
        sa.column("owner_email"),
        sa.column("visibility"),
    )

    prompts_tgt = sa.table(
        "prompts_tmp",
        sa.column("id"),
        sa.column("name"),
        sa.column("description"),
        sa.column("template"),
        sa.column("argument_schema"),
        sa.column("created_at"),
        sa.column("updated_at"),
        sa.column("enabled"),
        sa.column("tags"),
        sa.column("created_by"),
        sa.column("created_from_ip"),
        sa.column("created_via"),
        sa.column("created_user_agent"),
        sa.column("modified_by"),
        sa.column("modified_from_ip"),
        sa.column("modified_via"),
        sa.column("modified_user_agent"),
        sa.column("import_batch_id"),
        sa.column("federation_source"),
        sa.column("version"),
        sa.column("gateway_id"),
        sa.column("team_id"),
        sa.column("owner_email"),
        sa.column("visibility"),
    )

    target_cols = [
        "id",
        "name",
        "description",
        "template",
        "argument_schema",
        "created_at",
        "updated_at",
        "enabled",
        "tags",
        "created_by",
        "created_from_ip",
        "created_via",
        "created_user_agent",
        "modified_by",
        "modified_from_ip",
        "modified_via",
        "modified_user_agent",
        "import_batch_id",
        "federation_source",
        "version",
        "gateway_id",
        "team_id",
        "owner_email",
        "visibility",
    ]

    select_exprs = [
        prompts_src.c.id_new,
        prompts_src.c.name,
        prompts_src.c.description,
        prompts_src.c.template,
        prompts_src.c.argument_schema,
        prompts_src.c.created_at,
        prompts_src.c.updated_at,
        prompts_src.c.is_active,
        prompts_src.c.tags,
        prompts_src.c.created_by,
        prompts_src.c.created_from_ip,
        prompts_src.c.created_via,
        prompts_src.c.created_user_agent,
        prompts_src.c.modified_by,
        prompts_src.c.modified_from_ip,
        prompts_src.c.modified_via,
        prompts_src.c.modified_user_agent,
        prompts_src.c.import_batch_id,
        prompts_src.c.federation_source,
        prompts_src.c.version,
        prompts_src.c.gateway_id,
        prompts_src.c.team_id,
        prompts_src.c.owner_email,
        prompts_src.c.visibility,
    ]

    stmt = sa.select(*select_exprs)
    ins = sa.insert(prompts_tgt).from_select(target_cols, stmt)
    conn.execute(ins)

    # 4) Create new prompt_metrics table with prompt_id varchar(36)
    prompt_metrics_pk_name = "pk_prompt_metrics" if dialect == "sqlite" else "pk_prompt_metrics_tmp"
    op.create_table(
        "prompt_metrics_tmp",
        sa.Column("id", sa.Integer, primary_key=True, nullable=False),
        sa.Column("prompt_id", sa.String(36), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_time", sa.Float, nullable=False),
        sa.Column("is_success", sa.Boolean, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts_tmp.id"], name="fk_prompt_metrics_prompt_id"),
        sa.PrimaryKeyConstraint("id", name=prompt_metrics_pk_name),
    )

    # 5) Copy prompt_metrics mapping old integer prompt_id -> new uuid via join
    conn.execute(
        text(
            "INSERT INTO prompt_metrics_tmp (id, prompt_id, timestamp, response_time, is_success, error_message) SELECT pm.id, p.id_new, pm.timestamp, pm.response_time, pm.is_success, pm.error_message FROM prompt_metrics pm JOIN prompts p ON pm.prompt_id = p.id"
        )
    )

    # 6) Create new server_prompt_association table with prompt_id varchar(36)
    server_prompt_assoc_pk = "pk_server_prompt_assoc" if dialect == "sqlite" else "pk_server_prompt_assoc_tmp"
    op.create_table(
        "server_prompt_association_tmp",
        sa.Column("server_id", sa.String(36), nullable=False),
        sa.Column("prompt_id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("server_id", "prompt_id", name=server_prompt_assoc_pk),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], name="fk_server_prompt_server_id"),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts_tmp.id"], name="fk_server_prompt_prompt_id"),
    )

    conn.execute(text("INSERT INTO server_prompt_association_tmp (server_id, prompt_id) SELECT spa.server_id, p.id_new FROM server_prompt_association spa JOIN prompts p ON spa.prompt_id = p.id"))

    # Update observability spans that reference prompts: remap integer prompt IDs -> new uuid
    # PostgreSQL requires explicit cast when comparing varchar to int; other DBs (SQLite/MySQL) are permissive.
    dialect = conn.dialect.name if hasattr(conn, "dialect") else None
    if dialect == "postgresql":
        conn.execute(text("UPDATE observability_spans SET resource_id = p.id_new FROM prompts p WHERE observability_spans.resource_type = 'prompts' AND observability_spans.resource_id = p.id::text"))
    else:
        conn.execute(text("UPDATE observability_spans SET resource_id = p.id_new FROM prompts p WHERE observability_spans.resource_type = 'prompts' AND observability_spans.resource_id = p.id"))

    # 7) Drop old tables and rename tmp tables into place
    op.drop_table("prompt_metrics")
    op.drop_table("server_prompt_association")
    op.drop_table("prompts")

    op.rename_table("prompts_tmp", "prompts")
    op.rename_table("prompt_metrics_tmp", "prompt_metrics")
    op.rename_table("server_prompt_association_tmp", "server_prompt_association")
    # For SQLite we cannot ALTER constraints directly; skip constraint renames there.
    if dialect != "sqlite":
        # Drop dependent foreign keys first to allow primary key rename/recreation
        op.drop_constraint("fk_prompt_metrics_prompt_id", "prompt_metrics", type_="foreignkey")
        op.drop_constraint("fk_server_prompt_prompt_id", "server_prompt_association", type_="foreignkey")

        # Restore original constraint names for prompts and dependent tables
        op.drop_constraint("pk_prompts_tmp", "prompts", type_="primary")
        op.create_primary_key("pk_prompts", "prompts", ["id"])
        op.drop_constraint("uq_team_owner_name_prompt_tmp", "prompts", type_="unique")
        op.create_unique_constraint("uq_team_owner_name_prompt", "prompts", ["team_id", "owner_email", "name"])

        op.drop_constraint("pk_prompt_metrics_tmp", "prompt_metrics", type_="primary")
        op.create_primary_key("pk_prompt_metrics", "prompt_metrics", ["id"])

        op.drop_constraint("pk_server_prompt_assoc_tmp", "server_prompt_association", type_="primary")
        op.create_primary_key("pk_server_prompt_assoc", "server_prompt_association", ["server_id", "prompt_id"])

        # Recreate foreign keys referencing the new primary key name
        op.create_foreign_key("fk_prompt_metrics_prompt_id", "prompt_metrics", "prompts", ["prompt_id"], ["id"])
        op.create_foreign_key("fk_server_prompt_prompt_id", "server_prompt_association", "prompts", ["prompt_id"], ["id"])

    # -----------------------------
    # Resources -> change id to VARCHAR(32) and remap FKs
    # -----------------------------
    # Add temporary id_new to resources
    op.add_column("resources", sa.Column("id_new", sa.String(36), nullable=True))

    rows = conn.execute(text("SELECT id FROM resources")).fetchall()
    for (old_id,) in rows:
        new_id = uuid.uuid4().hex
        conn.execute(text("UPDATE resources SET id_new = :new WHERE id = :old"), {"new": new_id, "old": old_id})

    # Create resources_tmp with varchar(32) id
    resources_pk_name = "pk_resources" if dialect == "sqlite" else "pk_resources_tmp"
    resources_uq_name = "uq_team_owner_uri_resource" if dialect == "sqlite" else "uq_team_owner_uri_resource_tmp"
    op.create_table(
        "resources_tmp",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("uri", sa.String(767), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("size", sa.Integer, nullable=True),
        sa.Column("uri_template", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=True),
        sa.Column("tags", sa.JSON, nullable=False),
        sa.Column("text_content", sa.Text, nullable=True),
        sa.Column("binary_content", sa.LargeBinary, nullable=True),
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
        sa.UniqueConstraint("team_id", "owner_email", "uri", name=resources_uq_name),
        sa.PrimaryKeyConstraint("id", name=resources_pk_name),
    )

    # Copy data into resources_tmp using id_new via SQLAlchemy Core
    resources_src = sa.table(
        "resources",
        sa.column("id_new"),
        sa.column("uri"),
        sa.column("name"),
        sa.column("description"),
        sa.column("mime_type"),
        sa.column("size"),
        sa.column("uri_template"),
        sa.column("created_at"),
        sa.column("updated_at"),
        sa.column("is_active"),
        sa.column("tags"),
        sa.column("text_content"),
        sa.column("binary_content"),
        sa.column("created_by"),
        sa.column("created_from_ip"),
        sa.column("created_via"),
        sa.column("created_user_agent"),
        sa.column("modified_by"),
        sa.column("modified_from_ip"),
        sa.column("modified_via"),
        sa.column("modified_user_agent"),
        sa.column("import_batch_id"),
        sa.column("federation_source"),
        sa.column("version"),
        sa.column("gateway_id"),
        sa.column("team_id"),
        sa.column("owner_email"),
        sa.column("visibility"),
    )

    resources_tgt = sa.table(
        "resources_tmp",
        sa.column("id"),
        sa.column("uri"),
        sa.column("name"),
        sa.column("description"),
        sa.column("mime_type"),
        sa.column("size"),
        sa.column("uri_template"),
        sa.column("created_at"),
        sa.column("updated_at"),
        sa.column("enabled"),
        sa.column("tags"),
        sa.column("text_content"),
        sa.column("binary_content"),
        sa.column("created_by"),
        sa.column("created_from_ip"),
        sa.column("created_via"),
        sa.column("created_user_agent"),
        sa.column("modified_by"),
        sa.column("modified_from_ip"),
        sa.column("modified_via"),
        sa.column("modified_user_agent"),
        sa.column("import_batch_id"),
        sa.column("federation_source"),
        sa.column("version"),
        sa.column("gateway_id"),
        sa.column("team_id"),
        sa.column("owner_email"),
        sa.column("visibility"),
    )

    target_cols_res = [
        "id",
        "uri",
        "name",
        "description",
        "mime_type",
        "size",
        "uri_template",
        "created_at",
        "updated_at",
        "enabled",
        "tags",
        "text_content",
        "binary_content",
        "created_by",
        "created_from_ip",
        "created_via",
        "created_user_agent",
        "modified_by",
        "modified_from_ip",
        "modified_via",
        "modified_user_agent",
        "import_batch_id",
        "federation_source",
        "version",
        "gateway_id",
        "team_id",
        "owner_email",
        "visibility",
    ]

    select_exprs_res = [
        resources_src.c.id_new,
        resources_src.c.uri,
        resources_src.c.name,
        resources_src.c.description,
        resources_src.c.mime_type,
        resources_src.c.size,
        resources_src.c.uri_template,
        resources_src.c.created_at,
        resources_src.c.updated_at,
        resources_src.c.is_active,
        resources_src.c.tags,
        resources_src.c.text_content,
        resources_src.c.binary_content,
        resources_src.c.created_by,
        resources_src.c.created_from_ip,
        resources_src.c.created_via,
        resources_src.c.created_user_agent,
        resources_src.c.modified_by,
        resources_src.c.modified_from_ip,
        resources_src.c.modified_via,
        resources_src.c.modified_user_agent,
        resources_src.c.import_batch_id,
        resources_src.c.federation_source,
        resources_src.c.version,
        resources_src.c.gateway_id,
        resources_src.c.team_id,
        resources_src.c.owner_email,
        resources_src.c.visibility,
    ]

    stmt_res = sa.select(*select_exprs_res)
    ins_res = sa.insert(resources_tgt).from_select(target_cols_res, stmt_res)
    conn.execute(ins_res)

    # resource_metrics_tmp with resource_id varchar(32)
    resource_metrics_pk = "pk_resource_metrics" if dialect == "sqlite" else "pk_resource_metrics_tmp"
    op.create_table(
        "resource_metrics_tmp",
        sa.Column("id", sa.Integer, primary_key=True, nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_time", sa.Float, nullable=False),
        sa.Column("is_success", sa.Boolean, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["resource_id"], ["resources_tmp.id"], name="fk_resource_metrics_resource_id"),
        sa.PrimaryKeyConstraint("id", name=resource_metrics_pk),
    )

    # copy resource_metrics mapping old int->new uuid
    conn.execute(
        text(
            "INSERT INTO resource_metrics_tmp (id, resource_id, timestamp, response_time, is_success, error_message) SELECT rm.id, r.id_new, rm.timestamp, rm.response_time, rm.is_success, rm.error_message FROM resource_metrics rm JOIN resources r ON rm.resource_id = r.id"
        )
    )

    # server_resource_association_tmp
    server_resource_assoc_pk = "pk_server_resource_assoc" if dialect == "sqlite" else "pk_server_resource_assoc_tmp"
    op.create_table(
        "server_resource_association_tmp",
        sa.Column("server_id", sa.String(36), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("server_id", "resource_id", name=server_resource_assoc_pk),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], name="fk_server_resource_server_id"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources_tmp.id"], name="fk_server_resource_resource_id"),
    )

    conn.execute(
        text("INSERT INTO server_resource_association_tmp (server_id, resource_id) SELECT sra.server_id, r.id_new FROM server_resource_association sra JOIN resources r ON sra.resource_id = r.id")
    )

    # Update observability spans that reference resources: remap integer resource IDs -> new uuid
    # Cast for PostgreSQL to avoid varchar = integer operator error
    dialect = conn.dialect.name if hasattr(conn, "dialect") else None
    if dialect == "postgresql":
        conn.execute(
            text("UPDATE observability_spans SET resource_id = r.id_new FROM resources r WHERE observability_spans.resource_type = 'resources' AND observability_spans.resource_id = r.id::text")
        )
    else:
        conn.execute(text("UPDATE observability_spans SET resource_id = r.id_new FROM resources r WHERE observability_spans.resource_type = 'resources' AND observability_spans.resource_id = r.id"))

    # resource_subscriptions_tmp
    op.create_table(
        "resource_subscriptions_tmp",
        sa.Column("id", sa.Integer, primary_key=True, nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("subscriber_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notification", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["resource_id"], ["resources_tmp.id"], name="fk_resource_subscriptions_resource_id"),
    )

    conn.execute(
        text(
            "INSERT INTO resource_subscriptions_tmp (id, resource_id, subscriber_id, created_at, last_notification) SELECT rs.id, r.id_new, rs.subscriber_id, rs.created_at, rs.last_notification FROM resource_subscriptions rs JOIN resources r ON rs.resource_id = r.id"
        )
    )

    # Drop old resource-related tables and rename tmp tables
    op.drop_table("resource_metrics")
    op.drop_table("server_resource_association")
    op.drop_table("resource_subscriptions")
    op.drop_table("resources")

    op.rename_table("resources_tmp", "resources")
    op.rename_table("resource_metrics_tmp", "resource_metrics")
    op.rename_table("server_resource_association_tmp", "server_resource_association")
    op.rename_table("resource_subscriptions_tmp", "resource_subscriptions")
    # For SQLite we cannot ALTER constraints directly; skip constraint renames there.
    if dialect != "sqlite":
        # Drop dependent foreign keys first to allow primary key rename/recreation
        op.drop_constraint("fk_resource_metrics_resource_id", "resource_metrics", type_="foreignkey")
        op.drop_constraint("fk_server_resource_resource_id", "server_resource_association", type_="foreignkey")
        op.drop_constraint("fk_resource_subscriptions_resource_id", "resource_subscriptions", type_="foreignkey")

        # Restore original constraint names for resources and dependent tables
        op.drop_constraint("pk_resources_tmp", "resources", type_="primary")
        op.create_primary_key("pk_resources", "resources", ["id"])
        op.drop_constraint("uq_team_owner_uri_resource_tmp", "resources", type_="unique")
        op.create_unique_constraint("uq_team_owner_uri_resource", "resources", ["team_id", "owner_email", "uri"])

        op.drop_constraint("pk_resource_metrics_tmp", "resource_metrics", type_="primary")
        op.create_primary_key("pk_resource_metrics", "resource_metrics", ["id"])

        op.drop_constraint("pk_server_resource_assoc_tmp", "server_resource_association", type_="primary")
        op.create_primary_key("pk_server_resource_assoc", "server_resource_association", ["server_id", "resource_id"])

        # Recreate foreign keys referencing restored primary key
        op.create_foreign_key("fk_resource_metrics_resource_id", "resource_metrics", "resources", ["resource_id"], ["id"])
        op.create_foreign_key("fk_server_resource_resource_id", "server_resource_association", "resources", ["resource_id"], ["id"])
        op.create_foreign_key("fk_resource_subscriptions_resource_id", "resource_subscriptions", "resources", ["resource_id"], ["id"])

    with op.batch_alter_table("servers") as batch_op:
        batch_op.alter_column(
            "is_active",
            new_column_name="enabled",
            existing_type=sa.Boolean(),
            existing_server_default=sa.text("1"),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    dialect = conn.dialect.name if hasattr(conn, "dialect") else None

    # Best-effort: rebuild integer prompt ids and remap dependent FK columns.
    # 1) Create old-style prompts table with integer id (autoincrement)
    # If a previous partial downgrade left these tables behind, drop them first
    conn.execute(text("DROP TABLE IF EXISTS prompts_old"))
    prompts_old_pk = "pk_prompts" if dialect == "sqlite" else "pk_prompts_old"
    prompts_old_uq = "uq_team_owner_name_prompt" if dialect == "sqlite" else "uq_team_owner_name_prompt_old"
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
        sa.UniqueConstraint("team_id", "owner_email", "name", name=prompts_old_uq),
        sa.PrimaryKeyConstraint("id", name=prompts_old_pk),
    )

    # 2) Insert rows from current prompts into prompts_old letting id autoincrement.
    # We'll preserve uniqueness by using the team_id/owner_email/name triple to later remap.
    conn.execute(
        text(
            (
                "INSERT INTO prompts_old (name, description, template, argument_schema, created_at, updated_at, "
                "is_active, tags, created_by, created_from_ip, created_via, created_user_agent, modified_by, "
                "modified_from_ip, modified_via, modified_user_agent, import_batch_id, federation_source, version, "
                "gateway_id, team_id, owner_email, visibility) "
                "SELECT name, description, template, argument_schema, created_at, updated_at, enabled, tags, "
                "created_by, created_from_ip, created_via, created_user_agent, modified_by, modified_from_ip, "
                "modified_via, modified_user_agent, import_batch_id, federation_source, version, gateway_id, "
                "team_id, owner_email, visibility FROM prompts"
            )
        )
    )

    # 3) Build mapping from new uuid -> new integer id using the unique key (team_id, owner_email, name)
    mapping = {}
    res = conn.execute(
        text(
            (
                "SELECT p.id as uuid_id, p.team_id, p.owner_email, p.name, old.id as int_id "
                "FROM prompts p JOIN prompts_old old ON "
                "COALESCE(p.team_id, '') = COALESCE(old.team_id, '') AND "
                "COALESCE(p.owner_email, '') = COALESCE(old.owner_email, '') AND "
                "p.name = old.name"
            )
        )
    )
    for row in res:
        mapping[row[0]] = row[4]

    # 4) Recreate prompt_metrics_old and remap prompt_id
    conn.execute(text("DROP TABLE IF EXISTS prompt_metrics_old"))
    prompt_metrics_old_pk = "pk_prompt_metrics" if dialect == "sqlite" else "pk_prompt_metric_old"
    op.create_table(
        "prompt_metrics_old",
        sa.Column("id", sa.Integer, primary_key=True, nullable=False),
        sa.Column("prompt_id", sa.Integer, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_time", sa.Float, nullable=False),
        sa.Column("is_success", sa.Boolean, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts_old.id"], name="fk_prompt_metrics_prompt_id"),
        sa.PrimaryKeyConstraint("id", name=prompt_metrics_old_pk),
    )

    # Copy metrics mapping prompt_id via Python mapping
    rows = conn.execute(text("SELECT id, prompt_id, timestamp, response_time, is_success, error_message FROM prompt_metrics")).fetchall()
    for r in rows:
        old_uuid = r[1]
        int_id = mapping.get(old_uuid)
        if int_id is None:
            # skip orphaned metric
            continue
        conn.execute(
            text("INSERT INTO prompt_metrics_old (id, prompt_id, timestamp, response_time, is_success, error_message) VALUES (:id, :pid, :ts, :rt, :is_s, :err)"),
            {"id": r[0], "pid": int_id, "ts": r[2], "rt": r[3], "is_s": r[4], "err": r[5]},
        )

    # 5) Recreate server_prompt_association_old and remap prompt_id
    conn.execute(text("DROP TABLE IF EXISTS server_prompt_association_old"))
    server_prompt_assoc_old_pk = "pk_server_prompt_assoc" if dialect == "sqlite" else "pk_server_prompt_assoc_old"
    op.create_table(
        "server_prompt_association_old",
        sa.Column("server_id", sa.String(36), nullable=False),
        sa.Column("prompt_id", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("server_id", "prompt_id", name=server_prompt_assoc_old_pk),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], name="fk_server_prompt_server_id"),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts_old.id"], name="fk_server_prompt_prompt_id"),
    )

    rows = conn.execute(text("SELECT server_id, prompt_id FROM server_prompt_association")).fetchall()
    for server_id, prompt_uuid in rows:
        int_id = mapping.get(prompt_uuid)
        if int_id is None:
            continue
        conn.execute(text("INSERT INTO server_prompt_association_old (server_id, prompt_id) VALUES (:sid, :pid)"), {"sid": server_id, "pid": int_id})

    # Remap observability_spans for prompts: uuid -> integer id using mapping built above
    span_rows = conn.execute(text("SELECT span_id, resource_id FROM observability_spans WHERE resource_type = 'prompts'")).fetchall()
    for span_id, res_uuid in span_rows:
        int_id = mapping.get(res_uuid)
        if int_id is None:
            # skip orphaned span
            continue
        conn.execute(text("UPDATE observability_spans SET resource_id = :rid WHERE span_id = :sid"), {"rid": int_id, "sid": span_id})

    # 6) Drop current tables and rename old ones back
    op.drop_table("prompt_metrics")
    op.drop_table("server_prompt_association")
    op.drop_table("prompts")

    op.rename_table("prompts_old", "prompts")
    op.rename_table("prompt_metrics_old", "prompt_metrics")
    op.rename_table("server_prompt_association_old", "server_prompt_association")

    # For SQLite we cannot ALTER constraints directly; skip those steps there.
    if dialect != "sqlite":
        # Drop dependent foreign keys first to allow primary key rename/recreation
        op.drop_constraint("fk_prompt_metrics_prompt_id", "prompt_metrics", type_="foreignkey")
        op.drop_constraint("fk_server_prompt_prompt_id", "server_prompt_association", type_="foreignkey")

        # Restore original constraint names after renaming old tables back
        op.drop_constraint("pk_prompts_old", "prompts", type_="primary")
        op.create_primary_key("pk_prompts", "prompts", ["id"])
        op.drop_constraint("uq_team_owner_name_prompt_old", "prompts", type_="unique")
        op.create_unique_constraint("uq_team_owner_name_prompt", "prompts", ["team_id", "owner_email", "name"])

        op.drop_constraint("pk_prompt_metric_old", "prompt_metrics", type_="primary")
        op.create_primary_key("pk_prompt_metrics", "prompt_metrics", ["id"])

        op.drop_constraint("pk_server_prompt_assoc_old", "server_prompt_association", type_="primary")
        op.create_primary_key("pk_server_prompt_assoc", "server_prompt_association", ["server_id", "prompt_id"])

        # Recreate foreign keys referencing the new primary key name
        op.create_foreign_key("fk_prompt_metrics_prompt_id", "prompt_metrics", "prompts", ["prompt_id"], ["id"])
        op.create_foreign_key("fk_server_prompt_prompt_id", "server_prompt_association", "prompts", ["prompt_id"], ["id"])

    # =============================
    # Resources downgrade: rebuild integer ids and remap FKs
    # =============================
    # 1) Create old-style resources table with integer id (autoincrement)
    conn.execute(text("DROP TABLE IF EXISTS resources_old"))
    op.create_table(
        "resources_old",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, nullable=False),
        sa.Column("uri", sa.String(767), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("size", sa.Integer, nullable=True),
        sa.Column("uri_template", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=True),
        sa.Column("tags", sa.JSON, nullable=False),
        sa.Column("text_content", sa.Text, nullable=True),
        sa.Column("binary_content", sa.LargeBinary, nullable=True),
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
        sa.UniqueConstraint("team_id", "owner_email", "uri", name="uq_team_owner_uri_resource_old"),
        sa.PrimaryKeyConstraint("id", name="pk_resources_old"),
    )

    # 2) Insert rows from current resources into resources_old letting id autoincrement.
    conn.execute(
        text(
            (
                "INSERT INTO resources_old (uri, name, description, mime_type, size, uri_template, created_at, "
                "updated_at, is_active, tags, text_content, binary_content, created_by, created_from_ip, "
                "created_via, created_user_agent, modified_by, modified_from_ip, modified_via, modified_user_agent, "
                "import_batch_id, federation_source, version, gateway_id, team_id, owner_email, visibility) "
                "SELECT uri, name, description, mime_type, size, uri_template, created_at, updated_at, enabled, tags, "
                "text_content, binary_content, created_by, created_from_ip, created_via, created_user_agent, modified_by, "
                "modified_from_ip, modified_via, modified_user_agent, import_batch_id, federation_source, version, gateway_id, "
                "team_id, owner_email, visibility FROM resources"
            )
        )
    )

    # 3) Build mapping from new uuid -> new integer id using unique key (team_id, owner_email, uri)
    mapping_res = {}
    res_map = conn.execute(
        text(
            (
                "SELECT r.id as uuid_id, r.team_id, r.owner_email, r.uri, old.id as int_id "
                "FROM resources r JOIN resources_old old ON "
                "COALESCE(r.team_id, '') = COALESCE(old.team_id, '') AND "
                "COALESCE(r.owner_email, '') = COALESCE(old.owner_email, '') AND "
                "r.uri = old.uri"
            )
        )
    )
    for row in res_map:
        mapping_res[row[0]] = row[4]

    # 4) Recreate resource_metrics_old and remap resource_id
    conn.execute(text("DROP TABLE IF EXISTS resource_metrics_old"))
    op.create_table(
        "resource_metrics_old",
        sa.Column("id", sa.Integer, primary_key=True, nullable=False),
        sa.Column("resource_id", sa.Integer, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_time", sa.Float, nullable=False),
        sa.Column("is_success", sa.Boolean, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["resource_id"], ["resources_old.id"], name="fk_resource_metrics_resource_id"),
        sa.PrimaryKeyConstraint("id", name="pk_resource_metrics_old"),
    )

    # Copy resource metrics remapping ids
    rows = conn.execute(text("SELECT id, resource_id, timestamp, response_time, is_success, error_message FROM resource_metrics")).fetchall()
    for r in rows:
        old_uuid = r[1]
        int_id = mapping_res.get(old_uuid)
        if int_id is None:
            continue
        conn.execute(
            text("INSERT INTO resource_metrics_old (id, resource_id, timestamp, response_time, is_success, error_message) VALUES (:id, :rid, :ts, :rt, :is_s, :err)"),
            {"id": r[0], "rid": int_id, "ts": r[2], "rt": r[3], "is_s": r[4], "err": r[5]},
        )

    # 5) Recreate server_resource_association_old and remap resource_id
    conn.execute(text("DROP TABLE IF EXISTS server_resource_association_old"))
    op.create_table(
        "server_resource_association_old",
        sa.Column("server_id", sa.String(36), nullable=False),
        sa.Column("resource_id", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("server_id", "resource_id", name="pk_server_resource_assoc_old"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], name="fk_server_resource_server_id"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources_old.id"], name="fk_server_resource_resource_id"),
    )

    rows = conn.execute(text("SELECT server_id, resource_id FROM server_resource_association")).fetchall()
    for server_id, resource_uuid in rows:
        int_id = mapping_res.get(resource_uuid)
        if int_id is None:
            continue
        conn.execute(text("INSERT INTO server_resource_association_old (server_id, resource_id) VALUES (:sid, :rid)"), {"sid": server_id, "rid": int_id})

    # 6) Recreate resource_subscriptions_old and remap resource_id
    conn.execute(text("DROP TABLE IF EXISTS resource_subscriptions_old"))
    op.create_table(
        "resource_subscriptions_old",
        sa.Column("id", sa.Integer, primary_key=True, nullable=False),
        sa.Column("resource_id", sa.Integer, nullable=False),
        sa.Column("subscriber_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notification", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["resource_id"], ["resources_old.id"], name="fk_resource_subscriptions_resource_id"),
    )

    rows = conn.execute(text("SELECT id, resource_id, subscriber_id, created_at, last_notification FROM resource_subscriptions")).fetchall()
    for r in rows:
        int_id = mapping_res.get(r[1])
        if int_id is None:
            continue
        conn.execute(
            text("INSERT INTO resource_subscriptions_old (id, resource_id, subscriber_id, created_at, last_notification) VALUES (:id, :rid, :sub, :ts, :ln)"),
            {"id": r[0], "rid": int_id, "sub": r[2], "ts": r[3], "ln": r[4]},
        )

    # Remap observability_spans for resources: uuid -> integer id using mapping_res built above
    span_rows = conn.execute(text("SELECT span_id, resource_id FROM observability_spans WHERE resource_type = 'resources'")).fetchall()
    for span_id, res_uuid in span_rows:
        int_id = mapping_res.get(res_uuid)
        if int_id is None:
            continue
        conn.execute(text("UPDATE observability_spans SET resource_id = :rid WHERE span_id = :sid"), {"rid": int_id, "sid": span_id})

    # 7) Drop current resource tables and rename old ones back
    op.drop_table("resource_metrics")
    op.drop_table("server_resource_association")
    op.drop_table("resource_subscriptions")
    op.drop_table("resources")

    op.rename_table("resources_old", "resources")
    op.rename_table("resource_metrics_old", "resource_metrics")
    op.rename_table("server_resource_association_old", "server_resource_association")
    op.rename_table("resource_subscriptions_old", "resource_subscriptions")
    # For SQLite we cannot ALTER constraints directly; skip those steps there.
    if dialect != "sqlite":
        # Drop dependent foreign keys first to allow primary key rename/recreation
        op.drop_constraint("fk_resource_metrics_resource_id", "resource_metrics", type_="foreignkey")
        op.drop_constraint("fk_server_resource_resource_id", "server_resource_association", type_="foreignkey")
        op.drop_constraint("fk_resource_subscriptions_resource_id", "resource_subscriptions", type_="foreignkey")

        # Restore original constraint names for resources after downgrade
        op.drop_constraint("pk_resources_old", "resources", type_="primary")
        op.create_primary_key("pk_resources", "resources", ["id"])
        op.drop_constraint("uq_team_owner_uri_resource_old", "resources", type_="unique")
        op.create_unique_constraint("uq_team_owner_uri_resource", "resources", ["team_id", "owner_email", "uri"])

        op.drop_constraint("pk_resource_metrics_old", "resource_metrics", type_="primary")
        op.create_primary_key("pk_resource_metrics", "resource_metrics", ["id"])

        op.drop_constraint("pk_server_resource_assoc_old", "server_resource_association", type_="primary")
        op.create_primary_key("pk_server_resource_assoc", "server_resource_association", ["server_id", "resource_id"])

        # Recreate foreign keys to point to restored primary key
        op.create_foreign_key("fk_resource_metrics_resource_id", "resource_metrics", "resources", ["resource_id"], ["id"])
        op.create_foreign_key("fk_server_resource_resource_id", "server_resource_association", "resources", ["resource_id"], ["id"])
        op.create_foreign_key("fk_resource_subscriptions_resource_id", "resource_subscriptions", "resources", ["resource_id"], ["id"])
    with op.batch_alter_table("servers") as batch_op:
        batch_op.alter_column(
            "enabled",
            new_column_name="is_active",
            existing_type=sa.Boolean(),
            existing_server_default=sa.text("1"),
            existing_nullable=False,
        )
