# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_search_e2e.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end tests for GET /v1/search using a REAL signed JWT through the full
auth + token-scoping middleware stack (no dependency overrides).

Unlike the unit tests (which mock handlers) and the integration tests (which
inject the user context via dependency_overrides), these mint a real JWT signed
with the app's configured secret and let the genuine auth pipeline validate it.
This is the only layer that exercises the JWT -> middleware -> RBAC path
end-to-end, mirroring the manual curl verification on PR #5610.

Minimal, high-value cases (the ones that require the real JWT path):
  * unauthenticated request -> 401 (real auth middleware)
  * non-admin JWT -> 200 (proves /v1/search needs no admin access)
  * permission-scoped JWT (tools.read) -> 200 (token-scoping middleware allows /search)
"""

# Future
from __future__ import annotations

# Standard
import os
import tempfile
import time
import uuid

# Third-Party
from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient
import jwt as pyjwt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

E2E_JWT_SECRET = "e2e-search-jwt-secret-key-with-minimum-32-bytes"  # pragma: allowlist secret
SEARCH_TERM = "e2esearch"
MEMBER = "member-e2e@example.com"


def _jwt(*, email, is_admin=False, teams=None, scopes=None):
    """Mint a real JWT signed with the e2e secret."""
    now = int(time.time())
    payload = {
        "sub": email,
        "iat": now,
        "exp": now + 3600,
        "iss": "mcpgateway",
        "aud": "mcpgateway-api",
        "jti": uuid.uuid4().hex,
        "user": {"email": email, "is_admin": is_admin, "auth_provider": "local"},
        "teams": teams,
    }
    if scopes is not None:
        payload["scopes"] = scopes
    return pyjwt.encode(payload, E2E_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def e2e_client():
    """Real app + temp DB + real auth (no auth dependency overrides).

    Yields:
        TestClient bound to the real app with auth enforced and a seeded
        non-admin member holding a global tools.read role.
    """
    mp = MonkeyPatch()

    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    from pydantic import SecretStr

    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)
    mp.setattr(settings, "auth_required", True, raising=False)
    mp.setattr(settings, "jwt_secret_key", SecretStr(E2E_JWT_SECRET), raising=False)

    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod
    import mcpgateway.middleware.auth_middleware as auth_middleware_mod
    import mcpgateway.services.audit_trail_service as audit_trail_mod
    import mcpgateway.services.log_aggregator as log_aggregator_mod
    import mcpgateway.services.security_logger as sec_logger_mod
    import mcpgateway.services.structured_logger as struct_logger_mod

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    for mod in (db_mod, main_mod, auth_middleware_mod, sec_logger_mod, struct_logger_mod, audit_trail_mod, log_aggregator_mod):
        mp.setattr(mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(db_mod, "engine", engine, raising=False)

    db_mod.Base.metadata.create_all(bind=engine)

    from mcpgateway.db import EmailUser, Role, Tool, UserRole

    db = TestSessionLocal()
    db.add(EmailUser(id=uuid.uuid4().hex, email=MEMBER, password_hash="x", full_name="E2E Member", is_admin=False, is_active=True, auth_provider="local"))  # pragma: allowlist secret
    role_id = uuid.uuid4().hex
    db.add(Role(id=role_id, name="e2e-reader", scope="global", permissions=["tools.read"], created_by=MEMBER, is_active=True))
    db.add(UserRole(id=uuid.uuid4().hex, user_email=MEMBER, role_id=role_id, scope="global", scope_id=None, granted_by=MEMBER, is_active=True))
    db.add(
        Tool(
            id=uuid.uuid4().hex,
            original_name=f"{SEARCH_TERM}-tool",
            url="http://example.com/e2e",
            owner_email=MEMBER,
            visibility="public",
            integration_type="REST",
            request_type="GET",
            input_schema={},
            output_schema={},
            enabled=True,
            deprecated=False,
            created_by=MEMBER,
            tags=[],
        )
    )
    db.commit()
    db.close()

    from mcpgateway.main import app

    client = TestClient(app, raise_server_exceptions=False)
    yield client

    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


def test_unauthenticated_returns_401(e2e_client):
    """No token -> rejected by the real auth middleware."""
    assert e2e_client.get(f"/v1/search?q={SEARCH_TERM}").status_code == 401


def test_non_admin_jwt_reaches_search(e2e_client):
    """A real non-admin JWT reaches /v1/search and gets the grouped contract (no admin needed)."""
    token = _jwt(email=MEMBER, is_admin=False, teams=None)
    resp = e2e_client.get(f"/v1/search?q={SEARCH_TERM}&entity_types=tools", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"query", "entity_types", "results", "groups", "items", "count"}
    # Real RBAC + real query: the member's tools.read role lets the seeded public
    # tool come back, so this is not an empty/denied 200.
    assert any(t.get("name") == f"{SEARCH_TERM}-tool" for t in body["results"]["tools"])


def test_permission_scoped_jwt_reaches_search(e2e_client):
    """A non-wildcard permission-scoped JWT passes the token-scoping middleware for /search."""
    token = _jwt(email=MEMBER, is_admin=False, teams=None, scopes={"permissions": ["tools.read"]})
    resp = e2e_client.get(f"/v1/search?q={SEARCH_TERM}&entity_types=tools", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
