# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_card_refresh_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks for ``POST /a2a/{agent_id}/card`` (#7540) against an isolated gateway subprocess.

A loopback server plays the remote agent and records every request. Each denied call must leave
the agent without a new request.
"""

# Standard
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.a2a.test_a2a_extended_card_e2e import _Agent, _register, _request, agent, GOOD_KEY  # noqa: F401  # pylint: disable=unused-import
from tests.live_gateway.a2a.test_a2a_fetch_card_e2e import gateway  # noqa: F401  # pylint: disable=unused-import

pytestmark = pytest.mark.e2e


def _gets(remote):
    """Return the number of card GET requests the agent received."""
    return len([request for request in remote.requests if request[0] == "GET"])


def _new_agent(gateway, agent, name):  # noqa: F811
    """Register an agent and return its id."""
    created = _register(gateway, agent, name, GOOD_KEY)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_refresh_of_an_unchanged_card_reports_unchanged_and_adds_no_version(gateway, agent):  # noqa: F811
    """The agent serves the same card, so the refresh adds no version."""
    agent_id = _new_agent(gateway, agent, "e2e-refresh-unchanged")
    before = _gets(agent)

    response = _request(gateway, "POST", f"/a2a/{agent_id}/card")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "unchanged" and body["changedKeys"] == []
    assert _gets(agent) == before + 1
    assert _request(gateway, "GET", f"/a2a/{agent_id}/stored-card").json()["version"] == body["version"]


def test_second_refresh_inside_the_interval_is_429_and_fetches_nothing(gateway, agent):  # noqa: F811
    """A call inside the minimum interval gets 429 with Retry-After and no outbound request."""
    agent_id = _new_agent(gateway, agent, "e2e-refresh-throttle")
    assert _request(gateway, "POST", f"/a2a/{agent_id}/card").status_code == 200
    before = _gets(agent)

    response = _request(gateway, "POST", f"/a2a/{agent_id}/card")

    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
    assert _gets(agent) == before


@pytest.mark.parametrize(("permission", "status"), [("a2a.read", 403), ("a2a.create", 403), ("a2a.update", 200)])
def test_refresh_needs_a2a_update_in_the_token_scope(gateway, agent, permission, status):  # noqa: F811
    """Only a token scoped to a2a.update may refresh. A denied call fetches nothing."""
    agent_id = _new_agent(gateway, agent, f"e2e-refresh-scope-{permission}")
    before = _gets(agent)

    response = _request(gateway, "POST", f"/a2a/{agent_id}/card", scopes={"permissions": [permission]})

    assert response.status_code == status, response.text
    assert _gets(agent) == before + (1 if status == 200 else 0)


def _api_token(gateway, permissions):  # noqa: F811
    """Mint a stored API token limited to ``permissions``, so the RBAC layer sees its scopes."""
    created = _request(gateway, "POST", "/tokens", json={"name": f"refresh-{uuid.uuid4().hex[:8]}", "expires_in_days": 1, "scope": {"permissions": permissions}})
    assert created.status_code in (200, 201), created.text
    return created.json()["access_token"]


@pytest.mark.parametrize(("permissions", "status"), [(["a2a.update"], 403), (["a2a.update", "a2a.create"], 200)])
def test_base_url_needs_a2a_create_as_well(gateway, agent, permissions, status):  # noqa: F811
    """A token with only a2a.update cannot pick the URL the gateway fetches. A denied call fetches nothing."""
    agent_id = _new_agent(gateway, agent, f"e2e-refresh-base-url-{len(permissions)}")
    token = _api_token(gateway, permissions)
    before = _gets(agent)
    base, _ = gateway

    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        response = client.post(f"/a2a/{agent_id}/card", headers=make_auth_headers(token), json={"baseUrl": f"{agent.origin}/other"})

    assert response.status_code == status, response.text
    assert _gets(agent) == before + (1 if status == 200 else 0)


def test_caller_who_does_not_own_the_agent_cannot_refresh_it(gateway, agent):  # noqa: F811
    """A user with a2a.update who does not own the agent gets 404, and the agent receives no request."""
    agent_id = _new_agent(gateway, agent, "e2e-refresh-non-owner")
    email = f"refresher-{uuid.uuid4().hex[:8]}@example.com"
    role = _request(gateway, "POST", "/rbac/roles", json={"name": f"refresher-{uuid.uuid4().hex[:8]}", "description": "Update agents", "scope": "global", "permissions": ["a2a.read", "a2a.update"]})
    assert role.status_code == 200, role.text
    user = {"email": email, "password": f"Aa1!{uuid.uuid4().hex}", "full_name": email, "is_admin": False}
    assert _request(gateway, "POST", "/auth/email/admin/users", json=user).status_code == 201
    assert _request(gateway, "POST", f"/rbac/users/{email}/roles", json={"role_id": role.json()["id"], "scope": "global"}).status_code == 200
    before = _gets(agent)
    base, key = gateway
    token = make_test_jwt(email, is_admin=False, teams=[], secret=key, algorithm="HS256")

    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        response = client.post(f"/a2a/{agent_id}/card", headers=make_auth_headers(token))

    assert response.status_code == 404, response.text
    assert _gets(agent) == before


def test_refresh_of_an_unknown_agent_is_404(gateway):  # noqa: F811
    """An agent that does not exist answers 404."""
    assert _request(gateway, "POST", "/a2a/does-not-exist/card").status_code == 404
