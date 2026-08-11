# -*- coding: utf-8 -*-
"""Rejected Task 11 machine API regression contracts."""

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.db import PraxisBundleGeneration
from mcpgateway.middleware.praxis_endpoint_scoping import PraxisReplicaRequestIdentity
from mcpgateway.routers.praxis_config_machine import get_machine_service, PraxisMachineApiService, router
from mcpgateway.services.praxis_bundle_reconciler import LKG_MAX_AGE
from mcpgateway.services.praxis_config_archive import build_praxis_bundle
from mcpgateway.services.praxis_config_models import PraxisBundleBuildRequest, PraxisCompatibilityContract, PraxisRenderedDocument, PraxisSourceSnapshot
from tests.helpers.praxis_reconciler import FakeClock
from tests.security.test_praxis_artifact_authorization import machine_api  # noqa: F401

__all__ = ("machine_api",)


def test_conditional_desired_refreshes_freshness_without_changing_directive_or_eligibility(machine_api: tuple[Session, PraxisMachineApiService, bytes, str]) -> None:  # noqa: F811
    # Given
    _, service, _, directive_id = machine_api
    clock = service._reconciler._clock
    assert isinstance(clock, FakeClock)
    initial, unchanged = service.desired("target-a", "replica-a", None)
    clock.advance(60)

    # When
    refreshed, conditional = service.desired("target-a", "replica-a", f'"{initial.response_etag}"')

    # Then
    assert not unchanged and conditional
    assert refreshed.directive_id == initial.directive_id == directive_id
    assert refreshed.response_etag == initial.response_etag
    assert refreshed.eligibility_deadline == initial.eligibility_deadline
    assert refreshed.freshness_deadline == clock.now() + LKG_MAX_AGE
    assert refreshed.freshness_deadline > initial.freshness_deadline


def test_exact_machine_desired_path_returns_200_then_fresh_304(machine_api: tuple[Session, PraxisMachineApiService, bytes, str]) -> None:  # noqa: F811
    # Given
    _, service, _, _ = machine_api
    clock = service._reconciler._clock
    assert isinstance(clock, FakeClock)
    clock.advance(60)
    app = FastAPI()
    app.include_router(router)
    desired_route = next(route for route in router.routes if isinstance(route, APIRoute) and route.path == "/praxis/v1/desired")
    identity_dependency = desired_route.dependant.dependencies[0].call
    assert identity_dependency is not None
    app.dependency_overrides[identity_dependency] = lambda: PraxisReplicaRequestIdentity("target-a", "replica-a", "bound-jti")
    app.dependency_overrides[get_machine_service] = lambda: service

    # When
    with TestClient(app, base_url="https://gateway.test") as client:
        desired = client.get("/praxis/v1/desired")
        conditional = client.get("/praxis/v1/desired", headers={"If-None-Match": desired.headers["etag"]})

    # Then
    assert desired.status_code == 200
    assert conditional.status_code == 304
    assert conditional.headers["etag"] == desired.headers["etag"]
    assert desired.json()["freshness_deadline"] != desired.json()["eligibility_deadline"]


def test_http_artifact_rejects_valid_canonical_plaintext_with_wrong_content_hash(machine_api: tuple[Session, PraxisMachineApiService, bytes, str], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    # Given
    db, service, _, directive_id = machine_api
    alternate = build_praxis_bundle(
        PraxisBundleBuildRequest(
            snapshot=PraxisSourceSnapshot(target_id="target-a", source_fingerprint="2" * 64),
            compatibility=PraxisCompatibilityContract(
                bundle_schema="praxis-bundle/v1",
                renderer_version="1",
                praxis_revision="ed46eb5",
                cpex_contract_version="cpex/v1",
                mcp_protocol_version="2025-11-25",
                minimum_launcher_version="0.1.0",
            ),
            documents=(PraxisRenderedDocument(path="praxis.yaml", content=b'{"changed":true}'),),
        )
    ).archive_bytes
    generation = db.scalar(select(PraxisBundleGeneration))
    assert generation is not None
    decrypt = service._crypto.decrypt
    monkeypatch.setattr(service._crypto, "decrypt", lambda envelope, identity: alternate if identity.bundle_schema_version == generation.bundle_schema else decrypt(envelope, identity))
    app = FastAPI()
    app.include_router(router)
    artifact_route = next(route for route in router.routes if isinstance(route, APIRoute) and route.path == "/praxis/v1/artifact")
    identity_dependency = artifact_route.dependant.dependencies[0].call
    assert identity_dependency is not None
    app.dependency_overrides[identity_dependency] = lambda: PraxisReplicaRequestIdentity("target-a", "replica-a", "bound-jti")
    app.dependency_overrides[get_machine_service] = lambda: service

    # When
    with TestClient(app, base_url="https://gateway.test") as client:
        response = client.get("/praxis/v1/artifact", headers={"If-Match": directive_id})

    # Then
    assert response.status_code == 500
    assert alternate not in response.content
