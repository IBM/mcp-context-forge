# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_resource_route_names_scoping.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box tests for route names under resource prefixes.

Token scoping reads a resource ID from paths such as ``/gateways/{id}``. A route name under
the same prefix, such as ``/admin/gateways/discover-oauth``, is not a resource ID. A team-scoped
session that holds the route permission reaches the handler, and a session without the
permission gets 403 from RBAC.

Every account, team, role, grant and token is created through the HTTP API of a private
gateway subprocess (see ``isolated_gateway``). No Docker stack is required.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers
from tests.live_gateway.e2e.test_candidate_credential_handshake import _GatewayFixture, isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.parametrize("isolated_gateway", [{"AUTO_CREATE_PERSONAL_TEAMS": "false"}], ids=["no-personal-teams"], indirect=True),
]

_PASSWORD = "E2eRouteNames!42"  # pragma: allowlist secret
_CREATOR = "creator@example.com"
_MEMBER = "member@example.com"
_DISCOVER_OAUTH = "/admin/gateways/discover-oauth"


def _setup(client: httpx.Client, method: str, path: str, step: str, *, expected: tuple[int, ...] = (200, 201), **kwargs: Any) -> Any:
    """Send a setup request and return its JSON body.

    Raises:
        RuntimeError: If the response status is not in ``expected``.
    """
    response = client.request(method, path, **kwargs)
    if response.status_code not in expected:
        raise RuntimeError(f"setup: {step} {response.status_code} {response.text[:300]}")
    return response.json() if response.content else None


@pytest.fixture
def team_sessions(isolated_gateway: _GatewayFixture) -> tuple[str, dict[str, str]]:  # noqa: F811  pylint: disable=redefined-outer-name
    """Create two members of one team, grant ``gateways.create`` globally to one, and return the base URL and their session tokens."""
    admin, _token, base_url, _key = isolated_gateway
    team_id = _setup(admin, "POST", "/teams/", "team", json={"name": "route-names", "visibility": "private"})["id"]
    for email in (_CREATOR, _MEMBER):
        _setup(
            admin,
            "POST",
            "/auth/email/admin/users",
            f"user {email}",
            expected=(201,),
            json={"email": email, "password": _PASSWORD, "full_name": email.split("@")[0], "is_admin": False, "is_active": True, "password_change_required": False},
        )
        _setup(admin, "POST", f"/teams/{team_id}/members", f"member {email}", json={"email": email, "role": "member"})

    role = _setup(admin, "POST", "/rbac/roles", "role gateway-creator", json={"name": "gateway-creator", "scope": "global", "permissions": ["gateways.create"]})
    _setup(admin, "POST", f"/rbac/users/{_CREATOR}/roles", "grant gateway-creator", json={"role_id": role["id"], "scope": "global", "scope_id": None})

    sessions = {}
    with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as anonymous:
        for email in (_CREATOR, _MEMBER):
            sessions[email] = _setup(anonymous, "POST", "/auth/email/login", f"login {email}", json={"email": email, "password": _PASSWORD})["access_token"]
    return base_url, sessions


def _discover_oauth(base_url: str, token: str) -> httpx.Response:
    """Call OAuth discovery with an issuer that the handler rejects without a network call."""
    with httpx.Client(base_url=base_url, headers=make_auth_headers(token), timeout=30, trust_env=False) as client:
        return client.post(_DISCOVER_OAUTH, json={"issuer": "not-a-url"})


def test_discover_oauth_route_name_reaches_handler_for_team_scoped_session(team_sessions: tuple[str, dict[str, str]]) -> None:  # pylint: disable=redefined-outer-name
    """A team-scoped session with ``gateways.create`` reaches the discovery handler."""
    base_url, sessions = team_sessions

    response = _discover_oauth(base_url, sessions[_CREATOR])

    assert response.status_code == 400, response.text
    assert response.json()["success"] is False


def test_discover_oauth_without_permission_is_denied(team_sessions: tuple[str, dict[str, str]]) -> None:  # pylint: disable=redefined-outer-name
    """A team-scoped session without ``gateways.create`` gets 403."""
    base_url, sessions = team_sessions

    response = _discover_oauth(base_url, sessions[_MEMBER])

    assert response.status_code == 403, response.text


def test_discover_oauth_without_credentials_is_rejected(team_sessions: tuple[str, dict[str, str]]) -> None:  # pylint: disable=redefined-outer-name
    """A request without credentials gets 401."""
    base_url, _sessions = team_sessions
    with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as anonymous:
        response = anonymous.post(_DISCOVER_OAUTH, json={"issuer": "not-a-url"})

    assert response.status_code == 401, response.text
