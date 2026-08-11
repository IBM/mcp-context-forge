# -*- coding: utf-8 -*-
"""Production publication source-diff classification regressions."""

from datetime import datetime, timezone
import traceback

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Gateway, PraxisBundleGeneration, PraxisRollout, PraxisTarget, Resource, Server, server_resource_association
from mcpgateway.services._praxis_reconciliation import RolloutStatus, SourceChange
from mcpgateway.services import praxis_bundle_crypto
from mcpgateway.services.praxis_bundle_reconciler import PraxisBundleReconciler
from mcpgateway.services.praxis_bundle_renderer import render_praxis_bundle
from mcpgateway.services.praxis_bundle_service import PraxisBundlePublicationService, PraxisPublication
from mcpgateway.services.praxis_bundle_crypto import PraxisBundleAad, PraxisBundleCryptoError, PraxisBundleCryptoService
from mcpgateway.services.praxis_config_models import PraxisSourceError
from mcpgateway.services.praxis_generation_payload import encode_source_snapshot
from tests.helpers.praxis_reconciler import FakeClock
from tests.unit.mcpgateway.services.test_praxis_bundle_service import _NonceStore, _service, publication_factory  # noqa: F401

__all__ = ("publication_factory",)


def _verified_initial(factory: sessionmaker[Session]) -> tuple[PraxisBundlePublicationService, PraxisPublication]:
    publisher = _service(factory, [])
    first = publisher.publish("target-alpha")
    with factory() as db:
        rollout = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == first.rollout_id))
        assert rollout is not None
        rollout.status = RolloutStatus.VERIFIED.value
        rollout.rollback_eligible = True
        db.commit()
    return publisher, first


def test_published_generation_decrypts_to_exact_canonical_archive(publication_factory: sessionmaker[Session]) -> None:  # noqa: F811
    # Given
    publisher = _service(publication_factory, [])
    snapshot = publisher.source_service.snapshot("target-alpha")
    artifact = render_praxis_bundle(snapshot)
    publication = publisher.publish("target-alpha")
    with publication_factory() as db:
        generation = db.scalar(select(PraxisBundleGeneration).where(PraxisBundleGeneration.generation_id == publication.generation_id))
        assert generation is not None

    # When
    plaintext = publisher._crypto_service.decrypt(
        generation.ciphertext,
        PraxisBundleAad(generation.target_id, generation.generation_id, generation.bundle_schema, generation.content_hash),
    )

    # Then
    assert plaintext == artifact.archive_bytes
    assert not plaintext.startswith(b"CFPG")
    assert b'"servers"' not in plaintext[:512]
    source_plaintext = publisher._crypto_service.decrypt(
        generation.source_ciphertext,
        PraxisBundleAad(generation.target_id, generation.generation_id, generation.source_schema, generation.source_fingerprint),
    )
    assert source_plaintext == encode_source_snapshot(snapshot)
    assert generation.source_ciphertext != source_plaintext
    assert (generation.key_id, generation.nonce) != (generation.source_key_id, generation.source_nonce)
    rotated = PraxisBundleCryptoService({"key-a": b"k" * 32, "key-b": b"b" * 32}, "key-b", _NonceStore())
    assert rotated.decrypt(generation.ciphertext, PraxisBundleAad(generation.target_id, generation.generation_id, generation.bundle_schema, generation.content_hash)) == artifact.archive_bytes
    assert rotated.decrypt(
        generation.source_ciphertext,
        PraxisBundleAad(generation.target_id, generation.generation_id, generation.source_schema, generation.source_fingerprint),
    ) == encode_source_snapshot(snapshot)


def test_source_sentinel_exists_only_in_authenticated_sidecar_plaintext(publication_factory: sessionmaker[Session]) -> None:  # noqa: F811
    # Given
    sentinel = b"SOURCE-SIDECAR-SENTINEL-8d43"
    publisher = _service(publication_factory, [])
    with publication_factory() as db:
        server = db.get(Server, "server-team")
        assert server is not None
        server.name = sentinel.decode()
        db.commit()

    # When
    publication = publisher.publish("target-alpha")

    # Then
    with publication_factory() as db:
        generation = db.scalar(select(PraxisBundleGeneration).where(PraxisBundleGeneration.generation_id == publication.generation_id))
        assert generation is not None
    assert sentinel not in generation.ciphertext
    assert sentinel not in generation.source_ciphertext
    source_plaintext = publisher._crypto_service.decrypt(
        generation.source_ciphertext,
        PraxisBundleAad(generation.target_id, generation.generation_id, generation.source_schema, generation.source_fingerprint),
    )
    assert sentinel in source_plaintext


def test_nonce_collision_does_not_expose_source_sentinel(publication_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:  # noqa: F811
    # Given
    sentinel = "SOURCE-COLLISION-SENTINEL-42ac"
    publisher = _service(publication_factory, [])
    with publication_factory() as db:
        server = db.get(Server, "server-team")
        assert server is not None
        server.name = sentinel
        db.commit()
    monkeypatch.setattr(praxis_bundle_crypto.os, "urandom", lambda _size: b"z" * 12)

    # When
    with pytest.raises(PraxisBundleCryptoError) as captured:
        publisher.publish("target-alpha")

    # Then
    representations = (str(captured.value), repr(captured.value), "".join(traceback.format_exception(captured.value)), caplog.text)
    assert all(sentinel not in representation for representation in representations)


def test_additive_production_render_preserves_verified_predecessor(publication_factory: sessionmaker[Session]) -> None:  # noqa: F811
    # Given
    publisher, first = _verified_initial(publication_factory)
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None
        resource = Resource(id="resource-added", name="added", uri="docs://added", gateway_id="gateway-stream")
        db.add(resource)
        db.flush()
        db.execute(insert(server_resource_association), {"server_id": "server-team", "resource_id": resource.id})
        target.source_epoch += 1
        db.commit()

    # When
    candidate = publisher.publish("target-alpha")
    with publication_factory() as db:
        before_issuance_reconcile = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == first.rollout_id))
        assert before_issuance_reconcile is not None and before_issuance_reconcile.rollback_eligible
    PraxisBundleReconciler(publication_factory, FakeClock(datetime(2026, 8, 11, tzinfo=timezone.utc))).reconcile_committed_change("target-alpha", candidate.rollout_id, candidate.source_changes)

    # Then
    assert candidate.source_changes == frozenset({SourceChange.ADDITIVE})
    with publication_factory() as db:
        predecessor = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == first.rollout_id))
        assert predecessor is not None and predecessor.rollback_eligible


def test_descriptive_production_render_preserves_verified_predecessor(publication_factory: sessionmaker[Session]) -> None:  # noqa: F811
    # Given
    publisher, first = _verified_initial(publication_factory)
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        server = db.get(Server, "server-team")
        assert target is not None and server is not None
        server.name = "Descriptive server label"
        target.source_epoch += 1
        db.commit()

    # When
    candidate = publisher.publish("target-alpha")

    # Then
    assert candidate.source_changes == frozenset({SourceChange.DESCRIPTIVE})
    with publication_factory() as db:
        predecessor = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == first.rollout_id))
        assert predecessor is not None and predecessor.rollback_eligible


def test_removal_production_render_revokes_verified_predecessor(publication_factory: sessionmaker[Session]) -> None:  # noqa: F811
    # Given
    publisher, first = _verified_initial(publication_factory)
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        assert target is not None
        db.execute(delete(server_resource_association).where(server_resource_association.c.resource_id == "resource-1"))
        target.source_epoch += 1
        db.commit()

    # When
    candidate = publisher.publish("target-alpha")
    with publication_factory() as db:
        before_issuance_reconcile = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == first.rollout_id))
        assert before_issuance_reconcile is not None and not before_issuance_reconcile.rollback_eligible
    PraxisBundleReconciler(publication_factory, FakeClock(datetime(2026, 8, 11, tzinfo=timezone.utc))).reconcile_committed_change("target-alpha", candidate.rollout_id, candidate.source_changes)

    # Then
    assert SourceChange.REMOVAL in candidate.source_changes
    with publication_factory() as db:
        predecessor = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == first.rollout_id))
        assert predecessor is not None and not predecessor.rollback_eligible


def test_gateway_security_sensitive_render_revokes_verified_predecessor(publication_factory: sessionmaker[Session]) -> None:  # noqa: F811
    # Given
    publisher, first = _verified_initial(publication_factory)
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        gateway = db.get(Gateway, "gateway-stream")
        assert target is not None and gateway is not None
        gateway.url = "https://changed.example.test/mcp"
        target.source_epoch += 1
        db.commit()

    # When
    candidate = publisher.publish("target-alpha")
    with publication_factory() as db:
        before_issuance_reconcile = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == first.rollout_id))
        assert before_issuance_reconcile is not None and not before_issuance_reconcile.rollback_eligible
    PraxisBundleReconciler(publication_factory, FakeClock(datetime(2026, 8, 11, tzinfo=timezone.utc))).reconcile_committed_change("target-alpha", candidate.rollout_id, candidate.source_changes)

    # Then
    assert SourceChange.GATEWAY_ENDPOINT in candidate.source_changes
    with publication_factory() as db:
        predecessor = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == first.rollout_id))
        assert predecessor is not None and not predecessor.rollback_eligible


def test_secret_source_refusal_revokes_predecessor_without_desired_issuance(publication_factory: sessionmaker[Session]) -> None:  # noqa: F811
    # Given
    publisher, first = _verified_initial(publication_factory)
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        gateway = db.get(Gateway, "gateway-stream")
        assert target is not None and gateway is not None
        gateway.add_headers = {"Authorization": "Bearer secret-sentinel"}
        target.source_epoch += 1
        db.commit()

    # When / Then
    with pytest.raises(PraxisSourceError):
        publisher.publish("target-alpha")
    with publication_factory() as db:
        target = db.get(PraxisTarget, "target-alpha")
        predecessor = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == first.rollout_id))
        assert target is not None and target.desired_rollout_id == first.rollout_id
        assert predecessor is not None and not predecessor.rollback_eligible
        assert predecessor.eligibility_reason == SourceChange.SECRET_CLASSIFICATION.value
