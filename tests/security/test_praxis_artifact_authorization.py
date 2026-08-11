# -*- coding: utf-8 -*-
"""Security contract tests for target-bound Praxis artifact delivery."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
import hashlib

from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import mcpgateway.routers.praxis_config_machine as praxis_machine
from mcpgateway.db import Base, EmailUser, Permissions, PraxisBundleGeneration, PraxisReplica, PraxisReplicaCredential, PraxisRollout, PraxisRolloutReplica, PraxisTarget, Role, utc_now
from mcpgateway.middleware.praxis_endpoint_scoping import authorize_praxis_replica, PraxisReplicaRequestIdentity
from mcpgateway.routers.praxis_config_machine import (
    DESIRED_CHANGED,
    PraxisArtifactCorruptError,
    PraxisDesiredChangedError,
    PraxisMachineApiService,
    PraxisReportConflictError,
    artifact_response_headers,
    get_machine_service,
    report_response_headers,
    router,
)
from mcpgateway.services.praxis_bundle_crypto import PraxisBundleAad, PraxisBundleCryptoService
from mcpgateway.services.praxis_bundle_reconciler import PraxisBundleReconciler
from mcpgateway.services.praxis_bundle_observability import PraxisLifecycleEvent, PraxisTransition
from mcpgateway.services.praxis_config_archive import build_praxis_bundle
from mcpgateway.services.praxis_config_directives import DirectiveAction, PraxisDirectiveIdentity, PraxisPreparedReport, build_directive
from mcpgateway.services.praxis_config_models import PraxisBundleBuildRequest, PraxisCompatibilityContract, PraxisConfigSourceSnapshot, PraxisRenderedDocument, PraxisSourceSnapshot
from mcpgateway.services.praxis_generation_payload import build_generation, PraxisGenerationBuild
from mcpgateway.services.praxis_replica_identity import PraxisReplicaIdentityService
from tests.helpers.praxis_reconciler import FakeClock


class _NonceStore:
    def reserve(self, key_id: str, nonce: bytes) -> bool:
        _ = (key_id, nonce)
        return True


@pytest.fixture
def authorized_machine() -> Generator[tuple[Session, str], None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    db.add_all(
        [
            EmailUser(email="admin@example.com", password_hash="disabled", is_admin=True),
            PraxisTarget(id="bound-target", name="Bound Target", created_by="admin@example.com"),
            PraxisReplica(id="bound-replica", target_id="bound-target", name="Bound Replica"),
            Role(id="praxis-role", name="praxis_replica", scope="global", permissions=[Permissions.PRAXIS_ARTIFACTS_READ, Permissions.PRAXIS_REPORTS_WRITE], created_by="admin@example.com", is_system_role=True),
        ]
    )
    db.commit()
    issued = PraxisReplicaIdentityService(db).issue_credential("bound-replica", expires_at=utc_now() + timedelta(hours=1))
    yield db, issued.raw_token
    db.close()
    engine.dispose()


def _request(scheme: str, *, forwarded: bool = False) -> Request:
    headers = [(b"x-forwarded-proto", b"https")] if forwarded else []
    return Request({"type": "http", "method": "GET", "path": "/praxis/artifact", "scheme": scheme, "server": ("gateway", 443), "client": ("203.0.113.9", 1234), "headers": headers})


@pytest.fixture
def machine_api() -> Generator[tuple[Session, PraxisMachineApiService, bytes, str], None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)
    source_fingerprint = hashlib.sha256(b'{"servers":[],"target_id":"target-a"}').hexdigest()
    artifact = build_praxis_bundle(
        PraxisBundleBuildRequest(
            snapshot=PraxisSourceSnapshot(target_id="target-a", source_fingerprint=source_fingerprint),
            compatibility=PraxisCompatibilityContract(
                bundle_schema="praxis-bundle/v1",
                renderer_version="1",
                praxis_revision="ed46eb5",
                cpex_contract_version="cpex/v1",
                mcp_protocol_version="2025-11-25",
                minimum_launcher_version="0.1.0",
            ),
            documents=(PraxisRenderedDocument(path="praxis.yaml", content=b"{}"),),
        )
    )
    crypto = PraxisBundleCryptoService({"key-a": b"k" * 32}, "key-a", _NonceStore())
    identity = PraxisDirectiveIdentity(target_id="target-a", rollout_id="rollout-a", policy_epoch=1, action=DirectiveAction.ACTIVATE, generation_id=artifact.generation_id, eligibility_deadline=now + timedelta(hours=1))
    directive = build_directive(identity)
    db = factory()
    db.add_all(
        [
            PraxisTarget(id="target-a", name="Target A", created_by="admin@example.com"),
            PraxisReplica(id="replica-a", target_id="target-a", name="Replica A"),
        ]
    )
    db.flush()
    db.add(build_generation(PraxisGenerationBuild("target-a", 0, 0, 0, now, PraxisConfigSourceSnapshot(target_id="target-a", source_fingerprint=source_fingerprint), artifact), crypto))
    db.add(PraxisRollout(target_id="target-a", rollout_id="rollout-a", generation_id=artifact.generation_id, directive_id=directive.directive_id, policy_epoch=1, action="activate", status="desired", eligibility_deadline=now + timedelta(hours=1)))
    db.flush()
    db.add(PraxisRolloutReplica(target_id="target-a", rollout_id="rollout-a", replica_id="replica-a", directive_id=directive.directive_id, position=0))
    db.flush()
    target = db.get(PraxisTarget, "target-a")
    assert target is not None
    target.desired_rollout_id = "rollout-a"
    db.commit()
    service = PraxisMachineApiService(factory, crypto, PraxisBundleReconciler(factory, FakeClock(now)))
    yield db, service, artifact.archive_bytes, directive.directive_id
    db.close()
    engine.dispose()


def test_artifact_headers_are_private_and_content_bound() -> None:
    # Given
    content_hash = "a" * 64

    # When
    headers = artifact_response_headers(content_hash)

    # Then
    assert headers == {"Cache-Control": "private, no-store", "ETag": f'"{content_hash}"'}


def test_report_headers_are_private_and_cursor_bound() -> None:
    response_etag = "b" * 64

    headers = report_response_headers(response_etag)

    assert headers == {"Cache-Control": "private, no-store", "ETag": f'"{response_etag}"'}


def test_desired_change_error_code_is_stable() -> None:
    assert DESIRED_CHANGED == "praxis_desired_changed"


@pytest.mark.asyncio
@pytest.mark.parametrize("machine_request", [_request("http"), _request("http", forwarded=True)], ids=["direct_http", "forged_https"])
async def test_machine_routes_reject_direct_http_and_forged_forwarding(authorized_machine: tuple[Session, str], machine_request: Request) -> None:
    db, token = authorized_machine
    with pytest.raises(HTTPException) as denied:
        await authorize_praxis_replica(machine_request, token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert denied.value.status_code == 400


@pytest.mark.asyncio
async def test_machine_routes_reject_revoked_bound_jti(authorized_machine: tuple[Session, str]) -> None:
    db, token = authorized_machine
    credential = db.scalar(select(PraxisReplicaCredential))
    assert credential is not None
    assert PraxisReplicaIdentityService(db).revoke_credential("bound-replica", credential.jti)
    with pytest.raises(HTTPException) as denied:
        await authorize_praxis_replica(_request("https"), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert denied.value.status_code == 401


def test_desired_keeps_stable_directive_separate_from_cursor_etag(machine_api: tuple[Session, PraxisMachineApiService, bytes, str]) -> None:
    # Given
    _, service, _, directive_id = machine_api

    # When
    desired, unchanged = service.desired("target-a", "replica-a", None)

    # Then
    assert not unchanged
    assert desired.directive_id == directive_id
    assert desired.response_etag != directive_id
    assert (desired.last_report_sequence, desired.next_report_sequence) == (0, 1)
    _, conditional = service.desired("target-a", "replica-a", f'"{desired.response_etag}"')
    assert conditional


def test_artifact_requires_current_stable_if_match(machine_api: tuple[Session, PraxisMachineApiService, bytes, str]) -> None:
    # Given
    _, service, expected, directive_id = machine_api

    # When / Then
    for stale in (None, "f" * 64):
        with pytest.raises(PraxisDesiredChangedError):
            service.artifact("target-a", "replica-a", stale)
    content, content_hash = service.artifact("target-a", "replica-a", directive_id)
    assert content == expected
    assert hashlib.sha256(content).hexdigest() == content_hash


def test_expired_desired_emits_stale_generation_not_deprecation_gate(machine_api: tuple[Session, PraxisMachineApiService, bytes, str], monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    _, service, _, _ = machine_api
    clock = service._reconciler._clock
    assert isinstance(clock, FakeClock)
    clock.advance(3600)
    events: list[PraxisLifecycleEvent] = []
    monkeypatch.setattr(praxis_machine, "emit_praxis_event", events.append)

    # When
    desired, _ = service.desired("target-a", "replica-a", None)

    # Then
    assert not desired.eligible
    assert [event.transition for event in events] == [PraxisTransition.STALE_GENERATION]
    assert events[0].reason == "expired"


def test_expired_rollback_emits_stale_generation_not_deprecation_gate(machine_api: tuple[Session, PraxisMachineApiService, bytes, str], monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    db, service, _, _ = machine_api
    clock = service._reconciler._clock
    assert isinstance(clock, FakeClock)
    current = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "rollout-a"))
    target = db.get(PraxisTarget, "target-a")
    assert current is not None and current.generation_id is not None and target is not None
    deadline = clock.now() + timedelta(seconds=1)
    directive = build_directive(PraxisDirectiveIdentity(target_id="target-a", rollout_id="rollback-a", policy_epoch=2, action=DirectiveAction.ROLLBACK, generation_id=current.generation_id, eligibility_deadline=deadline))
    db.add(PraxisRollout(target_id="target-a", rollout_id="rollback-a", generation_id=current.generation_id, directive_id=directive.directive_id, policy_epoch=2, action="rollback", status="desired", rollback_eligible=True, eligibility_deadline=deadline))
    db.flush()
    db.add(PraxisRolloutReplica(target_id="target-a", rollout_id="rollback-a", replica_id="replica-a", directive_id=directive.directive_id, position=0))
    target.desired_rollout_id = "rollback-a"
    db.commit()
    clock.advance(1)
    events: list[PraxisLifecycleEvent] = []
    monkeypatch.setattr(praxis_machine, "emit_praxis_event", events.append)

    # When / Then
    with pytest.raises(PraxisDesiredChangedError):
        service.artifact("target-a", "replica-a", directive.directive_id)
    assert [event.transition for event in events] == [PraxisTransition.STALE_GENERATION]
    assert events[0].reason == "expired"


def test_same_generation_new_directive_invalidates_old_if_match(machine_api: tuple[Session, PraxisMachineApiService, bytes, str]) -> None:
    # Given
    db, service, _, old_directive = machine_api
    old = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "rollout-a"))
    assert old is not None
    deadline = datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc)
    new = build_directive(PraxisDirectiveIdentity(target_id="target-a", rollout_id="rollout-b", policy_epoch=2, action=DirectiveAction.RETRY, generation_id=old.generation_id, eligibility_deadline=deadline))
    db.add(PraxisRollout(target_id="target-a", rollout_id="rollout-b", generation_id=old.generation_id, directive_id=new.directive_id, policy_epoch=2, action="retry", status="desired", eligibility_deadline=deadline))
    db.flush()
    db.add(PraxisRolloutReplica(target_id="target-a", rollout_id="rollout-b", replica_id="replica-a", directive_id=new.directive_id, position=0))
    db.flush()
    target = db.get(PraxisTarget, "target-a")
    assert target is not None
    target.desired_rollout_id = "rollout-b"
    db.commit()

    # When / Then
    with pytest.raises(PraxisDesiredChangedError):
        service.artifact("target-a", "replica-a", old_directive)


def test_pointer_race_after_authenticated_decryption_returns_desired_changed(machine_api: tuple[Session, PraxisMachineApiService, bytes, str], monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    db, service, _, old_directive = machine_api
    old = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "rollout-a"))
    assert old is not None
    deadline = datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc)
    new = build_directive(PraxisDirectiveIdentity(target_id="target-a", rollout_id="rollout-race", policy_epoch=2, action=DirectiveAction.RETRY, generation_id=old.generation_id, eligibility_deadline=deadline))
    db.add(PraxisRollout(target_id="target-a", rollout_id="rollout-race", generation_id=old.generation_id, directive_id=new.directive_id, policy_epoch=2, action="retry", status="desired", eligibility_deadline=deadline))
    db.flush()
    db.add(PraxisRolloutReplica(target_id="target-a", rollout_id="rollout-race", replica_id="replica-a", directive_id=new.directive_id, position=0))
    db.commit()
    decrypt = service._crypto.decrypt

    def decrypt_then_advance(envelope: bytes, identity: PraxisBundleAad) -> bytes:
        plaintext = decrypt(envelope, identity)
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = "rollout-race"
        db.commit()
        return plaintext

    monkeypatch.setattr(service._crypto, "decrypt", decrypt_then_advance)

    # When / Then
    with pytest.raises(PraxisDesiredChangedError):
        service.artifact("target-a", "replica-a", old_directive)


def test_corrupt_gcm_returns_no_plaintext_value(machine_api: tuple[Session, PraxisMachineApiService, bytes, str]) -> None:
    # Given
    db, service, plaintext, directive_id = machine_api
    generation = db.scalar(select(PraxisBundleGeneration))
    assert generation is not None
    corrupted = generation.ciphertext[:-1] + bytes((generation.ciphertext[-1] ^ 1,))
    db.execute(update(PraxisBundleGeneration).values(ciphertext=corrupted, ciphertext_hash=hashlib.sha256(corrupted).hexdigest()))
    db.commit()
    leaked = bytearray()

    # When / Then
    with pytest.raises(PraxisArtifactCorruptError):
        result = service.artifact("target-a", "replica-a", directive_id)
        leaked.extend(result[0])
    assert bytes(leaked) == b""
    assert plaintext not in leaked


def test_http_artifact_stream_emits_only_after_full_authentication(machine_api: tuple[Session, PraxisMachineApiService, bytes, str]) -> None:
    # Given
    db, service, plaintext, directive_id = machine_api
    app = FastAPI()
    app.include_router(router)
    artifact_route = next(route for route in router.routes if isinstance(route, APIRoute) and route.path == "/praxis/v1/artifact")
    identity_dependency = artifact_route.dependant.dependencies[0].call
    assert identity_dependency is not None
    app.dependency_overrides[identity_dependency] = lambda: PraxisReplicaRequestIdentity("target-a", "replica-a", "bound-jti")
    app.dependency_overrides[get_machine_service] = lambda: service

    # When / Then
    with TestClient(app, base_url="https://gateway.test") as client:
        fetched = client.get("/praxis/v1/artifact", headers={"If-Match": directive_id})
        assert fetched.status_code == 200 and fetched.content == plaintext
        assert fetched.headers["cache-control"] == "private, no-store"
        generation = db.scalar(select(PraxisBundleGeneration))
        assert generation is not None
        corrupted = generation.ciphertext[:-1] + bytes((generation.ciphertext[-1] ^ 1,))
        db.execute(update(PraxisBundleGeneration).values(ciphertext=corrupted, ciphertext_hash=hashlib.sha256(corrupted).hexdigest()))
        db.commit()
        denied = client.get("/praxis/v1/artifact", headers={"If-Match": directive_id})
        assert denied.status_code == 500
        assert plaintext not in denied.content


def test_report_replay_is_idempotent_and_conflict_is_rejected(machine_api: tuple[Session, PraxisMachineApiService, bytes, str]) -> None:
    # Given
    _, service, _, directive_id = machine_api
    report = PraxisPreparedReport(directive_id=directive_id, sequence=1)

    with pytest.raises(PraxisDesiredChangedError):
        service.report("target-a", "replica-a", None, report)

    # When
    accepted = service.report("target-a", "replica-a", directive_id, report)
    duplicate = service.report("target-a", "replica-a", directive_id, report)

    # Then
    assert accepted.disposition == "accepted"
    assert duplicate.disposition == "duplicate"
    assert accepted.directive_id == duplicate.directive_id == directive_id
    assert accepted.response_etag == duplicate.response_etag
    with pytest.raises(PraxisReportConflictError):
        service.report("target-a", "replica-a", directive_id, PraxisPreparedReport(directive_id=directive_id, sequence=2))
