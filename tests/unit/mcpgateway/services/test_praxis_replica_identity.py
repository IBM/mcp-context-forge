# -*- coding: utf-8 -*-
"""Praxis replica identity and credential lifecycle tests."""

from collections.abc import Generator
from datetime import timedelta
import traceback

import jwt
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mcpgateway.db import Base, EmailApiToken, EmailUser, Permissions, PraxisReplica, PraxisReplicaCredential, PraxisTarget, Role, UserRole, utc_now
from mcpgateway.services.praxis_replica_identity import PraxisCredentialConflictError, PraxisCredentialLimitError, PraxisReplicaIdentityService, praxis_replica_principal


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add_all(
        [
            EmailUser(email="admin@example.com", password_hash="disabled", is_admin=True),
            PraxisTarget(id="target-a", name="Target A", created_by="admin@example.com"),
            PraxisReplica(id="replica-a", target_id="target-a", name="Replica A"),
            Role(
                id="praxis-role",
                name="praxis_replica",
                description="Praxis replica machine",
                scope="global",
                permissions=[Permissions.PRAXIS_ARTIFACTS_READ, Permissions.PRAXIS_REPORTS_WRITE],
                created_by="admin@example.com",
                is_system_role=True,
            ),
        ]
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_issue_credential_creates_machine_role_catalog_and_jti_binding(db: Session) -> None:
    issued = PraxisReplicaIdentityService(db).issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))

    payload = jwt.decode(issued.raw_token, options={"verify_signature": False})
    catalog = db.scalar(select(EmailApiToken).where(EmailApiToken.jti == issued.jti))
    binding = db.scalar(select(PraxisReplicaCredential).where(PraxisReplicaCredential.jti == issued.jti))
    assignment = db.scalar(select(UserRole).where(UserRole.user_email == praxis_replica_principal("replica-a")))

    assert payload["aud"] == "praxis-config"
    assert payload["token_use"] == "praxis_replica"
    assert set(payload["scopes"]["permissions"]) == {Permissions.PRAXIS_ARTIFACTS_READ, Permissions.PRAXIS_REPORTS_WRITE}
    assert catalog is not None and catalog.token_hash != issued.raw_token and catalog.is_active
    assert binding is not None and binding.target_id == "target-a" and binding.replica_id == "replica-a"
    assert assignment is not None and assignment.role_id == "praxis-role"


def test_issue_credential_enforces_two_active_jtis_and_atomic_epoch(db: Session) -> None:
    service = PraxisReplicaIdentityService(db)
    first = service.issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))
    second = service.issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))

    with pytest.raises(PraxisCredentialLimitError):
        service.issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))

    replica = db.get(PraxisReplica, "replica-a")
    assert replica is not None and replica.credential_epoch == 2
    assert {row.jti for row in db.scalars(select(PraxisReplicaCredential).where(PraxisReplicaCredential.revoked_at.is_(None)))} == {first.jti, second.jti}


def test_rotation_requires_new_jti_observation_before_old_revocation(db: Session) -> None:
    service = PraxisReplicaIdentityService(db)
    old = service.issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))
    new = service.issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))

    assert service.revoke_after_observation("replica-a", old_jti=old.jti, new_jti=new.jti) is False
    service.observe_credential(new.jti)
    assert service.revoke_after_observation("replica-a", old_jti=old.jti, new_jti=new.jti) is True

    old_catalog = db.scalar(select(EmailApiToken).where(EmailApiToken.jti == old.jti))
    old_binding = db.scalar(select(PraxisReplicaCredential).where(PraxisReplicaCredential.jti == old.jti))
    replica = db.get(PraxisReplica, "replica-a")
    assert old_catalog is not None and not old_catalog.is_active
    assert old_binding is not None and old_binding.revoked_at is not None
    assert replica is not None and replica.credential_epoch == 3


def test_raw_token_is_not_persisted_or_rendered_in_service_errors(db: Session) -> None:
    service = PraxisReplicaIdentityService(db)
    issued = service.issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))
    service.issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))

    with pytest.raises(PraxisCredentialLimitError) as error:
        service.issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))

    assert issued.raw_token not in str(error.value)
    assert issued.raw_token not in "\n".join(str(value) for row in db.execute(select(EmailApiToken)).scalars() for value in vars(row).values())


def test_integrity_failure_maps_to_sanitized_conflict_without_exception_retention(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = "TASK10_INTEGRITY_SECRET_SENTINEL"
    original_commit = db.commit

    def fail_commit() -> None:
        db.flush()
        raise IntegrityError("catalog insert", {"token": sentinel}, RuntimeError(sentinel))

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(PraxisCredentialConflictError) as conflict:
        PraxisReplicaIdentityService(db).issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))
    monkeypatch.setattr(db, "commit", original_commit)
    db.commit()

    representations = [
        str(conflict.value),
        repr(conflict.value),
        repr(vars(conflict.value)),
        "".join(traceback.format_exception(conflict.type, conflict.value, conflict.tb)),
    ]
    assert conflict.value.__cause__ is None
    assert conflict.value.__context__ is None
    assert all(sentinel not in representation for representation in representations)
    replica = db.get(PraxisReplica, "replica-a")
    assert replica is not None and replica.credential_epoch == 0
    assert db.scalar(select(EmailUser).where(EmailUser.email == praxis_replica_principal("replica-a"))) is None
    assert db.scalar(select(UserRole).where(UserRole.user_email == praxis_replica_principal("replica-a"))) is None
    assert db.scalar(select(EmailApiToken)) is None
    assert db.scalar(select(PraxisReplicaCredential)) is None
