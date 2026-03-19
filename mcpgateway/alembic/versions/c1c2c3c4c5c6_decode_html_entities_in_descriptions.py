# -*- coding: utf-8 -*-
"""decode html entities in descriptions

Revision ID: c1c2c3c4c5c6
Revises: v1a2b3c4d5e6
Create Date: 2026-02-06 08:42:00.000000

"""

# Standard
import html

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import MetaData

# revision identifiers, used by Alembic.
revision: str = "c1c2c3c4c5c6"
down_revision: str = "v1a2b3c4d5e6"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Decode HTML entities in description and display_name fields across all tables.

    This fixes descriptions and display names that were stored with HTML entities (e.g., &#x27; instead of ')
    due to the old html.escape() behavior in sanitize_display_text().

    Handles multiple levels of encoding by repeatedly unescaping until no more entities remain.

    Supports both SQLite and PostgreSQL.
    Uses SQLAlchemy ORM to avoid SQL injection risks.
    """
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Tables with description fields
    tables_with_description = ["tools", "resources", "prompts", "gateways", "servers", "a2a_agents", "grpc_services"]

    # Tables with display_name fields
    tables_with_display_name = ["tools", "prompts"]

    # Helper function to decode HTML entities
    def decode_field(old_value):
        """Decode HTML entities from a field value.

        Args:
            old_value: The field value that may contain HTML entities.

        Returns:
            The decoded field value with HTML entities converted to their corresponding characters.
        """
        if not old_value:
            return old_value

        new_value = old_value
        max_iterations = 10  # Safety limit to prevent infinite loops

        for _ in range(max_iterations):
            unescaped = html.unescape(new_value)
            if unescaped == new_value:
                # No more entities to decode
                break
            new_value = unescaped

        return new_value

    # Process description fields
    for table_name in tables_with_description:
        # Check if table exists
        if table_name not in inspector.get_table_names():
            continue

        # Check if description column exists
        columns = [col["name"] for col in inspector.get_columns(table_name)]
        if "description" not in columns:
            continue

        # Create a fresh metadata for each table to avoid conflicts
        metadata = MetaData()
        metadata.reflect(bind=connection, only=[table_name])
        table = metadata.tables[table_name]

        # Get all records with descriptions containing HTML entities
        # Check for both &#x (hex) and & (common entity) patterns
        amp_pattern = "%&%"
        quot_pattern = "%&" + "quot;%"
        lt_pattern = "%&" + "lt;%"
        gt_pattern = "%&" + "gt;%"

        select_stmt = sa.select(table.c.id, table.c.description).where(
            sa.and_(
                table.c.description.isnot(None),
                sa.or_(
                    table.c.description.like("%&#%"),
                    table.c.description.like(amp_pattern),
                    table.c.description.like(quot_pattern),
                    table.c.description.like(lt_pattern),
                    table.c.description.like(gt_pattern),
                ),
            )
        )
        results = connection.execute(select_stmt).fetchall()

        # Update each record with decoded description
        for row in results:
            record_id = row[0]
            old_description = row[1]
            new_description = decode_field(old_description)

            if old_description != new_description:
                # Use SQLAlchemy update to avoid SQL injection
                update_stmt = sa.update(table).where(table.c.id == record_id).values(description=new_description)
                connection.execute(update_stmt)

    # Process display_name fields for tools and prompts
    for table_name in tables_with_display_name:
        # Check if table exists
        if table_name not in inspector.get_table_names():
            continue

        # Check if display_name column exists
        columns = [col["name"] for col in inspector.get_columns(table_name)]
        if "display_name" not in columns:
            continue

        # Create a fresh metadata for each table to avoid conflicts
        metadata = MetaData()
        metadata.reflect(bind=connection, only=[table_name])
        table = metadata.tables[table_name]

        # Get all records with display_name containing HTML entities
        amp_pattern = "%&%"
        quot_pattern = "%&" + "quot;%"
        lt_pattern = "%&" + "lt;%"
        gt_pattern = "%&" + "gt;%"

        select_stmt = sa.select(table.c.id, table.c.display_name).where(
            sa.and_(
                table.c.display_name.isnot(None),
                sa.or_(
                    table.c.display_name.like("%&#%"),
                    table.c.display_name.like(amp_pattern),
                    table.c.display_name.like(quot_pattern),
                    table.c.display_name.like(lt_pattern),
                    table.c.display_name.like(gt_pattern),
                ),
            )
        )
        results = connection.execute(select_stmt).fetchall()

        # Update each record with decoded display_name
        for row in results:
            record_id = row[0]
            old_display_name = row[1]
            new_display_name = decode_field(old_display_name)

            if old_display_name != new_display_name:
                # Use SQLAlchemy update to avoid SQL injection
                update_stmt = sa.update(table).where(table.c.id == record_id).values(display_name=new_display_name)
                connection.execute(update_stmt)


def downgrade() -> None:
    """Re-encode special characters as HTML entities in description and display_name fields.

    This reverses the upgrade by re-applying html.escape() to descriptions and display names.

    IMPORTANT: This is a best-effort reversal. The old sanitize_display_text() applied
    html.escape() at input time, so the pre-upgrade DB state had HTML entities for data
    that went through the REST API validators. However, descriptions created via gateway
    discovery bypass validators and were stored as plain text. This downgrade will encode
    those too (e.g., "R&D" becomes "R&amp;D"), which is an acceptable trade-off since the
    old templates (without the decode_html filter) need encoded data to display correctly.

    Uses SQLAlchemy ORM to avoid SQL injection risks.
    """
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Tables with description fields
    tables_with_description = ["tools", "resources", "prompts", "gateways", "servers", "a2a_agents", "grpc_services"]

    # Tables with display_name fields
    tables_with_display_name = ["tools", "prompts"]

    # Process description fields
    for table_name in tables_with_description:
        # Check if table exists
        if table_name not in inspector.get_table_names():
            continue

        # Check if description column exists
        columns = [col["name"] for col in inspector.get_columns(table_name)]
        if "description" not in columns:
            continue

        # Create a fresh metadata for each table to avoid conflicts
        metadata = MetaData()
        metadata.reflect(bind=connection, only=[table_name])
        table = metadata.tables[table_name]

        # Get all records with descriptions
        select_stmt = sa.select(table.c.id, table.c.description).where(table.c.description.isnot(None))
        results = connection.execute(select_stmt).fetchall()

        # Update each record with HTML-escaped description
        for row in results:
            record_id = row[0]
            old_description = row[1]

            if old_description:
                # Re-encode special characters as HTML entities
                new_description = html.escape(old_description, quote=True)

                if old_description != new_description:
                    # Use SQLAlchemy update to avoid SQL injection
                    update_stmt = sa.update(table).where(table.c.id == record_id).values(description=new_description)
                    connection.execute(update_stmt)

    # Process display_name fields for tools and prompts
    for table_name in tables_with_display_name:
        # Check if table exists
        if table_name not in inspector.get_table_names():
            continue

        # Check if display_name column exists
        columns = [col["name"] for col in inspector.get_columns(table_name)]
        if "display_name" not in columns:
            continue

        # Create a fresh metadata for each table to avoid conflicts
        metadata = MetaData()
        metadata.reflect(bind=connection, only=[table_name])
        table = metadata.tables[table_name]

        # Get all records with display_name
        select_stmt = sa.select(table.c.id, table.c.display_name).where(table.c.display_name.isnot(None))
        results = connection.execute(select_stmt).fetchall()

        # Update each record with HTML-escaped display_name
        for row in results:
            record_id = row[0]
            old_display_name = row[1]

            if old_display_name:
                # Re-encode special characters as HTML entities
                new_display_name = html.escape(old_display_name, quote=True)

                if old_display_name != new_display_name:
                    # Use SQLAlchemy update to avoid SQL injection
                    update_stmt = sa.update(table).where(table.c.id == record_id).values(display_name=new_display_name)
                    connection.execute(update_stmt)
