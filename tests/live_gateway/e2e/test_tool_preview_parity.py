# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_tool_preview_parity.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box preview/live resolution checks for duplicate upstream tool names.
"""

# Future
from __future__ import annotations

# Standard
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid

# Third-Party
import httpx
from mcp.server.mcpserver import MCPServer
import pytest
import uvicorn

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]


@contextmanager
def _echo_upstream(label):
    """Serve one real MCP echo tool and retain its execution history.

    Args:
        label: Distinct upstream identity returned by the tool.

    Yields:
        The MCP URL and a list of received messages.
    """
    calls = []
    mcp = MCPServer(label)

    @mcp.tool()
    async def echo(message: str) -> dict:
        """Echo a message together with this source's identity."""
        calls.append(message)
        return {"source": label, "message": message}

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(mcp.streamable_http_app(host="127.0.0.1", stateless_http=True, json_response=True), log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, f"Echo upstream {label} failed to start"
        yield f"http://127.0.0.1:{port}/mcp/", calls
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        assert not worker.is_alive(), f"Echo upstream {label} failed to stop"


@pytest.fixture
def isolated_preview_gateway(tmp_path):
    """Run the current gateway code with a private database and preview enabled.

    Yields:
        An authenticated HTTP client for the isolated gateway.
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(_REPO_ROOT),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "AUTH_REQUIRED": "true",
        "EMAIL_AUTH_ENABLED": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        "MCPGATEWAY_TOOL_PREVIEW_ENABLED": "true",
        "SSRF_ALLOW_LOCALHOST": "true",
        "GATEWAY_TOOL_NAME_SEPARATOR": "-",
        "RATE_LIMITING_ENABLED": "false",
        "PLUGINS_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
    }
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    log_path = tmp_path / "gateway.log"
    with log_path.open("w") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=make_auth_headers(token), timeout=30, trust_env=False) as client:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()[-5000:]
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-5000:]}")
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _discover_echo(client, gateway_id):
    """Wait for an upstream's echo tool to appear in the gateway catalog.

    Args:
        client: Authenticated client for the gateway.
        gateway_id: Registered source identifier.

    Returns:
        The discovered tool, including its qualified name.
    """
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        response = client.get("/v1/tools", params={"gateway_id": gateway_id, "limit": 100})
        assert response.status_code == 200, response.text
        payload = response.json()
        tools = payload if isinstance(payload, list) else payload["tools"]
        if tools:
            assert len(tools) == 1, payload
            tool = tools[0]
            assert tool["originalName"] == "echo", tool
            return tool
        time.sleep(0.1)
    pytest.fail(f"Echo discovery timed out for gateway {gateway_id}")


def test_scoped_preview_and_live_resolve_same_duplicate_named_tool(isolated_preview_gateway):
    """Qualified names select the same source in Preview and Live without preview execution."""
    client = isolated_preview_gateway
    run_id = uuid.uuid4().hex[:10]
    sources = []
    with ExitStack() as cleanup:
        for index in range(2):
            name = f"preview-parity-{run_id}-{index}"
            url, calls = cleanup.enter_context(_echo_upstream(name))
            registered = client.post("/v1/gateways", json={"name": name, "url": url, "transport": "STREAMABLEHTTP", "visibility": "public"})
            assert registered.status_code in (200, 201, 202), registered.text
            gateway_id = registered.json()["id"]
            cleanup.callback(client.delete, f"/v1/gateways/{gateway_id}")
            tool = _discover_echo(client, gateway_id)
            sources.append({"name": name, "tool": tool, "calls": calls})

        assert sources[0]["tool"]["name"] != sources[1]["tool"]["name"]
        created = client.post(
            "/v1/servers",
            json={"server": {"name": f"preview-parity-{run_id}", "associated_tools": [source["tool"]["id"] for source in sources]}, "visibility": "public"},
        )
        assert created.status_code in (200, 201), created.text
        server_id = created.json()["id"]
        cleanup.callback(client.delete, f"/v1/servers/{server_id}")

        ambiguous = client.post("/v1/tools/preview/echo", json={"server_id": server_id, "arguments": {"message": "hello"}})
        assert ambiguous.status_code == 400, ambiguous.text
        assert "qualified tool name" in ambiguous.json()["detail"].lower()
        assert [len(source["calls"]) for source in sources] == [0, 0]

        for index, source in enumerate(sources):
            before = [len(peer["calls"]) for peer in sources]
            arguments = {"message": f"hello-{index}"}
            preview = client.post(f"/v1/tools/preview/{source['tool']['name']}", json={"server_id": server_id, "arguments": arguments})
            assert preview.status_code == 200, preview.text
            assert preview.json()["validated"] is True
            assert preview.json()["target"]["gatewayName"] == source["name"]
            assert [len(peer["calls"]) for peer in sources] == before

            live = client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "id": index + 1, "method": "tools/call", "params": {"name": source["tool"]["name"], "server_id": server_id, "arguments": arguments}},
            )
            assert live.status_code == 200, live.text
            payload = live.json()
            assert "error" not in payload, payload
            result = payload["result"]
            assert not result.get("isError", False), result
            text = "".join(block["text"] for block in result["content"] if block["type"] == "text")
            assert json.loads(text) == {"source": source["name"], **arguments}
            expected = before.copy()
            expected[index] += 1
            assert [len(peer["calls"]) for peer in sources] == expected
            assert source["calls"] == [arguments["message"]]
