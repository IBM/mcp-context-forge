# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Location: ./mcpgateway/alembic/versions/186346baa97c_add_multi_identity_oauth_support.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

add_multi_identity_oauth_support

Revision ID: 186346baa97c
Revises: 0a089912b5f0
Create Date: 2026-06-09 14:13:17.294492

Enables multiple OAuth identities per ContextForge user per gateway by changing
the unique constraint from (gateway_id, app_user_email) to include user_id
(the OAuth provider's user identifier).

This allows a single ContextForge admin to authorize a gateway with multiple
OAuth provider accounts (e.g., different IBMids) and have each identity's
tokens stored separately.

Old constraint: uq_oauth_gateway_user        -> (gateway_id, app_user_email)
New constraint: uq_oauth_gateway_user_identity -> (gateway_id, app_user_email, user_id)

Related: Issue #5043
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "186346baa97c"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "0a089912b5f0"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace (gateway_id, app_user_email) constraint with (gateway_id, app_user_email, user_id)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Skip if the table doesn't exist yet (fresh DB is created directly from db.py models)
    if "oauth_tokens" not in inspector.get_table_names():
        return

    # Clean up orphaned temp table from a previously failed batch_alter_table run.
    # On SQLite, DDL is non-transactional so the temp table persists after a rollback.
    if "_alembic_tmp_oauth_tokens" in inspector.get_table_names():
        op.drop_table("_alembic_tmp_oauth_tokens")

    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("oauth_tokens")}

    # batch_alter_table is required for SQLite compatibility (SQLite cannot DROP CONSTRAINT
    # directly; Alembic reconstructs the table internally under a batch context).
    with op.batch_alter_table("oauth_tokens") as batch_op:
        # Drop the old (gateway_id, app_user_email) constraint if present
        if "uq_oauth_gateway_user" in existing_constraints:
            batch_op.drop_constraint("uq_oauth_gateway_user", type_="unique")

        # Add the new (gateway_id, app_user_email, user_id) constraint if not already present
        if "uq_oauth_gateway_user_identity" not in existing_constraints:
            batch_op.create_unique_constraint(
                "uq_oauth_gateway_user_identity",
                ["gateway_id", "app_user_email", "user_id"],
            )


def downgrade() -> None:
    """Restore the original (gateway_id, app_user_email) unique constraint.

    WARNING: This downgrade will fail if multiple OAuth identities exist for the same
    (gateway_id, app_user_email) pair. Manual cleanup required before downgrade.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "oauth_tokens" not in inspector.get_table_names():
        return

    # Clean up orphaned temp table from a previously failed batch_alter_table run.
    if "_alembic_tmp_oauth_tokens" in inspector.get_table_names():
        op.drop_table("_alembic_tmp_oauth_tokens")

    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("oauth_tokens")}

    with op.batch_alter_table("oauth_tokens") as batch_op:
        # Remove the multi-identity constraint
        if "uq_oauth_gateway_user_identity" in existing_constraints:
            batch_op.drop_constraint("uq_oauth_gateway_user_identity", type_="unique")

        # Restore the original constraint
        # NOTE: This will fail if duplicate (gateway_id, app_user_email) pairs exist
        if "uq_oauth_gateway_user" not in existing_constraints:
            batch_op.create_unique_constraint(
                "uq_oauth_gateway_user",
                ["gateway_id", "app_user_email"],
            )
