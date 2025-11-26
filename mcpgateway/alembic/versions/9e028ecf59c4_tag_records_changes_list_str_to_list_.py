"""tag records changes list[str] to list[Dict[str,str]]

Revision ID: 9e028ecf59c4
Revises: 191a2def08d7
Create Date: 2025-11-26 18:15:07.113528

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json

# revision identifiers, used by Alembic.
revision: str = '9e028ecf59c4'
down_revision: Union[str, Sequence[str], None] = '191a2def08d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Data migration: convert servers.tags which are currently lists of strings
    # into lists of dicts with keys `id` (normalized) and `label` (original).
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

        rows = conn.execute(sa.text(f"SELECT id, tags FROM {table}")).fetchall()

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

            # Convert back to JSON for storage
            conn.execute(
                sa.text(f"UPDATE {table} SET tags = :new_tags WHERE id = :id"),
                {"new_tags": json.dumps(new_tags), "id": rec_id}
            )


def downgrade():
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

        rows = conn.execute(sa.text(f"SELECT id, tags FROM {table}")).fetchall()

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

            conn.execute(
                sa.text(f"UPDATE {table} SET tags = :tags WHERE id = :id"),
                {"tags": json.dumps(old_tags), "id": rec_id}
            )
   