# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_oauth_redirect_validation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box validation for gateway post-OAuth redirect configuration.
"""

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "POST",
            "/gateways",
            {
                "name": "invalid-oauth-redirect",
                "url": "https://mcp.example.com",
                "oauth_config": {"redirect_uri_after_oauth": "/oauth-complete"},
            },
        ),
        (
            "PUT",
            "/gateways/nonexistent",
            {"oauth_config": {"redirect_uri_after_oauth": "/oauth-complete"}},
        ),
    ],
)
def test_gateway_api_rejects_relative_post_oauth_redirect(method: str, path: str, payload: dict) -> None:
    """Running gateway rejects relative redirect targets on POST and PUT."""
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=JWT_SECRET)
    response = httpx.request(
        method,
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=10.0,
    )

    assert response.status_code == 422, response.text
    assert "redirect_uri_after_oauth" in response.text
