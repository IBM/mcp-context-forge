# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_oauth_extra_auth_params_live.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box test for extra authorization URL parameters (``oauth_config.extra_auth_params``).

Runs against a gateway started with ``make testing-up``. Registering an
authorization_code gateway skips the MCP connection, so no MCP server or
OAuth provider is needed. The URLs use real hostnames because URL validation
resolves them; the test sends no request to them.
"""

# Standard
from urllib.parse import parse_qs, urlparse
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

OAUTH_CONFIG = {
    "grant_type": "authorization_code",
    "client_id": "live-client",
    "client_secret": "live-secret",  # pragma: allowlist secret
    "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_url": "https://oauth2.googleapis.com/token",
    "redirect_uri": "https://example.com/oauth/callback",
    "scopes": ["openid"],
}
# The masked placeholder keeps the stored client_secret on update
UPDATE_CONFIG = {**OAUTH_CONFIG, "client_secret": "*****"}  # pragma: allowlist secret


@pytest.fixture
def client():
    """Admin HTTP client for the running gateway."""
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30.0) as http:
        yield http


def _authorize_query(client: httpx.Client, gateway_id: str) -> dict[str, list[str]]:
    response = client.get(f"/oauth/authorize/{gateway_id}", follow_redirects=False)
    assert response.status_code in (302, 307), response.text
    return parse_qs(urlparse(response.headers["location"]).query)


def _stored_extra_auth_params(client: httpx.Client, gateway_id: str) -> dict[str, str] | None:
    return (client.get(f"/gateways/{gateway_id}").json().get("oauthConfig") or {}).get("extra_auth_params")


def test_extra_auth_params_follow_create_update_and_clear(client: httpx.Client) -> None:
    """The provider redirect follows the stored extras through create, update, and clear; rejected and unauthenticated updates keep them."""
    suffix = uuid.uuid4().hex[:8]
    created = client.post(
        "/gateways",
        json={
            "name": f"extra-auth-params-live-{suffix}",
            "url": f"https://example.com/mcp/{suffix}",
            "auth_type": "oauth",
            "oauth_config": {**OAUTH_CONFIG, "extra_auth_params": {"access_type": "offline", "prompt": "consent"}},
        },
    )
    assert created.status_code in (200, 201), created.text
    gateway_id = created.json()["id"]
    try:
        assert _stored_extra_auth_params(client, gateway_id) == {"access_type": "offline", "prompt": "consent"}
        query = _authorize_query(client, gateway_id)
        assert query["access_type"] == ["offline"]
        assert query["prompt"] == ["consent"]
        assert query["redirect_uri"] == [OAUTH_CONFIG["redirect_uri"]]

        anonymous = httpx.put(f"{BASE_URL}/gateways/{gateway_id}", json={"oauth_config": {**UPDATE_CONFIG, "extra_auth_params": {"prompt": "none"}}}, timeout=30.0)
        assert anonymous.status_code == 401, anonymous.text
        assert _stored_extra_auth_params(client, gateway_id) == {"access_type": "offline", "prompt": "consent"}

        updated = client.put(f"/gateways/{gateway_id}", json={"oauth_config": {**UPDATE_CONFIG, "extra_auth_params": {"access_type": "offline", "prompt": "select_account"}}})
        assert updated.status_code == 200, updated.text
        assert _authorize_query(client, gateway_id)["prompt"] == ["select_account"]

        rejected = client.put(f"/gateways/{gateway_id}", json={"oauth_config": {**UPDATE_CONFIG, "extra_auth_params": {"redirect_uri": "https://attacker.example.com/callback"}}})
        assert rejected.status_code == 422, rejected.text
        assert _stored_extra_auth_params(client, gateway_id) == {"access_type": "offline", "prompt": "select_account"}

        cleared = client.put(f"/gateways/{gateway_id}", json={"oauth_config": {**UPDATE_CONFIG, "extra_auth_params": {}}})
        assert cleared.status_code == 200, cleared.text
        query = _authorize_query(client, gateway_id)
        assert "access_type" not in query and "prompt" not in query
    finally:
        client.delete(f"/gateways/{gateway_id}")
