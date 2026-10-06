# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_oauth_protected_resource_visibility.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box test for RFC 9728 discovery on private virtual servers.

An unauthenticated MCP request to an OAuth-enabled server gets HTTP 401.
The ``WWW-Authenticate`` header of that response names the Protected Resource Metadata URL.
The tests follow that URL as an MCP client does, for a private server.
"""

# Future
from __future__ import annotations

# Standard
from contextlib import suppress
import re
from typing import Iterator
from urllib.parse import urlsplit
import uuid

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, build_initialize, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

AUTHORIZATION_SERVER = "https://idp.example.com"
CLIENT_SECRET = "prm-live-client-secret"  # pragma: allowlist secret
MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
RESOURCE_METADATA_RE = re.compile(r'resource_metadata="([^"]+)"')


@pytest.fixture(scope="module")
def admin_client() -> Iterator[httpx.Client]:
    """HTTP client that sends a platform admin token."""
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=JWT_SECRET)
    with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=10.0) as client:
        yield client


def _create_private_server(admin_client: httpx.Client, server_fields: dict) -> str:
    """Create a private virtual server and return its ID."""
    payload = {
        "server": {"name": f"prm-visibility-{uuid.uuid4().hex[:8]}", **server_fields},
        "team_id": None,
        "visibility": "private",
    }
    response = admin_client.post("/servers", json=payload)
    assert response.status_code in (200, 201), response.text
    server = response.json()
    assert server["visibility"] == "private"
    return server["id"]


@pytest.fixture(scope="module")
def private_oauth_server(admin_client: httpx.Client) -> Iterator[str]:
    """Private server with OAuth enabled."""
    server_id = _create_private_server(
        admin_client,
        {
            "oauth_enabled": True,
            "oauth_config": {
                "authorization_servers": [AUTHORIZATION_SERVER],
                "client_id": "prm-live-client",
                "client_secret": CLIENT_SECRET,
            },
        },
    )
    yield server_id
    with suppress(httpx.HTTPError):
        admin_client.delete(f"/servers/{server_id}")


@pytest.fixture(scope="module")
def private_server_without_oauth(admin_client: httpx.Client) -> Iterator[str]:
    """Private server without OAuth."""
    server_id = _create_private_server(admin_client, {})
    yield server_id
    with suppress(httpx.HTTPError):
        admin_client.delete(f"/servers/{server_id}")


def _metadata_path(server_id: str) -> str:
    return f"/.well-known/oauth-protected-resource/servers/{server_id}/mcp"


def test_private_oauth_server_serves_advertised_metadata(private_oauth_server: str) -> None:
    """The metadata URL from the 401 response returns RFC 9728 fields and no credential."""
    challenge = httpx.post(f"{BASE_URL}/servers/{private_oauth_server}/mcp", json=build_initialize(), headers=MCP_HEADERS, timeout=10.0)
    assert challenge.status_code == 401, challenge.text
    match = RESOURCE_METADATA_RE.search(challenge.headers.get("www-authenticate", ""))
    assert match, challenge.headers.get("www-authenticate")
    assert urlsplit(match.group(1)).path == _metadata_path(private_oauth_server)

    response = httpx.get(f"{BASE_URL}{_metadata_path(private_oauth_server)}", timeout=10.0)

    assert response.status_code == 200, response.text
    metadata = response.json()
    assert set(metadata) == {"resource", "authorization_servers", "bearer_methods_supported"}
    assert metadata["authorization_servers"] == [AUTHORIZATION_SERVER]
    assert metadata["resource"].endswith(f"/servers/{private_oauth_server}/mcp")
    assert CLIENT_SECRET not in response.text


def test_metadata_does_not_open_private_mcp_endpoint(private_oauth_server: str) -> None:
    """A caller outside the owner scope still gets no access to the private server."""
    outsider = make_test_jwt(f"prm-outsider-{uuid.uuid4().hex[:8]}@example.com", is_admin=False, teams=[], secret=JWT_SECRET)

    response = httpx.post(
        f"{BASE_URL}/servers/{private_oauth_server}/mcp",
        json=build_initialize(),
        headers={**MCP_HEADERS, "Authorization": f"Bearer {outsider}"},
        timeout=10.0,
    )

    assert response.status_code == 403, response.text


def test_private_server_without_oauth_is_indistinguishable_from_missing_server(private_server_without_oauth: str) -> None:
    """A private server without OAuth returns the same 404 as an unknown server ID."""
    hidden = httpx.get(f"{BASE_URL}{_metadata_path(private_server_without_oauth)}", timeout=10.0)
    missing = httpx.get(f"{BASE_URL}{_metadata_path(uuid.uuid4().hex)}", timeout=10.0)

    assert hidden.status_code == 404, hidden.text
    assert (hidden.status_code, hidden.json()) == (missing.status_code, missing.json())
