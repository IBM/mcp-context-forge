# -*- coding: utf-8 -*-
"""Transactional publication tests for immutable Praxis bundles."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from cpex.framework.models import Config
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Base, PraxisBundleGeneration, PraxisReplica, PraxisRollout, PraxisRolloutReplica, PraxisTarget, ToolPluginBinding
from mcpgateway.schemas import PluginBindingMode, PluginPolicyItem, TeamPolicies, ToolPluginBindingRequest
from mcpgateway.services.praxis_bundle_crypto import PraxisBundleCryptoService
from mcpgateway.services.praxis_bundle_service import PraxisBundlePublicationService, PraxisPublicationHooks, PraxisPublicationStaleError
from mcpgateway.services.praxis_config_source import PraxisConfigSourceService
from mcpgateway.services.praxis_target_epoch import PraxisTargetEpochService
from mcpgateway.services.tool_plugin_binding_service import ToolPluginBindingService
from tests.unit.mcpgateway.services.test_praxis_config_source_support import seed_graph


class _NonceStore:
    def __init__(self) -> None:
        self.values: set[tuple[str, bytes]] = set()

    def reserve(self, key_id: str, nonce: bytes) -> bool:
        value = (key_id, nonce)
        if value in self.values:
            return False
        self.values.add(value)
        return True


class _PublicationCommitFailure(RuntimeError):
    pass


@pytest.fixture
def publication_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'publication.db'}", connect_args={"check_same_thread": False, "timeout": 10})
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    seed_graph(factory)
    with factory() as db:
        db.query(ToolPluginBinding).delete()
        db.add_all(
            [
                PraxisReplica(id="replica-a", target_id="target-alpha", name="Replica A"),
                PraxisReplica(id="replica-b", target_id="target-alpha", name="Replica B", enabled=False),
            ]
        )
        db.commit()
    yield factory
    engine.dispose()


def _service(factory: sessionmaker[Session], notifications: list[str]) -> PraxisBundlePublicationService:
    source = PraxisConfigSourceService(factory, Config())
    crypto = PraxisBundleCryptoService({"key-a": b"k" * 32}, "key-a", _NonceStore())
    return PraxisBundlePublicationService(factory, source, crypto, lambda event: notifications.append(event.rollout_id))


def test_same_generation_always_creates_fresh_rollout_and_frozen_cohort(publication_factory: sessionmaker[Session]) -> None:
    # Given
    notifications: list[str] = []
    service = _service(publication_factory, notifications)

    # When
    first = service.publish("target-alpha")
    second = service.publish("target-alpha")

    # Then
    assert first.generation_id == second.generation_id
    assert first.rollout_id != second.rollout_id
    assert first.directive_id != second.directive_id
    assert first.cohort_replica_ids == second.cohort_replica_ids == ("replica-a",)
    with publication_factory() as db:
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration)) == 1
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 2
        assert db.scalar(select(func.count()).select_from(PraxisRolloutReplica)) == 2
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None and target.desired_rollout_id == second.rollout_id
        generation = db.scalar(select(PraxisBundleGeneration))
        assert generation is not None
        assert isinstance(generation.ciphertext, bytes)
        assert b"praxis.yaml" not in generation.ciphertext
    assert notifications == [first.rollout_id, second.rollout_id]


def test_source_change_creates_compatibly_distinct_generation(publication_factory: sessionmaker[Session]) -> None:
    # Given
    notifications: list[str] = []
    service = _service(publication_factory, notifications)
    first = service.publish("target-alpha")
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None
        target.source_epoch += 1
        server = target.server_assignments[0].server
        server.name = "Changed server"
        db.commit()

    # When
    second = service.publish("target-alpha")

    # Then
    assert second.generation_id != first.generation_id
    assert second.source_fingerprint != first.source_fingerprint


def test_mutation_after_revalidation_rolls_back_all_publication_writes(publication_factory: sessionmaker[Session]) -> None:
    # Given
    notifications: list[str] = []
    service = _service(publication_factory, notifications)

    def mutate() -> None:
        with publication_factory() as db:
            target = db.get(PraxisTarget, "target-alpha")
            assert target is not None
            target.source_epoch += 1
            db.commit()

    hooks = PraxisPublicationHooks(after_revalidation=mutate)

    # When / Then
    with pytest.raises(PraxisPublicationStaleError):
        service.publish("target-alpha", hooks=hooks)
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None and target.desired_rollout_id is None
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration)) == 0
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 0
        assert db.scalar(select(func.count()).select_from(PraxisRolloutReplica)) == 0
    assert notifications == []


def test_disable_during_render_never_advances_pointer(publication_factory: sessionmaker[Session]) -> None:
    # Given
    notifications: list[str] = []
    service = _service(publication_factory, notifications)

    def disable() -> None:
        with publication_factory() as db:
            target = db.get(PraxisTarget, "target-alpha")
            assert target is not None
            target.enabled = False
            target.source_epoch += 1
            target.policy_epoch += 1
            target.fence += 1
            db.commit()

    hooks = PraxisPublicationHooks(after_render=disable)

    # When / Then
    with pytest.raises(PraxisPublicationStaleError):
        service.publish("target-alpha", hooks=hooks)
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None and target.desired_rollout_id is None
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 0
    assert notifications == []


def test_commit_failure_leaves_no_rows_pointer_or_notification(publication_factory: sessionmaker[Session]) -> None:
    # Given
    notifications: list[str] = []
    service = _service(publication_factory, notifications)

    def fail_publication_commit(session: Session) -> None:
        if session.info.get("praxis_publication"):
            raise _PublicationCommitFailure

    event.listen(Session, "before_commit", fail_publication_commit)
    try:
        # When / Then
        with pytest.raises(_PublicationCommitFailure):
            service.publish("target-alpha")
    finally:
        event.remove(Session, "before_commit", fail_publication_commit)
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None and target.desired_rollout_id is None
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration)) == 0
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 0
    assert notifications == []


def test_revalidation_fingerprint_mismatch_is_stale(publication_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    notifications: list[str] = []
    service = _service(publication_factory, notifications)
    original_snapshot = service.source_service.snapshot
    calls = 0

    def changed_snapshot(target_id: str):
        nonlocal calls
        calls += 1
        snapshot = original_snapshot(target_id)
        if calls == 2:
            return snapshot.model_copy(update={"source_fingerprint": "f" * 64})
        return snapshot

    monkeypatch.setattr(service.source_service, "snapshot", changed_snapshot)

    # When / Then
    with pytest.raises(PraxisPublicationStaleError):
        service.publish("target-alpha")
    assert notifications == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda service: service.bump_for_servers(("server-team",)),
        lambda service: service.bump_for_tools(("tool-1",)),
        lambda service: service.bump_for_resources(("resource-1",)),
        lambda service: service.bump_for_prompts(("prompt-1",)),
        lambda service: service.bump_for_gateways(("gateway-stream",)),
        lambda service: service.bump_for_bindings((("team-alpha", "summarize"),)),
    ],
)
def test_source_mutations_bump_only_server_derived_affected_targets(publication_factory: sessionmaker[Session], mutation) -> None:
    # Given
    with publication_factory() as db:
        service = PraxisTargetEpochService(db)

        # When
        affected = mutation(service)
        db.commit()

    # Then
    with publication_factory() as db:
        alpha = db.get(PraxisTarget, "target-alpha")
        beta = db.get(PraxisTarget, "target-beta")
        assert affected == ("target-alpha",)
        assert alpha is not None and (alpha.source_epoch, alpha.policy_epoch) == (1, 0)
        assert beta is not None and (beta.source_epoch, beta.policy_epoch) == (0, 0)


def test_stale_binding_pruning_bumps_the_removed_tools_target(publication_factory: sessionmaker[Session]) -> None:
    # Given
    with publication_factory() as db:
        db.add(
            ToolPluginBinding(
                team_id="team-alpha",
                tool_name="summarize",
                plugin_id="OutputLengthGuardPlugin",
                mode="enforce",
                priority=50,
                config={},
                binding_reference_id="binding-ref",
                created_by="admin@example.test",
                updated_by="admin@example.test",
            )
        )
        db.commit()
        request = ToolPluginBindingRequest(
            teams={
                "team-alpha": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["replacement-tool"],
                            plugin_id="OutputLengthGuardPlugin",
                            mode=PluginBindingMode.ENFORCE,
                            priority=50,
                            config={},
                            on_error=None,
                            binding_reference_id="binding-ref",
                        )
                    ]
                )
            }
        )

        # When
        ToolPluginBindingService().upsert_bindings(db, request, "admin@example.test")
        db.commit()

    # Then
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        removed = db.scalar(select(ToolPluginBinding).where(ToolPluginBinding.tool_name == "summarize"))
        assert target is not None and target.source_epoch == 1
        assert removed is None


def test_assignment_mutation_bumps_source_and_policy_epoch(publication_factory: sessionmaker[Session]) -> None:
    # Given
    with publication_factory() as db:
        service = PraxisTargetEpochService(db)

        # When
        affected = service.bump_for_assignments(("target-alpha",))
        db.commit()

    # Then
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert affected == ("target-alpha",)
        assert target is not None and (target.source_epoch, target.policy_epoch) == (1, 1)


def test_target_reassignment_bumps_old_and_new_target_policy_epochs(publication_factory: sessionmaker[Session]) -> None:
    # Given
    with publication_factory() as db:
        service = PraxisTargetEpochService(db)

        # When
        affected = service.reassign_server("server-team", "target-beta")
        db.commit()

    # Then
    with publication_factory() as db:
        alpha = db.get(PraxisTarget, "target-alpha")
        beta = db.get(PraxisTarget, "target-beta")
        assert affected == ("target-alpha", "target-beta")
        assert alpha is not None and (alpha.source_epoch, alpha.policy_epoch) == (1, 1)
        assert beta is not None and (beta.source_epoch, beta.policy_epoch) == (1, 1)


def test_target_disable_bumps_epochs_and_fence_and_issues_stop(publication_factory: sessionmaker[Session]) -> None:
    # Given
    with publication_factory() as db:
        service = PraxisTargetEpochService(db)

        # When
        stop = service.disable_target("target-alpha")
        db.commit()

    # Then
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        rollout = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == stop.rollout_id))
        cohort = tuple(db.scalars(select(PraxisRolloutReplica.replica_id).where(PraxisRolloutReplica.rollout_id == stop.rollout_id)).all())
        assert target is not None and (target.enabled, target.source_epoch, target.policy_epoch, target.fence) == (False, 1, 1, 1)
        assert target.desired_rollout_id == stop.rollout_id
        assert rollout is not None and rollout.action == "stop" and rollout.generation_id is None
        assert cohort == ("replica-a",)


def test_publication_disable_notifies_only_after_stop_commit(publication_factory: sessionmaker[Session]) -> None:
    # Given
    notifications: list[str] = []
    service = _service(publication_factory, notifications)

    # When
    stop = service.disable("target-alpha")

    # Then
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None and target.desired_rollout_id == stop.rollout_id
    assert stop.generation_id is None
    assert notifications == [stop.rollout_id]
