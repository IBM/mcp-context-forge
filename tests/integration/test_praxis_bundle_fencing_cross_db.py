# -*- coding: utf-8 -*-
"""Cross-database fencing tests for transactional Praxis publication."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import tempfile
from threading import Barrier, current_thread, Event, local
from types import SimpleNamespace

from cpex.framework.models import Config
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Base, PraxisBundleGeneration, PraxisCryptoNonceReservation, PraxisReplica, PraxisRollout, PraxisTarget, PraxisTargetServer, ToolPluginBinding
from mcpgateway.services import praxis_bundle_renderer
from mcpgateway.services import praxis_bundle_crypto
from mcpgateway.services import praxis_config_runtime
from mcpgateway.services.praxis_bundle_crypto import PraxisBundleCryptoError, PraxisBundleCryptoService
from mcpgateway.services.praxis_bundle_service import PraxisBundlePublicationService, PraxisPublicationHooks, PraxisPublicationStaleError
from mcpgateway.services.praxis_config_source import PraxisConfigSourceService
from mcpgateway.services.praxis_target_epoch import PraxisTargetEpochService
from tests.unit.mcpgateway.services.test_praxis_config_source_support import seed_graph


DATABASE_PARAMS = [pytest.param("sqlite", id="sqlite")]
if postgres_url := os.getenv("MCPGATEWAY_TEST_POSTGRES_URL"):
    DATABASE_PARAMS.append(pytest.param(postgres_url, id="postgresql"))


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


@pytest.fixture(params=DATABASE_PARAMS)
def engine(request: pytest.FixtureRequest) -> Iterator[Engine]:
    path: Path | None = None
    if request.param == "sqlite":
        descriptor, file_name = tempfile.mkstemp(prefix="praxis-publication-", suffix=".db")
        os.close(descriptor)
        path = Path(file_name)
        database_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 10})
        event.listen(database_engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    else:
        database_engine = create_engine(request.param)
    if path is None:
        Base.metadata.drop_all(database_engine)
    Base.metadata.create_all(database_engine)
    yield database_engine
    if path is None:
        Base.metadata.drop_all(database_engine)
    database_engine.dispose()
    if path is not None:
        path.unlink(missing_ok=True)


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    factory = sessionmaker(engine, expire_on_commit=False)
    seed_graph(factory)
    with factory() as db:
        db.query(ToolPluginBinding).delete()
        db.add(PraxisReplica(id="replica-a", target_id="target-alpha", name="Replica A"))
        db.commit()
    return factory


def _service(factory: sessionmaker[Session], notifications: list[str]) -> PraxisBundlePublicationService:
    return PraxisBundlePublicationService(
        factory,
        PraxisConfigSourceService(factory, Config()),
        PraxisBundleCryptoService({"key-a": b"k" * 32}, "key-a", _NonceStore()),
        lambda publication: notifications.append(publication.rollout_id),
    )


def _database_nonce_service(factory: sessionmaker[Session], notifications: list[str], monkeypatch: pytest.MonkeyPatch) -> PraxisBundlePublicationService:
    monkeypatch.setattr(praxis_config_runtime, "SessionLocal", factory)
    return PraxisBundlePublicationService(
        factory,
        PraxisConfigSourceService(factory, Config()),
        PraxisBundleCryptoService({"key-a": b"k" * 32}, "key-a", praxis_config_runtime._DatabaseNonceReservationStore()),
        lambda publication: notifications.append(publication.rollout_id),
    )


def test_same_generation_fresh_rollout(sessions: sessionmaker[Session]) -> None:
    notifications: list[str] = []
    service = _service(sessions, notifications)

    first = service.publish("target-alpha")
    second = service.publish("target-alpha")

    assert first.generation_id == second.generation_id
    assert first.rollout_id != second.rollout_id
    assert first.directive_id != second.directive_id
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration)) == 1
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 2


def test_database_nonce_reservation_has_exactly_one_concurrent_winner(sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    monkeypatch.setattr(praxis_config_runtime, "SessionLocal", sessions)
    store = praxis_config_runtime._DatabaseNonceReservationStore()
    barrier = Barrier(2)

    def reserve() -> bool:
        barrier.wait()
        return store.reserve("key-a", b"r" * 12)

    # When
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: reserve(), range(2)))

    # Then
    assert sorted(results) == [False, True]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(PraxisCryptoNonceReservation)) == 1


def test_database_nonce_reservations_do_not_deadlock_publication(sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    notifications: list[str] = []
    service = _database_nonce_service(sessions, notifications, monkeypatch)

    # When
    publication = service.publish("target-alpha")

    # Then
    with sessions() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None and target.desired_rollout_id == publication.rollout_id
        assert db.scalar(select(func.count()).select_from(PraxisCryptoNonceReservation)) == 2


def test_same_nonce_for_primary_and_sidecar_fails_without_publication(sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    notifications: list[str] = []
    service = _database_nonce_service(sessions, notifications, monkeypatch)
    monkeypatch.setattr(praxis_bundle_crypto.os, "urandom", lambda _size: b"x" * 12)

    # When
    with pytest.raises(PraxisBundleCryptoError, match="nonce_collision"):
        service.publish("target-alpha")

    # Then
    with sessions() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None and target.desired_rollout_id is None
        assert db.scalar(select(func.count()).select_from(PraxisCryptoNonceReservation)) == 1
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration)) == 0
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 0
    assert notifications == []


def test_concurrent_publications_sharing_primary_nonce_have_one_fail_closed_winner(sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    with sessions() as db:
        db.add(PraxisTargetServer(target_id="target-beta", server_id="server-unassigned", assigned_by="admin@example.test"))
        db.add(PraxisReplica(id="replica-beta", target_id="target-beta", name="Replica Beta"))
        db.commit()
    notifications: list[str] = []
    services = (_database_nonce_service(sessions, notifications, monkeypatch), _database_nonce_service(sessions, notifications, monkeypatch))
    barrier = Barrier(2)
    call_state = local()

    def forced_nonce(_size: int) -> bytes:
        call_count = getattr(call_state, "count", 0)
        call_state.count = call_count + 1
        return b"w" * 12 if call_count == 0 else hashlib.sha256(current_thread().name.encode()).digest()[:12]

    monkeypatch.setattr(praxis_bundle_crypto, "os", SimpleNamespace(urandom=forced_nonce))

    def publish(index: int):
        barrier.wait()
        target_id = ("target-alpha", "target-beta")[index]
        try:
            return services[index].publish(target_id)
        except PraxisBundleCryptoError as error:
            return error

    # When
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="nonce-worker") as pool:
        outcomes = tuple(pool.map(publish, range(2)))

    # Then
    assert sum(not isinstance(outcome, PraxisBundleCryptoError) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, PraxisBundleCryptoError) and outcome.code == "nonce_collision" for outcome in outcomes) == 1
    with sessions() as db:
        desired_count = db.scalar(select(func.count()).select_from(PraxisTarget).where(PraxisTarget.desired_rollout_id.is_not(None)))
        assert desired_count == 1
        assert db.scalar(select(func.count()).select_from(PraxisCryptoNonceReservation)) == 2
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration)) == 1
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 1
    assert len(notifications) == 1


def test_failed_publication_keeps_burned_nonce_reservations(sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    notifications: list[str] = []
    service = _database_nonce_service(sessions, notifications, monkeypatch)

    def fail_commit(session: Session) -> None:
        if session.info.get("praxis_publication"):
            raise _PublicationCommitFailure

    event.listen(Session, "before_commit", fail_commit)
    try:
        # When
        with pytest.raises(_PublicationCommitFailure):
            service.publish("target-alpha")
    finally:
        event.remove(Session, "before_commit", fail_commit)

    # Then
    with sessions() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None and target.desired_rollout_id is None
        assert db.scalar(select(func.count()).select_from(PraxisCryptoNonceReservation)) == 2
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration)) == 0
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 0
    assert notifications == []


def test_compatibility_changes_generation(sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    notifications: list[str] = []
    service = _service(sessions, notifications)
    first = service.publish("target-alpha")
    changed = praxis_bundle_renderer.DEFAULT_PRAXIS_COMPATIBILITY.model_copy(update={"renderer_version": "1.0.1"})
    monkeypatch.setattr(praxis_bundle_renderer, "DEFAULT_PRAXIS_COMPATIBILITY", changed)

    second = service.publish("target-alpha")

    assert second.generation_id != first.generation_id


def test_mutation_after_revalidation(sessions: sessionmaker[Session]) -> None:
    notifications: list[str] = []
    service = _service(sessions, notifications)

    def mutate() -> None:
        with sessions() as db:
            PraxisTargetEpochService(db).bump_for_servers(("server-team",))
            db.commit()

    with pytest.raises(PraxisPublicationStaleError):
        service.publish("target-alpha", hooks=PraxisPublicationHooks(after_revalidation=mutate))
    with sessions() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None and target.desired_rollout_id is None
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 0
    assert notifications == []


def test_disable_during_render(sessions: sessionmaker[Session]) -> None:
    notifications: list[str] = []
    service = _service(sessions, notifications)

    def disable() -> None:
        with sessions() as db:
            PraxisTargetEpochService(db).disable_target("target-alpha")
            db.commit()

    with pytest.raises(PraxisPublicationStaleError):
        service.publish("target-alpha", hooks=PraxisPublicationHooks(after_render=disable))
    with sessions() as db:
        target = db.get(PraxisTarget, "target-alpha")
        rollout = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == target.desired_rollout_id)) if target is not None else None
        assert target is not None and not target.enabled
        assert rollout is not None and rollout.action == "stop"
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration)) == 0
    assert notifications == []


def test_older_finishes_last(sessions: sessionmaker[Session]) -> None:
    notifications: list[str] = []
    older = _service(sessions, notifications)
    newer = _service(sessions, notifications)
    older_captured = Event()
    newer_finished = Event()

    def pause_older() -> None:
        older_captured.set()
        assert newer_finished.wait(timeout=10)

    def run_older():
        return older.publish("target-alpha", hooks=PraxisPublicationHooks(after_capture=pause_older))

    with ThreadPoolExecutor(max_workers=2) as pool:
        old_future = pool.submit(run_older)
        assert older_captured.wait(timeout=10)
        new_future = pool.submit(newer.publish, "target-alpha")
        newest = new_future.result(timeout=30)
        newer_finished.set()
        with pytest.raises(PraxisPublicationStaleError):
            old_future.result(timeout=30)
    with sessions() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None and target.desired_rollout_id == newest.rollout_id
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 1
    assert notifications == [newest.rollout_id]


def test_transaction_failure(sessions: sessionmaker[Session]) -> None:
    notifications: list[str] = []
    service = _service(sessions, notifications)

    def fail_commit(session: Session) -> None:
        if session.info.get("praxis_publication"):
            raise _PublicationCommitFailure

    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(_PublicationCommitFailure):
            service.publish("target-alpha")
    finally:
        event.remove(Session, "before_commit", fail_commit)
    with sessions() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None and target.desired_rollout_id is None
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration)) == 0
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 0
    assert notifications == []
