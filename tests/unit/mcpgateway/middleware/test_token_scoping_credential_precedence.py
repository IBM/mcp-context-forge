# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_token_scoping_credential_precedence.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Real-app coverage that token scopes apply to the bearer credential the route authenticates.

Each restriction test runs with every auth cookie variant. A cookie never
replaces the bearer token as the source of token scopes.
"""

# Standard
from datetime import datetime, timezone
import os
import tempfile
import uuid

# Third-Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.auth as auth_mod
import mcpgateway.db as db_mod
import mcpgateway.main as main_mod
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailTeamMember, EmailUser, Role, Tool, UserRole
from tests.helpers.auth import make_test_jwt

ADMIN_EMAIL = "restricted@example.com"
OTHER_EMAIL = "other@example.com"
MEMBER_EMAIL = "member@example.com"
TEAM_A_ID = "team-a"
TEAM_B_ID = "team-b"
TEAM_B_TOOL_ID = uuid.uuid4().hex
ALLOWED_IP = "192.0.2.10"
DISALLOWED_IP = "198.51.100.20"


def _admin_token(email: str = ADMIN_EMAIL, scopes: dict | None = None) -> str:
    """Mint an admin-bypass token, optionally with token scopes."""
    return make_test_jwt(email, is_admin=True, teams=None, scopes=scopes, extra_payload={"jti": str(uuid.uuid4())})


def _ip_restricted_token() -> str:
    """Mint an admin token restricted to ``ALLOWED_IP``."""
    return _admin_token(scopes={"ip_restrictions": [f"{ALLOWED_IP}/32"]})


COOKIES = {
    "none": None,
    "invalid_jwt_token": ("jwt_token", "invalid"),
    "invalid_access_token": ("access_token", "invalid"),
    "other_user_valid": ("jwt_token", _admin_token(OTHER_EMAIL)),
}


@pytest.fixture(scope="module")
def app_db():
    """Run the real application against a temporary database with seeded users, teams and a tool."""
    # Third-Party
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database_url = f"sqlite:///{path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    mp.setattr(settings, "database_url", database_url, raising=False)
    mp.setattr(settings, "auth_required", True)
    mp.setattr(settings, "require_user_in_db", True)
    mp.setattr(settings, "auth_cache_enabled", False)
    mp.setattr(settings, "auth_cache_batch_queries", False)
    mp.setattr(settings, "permission_audit_enabled", False)

    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", test_session_local, raising=False)
    mp.setattr(main_mod, "SessionLocal", test_session_local, raising=False)
    mp.setattr(auth_mod, "SessionLocal", test_session_local, raising=False)

    # These modules import SessionLocal directly and may run from middleware.
    import mcpgateway.middleware.auth_middleware as auth_middleware_mod
    import mcpgateway.services.audit_trail_service as audit_trail_mod
    import mcpgateway.services.log_aggregator as log_aggregator_mod
    import mcpgateway.services.security_logger as security_logger_mod
    import mcpgateway.services.structured_logger as structured_logger_mod

    for module in (auth_middleware_mod, audit_trail_mod, log_aggregator_mod, security_logger_mod, structured_logger_mod):
        mp.setattr(module, "SessionLocal", test_session_local, raising=False)

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = test_session_local()
        try:
            yield db
        finally:
            db.close()

    from mcpgateway.db import get_db as db_get_db
    from mcpgateway.middleware.rbac import get_db as rbac_get_db
    from mcpgateway.routers.auth import get_db as auth_get_db

    main_mod.app.dependency_overrides[db_get_db] = override_get_db
    main_mod.app.dependency_overrides[rbac_get_db] = override_get_db
    main_mod.app.dependency_overrides[auth_get_db] = override_get_db

    now = datetime.now(timezone.utc)
    with test_session_local() as db:
        db.add_all(
            [
                EmailUser(email=ADMIN_EMAIL, full_name="Restricted Admin", is_admin=True, is_active=True, email_verified_at=now),
                EmailUser(email=OTHER_EMAIL, full_name="Other Admin", is_admin=True, is_active=True, email_verified_at=now),
                EmailUser(email=MEMBER_EMAIL, full_name="Team Member", is_admin=False, is_active=True, email_verified_at=now),
            ]
        )
        db.flush()
        db.add_all(
            [
                EmailTeam(id=TEAM_A_ID, name="Team A", slug=f"team-a-{uuid.uuid4().hex}", created_by=ADMIN_EMAIL, visibility="private"),
                EmailTeam(id=TEAM_B_ID, name="Team B", slug=f"team-b-{uuid.uuid4().hex}", created_by=ADMIN_EMAIL, visibility="private"),
            ]
        )
        db.flush()
        db.add(EmailTeamMember(team_id=TEAM_A_ID, user_email=MEMBER_EMAIL, role="member", invited_by=ADMIN_EMAIL, is_active=True))
        reader = Role(name=f"tool-reader-{uuid.uuid4().hex}", scope="team", permissions=["tools.read"], created_by=ADMIN_EMAIL, is_active=True)
        db.add(reader)
        db.flush()
        db.add(UserRole(user_email=MEMBER_EMAIL, role_id=reader.id, scope="team", scope_id=TEAM_A_ID, granted_by=ADMIN_EMAIL, is_active=True))
        db.add(
            Tool(
                id=TEAM_B_TOOL_ID,
                original_name="team_b_tool",
                custom_name="team_b_tool",
                custom_name_slug=f"team-b-tool-{uuid.uuid4().hex}",
                input_schema={},
                team_id=TEAM_B_ID,
                owner_email=ADMIN_EMAIL,
                visibility="team",
            )
        )
        db.commit()

    yield

    main_mod.app.dependency_overrides.pop(db_get_db, None)
    main_mod.app.dependency_overrides.pop(rbac_get_db, None)
    main_mod.app.dependency_overrides.pop(auth_get_db, None)
    mp.undo()
    engine.dispose()
    os.unlink(path)


def _client(ip: str = DISALLOWED_IP) -> TestClient:
    """Build a client whose requests come from ``ip``."""
    return TestClient(main_mod.app, client=(ip, 50000), raise_server_exceptions=False)


def _send(method: str, path: str, *, bearer: str | None = None, cookie: tuple[str, str] | None = None, ip: str = DISALLOWED_IP, json: dict | None = None) -> int:
    """Send one request with an optional bearer token and auth cookie; return the status code."""
    client = _client(ip)
    try:
        if cookie is not None:
            client.cookies.set(*cookie)
        headers = {"Authorization": f"Bearer {bearer}"} if bearer is not None else {}
        return client.request(method, path, headers=headers, json=json).status_code
    finally:
        client.cookies.clear()
        client.close()


@pytest.mark.usefixtures("app_db")
def test_ip_restriction_allowed_ip_baseline():
    """An IP-restricted token works from its allowed address."""
    assert _send("GET", "/tools", bearer=_ip_restricted_token(), ip=ALLOWED_IP) == 200


@pytest.mark.usefixtures("app_db")
@pytest.mark.parametrize("cookie", COOKIES.values(), ids=COOKIES.keys())
def test_ip_restriction_enforced_on_bearer(cookie):
    """IP restrictions on the bearer token apply whatever auth cookie is present."""
    assert _send("GET", "/tools", bearer=_ip_restricted_token(), cookie=cookie) == 403


@pytest.mark.usefixtures("app_db")
@pytest.mark.parametrize("cookie", COOKIES.values(), ids=COOKIES.keys())
def test_server_id_restriction_enforced_on_bearer(cookie):
    """A server-bound bearer token cannot reach another server whatever auth cookie is present."""
    assert _send("GET", "/servers/srv-b/tools", bearer=_admin_token(scopes={"server_id": "srv-a"}), cookie=cookie) == 403


@pytest.mark.usefixtures("app_db")
@pytest.mark.parametrize("cookie", COOKIES.values(), ids=COOKIES.keys())
def test_permission_restriction_enforced_on_bearer(cookie):
    """Permission scopes on the bearer token apply whatever auth cookie is present."""
    body = {"tool": {"name": f"tool-{uuid.uuid4().hex[:8]}", "url": "https://example.com/api", "integration_type": "REST", "request_type": "GET"}}
    assert _send("POST", "/tools", bearer=_admin_token(scopes={"permissions": ["tools.read"]}), cookie=cookie, json=body) == 403


@pytest.mark.usefixtures("app_db")
@pytest.mark.parametrize("cookie", COOKIES.values(), ids=COOKIES.keys())
def test_team_scope_enforced_on_bearer(cookie):
    """A team-scoped bearer token cannot read another team's resource whatever auth cookie is present."""
    token = make_test_jwt(MEMBER_EMAIL, teams=[TEAM_A_ID], extra_payload={"jti": str(uuid.uuid4())})
    assert _send("GET", f"/tools/{TEAM_B_TOOL_ID}", bearer=token, cookie=cookie) == 403


@pytest.mark.usefixtures("app_db")
@pytest.mark.parametrize("cookie", COOKIES.values(), ids=COOKIES.keys())
def test_ip_restriction_enforced_when_auth_not_required(cookie, monkeypatch):
    """IP restrictions on the bearer token apply when auth is optional."""
    monkeypatch.setattr(settings, "auth_required", False)
    assert _send("GET", "/tools", bearer=_ip_restricted_token(), cookie=cookie) == 403


@pytest.mark.usefixtures("app_db")
def test_invalid_cookie_only_rejected():
    """An invalid auth cookie without a bearer token does not authenticate."""
    assert _send("GET", "/tools", cookie=("jwt_token", "invalid")) in (401, 403)


@pytest.mark.usefixtures("app_db")
def test_restricted_cookie_only_enforces_ip():
    """Token scopes apply to the auth cookie when no bearer token is present."""
    assert _send("GET", "/tools", cookie=("jwt_token", _ip_restricted_token())) == 403


@pytest.mark.usefixtures("app_db")
def test_invalid_bearer_with_restricted_cookie_rejected_on_version():
    """An invalid bearer token is not rescued by a valid auth cookie."""
    assert _send("GET", "/version", bearer="invalid", cookie=("jwt_token", _ip_restricted_token())) in (401, 403)
