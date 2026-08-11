# -*- coding: utf-8 -*-
"""API contract tests for privileged Praxis configuration controls."""

from collections.abc import Generator
from unittest.mock import MagicMock

from cpex.framework.models import Config
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from mcpgateway.db import Base, Permissions, PraxisTarget, PraxisTargetServer, Server
from mcpgateway.routers import praxis_config as praxis_config_router
from mcpgateway.routers.praxis_config import create_target, render_target, revoke_credential, router
from mcpgateway.config import settings
from mcpgateway.services._praxis_reconciliation import ReconcileResult, RolloutStatus, SourceChange
from mcpgateway.services.praxis_bundle_service import PraxisPublication
from mcpgateway.services.praxis_config_api_models import TargetCreate
from mcpgateway.services.praxis_config_models import PraxisSourceError, PraxisSourceErrorCode
from mcpgateway.services.praxis_config_source import PraxisConfigSourceService
from mcpgateway.services.praxis_target_service import PraxisTargetConflictError, PraxisTargetService
from tests.helpers.router_helpers import collect_routes


@pytest.fixture
def target_db() -> Generator[tuple[Session, PraxisTargetService], None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    db = factory()
    db.add_all(
        [
            PraxisTarget(id="target-a", name="Target A", created_by="admin@example.com"),
            PraxisTarget(id="target-b", name="Target B", created_by="admin@example.com"),
            Server(id="server-public", name="Public", visibility="public"),
            Server(id="server-private", name="Private", visibility="private", owner_email="owner@example.com"),
        ]
    )
    db.commit()
    yield db, PraxisTargetService(db, PraxisConfigSourceService(factory, Config()))
    db.close()
    engine.dispose()


@pytest.fixture
def disabled_delivery_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(settings, "praxis_artifact_delivery_enabled", False)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[praxis_config_router.get_current_user_with_permissions] = lambda: {"email": "admin@example.com", "token_scopes": [Permissions.PRAXIS_MANAGE]}
    return app


def test_router_exposes_privileged_target_controls() -> None:
    # Given
    paths = {(route.path, method) for route in router.routes if isinstance(route, APIRoute) for method in route.methods or set()}

    # When / Then
    assert Permissions.PRAXIS_MANAGE == "praxis.manage"
    assert {
        ("/praxis/targets", "GET"),
        ("/praxis/targets", "POST"),
        ("/praxis/targets/{target_id}", "PATCH"),
        ("/praxis/targets/{target_id}/assignments", "PUT"),
        ("/praxis/targets/{target_id}/render", "POST"),
        ("/praxis/targets/{target_id}/status", "GET"),
        ("/praxis/targets/{target_id}/replicas/{replica_id}", "DELETE"),
        ("/praxis/targets/{target_id}/replicas/{replica_id}/credentials", "POST"),
        ("/praxis/targets/{target_id}/disable", "POST"),
        ("/praxis/targets/{target_id}/rollback", "POST"),
        ("/praxis/targets/{target_id}/rollouts/{rollout_id}/retry", "POST"),
    } <= paths


def test_admin_router_does_not_expose_machine_routes() -> None:
    # Given
    paths = {route.path for route in router.routes if isinstance(route, APIRoute)}

    # When / Then
    assert {"/praxis/desired", "/praxis/artifact", "/praxis/reports"}.isdisjoint(paths)


def test_application_mounts_one_canonical_machine_control_plane() -> None:
    # Given
    from mcpgateway.main import app

    paths = [path for path, _, _ in collect_routes(app)]

    # When / Then
    assert paths.count("/praxis/v1/desired") == 1
    assert paths.count("/praxis/v1/artifact") == 1
    assert paths.count("/praxis/v1/reports") == 1
    assert "/v1/praxis/targets" in paths
    assert {"/praxis/desired", "/praxis/artifact", "/praxis/reports", "/v1/praxis/desired", "/v1/praxis/artifact", "/v1/praxis/reports"}.isdisjoint(paths)


def test_disabled_render_gates_before_publication_dependencies(disabled_delivery_app: FastAPI) -> None:
    # Given
    calls: list[str] = []

    def blocked() -> None:
        calls.append("publication")
        raise AssertionError("publication dependency resolved")

    disabled_delivery_app.dependency_overrides[praxis_config_router.get_praxis_publication_service] = blocked
    disabled_delivery_app.dependency_overrides[praxis_config_router.get_praxis_reconciler] = blocked

    # When
    with TestClient(disabled_delivery_app) as client:
        response = client.post("/praxis/targets/target-a/render")

    # Then
    assert response.status_code == 404
    assert response.json() == {"detail": "praxis_feature_disabled"}
    assert calls == []


def test_disabled_disable_gates_before_publication_dependency(disabled_delivery_app: FastAPI) -> None:
    # Given
    calls: list[str] = []

    def blocked() -> None:
        calls.append("publication")
        raise AssertionError("publication dependency resolved")

    disabled_delivery_app.dependency_overrides[praxis_config_router.get_praxis_publication_service] = blocked

    # When
    with TestClient(disabled_delivery_app) as client:
        response = client.post("/praxis/targets/target-a/disable")

    # Then
    assert response.status_code == 404
    assert response.json() == {"detail": "praxis_feature_disabled"}
    assert calls == []


def test_disabled_rollback_gates_before_reconciler_dependency(disabled_delivery_app: FastAPI) -> None:
    # Given
    calls: list[str] = []

    def blocked() -> None:
        calls.append("reconciler")
        raise AssertionError("reconciler dependency resolved")

    disabled_delivery_app.dependency_overrides[praxis_config_router.get_praxis_reconciler] = blocked

    # When
    with TestClient(disabled_delivery_app) as client:
        response = client.post("/praxis/targets/target-a/rollback")

    # Then
    assert response.status_code == 404
    assert response.json() == {"detail": "praxis_feature_disabled"}
    assert calls == []


def test_disabled_retry_gates_before_reconciler_dependency(disabled_delivery_app: FastAPI) -> None:
    calls: list[str] = []

    def blocked() -> None:
        calls.append("reconciler")
        raise AssertionError("reconciler dependency resolved")

    disabled_delivery_app.dependency_overrides[praxis_config_router.get_praxis_reconciler] = blocked

    with TestClient(disabled_delivery_app) as client:
        response = client.post("/praxis/targets/target-a/rollouts/rollout-a/retry")

    assert response.status_code == 404
    assert response.json() == {"detail": "praxis_feature_disabled"}
    assert calls == []


def test_disabled_credential_issuance_gates_before_database_dependency(disabled_delivery_app: FastAPI) -> None:
    # Given
    calls: list[str] = []

    def blocked() -> None:
        calls.append("database")
        raise AssertionError("database dependency resolved")

    disabled_delivery_app.dependency_overrides[praxis_config_router.get_db] = blocked

    # When
    with TestClient(disabled_delivery_app) as client:
        response = client.post("/praxis/targets/target-a/replicas/replica-a/credentials", json={})

    # Then
    assert response.status_code == 404
    assert response.json() == {"detail": "praxis_feature_disabled"}
    assert calls == []


@pytest.mark.asyncio
async def test_render_uses_authoritative_publication_source_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    publication = PraxisPublication("target-a", "1" * 64, "2" * 64, "rollout-a", "3" * 64, (), frozenset({SourceChange.ADDITIVE}))
    publisher = MagicMock()
    publisher.publish.return_value = publication
    reconciler = MagicMock()
    reconciler.reconcile_committed_change.return_value = ReconcileResult("target-a", "rollout-a", RolloutStatus.DESIRED)
    monkeypatch.setattr(settings, "praxis_artifact_delivery_enabled", True)

    # When
    await render_target("target-a", _user={"email": "admin@example.com"}, publisher=publisher, reconciler=reconciler)

    # Then
    reconciler.reconcile_committed_change.assert_called_once_with("target-a", "rollout-a", publication.source_changes)


@pytest.mark.asyncio
async def test_credential_revocation_remains_available_when_delivery_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "praxis_artifact_delivery_enabled", False)
    db = MagicMock()
    db.get.return_value = MagicMock(target_id="target-a")
    identity = MagicMock()
    identity.revoke_credential.return_value = True
    monkeypatch.setattr(praxis_config_router, "PraxisReplicaIdentityService", MagicMock(return_value=identity))

    response = await revoke_credential("target-a", "replica-a", "jti-a", _user={"email": "admin@example.com", "is_admin": True}, db=db)

    assert response.status_code == 204
    identity.revoke_credential.assert_called_once_with("replica-a", "jti-a")


@pytest.mark.asyncio
async def test_target_control_rejects_missing_praxis_manage_scope() -> None:
    # Given
    user = {"email": "user@example.com", "token_scopes": ["tools.read"]}

    # When / Then
    with pytest.raises(HTTPException) as denied:
        await create_target(payload=TargetCreate(name="Denied"), user=user, service=None)
    assert denied.value.status_code == 403


def test_target_crud_round_trip(target_db: tuple[Session, PraxisTargetService]) -> None:
    # Given
    db, service = target_db

    # When
    created = service.create(TargetCreate(name="Target C"), "admin@example.com")
    db.commit()

    # Then
    assert service.get(created.id).created_by == "admin@example.com"
    assert {target.name for target in service.list()} == {"Target A", "Target B", "Target C"}


def test_duplicate_enabled_assignment_requires_explicit_reassignment(target_db: tuple[Session, PraxisTargetService]) -> None:
    # Given
    db, service = target_db
    service.replace_assignments("target-a", ("server-public",), "admin@example.com", reassign=False)
    db.commit()

    # When / Then
    with pytest.raises(PraxisTargetConflictError):
        service.replace_assignments("target-b", ("server-public",), "admin@example.com", reassign=False)
    db.rollback()
    moved = service.replace_assignments("target-b", ("server-public",), "admin@example.com", reassign=True)
    db.commit()
    assert moved.server_ids == ("server-public",)
    assignment = db.scalar(select(PraxisTargetServer).where(PraxisTargetServer.server_id == "server-public"))
    assert assignment is not None and assignment.target_id == "target-b"


def test_owner_private_assignment_is_rejected_without_persistence(target_db: tuple[Session, PraxisTargetService]) -> None:
    # Given
    db, service = target_db

    # When / Then
    with pytest.raises(PraxisSourceError) as refusal:
        service.replace_assignments("target-a", ("server-private",), "admin@example.com", reassign=False)
    assert refusal.value.code is PraxisSourceErrorCode.OWNER_PRIVATE
    db.rollback()
    assert db.scalar(select(PraxisTargetServer).where(PraxisTargetServer.server_id == "server-private")) is None
