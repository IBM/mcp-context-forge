# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_gateway_header_inheritance.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify gateway header inheritance through real MCP tool calls.
"""

# Standard
from http.server import BaseHTTPRequestHandler
import json
import threading
from typing import Any

# Third-Party
import pytest

# Local
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.e2e import test_candidate_credential_handshake as handshake_fixtures
from tests.live_gateway.plugins._helpers import wait_for_gateway_tools

pytestmark = pytest.mark.e2e
isolated_gateway = handshake_fixtures.isolated_gateway


@pytest.fixture(params=[True, False], ids=["enabled", "disabled"])
def gateway_environment(request, tmp_path):
    """Configure global forwarding independently of each gateway allowlist."""
    return {
        "TMPDIR": str(tmp_path),
        "ENABLE_HEADER_PASSTHROUGH": str(request.param).lower(),
        "PASSTHROUGH_HEADERS_SOURCE": "env",
        "DEFAULT_PASSTHROUGH_HEADERS": '["X-Tenant-Id"]',
        "MCP_CLIENT_CONNECT_MODE": "legacy",
        "GATEWAY_ASYNC_LIFECYCLE_ENABLED": "false",
    }


@pytest.fixture
def upstream():
    """Serve a real MCP tool that reports the headers it receives."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        """Implement the MCP methods needed for registration and invocation."""

        def do_POST(self):  # noqa: N802
            """Handle MCP requests and record tool invocation headers."""
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method = body["method"]
            if "id" not in body:
                self.send_response(202)
                self.end_headers()
                return
            result: dict[str, Any]
            if method == "initialize":
                result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "echo", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "echo", "description": "Echo headers", "inputSchema": {"type": "object", "properties": {}}}]}
            elif method == "tools/call":
                headers = {key.lower(): value for key, value in self.headers.items()}
                calls.append(headers)
                result = {"content": [{"type": "text", "text": json.dumps(headers)}], "isError": False}
            else:
                result = {}
            response = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def do_GET(self):  # noqa: N802
            """Reject optional SSE listening on this stateless upstream."""
            self.send_response(405)
            self.end_headers()

        def log_message(self, format, *args):
            """Suppress fixture HTTP logs."""

    server = handshake_fixtures._DualStackThreadingHTTPServer(("::", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://localhost:{server.server_port}/mcp", calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.parametrize("allowlist", [None, [], ["X-Other"]], ids=["inherited", "empty", "explicit"])
def test_gateway_header_inheritance(isolated_gateway, gateway_environment, upstream, allowlist):
    """Preserve allowlist semantics across cold and warm tool lookups."""
    client, _, _, signing_key = isolated_gateway
    url, calls = upstream
    response = client.post("/gateways", json={"name": "header-echo", "url": url, "transport": "STREAMABLEHTTP", "passthrough_headers": allowlist})
    assert response.status_code in (200, 201), response.text
    tool = wait_for_gateway_tools(client, response.json()["id"])[0]
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool["name"], "arguments": {}}}
    headers = {"X-Tenant-Id": "tenant-1", "X-Other": "other", "X-Unlisted": "blocked"}
    enabled = gateway_environment["ENABLE_HEADER_PASSTHROUGH"] == "true"
    expected = (allowlist if allowlist is not None else ["X-Tenant-Id"]) if enabled else []
    for _ in range(2):
        response = client.post("/rpc", json=payload, headers=headers)
        assert response.status_code == 200, response.text
        assert "error" not in response.json(), response.text
        assert not response.json()["result"].get("isError"), response.text
        forwarded = json.loads(response.json()["result"]["content"][0]["text"])
        for header, value in headers.items():
            assert forwarded.get(header.lower()) == (value if header in expected else None)
    assert len(calls) == 2
    for authorization in ("", "Bearer " + make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, scopes={"permissions": ["tools.read"]})):
        response = client.post("/rpc", json=payload, headers={**headers, "Authorization": authorization})
        if authorization:
            assert response.status_code == 200, response.text
            assert response.json()["error"]["code"] == -32003, response.text
        else:
            assert response.status_code == 401, response.text
        assert len(calls) == 2
