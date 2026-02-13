"""convert_hex_uuids_to_hyphenated

Revision ID: 71e35d2065b6
Revises: c1c2c3c4c5c6
Create Date: 2026-02-13 13:40:21.370714

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '71e35d2065b6'
down_revision: Union[str, Sequence[str], None] = 'c1c2c3c4c5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert hex UUIDs (32 chars) to hyphenated format (36 chars) for consistency."""
    inspector = sa.inspect(op.get_bind())
    
    # Tables that use hex UUID format (32 chars) that need conversion
    tables_to_convert = [
        'gateways',
        'servers',
        'tools',
        'resources',
        'prompts',
        'rate_limits',
        'api_keys',
        'audit_logs',
        'plugin_executions',
        'plugin_violations',
        'oauth_tokens',
        'oauth_clients'
    ]
    
    connection = op.get_bind()
    
    for table_name in tables_to_convert:
        # Skip if table doesn't exist (fresh DB uses db.py models directly)
        if table_name not in inspector.get_table_names():
            continue
        
        # Check if id column exists and is 32 chars (hex format)
        columns = {col["name"]: col for col in inspector.get_columns(table_name)}
        if "id" not in columns:
            continue
        
        # Get all records with hex UUIDs (32 chars, no hyphens)
        result = connection.execute(
            sa.text(f"SELECT id FROM {table_name} WHERE LENGTH(id) = 32 AND id NOT LIKE '%-%'")
        )
        
        for row in result:
            hex_id = row[0]
            # Convert hex to hyphenated UUID format
            # Format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
            hyphenated_id = f"{hex_id[:8]}-{hex_id[8:12]}-{hex_id[12:16]}-{hex_id[16:20]}-{hex_id[20:]}"
            
            # Update the record
            connection.execute(
                sa.text(f"UPDATE {table_name} SET id = :new_id WHERE id = :old_id"),
                {"new_id": hyphenated_id, "old_id": hex_id}
            )
        
        connection.commit()


def downgrade() -> None:
    """Convert hyphenated UUIDs back to hex format."""
    inspector = sa.inspect(op.get_bind())
    
    tables_to_convert = [
        'gateways',
        'servers',
        'tools',
        'resources',
        'prompts',
        'rate_limits',
        'api_keys',
        'audit_logs',
        'plugin_executions',
        'plugin_violations',
        'oauth_tokens',
        'oauth_clients'
    ]
    
    connection = op.get_bind()
    
    for table_name in tables_to_convert:
        if table_name not in inspector.get_table_names():
            continue
        
        columns = {col["name"]: col for col in inspector.get_columns(table_name)}
        if "id" not in columns:
            continue
        
        # Get all records with hyphenated UUIDs (36 chars with hyphens)
        result = connection.execute(
            sa.text(f"SELECT id FROM {table_name} WHERE LENGTH(id) = 36 AND id LIKE '%-%'")
        )
        
        for row in result:
            hyphenated_id = row[0]
            # Remove hyphens to get hex format
            hex_id = hyphenated_id.replace("-", "")
            
            # Update the record
            connection.execute(
                sa.text(f"UPDATE {table_name} SET id = :new_id WHERE id = :old_id"),
                {"new_id": hex_id, "old_id": hyphenated_id}
            )
        
        connection.commit()