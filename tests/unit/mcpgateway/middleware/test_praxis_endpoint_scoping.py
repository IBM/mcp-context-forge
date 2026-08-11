# -*- coding: utf-8 -*-
"""Target-bound authorization tests for Praxis machine endpoints."""

from collections.abc import Generator
from datetime import timedelta
import hashlib
from typing import Annotated
from unittest.mock import MagicMock

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from uvicorn._types import ASGIReceiveCallable, ASGIReceiveEvent, ASGISendCallable, ASGISendEvent, HTTPScope, Scope
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from mcpgateway.db import Base, EmailApiToken, EmailUser, Permissions, PraxisReplica, PraxisReplicaCredential, PraxisTarget, Role, TokenRevocation, UserRole, utc_now
from mcpgateway.middleware import praxis_endpoint_scoping
from mcpgateway.middleware.praxis_endpoint_scoping import authorize_praxis_replica, PraxisReplicaRequestIdentity, require_praxis_replica
from mcpgateway.middleware.rbac import token_scope_grants
from mcpgateway.services.praxis_replica_identity import PraxisReplicaIdentityService
from mcpgateway.services.praxis_target_epoch import PraxisTargetEpochService
from mcpgateway.utils.jwt_config_helper import get_jwt_private_key_or_secret
from mcpgateway.config import settings


@pytest.fixture
def authorized(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[Session, str], None, None]:
    monkeypatch.setattr(settings, "praxis_artifact_delivery_enabled", True)
    monkeypatch.setattr(settings, "praxis_activation_enabled", True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
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
    issued = PraxisReplicaIdentityService(db).issue_credential("replica-a", expires_at=utc_now() + timedelta(hours=1))
    yield db, issued.raw_token
    db.close()
    engine.dispose()


def _request(*, scheme: str = "https", client: str = "127.0.0.1", path: str = "/praxis/artifact", headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "scheme": scheme, "server": ("gateway", 443), "client": (client, 1234), "headers": headers or []})


def test_global_empty_scope_inheritance_semantics_are_unchanged() -> None:
    assert token_scope_grants([], Permissions.PRAXIS_ARTIFACTS_READ)


@pytest.mark.parametrize(
    ("permission", "delivery_enabled", "activation_enabled"),
    [
        (Permissions.PRAXIS_ARTIFACTS_READ, False, False),
        (Permissions.PRAXIS_ARTIFACTS_READ, False, True),
        (Permissions.PRAXIS_REPORTS_WRITE, True, False),
    ],
)
def test_disabled_machine_stage_returns_fixed_404_before_auth_or_database(
    permission: str,
    delivery_enabled: bool,
    activation_enabled: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "praxis_artifact_delivery_enabled", delivery_enabled)
    monkeypatch.setattr(settings, "praxis_activation_enabled", activation_enabled)
    session_factory = MagicMock()
    monkeypatch.setattr(praxis_endpoint_scoping, "SessionLocal", session_factory)
    app = FastAPI()
    dependency = require_praxis_replica(permission)

    async def machine(_identity: Annotated[PraxisReplicaRequestIdentity, Depends(dependency)]) -> str:
        return "unexpected"

    app.add_api_route("/machine", machine, methods=["GET"])
    with TestClient(app, base_url="https://gateway.test") as client:
        response = client.get("/machine", headers={"Authorization": "Bearer rejected-before-parse"})

    assert response.status_code == 404
    assert response.json() == {"detail": "praxis_feature_disabled"}
    session_factory.assert_not_called()


def test_fastapi_dependency_uses_authorization_only_when_gateway_header_is_customized(authorized: tuple[Session, str], monkeypatch: pytest.MonkeyPatch) -> None:
    db, token = authorized
    bind = db.get_bind()
    monkeypatch.setattr(praxis_endpoint_scoping, "SessionLocal", lambda: Session(bind, expire_on_commit=False))
    monkeypatch.setattr(settings, "auth_header_name", "X-MCP-Gateway-Auth")
    app = FastAPI()
    dependency = require_praxis_replica(Permissions.PRAXIS_ARTIFACTS_READ)

    async def machine(identity: Annotated[PraxisReplicaRequestIdentity, Depends(dependency)]) -> str:
        return identity.replica_id

    app.add_api_route("/machine", machine, methods=["GET"])

    with TestClient(app, base_url="https://gateway.test") as client:
        assert client.get("/machine", headers={"Authorization": f"Bearer {token}"}).json() == "replica-a"
        assert client.get("/machine", headers={"X-MCP-Gateway-Auth": f"Bearer {token}"}).status_code == 401
        assert client.get(f"/machine?token={token}").status_code == 401
        client.cookies.set("jwt_token", token)
        assert client.get("/machine").status_code == 401


def test_activation_enabled_report_dependency_preserves_bound_identity(authorized: tuple[Session, str], monkeypatch: pytest.MonkeyPatch) -> None:
    db, token = authorized
    bind = db.get_bind()
    monkeypatch.setattr(praxis_endpoint_scoping, "SessionLocal", lambda: Session(bind, expire_on_commit=False))
    app = FastAPI()
    dependency = require_praxis_replica(Permissions.PRAXIS_REPORTS_WRITE)

    async def machine(identity: Annotated[PraxisReplicaRequestIdentity, Depends(dependency)]) -> str:
        return identity.replica_id

    app.add_api_route("/machine", machine, methods=["POST"])
    with TestClient(app, base_url="https://gateway.test") as client:
        response = client.post("/machine", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == "replica-a"


@pytest.mark.asyncio
async def test_https_bound_token_returns_server_side_identity(authorized: tuple[Session, str]) -> None:
    db, token = authorized
    identity = await authorize_praxis_replica(_request(), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert (identity.target_id, identity.replica_id) == ("target-a", "replica-a")


@pytest.mark.asyncio
async def test_trusted_proxy_normalized_https_is_accepted(authorized: tuple[Session, str]) -> None:
    db, token = authorized
    schemes: list[str] = []

    async def inner(scope: Scope, _receive: ASGIReceiveCallable, _send: ASGISendCallable) -> None:
        if scope["type"] == "http":
            schemes.append(scope["scheme"])

    async def receive() -> ASGIReceiveEvent:
        return {"type": "http.disconnect"}

    async def send(_message: ASGISendEvent) -> None:
        return None

    middleware = ProxyHeadersMiddleware(inner, trusted_hosts=["trusted-proxy"])
    scope: HTTPScope = {"type": "http", "method": "GET", "path": "/praxis/artifact", "raw_path": b"/praxis/artifact", "scheme": "http", "server": ("gateway", 80), "client": ("trusted-proxy", 1234), "headers": [(b"x-forwarded-proto", b"https")], "query_string": b"", "root_path": "", "http_version": "1.1", "asgi": {"version": "3.0", "spec_version": "2.3"}}
    await middleware(scope, receive, send)

    identity = await authorize_praxis_replica(_request(scheme=schemes[0]), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert identity.replica_id == "replica-a"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "machine_request",
    [
        _request(scheme="http"),
        _request(scheme="http", client="203.0.113.8", headers=[(b"x-forwarded-proto", b"https")]),
    ],
    ids=["direct_http", "forged_forwarded_https"],
)
async def test_http_and_forged_forwarded_https_are_denied(authorized: tuple[Session, str], machine_request: Request) -> None:
    db, token = authorized
    with pytest.raises(HTTPException) as error:
        await authorize_praxis_replica(machine_request, token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert error.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("scopes", [[], ["*"], [Permissions.PRAXIS_ARTIFACTS_READ], [Permissions.PRAXIS_REPORTS_WRITE]])
async def test_empty_scope_wildcard_and_inexact_machine_scopes_are_denied(authorized: tuple[Session, str], scopes: list[str]) -> None:
    db, token = authorized
    row = db.scalar(select(EmailApiToken))
    assert row is not None
    row.resource_scopes = scopes
    db.commit()

    with pytest.raises(HTTPException) as error:
        await authorize_praxis_replica(_request(), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim_updates", "expected_status"),
    [
        ({"aud": "mcpgateway-api"}, 401),
        ({"exp": 1}, 401),
        ({"token_use": "session"}, 401),
        ({"scopes": {"permissions": ["*"]}}, 403),
    ],
    ids=["wrong_audience", "expired", "user_client_token", "wildcard_claim"],
)
async def test_wrong_audience_expiration_token_type_and_claim_scope_are_denied(
    authorized: tuple[Session, str], claim_updates: dict, expected_status: int
) -> None:
    db, token = authorized
    payload = jwt.decode(token, options={"verify_signature": False})
    payload.update(claim_updates)
    modified = jwt.encode(payload, get_jwt_private_key_or_secret(), algorithm=settings.jwt_algorithm)
    catalog = db.scalar(select(EmailApiToken))
    assert catalog is not None
    catalog.token_hash = hashlib.sha256(modified.encode()).hexdigest()
    db.commit()

    with pytest.raises(HTTPException) as error:
        await authorize_praxis_replica(_request(), modified, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert error.value.status_code == expected_status


@pytest.mark.asyncio
async def test_wrong_binding_role_and_user_token_are_denied(authorized: tuple[Session, str]) -> None:
    db, token = authorized
    binding = db.scalar(select(PraxisReplicaCredential))
    assert binding is not None
    binding.replica_id = "replica-other"
    with pytest.raises(ValueError):
        db.flush()
    db.rollback()

    assignment = db.scalar(select(UserRole))
    assert assignment is not None
    assignment.is_active = False
    db.commit()
    with pytest.raises(HTTPException) as role_error:
        await authorize_praxis_replica(_request(), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert role_error.value.status_code == 403


@pytest.mark.asyncio
async def test_wildcard_machine_role_is_denied(authorized: tuple[Session, str]) -> None:
    db, token = authorized
    role = db.get(Role, "praxis-role")
    assert role is not None
    role.permissions = ["*"]
    db.commit()
    with pytest.raises(HTTPException) as error:
        await authorize_praxis_replica(_request(), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_wrong_replica_and_target_jti_binding_is_denied(authorized: tuple[Session, str]) -> None:
    db, token = authorized
    db.add_all(
        [
            PraxisTarget(id="target-b", name="Target B", created_by="admin@example.com"),
            PraxisReplica(id="replica-b", target_id="target-b", name="Replica B"),
        ]
    )
    db.commit()
    db.execute(update(PraxisReplicaCredential).values(target_id="target-b", replica_id="replica-b"))
    db.commit()
    with pytest.raises(HTTPException) as error:
        await authorize_praxis_replica(_request(), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_revoked_expired_inactive_and_wrong_target_binding_are_denied(authorized: tuple[Session, str]) -> None:
    db, token = authorized
    catalog = db.scalar(select(EmailApiToken))
    binding = db.scalar(select(PraxisReplicaCredential))
    assert catalog is not None and binding is not None
    db.add(TokenRevocation(jti=catalog.jti, revoked_by=catalog.user_email))
    db.commit()
    with pytest.raises(HTTPException) as revoked:
        await authorize_praxis_replica(_request(), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert revoked.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog_active", [False])
async def test_inactive_catalog_token_is_denied(authorized: tuple[Session, str], catalog_active: bool) -> None:
    db, token = authorized
    catalog = db.scalar(select(EmailApiToken))
    assert catalog is not None
    catalog.is_active = catalog_active
    db.commit()
    with pytest.raises(HTTPException) as error:
        await authorize_praxis_replica(_request(), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_disabled_target_is_denied_without_using_hostname_or_payload_identity(authorized: tuple[Session, str]) -> None:
    db, token = authorized
    target = db.get(PraxisTarget, "target-a")
    assert target is not None
    target.enabled = False
    db.commit()
    with pytest.raises(HTTPException) as error:
        await authorize_praxis_replica(_request(), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_disabled_target_can_fetch_only_its_current_stop_directive(authorized: tuple[Session, str]) -> None:
    db, token = authorized
    PraxisTargetEpochService(db).disable_target("target-a")
    db.commit()

    identity = await authorize_praxis_replica(_request(path="/praxis/v1/desired"), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert identity.target_id == "target-a"
    with pytest.raises(HTTPException) as error:
        await authorize_praxis_replica(_request(path="/praxis/v1/artifact"), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_public_errors_never_include_bearer_token(authorized: tuple[Session, str]) -> None:
    db, token = authorized
    with pytest.raises(HTTPException) as error:
        await authorize_praxis_replica(_request(scheme="http"), token, Permissions.PRAXIS_ARTIFACTS_READ, db)
    assert token not in str(error.value.detail)
