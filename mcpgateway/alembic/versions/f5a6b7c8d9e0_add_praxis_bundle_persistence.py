# -*- coding: utf-8 -*-
"""Add target-owned Praxis bundle, rollout, replica, and telemetry persistence.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-10 00:00:00.000000
Size exception: # noqa: SIZE_OK - one indivisible revision for interdependent tables.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f5a6b7c8d9e0"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d9"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TARGETS = "praxis_targets"
TARGET_SERVERS = "praxis_target_servers"
GENERATIONS = "praxis_bundle_generations"
NONCE_RESERVATIONS = "praxis_crypto_nonce_reservations"
ROLLOUTS = "praxis_rollouts"
REPLICAS = "praxis_replicas"
COHORT = "praxis_rollout_replicas"
CREDENTIALS = "praxis_replica_credentials"  # pragma: allowlist secret
REPORTS = "praxis_replica_reports"
LEGACY_STATE = "praxis_legacy_telemetry_state"
LEGACY_CONSUMERS = "praxis_legacy_consumers"
DESIRED_FK = "fk_praxis_targets_desired_rollout"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_targets() -> None:
    op.create_table(
        TARGETS,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("source_epoch", sa.BigInteger(), nullable=False),
        sa.Column("policy_epoch", sa.BigInteger(), nullable=False),
        sa.Column("fence", sa.BigInteger(), nullable=False),
        sa.Column("desired_rollout_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.CheckConstraint("source_epoch >= 0", name=op.f("ck_praxis_targets_source_epoch")),
        sa.CheckConstraint("policy_epoch >= 0", name=op.f("ck_praxis_targets_policy_epoch")),
        sa.CheckConstraint("fence >= 0", name=op.f("ck_praxis_targets_fence")),
        sa.PrimaryKeyConstraint("id", name="pk_praxis_targets"),
        sa.UniqueConstraint("name", name="uq_praxis_targets_name"),
    )


def _create_target_servers() -> None:
    op.create_table(
        TARGET_SERVERS,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("server_id", sa.String(36), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_by", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], [f"{TARGETS}.id"], name="fk_praxis_target_servers_target_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], name="fk_praxis_target_servers_server_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_praxis_target_servers"),
        sa.UniqueConstraint("target_id", "server_id", name="uq_praxis_target_servers_target_server"),
        sa.UniqueConstraint("server_id", name="uq_praxis_target_servers_assignment"),
    )


def _create_generations() -> None:
    op.create_table(
        GENERATIONS,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("generation_id", sa.String(64), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_epoch", sa.BigInteger(), nullable=False),
        sa.Column("policy_epoch", sa.BigInteger(), nullable=False),
        sa.Column("fence", sa.BigInteger(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("ciphertext_hash", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("envelope_version", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.String(255), nullable=False),
        sa.Column("nonce", sa.LargeBinary(12), nullable=False),
        sa.Column("source_ciphertext_hash", sa.String(64), nullable=False),
        sa.Column("source_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("source_envelope_version", sa.Integer(), nullable=False),
        sa.Column("source_key_id", sa.String(255), nullable=False),
        sa.Column("source_nonce", sa.LargeBinary(12), nullable=False),
        sa.Column("source_schema", sa.String(64), nullable=False),
        sa.Column("bundle_schema", sa.String(64), nullable=False),
        sa.Column("renderer_version", sa.String(64), nullable=False),
        sa.Column("praxis_revision", sa.String(64), nullable=False),
        sa.Column("cpex_contract_version", sa.String(64), nullable=False),
        sa.Column("mcp_protocol_version", sa.String(64), nullable=False),
        sa.Column("minimum_launcher_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_epoch >= 0", name=op.f("ck_praxis_bundle_generations_source_epoch")),
        sa.CheckConstraint("policy_epoch >= 0", name=op.f("ck_praxis_bundle_generations_policy_epoch")),
        sa.CheckConstraint("fence >= 0", name=op.f("ck_praxis_bundle_generations_fence")),
        sa.CheckConstraint("envelope_version > 0", name=op.f("ck_praxis_bundle_generations_envelope_version")),
        sa.CheckConstraint("source_envelope_version > 0", name=op.f("ck_praxis_bundle_generations_source_envelope_version")),
        sa.ForeignKeyConstraint(["target_id"], [f"{TARGETS}.id"], name="fk_praxis_bundle_generations_target_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_praxis_bundle_generations"),
        sa.UniqueConstraint("target_id", "generation_id", name="uq_praxis_bundle_generations_target_generation"),
        sa.UniqueConstraint("key_id", "nonce", name="uq_praxis_bundle_generations_key_nonce"),
        sa.UniqueConstraint("source_key_id", "source_nonce", name="uq_praxis_bundle_generations_source_key_nonce"),
    )
    op.create_index("ix_praxis_bundle_generations_source_fingerprint", GENERATIONS, ["source_fingerprint"], unique=False)


def _create_nonce_reservations() -> None:
    op.create_table(
        NONCE_RESERVATIONS,
        sa.Column("cryptographic_key_id", sa.String(255), nullable=False),
        sa.Column("nonce", sa.LargeBinary(12), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("cryptographic_key_id", "nonce", name="pk_praxis_crypto_nonce_reservations"),
    )


def _create_rollouts() -> None:
    op.create_table(
        ROLLOUTS,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("rollout_id", sa.String(64), nullable=False),
        sa.Column("generation_id", sa.String(64), nullable=True),
        sa.Column("directive_id", sa.String(64), nullable=False),
        sa.Column("policy_epoch", sa.BigInteger(), nullable=False),
        sa.Column("source_epoch", sa.BigInteger(), nullable=False),
        sa.Column("fence", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("eligibility_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("rollback_eligible", sa.Boolean(), nullable=False),
        sa.Column("eligibility_reason", sa.String(255), nullable=True),
        sa.Column("failure_category", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("policy_epoch >= 0", name=op.f("ck_praxis_rollouts_policy_epoch")),
        sa.CheckConstraint("source_epoch >= 0", name=op.f("ck_praxis_rollouts_source_epoch")),
        sa.CheckConstraint("fence >= 0", name=op.f("ck_praxis_rollouts_fence")),
        sa.CheckConstraint("action IN ('activate', 'retry', 'rollback', 'stop')", name=op.f("ck_praxis_rollouts_action")),
        sa.CheckConstraint("(action = 'stop' AND generation_id IS NULL) OR (action <> 'stop' AND generation_id IS NOT NULL)", name=op.f("ck_praxis_rollouts_action_generation")),
        sa.ForeignKeyConstraint(["target_id"], [f"{TARGETS}.id"], name="fk_praxis_rollouts_target_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id", "generation_id"], [f"{GENERATIONS}.target_id", f"{GENERATIONS}.generation_id"], name="fk_praxis_rollouts_target_generation"),
        sa.PrimaryKeyConstraint("id", name="pk_praxis_rollouts"),
        sa.UniqueConstraint("directive_id", name="uq_praxis_rollouts_directive_id"),
        sa.UniqueConstraint("target_id", "rollout_id", name="uq_praxis_rollouts_target_rollout"),
        sa.UniqueConstraint("target_id", "rollout_id", "directive_id", name="uq_praxis_rollouts_target_rollout_directive"),
    )


def _create_replicas() -> None:
    op.create_table(
        REPLICAS,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("credential_epoch", sa.BigInteger(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("credential_epoch >= 0", name=op.f("ck_praxis_replicas_credential_epoch")),
        sa.ForeignKeyConstraint(["target_id"], [f"{TARGETS}.id"], name="fk_praxis_replicas_target_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_praxis_replicas"),
        sa.UniqueConstraint("target_id", "id", name="uq_praxis_replicas_target_replica"),
        sa.UniqueConstraint("target_id", "name", name="uq_praxis_replicas_target_name"),
    )


def _create_cohort() -> None:
    op.create_table(
        COHORT,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("rollout_id", sa.String(64), nullable=False),
        sa.Column("replica_id", sa.String(36), nullable=False),
        sa.Column("directive_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("last_report_sequence", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("position >= 0", name=op.f("ck_praxis_rollout_replicas_position")),
        sa.CheckConstraint("last_report_sequence >= 0", name=op.f("ck_praxis_rollout_replicas_report_sequence")),
        sa.ForeignKeyConstraint(["target_id", "rollout_id", "directive_id"], [f"{ROLLOUTS}.target_id", f"{ROLLOUTS}.rollout_id", f"{ROLLOUTS}.directive_id"], name="fk_praxis_rollout_replicas_rollout_directive", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id", "replica_id"], [f"{REPLICAS}.target_id", f"{REPLICAS}.id"], name="fk_praxis_rollout_replicas_target_replica", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_praxis_rollout_replicas"),
        sa.UniqueConstraint("target_id", "rollout_id", "replica_id", name="uq_praxis_rollout_replicas_membership"),
        sa.UniqueConstraint("target_id", "rollout_id", "replica_id", "directive_id", name="uq_praxis_rollout_replicas_report_binding"),
        sa.UniqueConstraint("target_id", "rollout_id", "position", name="uq_praxis_rollout_replicas_position"),
    )


def _create_credentials() -> None:
    op.create_table(
        CREDENTIALS,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("replica_id", sa.String(36), nullable=False),
        sa.Column("jti", sa.String(255), nullable=False),
        sa.Column("credential_epoch", sa.BigInteger(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("credential_epoch >= 0", name=op.f("ck_praxis_replica_credentials_epoch")),
        sa.ForeignKeyConstraint(["target_id", "replica_id"], [f"{REPLICAS}.target_id", f"{REPLICAS}.id"], name="fk_praxis_replica_credentials_target_replica", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_praxis_replica_credentials"),
        sa.UniqueConstraint("jti", name="uq_praxis_replica_credentials_jti"),
    )


def _create_reports() -> None:
    op.create_table(
        REPORTS,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("rollout_id", sa.String(64), nullable=False),
        sa.Column("replica_id", sa.String(36), nullable=False),
        sa.Column("directive_id", sa.String(64), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("failure_category", sa.String(32), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_praxis_replica_reports_sequence")),
        sa.CheckConstraint("state IN ('prepared', 'canary_passed', 'active', 'failed')", name=op.f("ck_praxis_replica_reports_state")),
        sa.CheckConstraint("(state = 'failed' AND failure_category IS NOT NULL AND failure_category IN ('spawn', 'early_exit', 'config_validation', 'listener', 'policy_canary', 'timeout')) OR (state <> 'failed' AND failure_category IS NULL)", name=op.f("ck_praxis_replica_reports_failure_category")),
        sa.ForeignKeyConstraint(["target_id", "rollout_id", "replica_id", "directive_id"], [f"{COHORT}.target_id", f"{COHORT}.rollout_id", f"{COHORT}.replica_id", f"{COHORT}.directive_id"], name="fk_praxis_replica_reports_cohort", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_praxis_replica_reports"),
        sa.UniqueConstraint("target_id", "replica_id", "directive_id", "sequence", name="uq_praxis_replica_reports_identity"),
    )


def _create_legacy_state() -> None:
    op.create_table(
        LEGACY_STATE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("coverage_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inventory_attested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inventory_attested_by", sa.String(255), nullable=True),
        sa.Column("inventory_attestation_hash", sa.String(64), nullable=True),
        sa.Column("cas_epoch", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_praxis_legacy_telemetry_state_singleton")),
        sa.CheckConstraint("cas_epoch >= 0", name=op.f("ck_praxis_legacy_telemetry_state_cas_epoch")),
        sa.PrimaryKeyConstraint("id", name="pk_praxis_legacy_telemetry_state"),
    )


def _create_legacy_consumers() -> None:
    op.create_table(
        LEGACY_CONSUMERS,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("declared_identity", sa.String(255), nullable=False),
        sa.Column("declared_version", sa.String(64), nullable=False),
        sa.Column("observability_class", sa.String(64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(active = true AND revoked_at IS NULL) OR (active = false AND revoked_at IS NOT NULL)", name=op.f("ck_praxis_legacy_consumers_state")),
        sa.PrimaryKeyConstraint("id", name="pk_praxis_legacy_consumers"),
    )


def _ensure_desired_rollout_fk() -> None:
    foreign_keys = sa.inspect(op.get_bind()).get_foreign_keys(TARGETS)
    if any(foreign_key.get("name") == DESIRED_FK for foreign_key in foreign_keys):
        return
    with op.batch_alter_table(TARGETS) as batch_op:
        batch_op.create_foreign_key(DESIRED_FK, ROLLOUTS, ["id", "desired_rollout_id"], ["target_id", "rollout_id"])


def _ensure_source_fingerprint_index() -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes(GENERATIONS)
    if not any(index.get("name") == "ix_praxis_bundle_generations_source_fingerprint" for index in indexes):
        op.create_index("ix_praxis_bundle_generations_source_fingerprint", GENERATIONS, ["source_fingerprint"], unique=False)


def upgrade() -> None:
    """Create missing Praxis persistence tables and the target-owned pointer."""
    creators = (
        (TARGETS, _create_targets),
        (TARGET_SERVERS, _create_target_servers),
        (GENERATIONS, _create_generations),
        (NONCE_RESERVATIONS, _create_nonce_reservations),
        (ROLLOUTS, _create_rollouts),
        (REPLICAS, _create_replicas),
        (COHORT, _create_cohort),
        (CREDENTIALS, _create_credentials),
        (REPORTS, _create_reports),
        (LEGACY_STATE, _create_legacy_state),
        (LEGACY_CONSUMERS, _create_legacy_consumers),
    )
    existing = _tables()
    for table_name, creator in creators:
        if table_name not in existing:
            creator()
            existing.add(table_name)
    _ensure_desired_rollout_fk()
    _ensure_source_fingerprint_index()


def downgrade() -> None:
    """Drop only Praxis persistence tables, preserving unrelated schema and data."""
    existing = _tables()
    if TARGETS in existing:
        foreign_keys = sa.inspect(op.get_bind()).get_foreign_keys(TARGETS)
        if any(foreign_key.get("name") == DESIRED_FK for foreign_key in foreign_keys):
            with op.batch_alter_table(TARGETS) as batch_op:
                batch_op.drop_constraint(DESIRED_FK, type_="foreignkey")
    for table_name in (REPORTS, CREDENTIALS, COHORT, REPLICAS, ROLLOUTS, NONCE_RESERVATIONS, GENERATIONS, TARGET_SERVERS, LEGACY_CONSUMERS, LEGACY_STATE, TARGETS):
        if table_name in existing:
            op.drop_table(table_name)
