"""Authentication and API boundary tests for Praxis legacy telemetry."""

from collections.abc import Generator

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from mcpgateway.db import Base, EmailUser, get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.routers import praxis_legacy_telemetry as telemetry_router


@pytest.fixture
def app() -> Generator[FastAPI, None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = Session(engine)
    database.add_all(
        [
            EmailUser(email="admin@example.com", password_hash="test-hash", is_admin=True),
            EmailUser(email="consumer@example.com", password_hash="test-hash", is_admin=False),
        ]
    )
    database.commit()
    application = FastAPI()
    application.include_router(telemetry_router.router)
    application.dependency_overrides[get_db] = lambda: database
    yield application
    database.close()
    engine.dispose()


def _admin() -> dict[str, str | bool]:
    return {"email": "admin@example.com", "sub": "wrong@example.com", "is_admin": True}


def _user() -> dict[str, str | bool]:
    return {"email": "consumer@example.com", "is_admin": False}


def test_unauthenticated_management_is_denied(app: FastAPI) -> None:
    with TestClient(app) as client:
        assert client.get("/praxis/legacy/removal-readiness").status_code == 401


@pytest.mark.parametrize("path", ["/praxis/legacy/inventory", "/praxis/legacy/removal-readiness"])
def test_non_admin_management_is_denied(app: FastAPI, path: str) -> None:
    app.dependency_overrides[get_current_user_with_permissions] = _user
    with TestClient(app) as client:
        assert client.get(path).status_code == 403


def test_non_admin_attestation_is_denied(app: FastAPI) -> None:
    app.dependency_overrides[get_current_user_with_permissions] = _user
    with TestClient(app) as client:
        response = client.put(
            "/praxis/legacy/inventory-attestation",
            json={"consumers": [], "private_state_present": False, "shadow_diff_count": 0, "task20_e2e_passed": True, "launcher_fleet_compatible": True},
        )
    assert response.status_code == 403


def test_authenticated_heartbeat_derives_canonical_identity(app: FastAPI) -> None:
    app.dependency_overrides[get_current_user_with_permissions] = lambda: {"email": "email@example.com", "sub": "forged@example.com", "is_admin": False}
    with TestClient(app) as client:
        response = client.post("/praxis/legacy/heartbeat", json={"version": "1.2.0", "path": "control_plane_grpc"})
    assert response.status_code == 202
    assert response.json()["identity"] == "email@example.com"


def test_heartbeat_rejects_forged_identity_field(app: FastAPI) -> None:
    app.dependency_overrides[get_current_user_with_permissions] = _user
    with TestClient(app) as client:
        response = client.post(
            "/praxis/legacy/heartbeat",
            json={"identity": "victim@example.com", "version": "1.2.0", "path": "control_plane_grpc"},
        )
    assert response.status_code == 422


def test_unobservable_heartbeat_is_denied(app: FastAPI) -> None:
    app.dependency_overrides[get_current_user_with_permissions] = _user
    with TestClient(app) as client:
        response = client.post("/praxis/legacy/heartbeat", json={"version": "1.2.0", "path": "direct_redis"})
    assert response.status_code == 409
    assert response.json() == {"detail": "unobservable_consumer"}


def test_admin_attestation_and_report_use_email_precedence(app: FastAPI) -> None:
    app.dependency_overrides[get_current_user_with_permissions] = _admin
    with TestClient(app) as client:
        attested = client.put(
            "/praxis/legacy/inventory-attestation",
            json={"consumers": [], "private_state_present": False, "shadow_diff_count": 0, "task20_e2e_passed": True, "launcher_fleet_compatible": True},
        )
        report = client.get("/praxis/legacy/removal-readiness")
    assert attested.status_code == 200
    assert attested.json()["actor"] == "admin@example.com"
    assert report.status_code == 200
    assert report.json()["ready"] is False


def test_removal_report_cannot_remove_routes(app: FastAPI) -> None:
    app.dependency_overrides[get_current_user_with_permissions] = _admin
    before = {(route.path, tuple(sorted(route.methods or ()))) for route in app.routes if isinstance(route, APIRoute)}
    with TestClient(app) as client:
        assert client.get("/praxis/legacy/removal-readiness").status_code == 200
    after = {(route.path, tuple(sorted(route.methods or ()))) for route in app.routes if isinstance(route, APIRoute)}
    assert after == before
