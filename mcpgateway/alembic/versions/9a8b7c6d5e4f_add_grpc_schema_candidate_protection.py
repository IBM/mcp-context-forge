# -*- coding: utf-8 -*-
"""Add gRPC schema candidate/reflection-protection state.

Revision ID: 9a8b7c6d5e4f
Revises: f000baa38a15
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

revision: str = "9a8b7c6d5e4f"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "f000baa38a15"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table_name: str) -> set[str]:
    """Return current columns for an existing table."""
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _add_columns(table_name: str, columns: list[sa.Column]) -> None:
    """Idempotently add nullable/defaulted columns without rebuilding tables."""
    if table_name not in sa.inspect(op.get_bind()).get_table_names():
        return
    existing = _column_names(table_name)
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)


def _drop_columns(table_name: str, column_names: list[str]) -> None:
    """Idempotently drop columns without rebuilding tables."""
    if table_name not in sa.inspect(op.get_bind()).get_table_names():
        return
    existing = _column_names(table_name)
    for column_name in column_names:
        if column_name in existing:
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_column(column_name)


def upgrade() -> None:
    """Add candidate schema pointer and last reflection error to gRPC services."""
    _add_columns(
        "grpc_services",
        [
            sa.Column("candidate_artifact_id", sa.String(36), nullable=True),
            sa.Column("last_reflection_error", sa.Text(), nullable=True),
        ],
    )


def downgrade() -> None:
    """Drop candidate schema pointer and last reflection error columns."""
    _drop_columns("grpc_services", ["candidate_artifact_id", "last_reflection_error"])
