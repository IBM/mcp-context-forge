# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_product_terminology_aliases.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway checks for the product-terminology request aliases (issue #6544).

1. ``POST /servers`` accepts ``virtual_server`` and the record reads back.
2. The list filters accept ``mcp_server_id`` as an alias of ``gateway_id``.
3. Conflicting spellings return 422.
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
