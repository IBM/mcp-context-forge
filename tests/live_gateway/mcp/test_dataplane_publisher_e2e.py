# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_dataplane_publisher_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box publisher contract test: control-plane API -> Redis -> Rust data plane.

Run against dedicated local services with DATAPLANE_TEST_CONTROL_URL,
DATAPLANE_TEST_URL, DATAPLANE_TEST_REDIS_URL, DATAPLANE_TEST_JWT_SECRET and
DATAPLANE_TEST_SIGNING_KEY set (path to a test RSA private key).
The control plane must enable DATAPLANE_PUBLISHER with a short publish interval;
the data plane must use the same Redis, trust the test key through JWKS, permit plaintext upstreams,
and disable its config cache. Both services must reach this test's localhost.
For a direct data-plane listener, DATAPLANE_TEST_URL includes /contextforge-rs.
The test starts its own SDK upstreams and removes all API objects it creates.
"""

# Standard
import json
import multiprocessing
import os
from pathlib import Path
import socket
import time
from contextlib import ExitStack
from typing import Any
from uuid import uuid4

# Third-Party
import httpx
import msgpack
import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP
from redis import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# First-Party
from tests.helpers.auth import make_test_jwt

_REQUIRED_ENV = ("DATAPLANE_TEST_CONTROL_URL", "DATAPLANE_TEST_URL", "DATAPLANE_TEST_REDIS_URL", "DATAPLANE_TEST_JWT_SECRET", "DATAPLANE_TEST_SIGNING_KEY")
pytestmark = [pytest.mark.e2e, pytest.mark.skipif(not all(os.getenv(key) for key in _REQUIRED_ENV), reason="Requires dedicated control-plane, Redis and data-plane services")]


def _serve_upstream(port: int, marker: str) -> None:
    """Expose exact SDK names that fail if the router reconstructs or slugifies them."""
    server = FastMCP("Publisher contract", host="127.0.0.1", port=port, stateless_http=True, json_response=True)

    @server.tool(name="Admin.Tools_List")
    def list_admin_tools() -> str:
        """Return the upstream identity and exact tool name."""
        return f"{marker}:Admin.Tools_List"

    @server.prompt(name="Prompt.Original")
    def original_prompt() -> str:
        """Return the upstream identity and exact prompt name."""
        return f"{marker}:Prompt.Original"

    @server.resource("resource://exact/path")
    def original_resource() -> str:
        """Return the upstream identity for an exact resource URI."""
        return f"{marker}:resource://exact/path"

    app = server.streamable_http_app()

    async def unsupported_discovery(request, call_next):
        """Return method-not-found for discovery so modern clients negotiate legacy MCP."""
        # The pinned SDK predates server/discover and incorrectly responds with
        # invalid-params. A method-not-found response permits the consumer's
        # existing Auto lifecycle to negotiate the SDK's supported version.
        if request.method == "POST":
            payload = await request.json()
            if payload.get("method") == "server/discover":
                return JSONResponse({"jsonrpc": "2.0", "id": payload["id"], "error": {"code": -32601, "message": "Method not found"}})
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=unsupported_discovery)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


@pytest.fixture
def upstream_urls():
    """Start two independent SDK servers, terminating only these test processes."""
    processes = []
    urls = []
    try:
        for marker in ("one", "two"):
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            process = multiprocessing.get_context("spawn").Process(target=_serve_upstream, args=(port, marker))
            process.start()
            processes.append(process)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                assert process.is_alive(), "SDK upstream exited before startup"
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                pytest.fail("SDK upstream did not start")
            urls.append(f"http://127.0.0.1:{port}/mcp")
        yield urls
    finally:
        for process in processes:
            process.terminate()
            process.join(timeout=10)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)


def _api(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    """Issue a control-plane request and retain the response body on failure."""
    response = client.request(method, path, **kwargs)
    assert response.is_success, f"{method} {path}: {response.status_code} {response.text}"
    return response.json()


def _rpc(client: httpx.Client, server_id: str, method: str, params: dict[str, Any]) -> httpx.Response:
    """Send a modern stateless MCP request with matching parameter headers."""
    headers = {"Mcp-Protocol-Version": "2026-07-28", "Mcp-Method": method, "Mcp-Name": str(params.get("name", params.get("uri", "")))}
    return client.post(
        f"/servers/{server_id}/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": {
                **params,
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientInfo": {"name": "publisher-contract", "version": "1"},
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        },
    )


def _result(response: httpx.Response) -> dict[str, Any]:
    """Read the JSON-RPC result from either JSON or an SSE response."""
    assert response.is_success, response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        messages = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
        payload = next(message for message in messages if message.get("id") == 1)
    else:
        payload = response.json()
    assert "error" not in payload, payload
    result = payload["result"]
    assert isinstance(result, dict), result
    return result


def test_published_routes_execute_exact_names_and_reject_collisions(upstream_urls):
    """Exercise real discovery, publication, consumer decoding, routing and collision fallback."""
    secret = os.environ["DATAPLANE_TEST_JWT_SECRET"]
    email = os.getenv("DATAPLANE_TEST_ADMIN_EMAIL", "admin@example.com")
    admin_token = make_test_jwt(email, is_admin=True, teams=None, secret=secret)
    suffix = uuid4().hex[:12]
    with ExitStack() as cleanup:
        control = cleanup.enter_context(httpx.Client(base_url=os.environ["DATAPLANE_TEST_CONTROL_URL"], headers={"Authorization": f"Bearer {admin_token}"}, timeout=30, follow_redirects=True))
        redis = Redis.from_url(os.environ["DATAPLANE_TEST_REDIS_URL"])
        cleanup.callback(redis.close)
        gateways = []
        for index, url in enumerate(upstream_urls):
            team = _api(control, "POST", "/teams/", json={"name": f"publisher-{suffix}-{index}"})
            cleanup.callback(control.delete, f"/teams/{team['id']}")
            gateway = _api(control, "POST", "/gateways", json={"name": f"shared-{suffix}", "url": url, "transport": "STREAMABLEHTTP", "team_id": team["id"], "visibility": "team"})
            gateways.append(gateway["id"])
            cleanup.callback(control.delete, f"/gateways/{gateway['id']}")

        tools = _api(control, "GET", "/tools")
        tools_by_gateway = {gateway: [tool for tool in tools if tool.get("gatewayId") == gateway] for gateway in gateways}
        assert all(len(items) == 1 for items in tools_by_gateway.values()), tools_by_gateway
        resources = [item for item in _api(control, "GET", "/resources") if item.get("gatewayId") == gateways[0]]
        prompts = [item for item in _api(control, "GET", "/prompts") if item.get("gatewayId") == gateways[0]]
        assert len(resources) == len(prompts) == 1
        first_tool = tools_by_gateway[gateways[0]][0]
        server = _api(
            control,
            "POST",
            "/servers",
            json={"server": {"name": f"publisher-{suffix}", "associated_tools": [first_tool["id"]], "associated_resources": [resources[0]["id"]], "associated_prompts": [prompts[0]["id"]]}},
        )
        server_id = server["id"]
        cleanup.callback(control.delete, f"/servers/{server_id}")

        # Read the actual publisher output; do not manufacture a consumer config.
        deadline = time.monotonic() + 30
        subject = None
        while time.monotonic() < deadline and subject is None:
            for key in redis.scan_iter():
                try:
                    decoded_key = msgpack.unpackb(key, raw=False)
                except (ValueError, msgpack.ExtraData):
                    continue
                if not isinstance(decoded_key, list) or len(decoded_key) != 2 or decoded_key[0] != "UserConfig":
                    continue
                value = redis.get(key)
                if value and server_id in msgpack.unpackb(value, raw=False)["virtual_hosts"]:
                    subject = decoded_key[1]
                    break
            if subject is None:
                time.sleep(0.2)
        assert subject is not None, "Publisher did not publish the server"
        token = make_test_jwt(
            email, is_admin=True, teams=None, secret=Path(os.environ["DATAPLANE_TEST_SIGNING_KEY"]).read_text(), algorithm="RS256", extra_payload={"sub": subject, "tenant_id": "publisher-contract"}
        )
        data_plane = cleanup.enter_context(
            httpx.Client(base_url=os.environ["DATAPLANE_TEST_URL"], headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}, timeout=20)
        )

        tool_result = _result(_rpc(data_plane, server_id, "tools/call", {"name": first_tool["name"], "arguments": {}}))
        assert tool_result.get("isError") is not True, tool_result
        assert tool_result["content"][0]["text"] == "one:Admin.Tools_List"
        prompt_result = _result(_rpc(data_plane, server_id, "prompts/get", {"name": prompts[0]["name"], "arguments": {}}))
        assert prompt_result["messages"][0]["content"]["text"] == "one:Prompt.Original"
        resource_result = _result(_rpc(data_plane, server_id, "resources/read", {"uri": resources[0]["uri"]}))
        assert resource_result["contents"][0]["text"] == "one:resource://exact/path"

        # An unassociated upstream tool name is not accepted as a route.
        unknown = _rpc(data_plane, server_id, "tools/call", {"name": "Admin.Tools_List", "arguments": {}})
        assert unknown.status_code in (200, 400) and unknown.json().get("error", {}).get("code") == -32602, unknown.text
        anonymous = cleanup.enter_context(httpx.Client(base_url=os.environ["DATAPLANE_TEST_URL"], timeout=10))
        unauthorized = _rpc(anonymous, server_id, "tools/call", {"name": first_tool["name"], "arguments": {}})
        assert unauthorized.status_code == 401

        second_tool = tools_by_gateway[gateways[1]][0]
        assert first_tool["name"] == second_tool["name"]
        _api(control, "PUT", f"/servers/{server_id}", json={"associated_tools": [first_tool["id"], second_tool["id"]]})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = _rpc(data_plane, server_id, "tools/call", {"name": first_tool["name"], "arguments": {}})
            if response.status_code == 404:
                break
            time.sleep(0.2)
        assert response.status_code == 404, "Ambiguous virtual host remained published"
        assert _api(control, "GET", f"/servers/{server_id}")["id"] == server_id
