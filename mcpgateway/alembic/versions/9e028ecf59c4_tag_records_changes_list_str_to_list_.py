# -*- coding: utf-8 -*-
"""tag records changes list[str] to list[Dict[str,str]]

Revision ID: 9e028ecf59c4
Revises: add_toolops_test_cases_table
Create Date: 2025-11-26 18:15:07.113528

"""

# Standard
import json
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9e028ecf59c4"
down_revision: Union[str, Sequence[str], None] = "add_toolops_test_cases_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert string-only tag lists into dict-form tag lists.

    Many tables store a JSON `tags` column. Older versions stored tags as a
    list of plain strings. The application now expects each tag to be a
    mapping with an `id` and a `label` (for example:
    `{"id": "network", "label": "network"}`).

    This migration iterates over a set of known tables and, for any row
    where `tags` is a list that contains plain strings, replaces those
    strings with dicts of the form `{"id": <string>, "label": <string>}`.
    Non-list `tags` values and tags already in dict form are left
    unchanged. Tables that are not present in the database are skipped.
    """

    conn = op.get_bind()
    # Apply same transformation to multiple tables that use a `tags` JSON column.
    tables = [
        "servers",
        "tools",
        "prompts",
        "resources",
        "a2a_agents",
        "gateways",
        "grpc_services",
    ]

    inspector = sa.inspect(conn)
    available = set(inspector.get_table_names())

    for table in tables:
        if table not in available:
            # Skip non-existent tables in older DBs
            continue

        tbl = sa.table(table, sa.column("id"), sa.column("tags"))
        rows = conn.execute(sa.select(tbl.c.id, tbl.c.tags)).fetchall()

        for row in rows:
            rec_id = row[0]
            tags_raw = row[1]

            # Parse JSON (SQLite returns string)
            if isinstance(tags_raw, str):
                tags = json.loads(tags_raw)
            else:
                tags = tags_raw

            # Skip if not a list
            if not isinstance(tags, list):
                continue

            contains_string = any(isinstance(t, str) for t in tags)
            if not contains_string:
                continue

            # Convert strings → dict format
            new_tags = []
            for t in tags:
                if isinstance(t, str):
                    new_tags.append({"id": t, "label": t})
                else:
                    new_tags.append(t)

            # Convert back to JSON for storage using SQLAlchemy constructs
            stmt = sa.update(tbl).where(tbl.c.id == rec_id).values(tags=json.dumps(new_tags))
            conn.execute(stmt)


def downgrade() -> None:
    """Revert dict-form tag lists back to string-only lists.

    Reverse the transformation applied in `upgrade()`: for any tag that is a
    dict and contains an `id` key, replace the dict with its `id` string.
    Other values are left unchanged. The operation is applied across the
    same set of tables and skips missing tables or non-list `tags` values.
    """

    conn = op.get_bind()
    # Reverse the transformation across the same set of tables.
    tables = [
        "servers",
        "tools",
        "prompts",
        "resources",
        "a2a_agents",
        "gateways",
        "grpc_services",
    ]

    inspector = sa.inspect(conn)
    available = set(inspector.get_table_names())

    for table in tables:
        if table not in available:
            continue

        tbl = sa.table(table, sa.column("id"), sa.column("tags"))
        rows = conn.execute(sa.select(tbl.c.id, tbl.c.tags)).fetchall()

        for row in rows:
            rec_id = row[0]
            tags_raw = row[1]

            if isinstance(tags_raw, str):
                tags = json.loads(tags_raw)
            else:
                tags = tags_raw

            if not isinstance(tags, list):
                continue

            contains_dict = any(isinstance(t, dict) and "id" in t for t in tags)
            if not contains_dict:
                continue

            old_tags = []
            for t in tags:
                if isinstance(t, dict) and "id" in t:
                    old_tags.append(t["id"])
                else:
                    old_tags.append(t)

            stmt = sa.update(tbl).where(tbl.c.id == rec_id).values(tags=json.dumps(old_tags))
            conn.execute(stmt)
