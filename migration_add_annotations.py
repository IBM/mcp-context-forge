# -*- coding: utf-8 -*-
"""
Migration script to add the annotations column to the tools table.

This migration adds support for MCP tool annotations like readOnlyHint, destructiveHint, etc.
"""

# Standard
import os
import sys

# Third-Party
from sqlalchemy import text

# Add the project root to the path so we can import mcpgateway modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# First-Party
from mcpgateway.db import engine, get_db


def migrate_up():
    """Add annotations column to tools table."""
    print("Adding annotations column to tools table...")

    # Check if column already exists
    with engine.connect() as conn:
        # Try to describe the table first
        try:
            result = conn.execute(text("PRAGMA table_info(tools)"))
            columns = [row[1] for row in result]

            if 'annotations' in columns:
                print("Annotations column already exists, skipping migration.")
                return
        except Exception:
            # For non-SQLite databases, use a different approach
            try:
                conn.execute(text("SELECT annotations FROM tools LIMIT 1"))
                print("Annotations column already exists, skipping migration.")
                return
            except Exception:
                pass  # Column doesn't exist, continue with migration

        # Add the annotations column
        try:
            conn.execute(text("ALTER TABLE tools ADD COLUMN annotations JSON DEFAULT '{}'"))
            conn.commit()
            print("Successfully added annotations column to tools table.")
        except Exception as e:
            print(f"Error adding annotations column: {e}")
            conn.rollback()
            raise

def migrate_down():
    """Remove annotations column from tools table."""
    print("Removing annotations column from tools table...")

    with engine.connect() as conn:
        try:
            # Note: SQLite doesn't support DROP COLUMN, so this would require table recreation
            # For now, we'll just print a warning
            print("Warning: SQLite doesn't support DROP COLUMN. Manual intervention required to remove annotations column.")
        except Exception as e:
            print(f"Error removing annotations column: {e}")
            raise

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "down":
        migrate_down()
    else:
        migrate_up()
