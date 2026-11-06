# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_tool_upstream_auth_error.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify upstream authorization details through a live gateway.

Set MCP_CLI_BASE_URL and JWT_SECRET_KEY for the gateway under test.
Set MCP_AUTH_UPSTREAM_HOST=host.docker.internal for a containerized gateway.
"""

# Standard
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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import uvicorn

# Local
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]
CHALLENGE = 'Bearer error="invalid_token", resource_metadata="https://upstream.example/metadata", scope="openid email"'


@pytest.fixture(scope="module")
def auth_upstream() -> Iterator[tuple[httpx.Client, str, dict]]:
    """Register an upstream that rejects tool calls after successful discovery."""
    name = f"auth{uuid.uuid4().hex[:12]}"
    upstream = MCPServer(name)
    rejection = {"status": 401, "challenge": CHALLENGE}

    @upstream.tool()
    def protected_tool() -> str:
        """Return a protected result."""
        return "protected"

    app = upstream.streamable_http_app(stateless_http=True, json_response=True)

    async def reject_tool_call(request: Request, call_next):
        """Reject tool execution while allowing MCP discovery and initialization."""
        if request.method == "POST":
            body = await request.json()
            if body.get("method") == "tools/call":
                headers = {"WWW-Authenticate": rejection["challenge"]} if rejection["challenge"] else {}
                return Response(status_code=rejection["status"], headers=headers)
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=reject_tool_call)

    host = os.getenv("MCP_AUTH_UPSTREAM_HOST", "127.0.0.1")
    bind_host = "127.0.0.1" if host in {"127.0.0.1", "localhost"} else "0.0.0.0"  # nosec B104 - Test upstream for a containerized gateway.
    with socket.socket() as listener:
        listener.bind((bind_host, 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        gateway_id = None
        token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.started, "Authorization upstream failed to start"
            with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
                try:
                    response = client.post("/gateways", json={"name": name, "url": f"http://{host}:{port}/mcp", "transport": "STREAMABLEHTTP"})
                    response.raise_for_status()
                    gateway_id = response.json()["id"]
                    response = client.get("/tools", params={"gateway_id": gateway_id})
                    response.raise_for_status()
                    tools = [tool for tool in response.json() if tool.get("gatewayId") == gateway_id]
                    assert len(tools) == 1, tools
                    yield client, tools[0]["name"], rejection
                finally:
                    if gateway_id:
                        client.delete(f"/gateways/{gateway_id}").raise_for_status()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "Authorization upstream failed to stop"


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("challenge", [None, CHALLENGE])
def test_rpc_preserves_upstream_auth_error(auth_upstream: tuple[httpx.Client, str, dict], status: int, challenge: str | None) -> None:
    """Expose the upstream status and challenge without changing the outer HTTP status."""
    client, tool_name, rejection = auth_upstream
    rejection.update(status=status, challenge=challenge)
    response = client.post("/rpc", json={"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": tool_name, "arguments": {}}})
    assert response.status_code == 200
    data: dict[str, int | str] = {"status": status}
    if challenge:
        data["www_authenticate"] = challenge
    assert response.json() == {"jsonrpc": "2.0", "id": 9, "error": {"code": -32000, "message": "Upstream tool authorization failed", "data": data}}


def test_rpc_unauthenticated_call_hides_upstream_auth_details(auth_upstream: tuple[httpx.Client, str, dict]) -> None:
    """Reject unauthenticated callers before invoking the protected upstream."""
    client, tool_name, _rejection = auth_upstream
    with httpx.Client(base_url=str(client.base_url), timeout=30) as anonymous:
        response = anonymous.post("/rpc", json={"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": tool_name}})
    assert response.status_code == 401
    assert "upstream.example" not in response.text
    assert "upstream.example" not in response.headers.get("www-authenticate", "")
