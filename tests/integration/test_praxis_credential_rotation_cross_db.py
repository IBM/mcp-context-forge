# -*- coding: utf-8 -*-
"""Cross-database concurrency tests for Praxis credential rotation."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from pathlib import Path
import tempfile
from typing import assert_never, Literal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Base, EmailApiToken, EmailUser, Permissions, PraxisReplica, PraxisReplicaCredential, PraxisTarget, Role, UserRole, utc_now
from mcpgateway.services import praxis_replica_identity
from mcpgateway.services.praxis_replica_identity import PraxisCredentialLimitError, PraxisReplicaIdentityService, praxis_replica_principal


DATABASE_PARAMS = [pytest.param("sqlite", id="sqlite")]
if postgres_url := os.getenv("MCPGATEWAY_TEST_POSTGRES_URL"):
    DATABASE_PARAMS.append(pytest.param(postgres_url, id="postgresql"))


class IssuanceAbort(BaseException):
    """Injected cancellation-like failure that must not leave pending state."""


type IssuanceFault = Literal["mint", "signing", "catalog_flush", "commit"]


@pytest.fixture(params=DATABASE_PARAMS)
def engine(request: pytest.FixtureRequest) -> Iterator[Engine]:
    path: Path | None = None
    if request.param == "sqlite":
        descriptor, file_name = tempfile.mkstemp(prefix="praxis-rotation-", suffix=".db")
        os.close(descriptor)
        path = Path(file_name)
        database_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 10})
    else:
        database_engine = create_engine(request.param)
    Base.metadata.drop_all(database_engine)
    Base.metadata.create_all(database_engine)
    yield database_engine
    Base.metadata.drop_all(database_engine)
    database_engine.dispose()
    if path is not None:
        path.unlink(missing_ok=True)


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all(
            [
                EmailUser(email="admin@example.com", password_hash="disabled", is_admin=True),
                PraxisTarget(id="target-a", name="Target A", created_by="admin@example.com"),
                PraxisReplica(id="replica-a", target_id="target-a", name="Replica A"),
                Role(
                    id="praxis-role",
                    name="praxis_replica",
                    scope="global",
                    permissions=[Permissions.PRAXIS_ARTIFACTS_READ, Permissions.PRAXIS_REPORTS_WRITE],
                    created_by="admin@example.com",
                    is_system_role=True,
                ),
            ]
        )
        db.commit()
    return factory


def _issue(factory: sessionmaker[Session]) -> str:
    with factory() as db:
        return PraxisReplicaIdentityService(db).issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1)).jti


def test_overlap_then_revoke_preserves_one_active_credential(sessions: sessionmaker[Session]) -> None:
    old_jti = _issue(sessions)
    new_jti = _issue(sessions)
    with sessions() as db:
        service = PraxisReplicaIdentityService(db)
        service.observe_credential(new_jti)
        assert service.revoke_after_observation("replica-a", old_jti=old_jti, new_jti=new_jti)
        active = list(db.scalars(select(PraxisReplicaCredential.jti).where(PraxisReplicaCredential.revoked_at.is_(None))))
    assert active == [new_jti]


def test_concurrent_third_issuance_never_exceeds_two_active_jtis(sessions: sessionmaker[Session]) -> None:
    _issue(sessions)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_issue, sessions) for _ in range(8)]
    outcomes = []
    for future in futures:
        try:
            outcomes.append(future.result())
        except PraxisCredentialLimitError:
            outcomes.append("limited")
    with sessions() as db:
        active_count = len(list(db.scalars(select(PraxisReplicaCredential).where(PraxisReplicaCredential.revoked_at.is_(None)))))
    assert active_count == 2
    assert outcomes.count("limited") == 7


def test_rotate_revoke_race_serializes_epoch_and_active_count(sessions: sessionmaker[Session]) -> None:
    old_jti = _issue(sessions)

    def revoke() -> bool:
        with sessions() as db:
            return PraxisReplicaIdentityService(db).revoke_credential("replica-a", old_jti)

    with ThreadPoolExecutor(max_workers=2) as pool:
        issued_future = pool.submit(_issue, sessions)
        revoked_future = pool.submit(revoke)
    issued_future.result()
    revoked_future.result()
    with sessions() as db:
        active = list(db.scalars(select(PraxisReplicaCredential).where(PraxisReplicaCredential.revoked_at.is_(None))))
        replica = db.get(PraxisReplica, "replica-a")
    assert len(active) <= 2
    assert replica is not None and replica.credential_epoch == 3


@pytest.mark.parametrize("fault", ["mint", "signing", "catalog_flush", "commit"])
def test_issuance_fault_rolls_back_every_partial_mutation(sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, fault: IssuanceFault) -> None:
    with sessions() as db:
        service = PraxisReplicaIdentityService(db)
        original_flush = db.flush
        original_commit = db.commit

        match fault:
            case "mint":
                monkeypatch.setattr(service, "_mint_token", lambda *_args: (_ for _ in ()).throw(IssuanceAbort()))
            case "signing":
                monkeypatch.setattr(praxis_replica_identity, "validate_jwt_algo_and_keys", lambda: (_ for _ in ()).throw(IssuanceAbort()))
            case "catalog_flush":
                def fail_catalog_flush(*args, **kwargs):
                    if any(isinstance(row, EmailApiToken) for row in db.new):
                        raise IssuanceAbort
                    return original_flush(*args, **kwargs)

                monkeypatch.setattr(db, "flush", fail_catalog_flush)
            case "commit":
                def fail_commit() -> None:
                    original_flush()
                    raise IssuanceAbort

                monkeypatch.setattr(db, "commit", fail_commit)
            case unreachable:
                assert_never(unreachable)

        with pytest.raises(IssuanceAbort):
            service.issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))

        monkeypatch.setattr(db, "flush", original_flush)
        monkeypatch.setattr(db, "commit", original_commit)
        db.commit()
        principal = praxis_replica_principal("replica-a")
        replica = db.get(PraxisReplica, "replica-a")
        assert replica is not None and replica.credential_epoch == 0
        assert db.scalar(select(func.count()).select_from(EmailUser).where(EmailUser.email == principal)) == 0
        assert db.scalar(select(func.count()).select_from(UserRole).where(UserRole.user_email == principal)) == 0
        assert db.scalar(select(func.count()).select_from(EmailApiToken)) == 0
        assert db.scalar(select(func.count()).select_from(PraxisReplicaCredential)) == 0
