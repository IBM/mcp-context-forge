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
revision: str = "e28cd485ad3c"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "0a089912b5f0"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove global unique constraints that break multi-tenant isolation.

    This migration fixes bug #5146 by removing global unique constraints that
    prevent different teams from registering entities with the same names.
    Uses direct constraint drop for PostgreSQL and batch mode for SQLite.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()
    dialect = bind.dialect.name

    # Tables and their columns with global unique constraints to remove
    tables_to_fix = {
        "gateways": ["slug", "url"],
        "servers": ["name"],
        "tools": ["name"],
        "prompts": ["name"],
        "resources": ["uri"],
    }

    failures = []

    for table_name, columns_to_fix in tables_to_fix.items():
        if table_name not in existing_tables:
            continue

        try:
            print(f"Processing {table_name} to remove global unique constraints...")

            # Get existing unique constraints
            unique_constraints = inspector.get_unique_constraints(table_name)

            # Find single-column constraints to drop
            constraints_to_drop = []
            for uc in unique_constraints:
                column_names = uc.get("column_names", [])
                constraint_name = uc.get("name")
                # Check if it's a single-column constraint on one of our target columns
                if len(column_names) == 1 and column_names[0] in columns_to_fix and constraint_name:
                    constraints_to_drop.append(constraint_name)

            if not constraints_to_drop:
                print(f"  ✓ {table_name}: No global unique constraints found, skipping")
                continue

            # Drop constraints based on dialect
            if dialect == "sqlite":
                # SQLite: Use batch mode to recreate table without the constraints
                with op.batch_alter_table(table_name, schema=None) as batch_op:
                    for constraint_name in constraints_to_drop:
                        batch_op.drop_constraint(constraint_name, type_="unique")
                print(f"  ✓ {table_name}: Removed {len(constraints_to_drop)} constraint(s) via batch mode")
            else:
                # PostgreSQL: Direct constraint drop
                for constraint_name in constraints_to_drop:
                    op.drop_constraint(constraint_name, table_name, type_="unique")
                print(f"  ✓ {table_name}: Removed {len(constraints_to_drop)} constraint(s)")

        except Exception as e:
            error_msg = f"Failed to update unique constraints on {table_name}: {e}"
            print(f"  ✗ {error_msg}")
            failures.append(error_msg)

    if failures:
        error_summary = "\n  - ".join(failures)
        if dialect == "sqlite":
            raise RuntimeError(
                f"Migration failed with {len(failures)} error(s):\n  - {error_summary}\n\n"
                "SQLite batch mode commits per table, so partial changes may have been applied. "
                "Run 'alembic downgrade -1' to roll back this migration manually."
            )
        else:
            raise RuntimeError(
                f"Migration failed with {len(failures)} error(s):\n  - {error_summary}\n\n"
                "PostgreSQL will automatically roll back all changes in this transaction."
            )


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
    dialect = bind.dialect.name

    # Tables and their columns needing global unique constraints
    tables_to_restore = {
        "gateways": ["slug", "url"],
        "servers": ["name"],
        "tools": ["name"],
        "prompts": ["name"],
        "resources": ["uri"],
    }

    failures = []

    for table_name, columns_to_restore in tables_to_restore.items():
        if table_name not in existing_tables:
            continue

        try:
            print(f"Processing {table_name} to restore global unique constraints...")

            # Get existing unique constraints
            unique_constraints = inspector.get_unique_constraints(table_name)
            existing_constraint_columns = set()
            for uc in unique_constraints:
                column_names = uc.get("column_names", [])
                if len(column_names) == 1:
                    existing_constraint_columns.add(column_names[0])

            # Determine which constraints need to be created
            constraints_to_create = []
            for col_name in columns_to_restore:
                if col_name not in existing_constraint_columns:
                    constraints_to_create.append(col_name)

            if not constraints_to_create:
                print(f"  ✓ {table_name}: Global unique constraints already exist, skipping")
                continue

            # Create constraints based on dialect
            if dialect == "sqlite":
                # SQLite: Use batch mode to recreate table with the constraints
                with op.batch_alter_table(table_name, schema=None) as batch_op:
                    for col_name in constraints_to_create:
                        # Use table_column naming pattern for constraint
                        constraint_name = f"uq_{table_name}_{col_name}"
                        batch_op.create_unique_constraint(constraint_name, [col_name])
                print(f"  ✓ {table_name}: Created {len(constraints_to_create)} constraint(s) via batch mode")
            else:
                # PostgreSQL: Direct constraint creation
                for col_name in constraints_to_create:
                    constraint_name = f"uq_{table_name}_{col_name}"
                    op.create_unique_constraint(constraint_name, table_name, [col_name])
                print(f"  ✓ {table_name}: Created {len(constraints_to_create)} constraint(s)")

        except Exception as e:
            error_msg = f"Failed to restore unique constraints on {table_name}: {e}"
            print(f"  ✗ {error_msg}")
            failures.append(error_msg)

    if failures:
        error_summary = "\n  - ".join(failures)
        if dialect == "sqlite":
            raise RuntimeError(
                f"Migration downgrade failed with {len(failures)} error(s):\n  - {error_summary}\n\n"
                "SQLite batch mode commits per table, so partial changes may have been applied. "
                "Run 'alembic downgrade -1' again or manually inspect schema state."
            )
        else:
            raise RuntimeError(
                f"Migration downgrade failed with {len(failures)} error(s):\n  - {error_summary}\n\n"
                "PostgreSQL will automatically roll back all changes in this transaction."
            )
