# -*- coding: utf-8 -*-
"""Persistence contract tests for Praxis bundle delivery models."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mcpgateway.db import (
    Base,
    PraxisBundleGeneration,
    PraxisCryptoNonceReservation,
    PraxisLegacyConsumer,
    PraxisLegacyTelemetryState,
    PraxisReplica,
    PraxisReplicaCredential,
    PraxisReplicaReport,
    PraxisRollout,
    PraxisRolloutReplica,
    PraxisTarget,
    PraxisTargetServer,
    Server,
)

MIGRATION_MODULE = "mcpgateway.alembic.versions.f5a6b7c8d9e0_add_praxis_bundle_persistence"
TELEMETRY_MIGRATION_MODULE = "mcpgateway.alembic.versions.a6b7c8d9e0f1_extend_praxis_legacy_telemetry"
PRAXIS_TABLES = {name for name in Base.metadata.tables if name.startswith("praxis_")}


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = sa.create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    engine.dispose()


def _target(target_id: str) -> PraxisTarget:
    return PraxisTarget(id=target_id, name=f"Target {target_id}", created_by="admin@example.com")


def _generation(target_id: str, generation_id: str, *, nonce: bytes = b"n" * 12) -> PraxisBundleGeneration:
    return PraxisBundleGeneration(
        target_id=target_id,
        generation_id=generation_id,
        source_fingerprint="1" * 64,
        payload_hash="2" * 64,
        content_hash="3" * 64,
        ciphertext_hash="4" * 64,
        ciphertext=b"ciphertext-and-tag",
        envelope_version=1,
        key_id="key-1",
        nonce=nonce,
        source_ciphertext_hash="5" * 64,
        source_ciphertext=b"source-ciphertext-and-tag",
        source_envelope_version=1,
        source_key_id="source-key-1",
        source_nonce=nonce,
        source_schema="praxis-source/v1",
        bundle_schema="praxis-bundle/v1",
        renderer_version="1",
        praxis_revision="ed46eb5",
        cpex_contract_version="1",
        mcp_protocol_version="2025-11-25",
        minimum_launcher_version="1",
    )


def _rollout(target_id: str, rollout_id: str, generation_id: str, directive_id: str) -> PraxisRollout:
    return PraxisRollout(
        target_id=target_id,
        rollout_id=rollout_id,
        generation_id=generation_id,
        directive_id=directive_id,
        policy_epoch=1,
        action="activate",
        eligibility_deadline=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _replica(target_id: str, replica_id: str) -> PraxisReplica:
    return PraxisReplica(id=replica_id, target_id=target_id, name=f"Replica {replica_id}")


def test_models_expose_epochs_binary_ciphertext_and_source_index() -> None:
    target_columns = PraxisTarget.__table__.c
    generation_columns = PraxisBundleGeneration.__table__.c
    reservation_columns = PraxisCryptoNonceReservation.__table__.c

    assert len(PRAXIS_TABLES) == 11
    assert {"source_epoch", "policy_epoch", "fence", "desired_rollout_id"} <= set(target_columns.keys())
    assert isinstance(generation_columns.ciphertext.type, sa.LargeBinary)
    assert isinstance(reservation_columns.nonce.type, sa.LargeBinary)
    assert {column.name for column in PraxisCryptoNonceReservation.__table__.primary_key} == {"cryptographic_key_id", "nonce"}
    assert "plaintext" not in generation_columns
    assert "ix_praxis_bundle_generations_source_fingerprint" in {index.name for index in PraxisBundleGeneration.__table_args__ if isinstance(index, sa.Index)}


def test_server_assignment_is_unique_and_target_owned(session: Session) -> None:
    session.add_all([_target("target-a"), _target("target-b"), Server(id="server-1", name="server")])
    session.flush()
    session.add(PraxisTargetServer(target_id="target-a", server_id="server-1", assigned_by="admin@example.com"))
    session.flush()

    session.add(PraxisTargetServer(target_id="target-b", server_id="server-1", assigned_by="admin@example.com"))

    with pytest.raises(IntegrityError):
        session.flush()


def test_generation_identity_and_nonce_are_unique(session: Session) -> None:
    session.add_all([_target("target-a"), _target("target-b")])
    session.flush()
    session.add(_generation("target-a", "generation-1"))
    session.flush()

    session.add(_generation("target-a", "generation-1", nonce=b"x" * 12))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    session.add(_generation("target-b", "generation-2"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_rollout_generation_and_desired_pointer_cannot_cross_targets(session: Session) -> None:
    session.add_all([_target("target-a"), _target("target-b"), _generation("target-a", "generation-1")])
    session.flush()
    session.add(_rollout("target-b", "rollout-1", "generation-1", "a" * 64))

    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    session.add_all([_target("target-a"), _target("target-b")])
    session.flush()
    session.add_all([_generation("target-a", "generation-1"), _generation("target-b", "generation-2", nonce=b"x" * 12)])
    session.flush()
    session.add(_rollout("target-b", "rollout-2", "generation-2", "b" * 64))
    session.flush()
    target_a = session.get(PraxisTarget, "target-a")
    assert target_a is not None
    target_a.desired_rollout_id = "rollout-2"
    with pytest.raises(IntegrityError):
        session.flush()


def test_frozen_cohort_binds_target_rollout_replica_and_directive(session: Session) -> None:
    session.add_all([_target("target-a"), _target("target-b"), _generation("target-a", "generation-1"), _replica("target-a", "replica-1")])
    session.flush()
    session.add(_rollout("target-a", "rollout-1", "generation-1", "a" * 64))
    session.flush()
    session.add(PraxisRolloutReplica(target_id="target-b", rollout_id="rollout-1", replica_id="replica-1", directive_id="a" * 64))

    with pytest.raises(IntegrityError):
        session.flush()


def test_credentials_have_global_jti_identity(session: Session) -> None:
    session.add_all([_target("target-a"), _target("target-b"), _replica("target-a", "replica-1"), _replica("target-b", "replica-2")])
    session.flush()
    session.add(PraxisReplicaCredential(target_id="target-a", replica_id="replica-1", jti="global-jti", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    session.flush()
    session.add(PraxisReplicaCredential(target_id="target-b", replica_id="replica-2", jti="global-jti", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))

    with pytest.raises(IntegrityError):
        session.flush()


def test_reports_are_unique_and_bound_to_frozen_cohort(session: Session) -> None:
    session.add_all([_target("target-a"), _generation("target-a", "generation-1"), _replica("target-a", "replica-1")])
    session.flush()
    session.add(_rollout("target-a", "rollout-1", "generation-1", "a" * 64))
    session.flush()
    session.add(PraxisRolloutReplica(target_id="target-a", rollout_id="rollout-1", replica_id="replica-1", directive_id="a" * 64))
    session.flush()
    report = PraxisReplicaReport(target_id="target-a", rollout_id="rollout-1", replica_id="replica-1", directive_id="a" * 64, sequence=1, state="prepared")
    session.add(report)
    session.flush()
    session.add(PraxisReplicaReport(target_id="target-a", rollout_id="rollout-1", replica_id="replica-1", directive_id="a" * 64, sequence=1, state="active"))

    with pytest.raises(IntegrityError):
        session.flush()


def test_report_to_wrong_directive_is_rejected(session: Session) -> None:
    session.add_all([_target("target-a"), _generation("target-a", "generation-1"), _replica("target-a", "replica-1")])
    session.flush()
    session.add(_rollout("target-a", "rollout-1", "generation-1", "a" * 64))
    session.flush()
    session.add(PraxisRolloutReplica(target_id="target-a", rollout_id="rollout-1", replica_id="replica-1", directive_id="a" * 64))
    session.flush()
    session.add(PraxisReplicaReport(target_id="target-a", rollout_id="rollout-1", replica_id="replica-1", directive_id="b" * 64, sequence=1, state="prepared"))

    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize(
    ("factory", "field", "replacement"),
    [
        (lambda: _generation("target-a", "generation-pk", nonce=b"p" * 12), "id", "generation-row-2"),
        (lambda: _generation("target-a", "generation-created", nonce=b"c" * 12), "created_at", datetime(2020, 1, 1, tzinfo=timezone.utc)),
        (lambda: _generation("target-a", "generation-immutable", nonce=b"i" * 12), "generation_id", "generation-2"),
        (lambda: _generation("target-a", "generation-source-hash", nonce=b"h" * 12), "source_ciphertext_hash", "6" * 64),
        (lambda: _generation("target-a", "generation-source-ciphertext", nonce=b"q" * 12), "source_ciphertext", b"changed-source-ciphertext"),
        (lambda: _generation("target-a", "generation-source-version", nonce=b"v" * 12), "source_envelope_version", 2),
        (lambda: _generation("target-a", "generation-source-key", nonce=b"k" * 12), "source_key_id", "source-key-2"),
        (lambda: _generation("target-a", "generation-source-nonce", nonce=b"n" * 12), "source_nonce", b"m" * 12),
        (lambda: _generation("target-a", "generation-source-schema", nonce=b"s" * 12), "source_schema", "praxis-source/v2"),
        (lambda: _rollout("target-a", "rollout-pk", "generation-base", "d" * 64), "id", "rollout-row-2"),
        (lambda: _rollout("target-a", "rollout-created", "generation-base", "e" * 64), "created_at", datetime(2020, 1, 1, tzinfo=timezone.utc)),
        (lambda: _rollout("target-a", "rollout-immutable", "generation-base", "b" * 64), "directive_id", "c" * 64),
        (lambda: PraxisRolloutReplica(target_id="target-a", rollout_id="rollout-base", replica_id="replica-1", directive_id="a" * 64), "id", "cohort-row-2"),
        (lambda: PraxisRolloutReplica(target_id="target-a", rollout_id="rollout-base", replica_id="replica-1", directive_id="a" * 64), "replica_id", "replica-2"),
        (lambda: PraxisReplicaCredential(target_id="target-a", replica_id="replica-1", jti="jti-pk", expires_at=datetime.now(timezone.utc)), "id", "credential-row-2"),
        (lambda: PraxisReplicaCredential(target_id="target-a", replica_id="replica-1", jti="jti-1", expires_at=datetime.now(timezone.utc)), "jti", "jti-2"),
        (lambda: PraxisReplicaReport(target_id="target-a", rollout_id="rollout-base", replica_id="replica-1", directive_id="a" * 64, sequence=2, state="prepared"), "id", "report-row-2"),
        (lambda: PraxisReplicaReport(target_id="target-a", rollout_id="rollout-base", replica_id="replica-1", directive_id="a" * 64, sequence=1, state="prepared"), "sequence", 2),
        (lambda: _replica("target-a", "replica-identity"), "id", "replica-moved"),
        (lambda: _replica("target-a", "replica-target"), "target_id", "target-b"),
    ],
)
def test_persisted_identity_fields_are_immutable(session: Session, factory, field: str, replacement: str | bytes | int | datetime) -> None:
    session.add_all([_target("target-a"), _target("target-b"), _generation("target-a", "generation-base", nonce=b"z" * 12), _replica("target-a", "replica-1"), _replica("target-a", "replica-2")])
    session.flush()
    session.add(_rollout("target-a", "rollout-base", "generation-base", "a" * 64))
    session.flush()
    model = factory()
    if type(model) is PraxisReplicaReport:
        session.add(PraxisRolloutReplica(target_id="target-a", rollout_id="rollout-base", replica_id="replica-1", directive_id="a" * 64))
        session.flush()
    session.add(model)
    session.commit()
    setattr(model, field, replacement)

    with pytest.raises(ValueError, match="immutable"):
        session.flush()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("cryptographic_key_id", "key-b"),
        ("nonce", b"m" * 12),
        ("reserved_at", datetime(2030, 1, 1, tzinfo=timezone.utc)),
    ],
)
def test_persisted_nonce_reservation_fields_are_immutable_after_rollback(session: Session, field: str, replacement: str | bytes | datetime) -> None:
    # Given
    reserved_at = datetime(2026, 8, 11, tzinfo=timezone.utc)
    reservation = PraxisCryptoNonceReservation(cryptographic_key_id="key-a", nonce=b"n" * 12, reserved_at=reserved_at)
    session.add(reservation)
    session.commit()
    session.refresh(reservation)
    stored_reserved_at = reservation.reserved_at

    # When
    setattr(reservation, field, replacement)

    # Then
    with pytest.raises(ValueError, match=f"PraxisCryptoNonceReservation.{field} is immutable"):
        session.flush()
    session.rollback()
    reloaded = session.get(PraxisCryptoNonceReservation, {"cryptographic_key_id": "key-a", "nonce": b"n" * 12})
    assert reloaded is not None
    assert (reloaded.cryptographic_key_id, reloaded.nonce, reloaded.reserved_at) == ("key-a", b"n" * 12, stored_reserved_at)


def test_lifecycle_fields_remain_mutable(session: Session) -> None:
    now = datetime.now(timezone.utc)
    target = _target("target-a")
    generation = _generation("target-a", "generation-base")
    replica = _replica("target-a", "replica-1")
    session.add_all([target, generation, replica])
    session.flush()
    rollout = _rollout("target-a", "rollout-base", "generation-base", "a" * 64)
    session.add(rollout)
    session.flush()
    cohort = PraxisRolloutReplica(target_id="target-a", rollout_id="rollout-base", replica_id="replica-1", directive_id="a" * 64)
    credential = PraxisReplicaCredential(target_id="target-a", replica_id="replica-1", jti="jti-1", expires_at=now + timedelta(days=1))
    telemetry = PraxisLegacyTelemetryState(id=1, cas_epoch=0)
    consumer = PraxisLegacyConsumer(id="consumer-1", declared_identity="legacy", declared_version="1", observability_class="heartbeat")
    session.add_all([cohort, credential, telemetry, consumer])
    session.flush()

    target.source_epoch = target.policy_epoch = target.fence = 1
    target.desired_rollout_id = "rollout-base"
    rollout.status, rollout.failure_category = "failed", "timeout"
    replica.last_heartbeat_at, replica.revoked_at, replica.credential_epoch = now, now, 1
    cohort.state, cohort.last_report_sequence = "failed", 1
    credential.last_seen_at = credential.revoked_at = now
    telemetry.coverage_started_at, telemetry.inventory_attested_at, telemetry.cas_epoch = now, now, 1
    consumer.last_seen_at, consumer.active, consumer.revoked_at, consumer.retain_until = now, False, now, now + timedelta(days=90)
    session.flush()


def test_legacy_state_is_singleton_and_consumer_uuid_is_unique(session: Session) -> None:
    session.add(PraxisLegacyTelemetryState(id=1, cas_epoch=0))
    session.add(PraxisLegacyConsumer(id="consumer-uuid", declared_identity="legacy-a", declared_version="1", observability_class="heartbeat"))
    session.flush()
    session.add(PraxisLegacyTelemetryState(id=2, cas_epoch=0))

    with pytest.raises(IntegrityError):
        session.flush()


def test_migration_is_idempotent_and_roundtrip_preserves_unrelated_data() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        connection.execute(sa.text("CREATE TABLE servers (id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE task6_sentinel (value TEXT NOT NULL)"))
        connection.execute(sa.text("INSERT INTO task6_sentinel VALUES ('preserved')"))
        context = MigrationContext.configure(connection)
        module = importlib.import_module(MIGRATION_MODULE)
        telemetry_module = importlib.import_module(TELEMETRY_MIGRATION_MODULE)
        with Operations.context(context):
            module.upgrade()
            module.upgrade()
            telemetry_module.upgrade()
            telemetry_module.upgrade()
        inspector = sa.inspect(connection)
        assert PRAXIS_TABLES <= set(inspector.get_table_names())
        for table_name in PRAXIS_TABLES:
            expected = Base.metadata.tables[table_name]
            actual_columns = {column["name"]: (str(column["type"].compile(dialect=engine.dialect)), column["nullable"]) for column in inspector.get_columns(table_name)}
            expected_columns = {column.name: (str(column.type.compile(dialect=engine.dialect)), column.nullable) for column in expected.c}
            assert actual_columns == expected_columns
            assert {(constraint["name"], tuple(constraint["column_names"])) for constraint in inspector.get_unique_constraints(table_name)} == {(constraint.name, tuple(column.name for column in constraint.columns)) for constraint in expected.constraints if isinstance(constraint, sa.UniqueConstraint)}
            assert {(constraint["name"], tuple(constraint["constrained_columns"]), constraint["referred_table"], tuple(constraint["referred_columns"])) for constraint in inspector.get_foreign_keys(table_name)} == {(constraint.name, tuple(column.name for column in constraint.columns), constraint.referred_table.name, tuple(element.column.name for element in constraint.elements)) for constraint in expected.constraints if isinstance(constraint, sa.ForeignKeyConstraint)}
            assert {constraint["name"] for constraint in inspector.get_check_constraints(table_name)} == {constraint.name for constraint in expected.constraints if isinstance(constraint, sa.CheckConstraint)}
            assert {(index["name"], tuple(index["column_names"]), index["unique"]) for index in inspector.get_indexes(table_name) if not index.get("duplicates_constraint")} == {(index.name, tuple(column.name for column in index.columns), index.unique) for index in expected.indexes}

        with Operations.context(context):
            telemetry_module.downgrade()
            module.downgrade()
        assert PRAXIS_TABLES.isdisjoint(sa.inspect(connection).get_table_names())
        assert connection.execute(sa.text("SELECT value FROM task6_sentinel")).scalar_one() == "preserved"
    engine.dispose()


def test_migration_extends_the_verified_head() -> None:
    module = importlib.import_module(MIGRATION_MODULE)
    telemetry_module = importlib.import_module(TELEMETRY_MIGRATION_MODULE)

    assert module.revision == "f5a6b7c8d9e0"  # pragma: allowlist secret
    assert module.down_revision == "e4f5a6b7c8d9"  # pragma: allowlist secret
    assert telemetry_module.revision == "a6b7c8d9e0f1"  # pragma: allowlist secret
    assert telemetry_module.down_revision == module.revision
