"""decode html entities in descriptions

Revision ID: c1c2c3c4c5c6
Revises: b1b2b3b4b5b6
Create Date: 2026-02-06 08:42:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Table, MetaData
import html

# revision identifiers, used by Alembic.
revision: str = "c1c2c3c4c5c6"
down_revision: str = "b1b2b3b4b5b6"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Decode HTML entities in description fields across all tables.
    
    This fixes descriptions that were stored with HTML entities (e.g., &#x27; instead of ')
    due to the old html.escape() behavior in sanitize_display_text().
    
    Supports both SQLite and PostgreSQL.
    Uses SQLAlchemy ORM to avoid SQL injection risks.
    """
    connection = op.get_bind()
    metadata = MetaData()
    
    # Tables with description fields
    table_names = [
        "tools",
        "resources",
        "prompts",
        "gateways",
        "servers",
        "a2a_agents"
    ]
    
    for table_name in table_names:
        # Check if table exists
        inspector = sa.inspect(connection)
        if table_name not in inspector.get_table_names():
            continue
        
        # Reflect the table structure
        table = Table(table_name, metadata, autoload_with=connection)
        
        # Check if description column exists
        if "description" not in table.c:
            continue
            
        # Get all records with descriptions containing HTML entities
        # Use SQLAlchemy select to avoid SQL injection
        select_stmt = sa.select(table.c.id, table.c.description).where(
            table.c.description.like("%&#%")
        )
        results = connection.execute(select_stmt).fetchall()
        
        if not results:
            continue
        
        # Update each record with decoded description
        for row in results:
            record_id = row[0]
            old_description = row[1]
            
            if old_description:
                new_description = html.unescape(old_description)
                
                if old_description != new_description:
                    # Use SQLAlchemy update to avoid SQL injection
                    update_stmt = (
                        sa.update(table)
                        .where(table.c.id == record_id)
                        .values(description=new_description)
                    )
                    connection.execute(update_stmt)


def downgrade() -> None:
    """Re-encode special characters as HTML entities in description fields.
    
    This reverses the upgrade by re-applying html.escape() to descriptions.
    Note: This will only encode common special characters like ', ", <, >, &
    Uses SQLAlchemy ORM to avoid SQL injection risks.
    """
    connection = op.get_bind()
    metadata = MetaData()
    
    # Tables with description fields
    table_names = [
        "tools",
        "resources",
        "prompts",
        "gateways",
        "servers",
        "a2a_agents"
    ]
    
    for table_name in table_names:
        # Check if table exists
        inspector = sa.inspect(connection)
        if table_name not in inspector.get_table_names():
            continue
        
        # Reflect the table structure
        table = Table(table_name, metadata, autoload_with=connection)
        
        # Check if description column exists
        if "description" not in table.c:
            continue
            
        # Get all records with descriptions
        # Use SQLAlchemy select to avoid SQL injection
        select_stmt = sa.select(table.c.id, table.c.description).where(
            table.c.description.isnot(None)
        )
        results = connection.execute(select_stmt).fetchall()
        
        if not results:
            continue
        
        # Update each record with HTML-escaped description
        for row in results:
            record_id = row[0]
            old_description = row[1]
            
            if old_description:
                # Re-encode special characters as HTML entities
                new_description = html.escape(old_description, quote=True)
                
                if old_description != new_description:
                    # Use SQLAlchemy update to avoid SQL injection
                    update_stmt = (
                        sa.update(table)
                        .where(table.c.id == record_id)
                        .values(description=new_description)
                    )
                    connection.execute(update_stmt)

