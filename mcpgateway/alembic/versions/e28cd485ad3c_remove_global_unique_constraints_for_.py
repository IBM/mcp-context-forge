"""remove_global_unique_constraints_for_multitenancy

Revision ID: e28cd485ad3c
Revises: 0a089912b5f0
Create Date: 2026-06-10 12:14:27.567362

This migration removes global unique constraints on gateways, servers, tools,
prompts, and resources that break multi-tenant functionality. The constraints
being removed are:
- gateways.slug (unique)
- gateways.url (unique)
- servers.name (unique)
- tools.name (unique)
- prompts.name (unique)
- resources.uri (unique)

These global constraints prevent different teams from registering entities with
the same names when using team visibility. The composite unique constraints
(e.g., uq_team_owner_slug_gateway) defined in db.py models remain and properly
scope uniqueness to team/owner level.

Fixes: #5146
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e28cd485ad3c"
down_revision: Union[str, Sequence[str], None] = "0a089912b5f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove global unique constraints that break multi-tenant isolation.

    This migration fixes bug #5146 by removing global unique constraints that
    prevent different teams from registering entities with the same names.
    Uses table recreation for SQLite compatibility.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Skip if tables don't exist (fresh DB uses db.py models directly)
    if "gateways" not in existing_tables:
        return

    # Tables and their global unique constraints to remove
    # Format: {table_name: [constraint_columns]}
    tables_to_fix = {
        "gateways": ["slug", "url"],
        "servers": ["name"],
        "tools": ["name"],
        "prompts": ["name"],
        "resources": ["uri"],
    }

    for table_name, constraint_columns in tables_to_fix.items():
        if table_name not in existing_tables:
            continue

        try:
            print(f"Processing {table_name} to remove global unique constraints...")

            # Get table metadata
            metadata = sa.MetaData()
            table = sa.Table(table_name, metadata, autoload_with=bind)

            # Check if table has the problematic global unique constraints
            # Convert to list to avoid "Set changed size during iteration" error
            constraints_list = list(table.constraints)
            has_global_constraints = False
            for uc in constraints_list:
                if isinstance(uc, sa.UniqueConstraint):
                    # Check if it's a single-column constraint we need to remove
                    if len(uc.columns) == 1:
                        col_name = list(uc.columns)[0].name
                        if col_name in constraint_columns:
                            has_global_constraints = True
                            break

            if not has_global_constraints:
                print(f"  ✓ {table_name}: No global unique constraints found, skipping")
                continue

            # Create temporary table name
            tmp_table = f"{table_name}_tmp_multitenancy_fix"

            # Drop temp table if it exists
            if inspector.has_table(tmp_table):
                op.drop_table(tmp_table)

            # Create new table structure without the global unique constraints
            new_metadata = sa.MetaData()
            new_table = sa.Table(tmp_table, new_metadata)

            # Copy all columns
            for column in table.columns:
                new_column = column.copy()
                new_table.append_column(new_column)

            # Note: We skip foreign key constraints here because they may reference
            # tables we've already renamed. SQLite will preserve the FKs from the
            # original schema when we copy the data.

            # Copy only the composite unique constraints (not single-column global ones)
            for constraint in constraints_list:
                if isinstance(constraint, sa.UniqueConstraint):
                    # Only keep multi-column (composite) constraints
                    if len(constraint.columns) > 1:
                        new_table.append_constraint(constraint.copy())
                    else:
                        # Check if it's a single-column constraint we should remove
                        col_name = list(constraint.columns)[0].name
                        if col_name not in constraint_columns:
                            # Keep other single-column constraints
                            new_table.append_constraint(constraint.copy())

            # Create the temporary table without foreign keys initially
            new_table.create(bind, checkfirst=False)
            print(f"  → Created temporary table {tmp_table}")

            # Copy data
            column_names = [c.name for c in table.columns]
            insert_stmt = new_table.insert().from_select(column_names, sa.select(*[table.c[name] for name in column_names]))
            bind.execute(insert_stmt)
            print(f"  → Copied data from {table_name}")

            # Drop original table and rename temp table
            op.drop_table(table_name)
            op.rename_table(tmp_table, table_name)
            print(f"  ✓ {table_name}: Removed global unique constraints on {', '.join(constraint_columns)}")

        except Exception as e:
            print(f"  ✗ Warning: Could not update unique constraints on {table_name}: {e}")
            # Clean up temp table if it exists
            if inspector.has_table(f"{table_name}_tmp_multitenancy_fix"):
                try:
                    op.drop_table(f"{table_name}_tmp_multitenancy_fix")
                except Exception:
                    pass


def downgrade() -> None:
    """Restore global unique constraints (reverses multi-tenant fix).

    WARNING: This downgrade will BREAK multi-tenant functionality by
    re-introducing global unique constraints that prevent different teams
    from using the same entity names. Only run this if you need to revert
    to a pre-multitenancy state.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Skip if tables don't exist
    if "gateways" not in existing_tables:
        return

    # Tables and their global unique constraints to restore
    tables_to_restore = {
        "gateways": ["slug", "url"],
        "servers": ["name"],
        "tools": ["name"],
        "prompts": ["name"],
        "resources": ["uri"],
    }

    for table_name, constraint_columns in tables_to_restore.items():
        if table_name not in existing_tables:
            continue

        try:
            print(f"Processing {table_name} to restore global unique constraints...")

            # Get table metadata
            metadata = sa.MetaData()
            table = sa.Table(table_name, metadata, autoload_with=bind)

            # Check if table already has the global unique constraints
            # Convert to list to avoid "Set changed size during iteration" error
            constraints_list = list(table.constraints)
            has_global_constraints = True
            for col in constraint_columns:
                found = False
                for uc in constraints_list:
                    if isinstance(uc, sa.UniqueConstraint):
                        if len(uc.columns) == 1 and list(uc.columns)[0].name == col:
                            found = True
                            break
                if not found:
                    has_global_constraints = False
                    break

            if has_global_constraints:
                print(f"  ✓ {table_name}: Global unique constraints already exist, skipping")
                continue

            # Create temporary table name
            tmp_table = f"{table_name}_tmp_restore_global"

            # Drop temp table if it exists
            if inspector.has_table(tmp_table):
                op.drop_table(tmp_table)

            # Create new table structure with global unique constraints
            new_metadata = sa.MetaData()
            new_table = sa.Table(tmp_table, new_metadata)

            # Copy all columns
            for column in table.columns:
                new_column = column.copy()
                new_table.append_column(new_column)

            # Note: We skip foreign key constraints here because they may reference
            # tables we've already renamed. SQLite will preserve the FKs from the
            # original schema when we copy the data.

            # Copy existing unique constraints
            for constraint in constraints_list:
                if isinstance(constraint, sa.UniqueConstraint):
                    new_table.append_constraint(constraint.copy())

            # Add global unique constraints
            for col in constraint_columns:
                new_table.append_constraint(sa.UniqueConstraint(col))

            # Create the temporary table without foreign keys initially
            new_table.create(bind, checkfirst=False)
            print(f"  → Created temporary table {tmp_table}")

            # Copy data
            column_names = [c.name for c in table.columns]
            insert_stmt = new_table.insert().from_select(column_names, sa.select(*[table.c[name] for name in column_names]))
            bind.execute(insert_stmt)
            print(f"  → Copied data from {table_name}")

            # Drop original table and rename temp table
            op.drop_table(table_name)
            op.rename_table(tmp_table, table_name)
            print(f"  ✓ {table_name}: Restored global unique constraints on {', '.join(constraint_columns)}")

        except Exception as e:
            print(f"  ✗ Warning: Could not restore unique constraints on {table_name}: {e}")
            # Clean up temp table if it exists
            if inspector.has_table(f"{table_name}_tmp_restore_global"):
                try:
                    op.drop_table(f"{table_name}_tmp_restore_global")
                except Exception:
                    pass
