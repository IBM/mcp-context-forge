"""add_ondelete_cascade_to_metrics_and_associations

Revision ID: 9fb98535724d
Revises: 926d3e07d098
Create Date: 2026-04-28 15:14:01.089813

"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9fb98535724d"
down_revision: Union[str, Sequence[str], None] = "926d3e07d098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_fk_names(inspector, table_name: str, referred_table: str | None = None) -> list[str]:
    """Return foreign-key constraint names for a table, optionally filtered by target table."""
    names: list[str] = []
    for fk in inspector.get_foreign_keys(table_name):
        if referred_table is not None and fk.get("referred_table") != referred_table:
            continue
        name = fk.get("name")
        if name:
            names.append(name)
    return names


def _has_cascade_fk(inspector, table_name: str, referred_table: str) -> bool:
    """Return True when the FK to the referred table already uses ON DELETE CASCADE."""
    for fk in inspector.get_foreign_keys(table_name):
        if fk.get("referred_table") != referred_table:
            continue
        if (fk.get("options") or {}).get("ondelete") == "CASCADE":
            return True
    return False


def _replace_single_fk_with_cascade(table_name: str, referred_table: str, local_cols: list[str], remote_cols: list[str]) -> None:
    """Replace a single FK to the referred table with an ON DELETE CASCADE version."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if table_name not in inspector.get_table_names():
        return

    if _has_cascade_fk(inspector, table_name, referred_table):
        return

    fk_names = _get_fk_names(inspector, table_name, referred_table)
    if len(fk_names) != 1:
        raise RuntimeError(f"Expected exactly one foreign key from {table_name} to {referred_table}, found {fk_names}")

    fk_name = fk_names[0]
    new_fk_name = f"fk_{table_name}_{local_cols[0]}"

    with op.batch_alter_table(table_name, schema=None) as batch_op:
        batch_op.drop_constraint(fk_name, type_="foreignkey")
        batch_op.create_foreign_key(new_fk_name, referred_table, local_cols, remote_cols, ondelete="CASCADE")


def _replace_all_fks_with_cascade(table_name: str, fk_specs: list[tuple[str, list[str], list[str]]]) -> None:
    """Replace all FKs on an association table with ON DELETE CASCADE versions."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if table_name not in inspector.get_table_names():
        return

    current_fks = inspector.get_foreign_keys(table_name)
    if not current_fks:
        return

    all_cascade = True
    for referred_table, _local_cols, _remote_cols in fk_specs:
        if not _has_cascade_fk(inspector, table_name, referred_table):
            all_cascade = False
            break

    if all_cascade:
        return

    fk_names = [fk.get("name") for fk in current_fks if fk.get("name")]
    expected_targets = {spec[0] for spec in fk_specs}
    actual_targets = {fk.get("referred_table") for fk in current_fks}

    if actual_targets != expected_targets:
        raise RuntimeError(f"Unexpected foreign key layout for {table_name}: targets={sorted(actual_targets)} names={fk_names}")

    with op.batch_alter_table(table_name, schema=None) as batch_op:
        for fk_name in fk_names:
            batch_op.drop_constraint(fk_name, type_="foreignkey")

        for referred_table, local_cols, remote_cols in fk_specs:
            batch_op.create_foreign_key(f"fk_{table_name}_{local_cols[0]}", referred_table, local_cols, remote_cols, ondelete="CASCADE")


def upgrade() -> None:
    """Add CASCADE ondelete to foreign keys in metrics and association tables."""
    _replace_single_fk_with_cascade("tool_metrics", "tools", ["tool_id"], ["id"])
    _replace_single_fk_with_cascade("resource_metrics", "resources", ["resource_id"], ["id"])
    _replace_single_fk_with_cascade("prompt_metrics", "prompts", ["prompt_id"], ["id"])

    _replace_all_fks_with_cascade(
        "server_tool_association",
        [
            ("servers", ["server_id"], ["id"]),
            ("tools", ["tool_id"], ["id"]),
        ],
    )
    _replace_all_fks_with_cascade(
        "server_resource_association",
        [
            ("servers", ["server_id"], ["id"]),
            ("resources", ["resource_id"], ["id"]),
        ],
    )
    _replace_all_fks_with_cascade(
        "server_prompt_association",
        [
            ("servers", ["server_id"], ["id"]),
            ("prompts", ["prompt_id"], ["id"]),
        ],
    )


def _replace_single_fk_without_cascade(table_name: str, referred_table: str, local_cols: list[str], remote_cols: list[str]) -> None:
    """Replace a single FK to the referred table with a default NO ACTION version."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if table_name not in inspector.get_table_names():
        return

    if not _has_cascade_fk(inspector, table_name, referred_table):
        return

    fk_names = _get_fk_names(inspector, table_name, referred_table)
    if len(fk_names) != 1:
        raise RuntimeError(f"Expected exactly one foreign key from {table_name} to {referred_table}, found {fk_names}")

    fk_name = fk_names[0]
    new_fk_name = f"fk_{table_name}_{local_cols[0]}"

    with op.batch_alter_table(table_name, schema=None) as batch_op:
        batch_op.drop_constraint(fk_name, type_="foreignkey")
        batch_op.create_foreign_key(new_fk_name, referred_table, local_cols, remote_cols)


def _replace_all_fks_without_cascade(table_name: str, fk_specs: list[tuple[str, list[str], list[str]]]) -> None:
    """Replace all FKs on an association table with default NO ACTION versions."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if table_name not in inspector.get_table_names():
        return

    current_fks = inspector.get_foreign_keys(table_name)
    if not current_fks:
        return

    any_cascade = False
    for referred_table, _local_cols, _remote_cols in fk_specs:
        if _has_cascade_fk(inspector, table_name, referred_table):
            any_cascade = True
            break

    if not any_cascade:
        return

    fk_names = [fk.get("name") for fk in current_fks if fk.get("name")]
    expected_targets = {spec[0] for spec in fk_specs}
    actual_targets = {fk.get("referred_table") for fk in current_fks}

    if actual_targets != expected_targets:
        raise RuntimeError(f"Unexpected foreign key layout for {table_name}: targets={sorted(actual_targets)} names={fk_names}")

    with op.batch_alter_table(table_name, schema=None) as batch_op:
        for fk_name in fk_names:
            batch_op.drop_constraint(fk_name, type_="foreignkey")

        for referred_table, local_cols, remote_cols in fk_specs:
            batch_op.create_foreign_key(f"fk_{table_name}_{local_cols[0]}", referred_table, local_cols, remote_cols)


def downgrade() -> None:
    """Revert CASCADE ondelete back to default (NO ACTION)."""
    _replace_all_fks_without_cascade(
        "server_prompt_association",
        [
            ("servers", ["server_id"], ["id"]),
            ("prompts", ["prompt_id"], ["id"]),
        ],
    )
    _replace_all_fks_without_cascade(
        "server_resource_association",
        [
            ("servers", ["server_id"], ["id"]),
            ("resources", ["resource_id"], ["id"]),
        ],
    )
    _replace_all_fks_without_cascade(
        "server_tool_association",
        [
            ("servers", ["server_id"], ["id"]),
            ("tools", ["tool_id"], ["id"]),
        ],
    )
    _replace_single_fk_without_cascade("prompt_metrics", "prompts", ["prompt_id"], ["id"])
    _replace_single_fk_without_cascade("resource_metrics", "resources", ["resource_id"], ["id"])
    _replace_single_fk_without_cascade("tool_metrics", "tools", ["tool_id"], ["id"])
