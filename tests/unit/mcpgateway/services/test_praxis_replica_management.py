"""Replica lifecycle contracts for Praxis target management."""

from collections.abc import Generator
from datetime import timedelta

from cpex.framework.models import Config
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from mcpgateway.db import Base, PraxisReplica, PraxisReplicaCredential, PraxisTarget, utc_now
from mcpgateway.services.praxis_config_source import PraxisConfigSourceService
from mcpgateway.services.praxis_target_service import PraxisTargetConflictError, PraxisTargetNotFoundError, PraxisTargetService


@pytest.fixture
def replica_service() -> Generator[tuple[Session, PraxisTargetService], None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    db = factory()
    db.add_all(
        (
            PraxisTarget(id="target-a", name="Target A", created_by="admin@example.com"),
            PraxisTarget(id="target-b", name="Target B", created_by="admin@example.com"),
        )
    )
    db.commit()
    yield db, PraxisTargetService(db, PraxisConfigSourceService(factory, Config()))
    db.close()
    engine.dispose()


def test_create_replica_bumps_target_epochs(replica_service: tuple[Session, PraxisTargetService]) -> None:
    # Given
    db, service = replica_service

    # When
    created = service.create_replica("target-a", "Replica A")

    # Then
    target = db.get(PraxisTarget, "target-a")
    assert created.target_id == "target-a"
    assert target is not None
    assert (target.source_epoch, target.policy_epoch) == (1, 1)


def test_create_replica_rejects_disabled_target(replica_service: tuple[Session, PraxisTargetService]) -> None:
    # Given
    db, service = replica_service
    target = db.get(PraxisTarget, "target-a")
    assert target is not None
    target.enabled = False

    # When / Then
    with pytest.raises(PraxisTargetConflictError):
        service.create_replica("target-a", "Replica A")


def test_remove_replica_revokes_identity_and_bumps_epochs(replica_service: tuple[Session, PraxisTargetService]) -> None:
    # Given
    db, service = replica_service
    replica = PraxisReplica(id="replica-a", target_id="target-a", name="Replica A")
    credential = PraxisReplicaCredential(
        target_id="target-a",
        replica_id="replica-a",
        jti="jti-a",
        credential_epoch=0,
        expires_at=utc_now() + timedelta(hours=1),
    )
    db.add_all((replica, credential))
    db.flush()

    # When
    service.remove_replica("target-a", "replica-a")

    # Then
    target = db.get(PraxisTarget, "target-a")
    assert target is not None
    assert (target.source_epoch, target.policy_epoch) == (1, 1)
    assert not replica.enabled
    assert replica.revoked_at is not None
    assert replica.credential_epoch == 1
    assert credential.revoked_at is not None


def test_remove_replica_rejects_cross_target_identity(replica_service: tuple[Session, PraxisTargetService]) -> None:
    # Given
    db, service = replica_service
    replica = PraxisReplica(id="replica-b", target_id="target-b", name="Replica B")
    db.add(replica)
    db.flush()

    # When / Then
    with pytest.raises(PraxisTargetNotFoundError):
        service.remove_replica("target-a", "replica-b")
    assert replica.enabled
    assert replica.revoked_at is None
