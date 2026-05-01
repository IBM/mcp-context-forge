# -*- coding: utf-8 -*-
"""Add migration_metadata table for hermetic config snapshots

Revision ID: f9a8b7c6d5e4
Revises: a31c6ffc2239
Create Date: 2026-04-27 00:00:00.000000

Introduces a lightweight ``migration_metadata`` table that data migrations can
use to snapshot runtime configuration values at upgrade time.  The
``downgrade()`` of any migration that references ``settings.*`` must read its
config from this snapshot rather than from the live environment, so that
rollbacks are deterministic regardless of what env-vars are set at downgrade
time.

Schema
------
  migration_metadata
    revision   VARCHAR(64)   -- Alembic revision ID           \\
    key        VARCHAR(128)  -- config key name               /  composite PK
    value      TEXT          -- config value (as string)
    created_at TIMESTAMPTZ   -- wall-clock time of the snapshot
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "f9a8b7c6d5e4"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "a31c6ffc2239"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create migration_metadata table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "migration_metadata" in inspector.get_table_names():
        print("  ℹ migration_metadata table already exists. Skipping creation.")
        return

    op.create_table(
        "migration_metadata",
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("revision", "key"),
    )
    print("  ✓ Created migration_metadata table")


def downgrade() -> None:
    """Drop migration_metadata table.

    Raises:
        RuntimeError: If snapshot rows remain in the table, indicating that
            dependent migrations have not been downgraded first.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "migration_metadata" not in inspector.get_table_names():
        print("  ℹ migration_metadata table does not exist. Nothing to drop.")
        return

    count = bind.execute(text("SELECT COUNT(*) FROM migration_metadata")).scalar() or 0
    if count:
        raise RuntimeError(
            f"Cannot drop migration_metadata — {count} snapshot row(s) remain. "
            "Downgrade dependent migrations first (e.g., ba202ac1665f)."
        )

    op.drop_table("migration_metadata")
    print("  ✓ Dropped migration_metadata table")
