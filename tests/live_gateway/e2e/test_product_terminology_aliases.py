# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_product_terminology_aliases.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway checks for the product-terminology request aliases (issue #6544).

1. ``POST /servers`` accepts ``virtual_server`` and the record reads back.
2. The list filters accept ``mcp_server_id`` as an alias of ``gateway_id``.
3. Conflicting spellings return 422.
4. Tool, resource and prompt responses carry ``mcpServerId`` next to ``gatewayId``.
"""

# Future
from __future__ import annotations

# Standard
import os
import subprocess
import sys
import uuid

# Third-Party
import httpx
import pytest

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("MCP_CLI_BASE_URL", "http://127.0.0.1:8080").replace("//localhost", "//127.0.0.1")
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
TOKEN_EXPIRY = os.getenv("MCP_CLI_TOKEN_EXPIRY", "60")


def _gateway_reachable() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/health", timeout=5).status_code == 200
    except Exception:
        return False


skip_no_gateway = pytest.mark.skipif(not _gateway_reachable(), reason=f"Gateway not reachable at {BASE_URL}")


@pytest.fixture(scope="module")
def auth_headers() -> dict[str, str]:
    """Build admin bearer headers for the test module."""
    result = subprocess.run(
        [sys.executable, "-m", "mcpgateway.utils.create_jwt_token", "--username", ADMIN_EMAIL, "--exp", TOKEN_EXPIRY, "--secret", JWT_SECRET],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"JWT generation failed: {result.stderr}"
    return {"Authorization": f"Bearer {result.stdout.strip().strip(chr(34))}"}


@skip_no_gateway
@pytest.mark.parametrize("body_key", ["server", "virtual_server"])
def test_create_server_accepts_both_body_keys(auth_headers, body_key):
    """Both body keys create a server that reads back by id."""
    name = f"alias-{body_key}-{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE_URL, headers=auth_headers, timeout=30) as client:
        created = client.post("/servers", json={body_key: {"name": name}, "visibility": "public"})
        assert created.status_code == 201, created.text
        server_id = created.json()["id"]
        try:
            fetched = client.get(f"/servers/{server_id}")
            assert fetched.status_code == 200
            assert fetched.json()["name"] == name
        finally:
            client.delete(f"/servers/{server_id}")


@skip_no_gateway
@pytest.mark.parametrize("path", ["/tools", "/resources", "/prompts"])
def test_list_filter_accepts_mcp_server_id(auth_headers, path):
    """The alias filter matches the original filter and conflicts return 422."""
    unknown = uuid.uuid4().hex
    with httpx.Client(base_url=BASE_URL, headers=auth_headers, timeout=30) as client:
        original = client.get(path, params={"gateway_id": unknown})
        alias = client.get(path, params={"mcp_server_id": unknown})
        assert original.status_code == alias.status_code == 200
        assert alias.json() == original.json() == []

        conflict = client.get(path, params={"gateway_id": unknown, "mcp_server_id": uuid.uuid4().hex})
        assert conflict.status_code == 422


@skip_no_gateway
def test_create_server_rejects_conflicting_body_keys(auth_headers):
    """Different values under both body keys return 422."""
    with httpx.Client(base_url=BASE_URL, headers=auth_headers, timeout=30) as client:
        response = client.post("/servers", json={"server": {"name": "a"}, "virtual_server": {"name": "b"}})
        assert response.status_code == 422


def _create_tool(client: httpx.Client) -> dict:
    body = {"tool": {"name": f"alias-probe-{uuid.uuid4().hex[:8]}", "url": "https://example.com/probe", "integration_type": "REST", "request_type": "GET"}, "visibility": "public"}
    response = client.post("/tools", json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


def _create_resource(client: httpx.Client) -> dict:
    uid = uuid.uuid4().hex[:8]
    body = {"resource": {"uri": f"test://alias-probe/{uid}", "name": f"alias-probe-{uid}", "mimeType": "text/plain", "content": "probe"}, "visibility": "public"}
    response = client.post("/resources", json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


def _create_prompt(client: httpx.Client) -> dict:
    body = {"prompt": {"name": f"alias-probe-{uuid.uuid4().hex[:8]}", "template": "hello", "arguments": []}, "visibility": "public"}
    response = client.post("/prompts", json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


# entity -> (create helper, list path, record route that returns the Read model, or None when only the create response does)
_ENTITIES = {
    "tools": (_create_tool, "/v1/tools", "/v1/tools/{id}"),
    "resources": (_create_resource, "/v1/resources", "/v1/resources/{id}/info"),
    "prompts": (_create_prompt, "/v1/prompts", None),
}


def _assert_alias(record: dict) -> None:
    assert "mcpServerId" in record, f"mcpServerId missing from {sorted(record)}"
    assert record["mcpServerId"] == record["gatewayId"]


@skip_no_gateway
@pytest.mark.parametrize("entity", sorted(_ENTITIES))
def test_responses_carry_mcp_server_id(auth_headers, entity):
    """A created record repeats gatewayId under mcpServerId in the create response, the list, and the record route."""
    create, path, record_route = _ENTITIES[entity]
    with httpx.Client(base_url=BASE_URL, headers=auth_headers, timeout=30) as client:
        created = create(client)
        record_id = str(created["id"])
        try:
            _assert_alias(created)

            listing = client.get(path, params={"limit": 0})
            assert listing.status_code == 200, listing.text
            records = listing.json()
            assert isinstance(records, list), f"{path}?limit=0 should return an unpaginated list, got {type(records).__name__}"
            assert records, f"{path} returned no records after creating one"
            _assert_alias(next(record for record in records if str(record["id"]) == record_id))

            if record_route:
                single = client.get(record_route.format(id=record_id))
                assert single.status_code == 200, single.text
                _assert_alias(single.json())
        finally:
            client.delete(f"{path}/{record_id}")
