# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_binary_resource_read.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify binary resource reads through a live gateway and a real MCP upstream.

Set MCP_CLI_BASE_URL and JWT_SECRET_KEY for the gateway under test.
Set MCP_BINARY_UPSTREAM_HOST=host.docker.internal for a gateway running in Docker.
"""

# Standard
import base64
from collections.abc import Iterator
import os
import socket
import threading
import time
import uuid

# Third-Party
import httpx
from mcp.server.mcpserver import MCPServer
import pytest
import uvicorn

# Local
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]
BINARY_CONTENT = b"\x00\xffbinary"


@pytest.fixture(scope="module")
def binary_resources() -> Iterator[tuple[httpx.Client, dict[str, str], str]]:
    """Register a real binary upstream and clean up its gateway and listener."""
    name = f"binary{uuid.uuid4().hex[:12]}"
    uri = f"test://{name}"
    upstream = MCPServer(name)

    @upstream.resource(f"{uri}/nonempty", mime_type="application/octet-stream")
    def nonempty() -> bytes:
        """Return bytes that cannot be represented as UTF-8 text."""
        return BINARY_CONTENT

    @upstream.resource(f"{uri}/empty", mime_type="application/octet-stream")
    def empty() -> bytes:
        """Return an empty binary payload."""
        return b""

    host = os.getenv("MCP_BINARY_UPSTREAM_HOST", "127.0.0.1")
    bind_host = "127.0.0.1" if host in {"127.0.0.1", "localhost"} else "0.0.0.0"  # nosec B104 - Test upstream for a containerized gateway.
    with socket.socket() as listener:
        listener.bind((bind_host, 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(upstream.streamable_http_app(host=bind_host, stateless_http=True, json_response=True), log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        gateway_id = None
        token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.started, "Binary upstream failed to start"
            with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
                try:
                    response = client.post("/gateways", json={"name": name, "url": f"http://{host}:{port}/mcp/", "transport": "STREAMABLEHTTP"})
                    response.raise_for_status()
                    gateway_id = response.json()["id"]
                    response = client.get("/resources", params={"gateway_id": gateway_id})
                    response.raise_for_status()
                    resources = response.json()
                    by_uri = {resource["uri"]: resource["id"] for resource in resources if resource.get("gatewayId") == gateway_id}
                    assert set(by_uri) == {f"{uri}/empty", f"{uri}/nonempty"}, resources
                    yield client, by_uri, uri
                finally:
                    if gateway_id:
                        response = client.delete(f"/gateways/{gateway_id}")
                        response.raise_for_status()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "Binary upstream failed to stop"


@pytest.mark.parametrize("resource_name,expected", [("empty", b""), ("nonempty", BINARY_CONTENT)])
def test_rest_gateway_binary_resource(binary_resources: tuple[httpx.Client, dict[str, str], str], resource_name: str, expected: bytes) -> None:
    """REST reads preserve empty and non-empty upstream binary payloads."""
    client, by_uri, root_uri = binary_resources
    uri = f"{root_uri}/{resource_name}"
    response = client.get(f"/resources/{by_uri[uri]}")

    response.raise_for_status()
    content = response.json()
    assert content["uri"] == uri
    assert content["mimeType"] == "application/octet-stream"
    assert content["blob"] == base64.b64encode(expected).decode("ascii")
    assert "text" not in content
