# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_oauth_status_live.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box test for the per-caller OAuth token status endpoints.

Exercises ``GET /oauth/status/{gateway_id}`` and the batch
``GET /oauth/status`` against a running gateway (``make testing-up``),
writing directly to the compose Postgres instance the gateway container
reads from - the same approach used by the PR's manual test script
(create gateway row, seed a token via ``DatabaseTokenBackend``, curl the
endpoint, verify per-user isolation) but automated.
"""

from __future__ import annotations

# Standard
import asyncio
import os
import uuid

# Third-Party
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, Gateway, OAuthToken
from mcpgateway.services.role_service import RoleService
from mcpgateway.services.token_backends.db_backend import DatabaseTokenBackend
from mcpgateway.utils.create_slug import slugify
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, skip_no_gateway

LIVE_DB_URL = os.getenv(
    "LIVE_GATEWAY_DB_URL",
    "postgresql+psycopg://postgres:mysecretpassword@localhost:5433/mcp",  # pragma: allowlist secret
)

SECOND_USER_EMAIL = "oauth-status-live-second-user@example.com"
NO_PERMISSION_USER_EMAIL = "oauth-status-live-no-permission-user@example.com"


def _db_reachable() -> bool:
    try:
        engine = create_engine(LIVE_DB_URL)
        with engine.connect():
            return True
    except Exception:
        return False


skip_no_db = pytest.mark.skipif(not _db_reachable(), reason=f"Postgres not reachable at {LIVE_DB_URL}")
pytestmark = [pytest.mark.e2e, skip_no_gateway, skip_no_db]


@pytest.fixture(scope="module")
def db_session():
    """Session bound directly to the compose Postgres instance (bypasses pgbouncer)."""
    engine = create_engine(LIVE_DB_URL)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(scope="module")
def oauth_gateway(db_session):
    """Insert an authorization_code OAuth gateway row directly.

    ``POST /gateways`` actively probes the URL and rolls back if it isn't a
    real MCP server, so the status endpoints are exercised against a row
    inserted directly - the same workaround the PR's manual test uses.
    """
    name = f"oauth-status-live-{uuid.uuid4().hex[:8]}"
    gateway = Gateway(
        id=uuid.uuid4().hex,
        name=name,
        slug=slugify(name),
        url="https://mcp.example.com",
        capabilities={},
        visibility="public",
        oauth_config={
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "authorization_url": "https://idp.example.com/authorize",
            "token_url": "https://idp.example.com/token",
            "redirect_uri": "http://localhost:8080/oauth/callback",
            "scopes": ["read"],
        },
    )
    db_session.add(gateway)
    db_session.commit()
    gateway_id = gateway.id

    yield gateway_id

    db_session.query(OAuthToken).filter(OAuthToken.gateway_id == gateway_id).delete()
    db_session.query(Gateway).filter(Gateway.id == gateway_id).delete()
    db_session.commit()


@pytest.fixture(scope="module")
def second_user(db_session):
    """A second, non-admin user distinct from the bootstrapped platform admin.

    Holds the global, system-seeded ``platform_viewer`` role so it carries
    ``gateways.read`` - required by the ``@require_permission`` gate on both
    OAuth status routes - without granting any gateway ownership. This lets
    the isolation and visibility scenarios reach the per-user/private-gateway
    logic in the handlers instead of being turned away at the RBAC gate.
    """
    existing = db_session.query(EmailUser).filter_by(email=SECOND_USER_EMAIL).first()
    created_here = existing is None
    if created_here:
        db_session.add(
            EmailUser(
                email=SECOND_USER_EMAIL,
                password_hash="",  # pragma: allowlist secret
                full_name="OAuth Status Live Second User",
                is_admin=False,
            )
        )
        db_session.commit()

    role_service = RoleService(db_session)
    role = asyncio.run(role_service.get_role_by_name("platform_viewer", "global"))
    assignment_created = False
    if role is not None and asyncio.run(role_service.get_user_role_assignment(SECOND_USER_EMAIL, role.id, "global", None)) is None:
        asyncio.run(role_service.assign_role_to_user(SECOND_USER_EMAIL, role.id, "global", None, granted_by="admin@example.com"))
        assignment_created = True

    yield SECOND_USER_EMAIL

    if assignment_created and role is not None:
        asyncio.run(role_service.revoke_role_from_user(SECOND_USER_EMAIL, role.id, "global", None))
    if created_here:
        db_session.query(EmailUser).filter_by(email=SECOND_USER_EMAIL).delete()
        db_session.commit()


@pytest.fixture(scope="module")
def no_permission_user(db_session):
    """A role-less, non-admin user - has no ``gateways.read`` permission at all.

    Used for the explicit no-permission 403 coverage on both OAuth status
    routes, kept separate from ``second_user`` (which now holds
    ``gateways.read`` so it can exercise per-user isolation and private-gateway
    visibility instead of being blocked by RBAC).
    """
    existing = db_session.query(EmailUser).filter_by(email=NO_PERMISSION_USER_EMAIL).first()
    created_here = existing is None
    if created_here:
        db_session.add(
            EmailUser(
                email=NO_PERMISSION_USER_EMAIL,
                password_hash="",  # pragma: allowlist secret
                full_name="OAuth Status Live No Permission User",
                is_admin=False,
            )
        )
        db_session.commit()

    yield NO_PERMISSION_USER_EMAIL

    if created_here:
        db_session.query(EmailUser).filter_by(email=NO_PERMISSION_USER_EMAIL).delete()
        db_session.commit()


@pytest.fixture(scope="module")
def private_gateway(db_session):
    """A private, admin-owned OAuth gateway - used to exercise the deny path for a non-owner caller."""
    name = f"oauth-status-live-private-{uuid.uuid4().hex[:8]}"
    gateway = Gateway(
        id=uuid.uuid4().hex,
        name=name,
        slug=slugify(name),
        url="https://mcp-private.example.com",
        capabilities={},
        visibility="private",
        owner_email="admin@example.com",
        oauth_config={
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "authorization_url": "https://idp.example.com/authorize",
            "token_url": "https://idp.example.com/token",
            "redirect_uri": "http://localhost:8080/oauth/callback",
            "scopes": ["read"],
        },
    )
    db_session.add(gateway)
    db_session.commit()
    gateway_id = gateway.id

    yield gateway_id

    db_session.query(OAuthToken).filter(OAuthToken.gateway_id == gateway_id).delete()
    db_session.query(Gateway).filter(Gateway.id == gateway_id).delete()
    db_session.commit()


def _seed_token(db_session, gateway_id: str, app_user_email: str, expires_in: int) -> None:
    backend = DatabaseTokenBackend(db_session, settings)
    asyncio.run(
        backend.store_tokens(
            gateway_id=gateway_id,
            team_id=None,
            user_id="idp-user-1",
            app_user_email=app_user_email,
            access_token="fake-access-token",  # pragma: allowlist secret
            refresh_token=None,
            expires_in=expires_in,
            scopes=["read"],
        )
    )


def _get_status(gateway_id: str, token: str) -> httpx.Response:
    return httpx.get(
        f"{BASE_URL}/oauth/status/{gateway_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )


def test_missing_before_authorization(oauth_gateway: str) -> None:
    """A caller who has never completed the OAuth flow sees status 'missing'."""
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=JWT_SECRET)
    response = _get_status(oauth_gateway, token)

    assert response.status_code == 200, response.text
    user_status = response.json()["user_token_status"]
    assert user_status["status"] == "missing"
    assert user_status["authorized"] is False


@pytest.mark.parametrize(
    ("expires_in", "expected_status"),
    [(3600, "valid"), (60, "near_expiry"), (-60, "expired")],
)
def test_status_reflects_token_freshness(db_session, oauth_gateway: str, expires_in: int, expected_status: str) -> None:
    """Status tracks the seeded token's expiry across valid/near_expiry/expired."""
    _seed_token(db_session, oauth_gateway, "admin@example.com", expires_in)
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=JWT_SECRET)
    response = _get_status(oauth_gateway, token)

    assert response.status_code == 200, response.text
    user_status = response.json()["user_token_status"]
    assert user_status["status"] == expected_status
    assert user_status["authorized"] is (expected_status in ("valid", "near_expiry"))


def test_per_user_isolation(db_session, oauth_gateway: str, second_user: str) -> None:
    """A second user must see 'missing' even though the admin has a valid token on the same gateway."""
    _seed_token(db_session, oauth_gateway, "admin@example.com", 3600)

    other_token = make_test_jwt(second_user, is_admin=False, teams=[], secret=JWT_SECRET)
    response = _get_status(oauth_gateway, other_token)

    assert response.status_code == 200, response.text
    assert response.json()["user_token_status"]["status"] == "missing"


def test_batch_endpoint_omits_unknown_ids(oauth_gateway: str) -> None:
    """The batch endpoint returns the real gateway and silently omits an unknown id."""
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=JWT_SECRET)
    response = httpx.get(
        f"{BASE_URL}/oauth/status",
        params=[("gateway_ids", oauth_gateway), ("gateway_ids", "nonexistent-id")],
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert oauth_gateway in body
    assert "nonexistent-id" not in body


def test_private_gateway_denies_non_owner(private_gateway: str, second_user: str) -> None:
    """A caller who isn't the owner of a private gateway, but does hold ``gateways.read``, gets 403 from the single-gateway endpoint due to private-gateway visibility, not RBAC."""
    other_token = make_test_jwt(second_user, is_admin=False, teams=[], secret=JWT_SECRET)
    response = _get_status(private_gateway, other_token)

    assert response.status_code == 403, response.text


def test_batch_endpoint_omits_private_gateway_for_non_owner(private_gateway: str, second_user: str) -> None:
    """The batch endpoint silently omits a private gateway the caller doesn't own, rather than 403ing the whole batch."""
    other_token = make_test_jwt(second_user, is_admin=False, teams=[], secret=JWT_SECRET)
    response = httpx.get(
        f"{BASE_URL}/oauth/status",
        params=[("gateway_ids", private_gateway)],
        headers={"Authorization": f"Bearer {other_token}"},
        timeout=10.0,
    )

    assert response.status_code == 200, response.text
    assert private_gateway not in response.json()


def test_single_endpoint_denies_no_permission_user(oauth_gateway: str, no_permission_user: str) -> None:
    """A caller with no ``gateways.read`` permission at all gets 403 from the single-gateway endpoint, even for a public gateway."""
    other_token = make_test_jwt(no_permission_user, is_admin=False, teams=[], secret=JWT_SECRET)
    response = _get_status(oauth_gateway, other_token)

    assert response.status_code == 403, response.text


def test_batch_endpoint_denies_no_permission_user(oauth_gateway: str, no_permission_user: str) -> None:
    """A caller with no ``gateways.read`` permission at all gets 403 from the batch endpoint, even for a public gateway."""
    other_token = make_test_jwt(no_permission_user, is_admin=False, teams=[], secret=JWT_SECRET)
    response = httpx.get(
        f"{BASE_URL}/oauth/status",
        params=[("gateway_ids", oauth_gateway)],
        headers={"Authorization": f"Bearer {other_token}"},
        timeout=10.0,
    )

    assert response.status_code == 403, response.text
