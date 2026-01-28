# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/b1b2b3b4b5b6_fix_constraints.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Alembic migration to fix constraints for resources and prompts to allow gateway namespacing,
using team/owner/gateway composite constraints, plus partial indexes for local uniqueness.

Revision ID: b1b2b3b4b5b6
Revises: 4e6273136e56
Create Date: 2026-01-26 13:01:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "b1b2b3b4b5b6"
down_revision: Union[str, Sequence[str], None] = "4e6273136e56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def constraint_exists(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    """Check if a unique constraint exists on a table.

    Args:
        inspector: SQLAlchemy inspector instance.
        table_name: Name of the table to inspect.
        constraint_name: Name of the constraint to check.

    Returns:
        True if constraint exists, False if not or if check failed.
    """
    try:
        unique_constraints = inspector.get_unique_constraints(table_name)
        return any(uc["name"] == constraint_name for uc in unique_constraints)
    except Exception:
        # If introspection fails, return False so creates are attempted
        return False


def index_exists(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table.

    Args:
        inspector: SQLAlchemy inspector instance.
        table_name: Name of the table to inspect.
        index_name: Name of the index to check.

    Returns:
        True if index exists, False if not or if check failed.
    """
    try:
        indexes = inspector.get_indexes(table_name)
        return any(idx["name"] == index_name for idx in indexes)
    except Exception:
        # If introspection fails, return False so creates are attempted
        return False


def _upgrade_resources(inspector: sa.Inspector) -> None:
    """Update constraints for resources table.

    Args:
        inspector: SQLAlchemy inspector instance for database introspection.
    """
    if "resources" not in inspector.get_table_names():
        print("Resources table not found. Skipping resources migration.")
        return

    print("Processing resources table constraints...")
    with op.batch_alter_table("resources", schema=None) as batch_op:
        # Drop old constraint if exists
        if constraint_exists(inspector, "resources", "uq_team_owner_uri_resource"):
            try:
                batch_op.drop_constraint("uq_team_owner_uri_resource", type_="unique")
                print("Dropped constraint uq_team_owner_uri_resource.")
            except Exception as e:
                print(f"Could not drop constraint uq_team_owner_uri_resource: {e}")

        # Add new composite constraint if not exists
        if not constraint_exists(inspector, "resources", "uq_team_owner_gateway_uri_resource"):
            try:
                batch_op.create_unique_constraint("uq_team_owner_gateway_uri_resource", ["team_id", "owner_email", "gateway_id", "uri"])
                print("Created constraint uq_team_owner_gateway_uri_resource.")
            except Exception as e:
                print(f"Could not create constraint uq_team_owner_gateway_uri_resource (may already exist): {e}")
        else:
            print("Constraint uq_team_owner_gateway_uri_resource already exists, skipping create.")

        # Add partial index for local resources if not exists
        if not index_exists(inspector, "resources", "uq_team_owner_uri_resource_local"):
            try:
                batch_op.create_index(
                    "uq_team_owner_uri_resource_local", ["team_id", "owner_email", "uri"], unique=True, postgresql_where=text("gateway_id IS NULL"), sqlite_where=text("gateway_id IS NULL")
                )
                print("Created index uq_team_owner_uri_resource_local.")
            except Exception as e:
                print(f"Could not create index uq_team_owner_uri_resource_local (may already exist): {e}")
        else:
            print("Index uq_team_owner_uri_resource_local already exists, skipping create.")


def _upgrade_prompts(inspector: sa.Inspector) -> None:
    """Update constraints for prompts table.

    Args:
        inspector: SQLAlchemy inspector instance for database introspection.
    """
    if "prompts" not in inspector.get_table_names():
        print("Prompts table not found. Skipping prompts migration.")
        return

    print("Processing prompts table constraints...")
    with op.batch_alter_table("prompts", schema=None) as batch_op:
        # Drop old constraint if exists
        if constraint_exists(inspector, "prompts", "uq_team_owner_name_prompt"):
            try:
                batch_op.drop_constraint("uq_team_owner_name_prompt", type_="unique")
                print("Dropped constraint uq_team_owner_name_prompt.")
            except Exception as e:
                print(f"Could not drop constraint uq_team_owner_name_prompt: {e}")

        # Add new composite constraint if not exists
        if not constraint_exists(inspector, "prompts", "uq_team_owner_gateway_name_prompt"):
            try:
                batch_op.create_unique_constraint("uq_team_owner_gateway_name_prompt", ["team_id", "owner_email", "gateway_id", "name"])
                print("Created constraint uq_team_owner_gateway_name_prompt.")
            except Exception as e:
                print(f"Could not create constraint uq_team_owner_gateway_name_prompt (may already exist): {e}")
        else:
            print("Constraint uq_team_owner_gateway_name_prompt already exists, skipping create.")

        # Add partial index for local prompts if not exists
        if not index_exists(inspector, "prompts", "uq_team_owner_name_prompt_local"):
            try:
                batch_op.create_index(
                    "uq_team_owner_name_prompt_local", ["team_id", "owner_email", "name"], unique=True, postgresql_where=text("gateway_id IS NULL"), sqlite_where=text("gateway_id IS NULL")
                )
                print("Created index uq_team_owner_name_prompt_local.")
            except Exception as e:
                print(f"Could not create index uq_team_owner_name_prompt_local (may already exist): {e}")
        else:
            print("Index uq_team_owner_name_prompt_local already exists, skipping create.")


def upgrade() -> None:
    """Update unique constraints for Resources and Prompts.

    1. Drop restrictive old constraints (if they exist).
    2. Add new team-aware composite constraints (team, owner, gateway, id).
    3. Add partial unique indexes for local items (gateway_id IS NULL).

    Each table is processed independently - failure on one does not skip the other.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _upgrade_resources(inspector)
    _upgrade_prompts(inspector)


def _downgrade_resources(inspector: sa.Inspector) -> None:
    """Revert constraints for resources table.

    Args:
        inspector: SQLAlchemy inspector instance for database introspection.
    """
    if "resources" not in inspector.get_table_names():
        print("Resources table not found. Skipping resources downgrade.")
        return

    print("Reverting resources table constraints...")
    with op.batch_alter_table("resources", schema=None) as batch_op:
        # Drop new index if exists
        if index_exists(inspector, "resources", "uq_team_owner_uri_resource_local"):
            try:
                batch_op.drop_index("uq_team_owner_uri_resource_local")
                print("Dropped index uq_team_owner_uri_resource_local.")
            except Exception as e:
                print(f"Could not drop index uq_team_owner_uri_resource_local: {e}")

        # Drop new constraint if exists
        if constraint_exists(inspector, "resources", "uq_team_owner_gateway_uri_resource"):
            try:
                batch_op.drop_constraint("uq_team_owner_gateway_uri_resource", type_="unique")
                print("Dropped constraint uq_team_owner_gateway_uri_resource.")
            except Exception as e:
                print(f"Could not drop constraint uq_team_owner_gateway_uri_resource: {e}")

        # Recreate old constraint if not exists
        if not constraint_exists(inspector, "resources", "uq_team_owner_uri_resource"):
            try:
                batch_op.create_unique_constraint("uq_team_owner_uri_resource", ["team_id", "owner_email", "uri"])
                print("Created constraint uq_team_owner_uri_resource.")
            except Exception as e:
                print(f"Could not create constraint uq_team_owner_uri_resource (may already exist): {e}")


def _downgrade_prompts(inspector: sa.Inspector) -> None:
    """Revert constraints for prompts table.

    Args:
        inspector: SQLAlchemy inspector instance for database introspection.
    """
    if "prompts" not in inspector.get_table_names():
        print("Prompts table not found. Skipping prompts downgrade.")
        return

    print("Reverting prompts table constraints...")
    with op.batch_alter_table("prompts", schema=None) as batch_op:
        # Drop new index if exists
        if index_exists(inspector, "prompts", "uq_team_owner_name_prompt_local"):
            try:
                batch_op.drop_index("uq_team_owner_name_prompt_local")
                print("Dropped index uq_team_owner_name_prompt_local.")
            except Exception as e:
                print(f"Could not drop index uq_team_owner_name_prompt_local: {e}")

        # Drop new constraint if exists
        if constraint_exists(inspector, "prompts", "uq_team_owner_gateway_name_prompt"):
            try:
                batch_op.drop_constraint("uq_team_owner_gateway_name_prompt", type_="unique")
                print("Dropped constraint uq_team_owner_gateway_name_prompt.")
            except Exception as e:
                print(f"Could not drop constraint uq_team_owner_gateway_name_prompt: {e}")

        # Recreate old constraint if not exists
        if not constraint_exists(inspector, "prompts", "uq_team_owner_name_prompt"):
            try:
                batch_op.create_unique_constraint("uq_team_owner_name_prompt", ["team_id", "owner_email", "name"])
                print("Created constraint uq_team_owner_name_prompt.")
            except Exception as e:
                print(f"Could not create constraint uq_team_owner_name_prompt (may already exist): {e}")


def downgrade() -> None:
    """Revert constraints to original state.

    Each table is processed independently - failure on one does not skip the other.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _downgrade_resources(inspector)
    _downgrade_prompts(inspector)
