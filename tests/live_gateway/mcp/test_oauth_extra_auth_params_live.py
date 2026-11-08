# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_oauth_extra_auth_params_live.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box tests for ``oauth_config.extra_auth_params`` (issue #4044).

A running gateway rejects reserved names on create and update, stores valid
parameters, and adds them to the provider authorization redirect.
"""

# Standard
from urllib.parse import parse_qs, urlparse
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]


def _headers() -> dict:
    """Admin bearer headers for the running gateway."""
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=JWT_SECRET)
    return {"Authorization": f"Bearer {token}"}


def _oauth_config(extra_auth_params) -> dict:
    """Authorization-code oauth_config with the given extra parameters."""
    return {
        "grant_type": "authorization_code",
        "client_id": "live-test-client",
        "client_secret": "live-test-secret",  # pragma: allowlist secret
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "redirect_uri": "https://gateway.example.com/oauth/callback",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
        "omit_resource": True,
        "extra_auth_params": extra_auth_params,
    }


@pytest.mark.parametrize("extra", [{"state": "attacker"}, {"Redirect_URI": "https://evil.example.com"}, {"access_type": 1}])
def test_gateway_api_rejects_invalid_extra_auth_params(extra: dict) -> None:
    """Running gateway rejects reserved names and non-string values on POST and PUT."""
    for method, path in (("POST", "/gateways"), ("PUT", "/gateways/nonexistent")):
        payload = {"oauth_config": _oauth_config(extra)}
        if method == "POST":
            payload.update({"name": f"extra-auth-invalid-{uuid.uuid4().hex[:8]}", "url": "https://mcp.example.com/mcp", "auth_type": "oauth"})
        response = httpx.request(method, f"{BASE_URL}{path}", headers=_headers(), json=payload, timeout=10.0)
        assert response.status_code == 422, f"{method} {path}: {response.status_code} {response.text}"
        assert "extra_auth_params" in response.text


def test_authorization_redirect_carries_extra_auth_params() -> None:
    """A stored gateway sends its extra parameters to the provider, next to PKCE and state."""
    payload = {
        "name": f"extra-auth-live-{uuid.uuid4().hex[:8]}",
        "url": "https://mcp.example.com/mcp",
        "transport": "STREAMABLEHTTP",
        "auth_type": "oauth",
        "oauth_config": _oauth_config({"access_type": "offline", "prompt": "consent"}),
    }
    created = httpx.post(f"{BASE_URL}/gateways", headers=_headers(), json=payload, timeout=30.0)
    assert created.status_code in (200, 201), created.text
    gateway_id = created.json()["id"]
    try:
        stored = httpx.get(f"{BASE_URL}/gateways/{gateway_id}", headers=_headers(), timeout=10.0)
        assert stored.status_code == 200, stored.text
        assert stored.json()["oauthConfig"]["extra_auth_params"] == {"access_type": "offline", "prompt": "consent"}

        response = httpx.get(f"{BASE_URL}/oauth/authorize/{gateway_id}", headers=_headers(), follow_redirects=False, timeout=10.0)
        assert response.status_code in (302, 303, 307), response.text
        location = response.headers["location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        query = {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}
        assert query["access_type"] == "offline"
        assert query["prompt"] == "consent"
        assert query["response_type"] == "code"
        assert query["client_id"] == "live-test-client"
        assert query["code_challenge_method"] == "S256"
        assert query["state"]
    finally:
        httpx.delete(f"{BASE_URL}/gateways/{gateway_id}", headers=_headers(), timeout=10.0)
