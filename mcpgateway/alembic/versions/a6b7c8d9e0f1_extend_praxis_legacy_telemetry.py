"""Extend Praxis legacy telemetry for authenticated removal gating.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a6b7c8d9e0f1"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "f5a6b7c8d9e0"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATE = "praxis_legacy_telemetry_state"
CONSUMERS = "praxis_legacy_consumers"
STATE_SHADOW_CHECK = "ck_praxis_legacy_telemetry_state_shadow_diff_count"
CONSUMER_RETENTION_CHECK = "ck_praxis_legacy_consumers_retention_state"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _unique_names(table: str) -> set[str | None]:
    return {constraint.get("name") for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table)}


def _check_names(table: str) -> set[str | None]:
    return {constraint.get("name") for constraint in sa.inspect(op.get_bind()).get_check_constraints(table)}


def upgrade() -> None:
    """Add only missing gate and authenticated-heartbeat fields."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if STATE in tables:
        columns = _columns(STATE)
        checks = _check_names(STATE)
        additions = (
            ("private_state_present", sa.Column("private_state_present", sa.Boolean(), nullable=False, server_default=sa.false())),
            ("shadow_diff_count", sa.Column("shadow_diff_count", sa.Integer(), nullable=False, server_default="0")),
            ("task20_e2e_passed", sa.Column("task20_e2e_passed", sa.Boolean(), nullable=False, server_default=sa.false())),
            ("launcher_fleet_compatible", sa.Column("launcher_fleet_compatible", sa.Boolean(), nullable=False, server_default=sa.false())),
        )
        with op.batch_alter_table(STATE) as batch:
            for name, column in additions:
                if name not in columns:
                    batch.add_column(column)
            if STATE_SHADOW_CHECK not in checks:
                batch.create_check_constraint(op.f(STATE_SHADOW_CHECK), "shadow_diff_count >= 0")
    if CONSUMERS in tables:
        columns = _columns(CONSUMERS)
        checks = _check_names(CONSUMERS)
        additions = (
            ("consumer_path", sa.Column("consumer_path", sa.String(64), nullable=False, server_default="control_plane_grpc")),
            ("authenticated_identity", sa.Column("authenticated_identity", sa.String(255), nullable=True)),
            ("observed", sa.Column("observed", sa.Boolean(), nullable=False, server_default=sa.false())),
            ("attested", sa.Column("attested", sa.Boolean(), nullable=False, server_default=sa.false())),
            ("expires_at", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)),
            ("retention_state", sa.Column("retention_state", sa.String(32), nullable=False, server_default="active")),
        )
        with op.batch_alter_table(CONSUMERS) as batch:
            for name, column in additions:
                if name not in columns:
                    batch.add_column(column)
            if CONSUMER_RETENTION_CHECK not in checks:
                batch.create_check_constraint(op.f(CONSUMER_RETENTION_CHECK), "retention_state IN ('active', 'retained', 'expired')")
            if "uq_praxis_legacy_consumers_identity_path" not in _unique_names(CONSUMERS):
                batch.create_unique_constraint("uq_praxis_legacy_consumers_identity_path", ["declared_identity", "consumer_path"])


def downgrade() -> None:
    """Remove only fields introduced by this revision."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if CONSUMERS in tables:
        columns = _columns(CONSUMERS)
        checks = _check_names(CONSUMERS)
        with op.batch_alter_table(CONSUMERS) as batch:
            if "uq_praxis_legacy_consumers_identity_path" in _unique_names(CONSUMERS):
                batch.drop_constraint("uq_praxis_legacy_consumers_identity_path", type_="unique")
            if CONSUMER_RETENTION_CHECK in checks:
                batch.drop_constraint(op.f(CONSUMER_RETENTION_CHECK), type_="check")
            for name in ("retention_state", "expires_at", "attested", "observed", "authenticated_identity", "consumer_path"):
                if name in columns:
                    batch.drop_column(name)
    if STATE in tables:
        columns = _columns(STATE)
        checks = _check_names(STATE)
        with op.batch_alter_table(STATE) as batch:
            if STATE_SHADOW_CHECK in checks:
                batch.drop_constraint(op.f(STATE_SHADOW_CHECK), type_="check")
            for name in ("launcher_fleet_compatible", "task20_e2e_passed", "shadow_diff_count", "private_state_present"):
                if name in columns:
                    batch.drop_column(name)
