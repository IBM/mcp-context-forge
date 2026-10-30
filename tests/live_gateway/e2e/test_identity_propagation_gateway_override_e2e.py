# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_identity_propagation_gateway_override_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box check that a per-gateway ``identity_propagation`` override wins over
the global setting on the MCP tool path.

Starts a private gateway subprocess with identity propagation enabled globally,
registers an upstream MCP server that records every request header, and calls a
tool through a virtual server. A gateway set to ``enabled: false`` must receive
no user identity headers; a gateway set to ``enabled: true`` must receive them.
"""

from __future__ import annotations

# Standard
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time

# Third-Party
import httpx
from mcp.server.mcpserver import MCPServer
import pytest
import uvicorn

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.plugins._helpers import create_virtual_server, initialize_session, mcp_headers

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]
_IDENTITY_PREFIX = "x-forwarded-user"


class _HeaderRecorder:
    """ASGI wrapper that records the headers of every HTTP request."""

    def __init__(self, app, sink: list):
        """Wrap ``app`` and append each request's header dict to ``sink``."""
        self._app = app
        self._sink = sink

    async def __call__(self, scope, receive, send):
        """Record request headers, then delegate to the wrapped app."""
        if scope["type"] == "http":
            self._sink.append({k.decode().lower(): v.decode() for k, v in scope["headers"]})
        await self._app(scope, receive, send)


@pytest.fixture
def recording_upstream():
    """Serve an MCP upstream with one tool and record all inbound headers.

    Yields:
        A tuple of the upstream URL and the list of recorded header dicts.
    """
    recorded: list[dict[str, str]] = []
    app = MCPServer("identity-probe")

    @app.tool(name="whoami")
    def whoami() -> str:
        """Return a fixed marker."""
        return "ok"

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    asgi = _HeaderRecorder(app.streamable_http_app(host="127.0.0.1", stateless_http=True, json_response=True), recorded)
    server = uvicorn.Server(uvicorn.Config(asgi, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "Recording upstream failed to start"
    try:
        yield f"http://127.0.0.1:{port}/mcp/", recorded
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


@pytest.fixture
def isolated_gateway(tmp_path):
    """Start a private gateway subprocess with identity propagation enabled globally.

    Yields:
        A tuple of an authenticated ``httpx.Client``, the admin bearer token and the gateway database path.
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), *[str(Path(path).resolve()) for path in os.getenv("PYTHONPATH", "").split(os.pathsep) if path]]),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "AUTH_REQUIRED": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        "SSRF_ALLOW_LOCALHOST": "true",
        "SSRF_ALLOW_PRIVATE_NETWORKS": "true",
        "PLUGINS_ENABLED": "false",
        "IDENTITY_PROPAGATION_ENABLED": "true",
        "IDENTITY_PROPAGATION_MODE": "both",
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
                yield client, token, tmp_path / "gateway.db"
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _set_gateway_override(db_path, gateway_id, identity_propagation):
    """Store the per-gateway override directly, because the gateway API does not persist it.

    Args:
        db_path: SQLite file of the isolated gateway.
        gateway_id: Gateway identifier.
        identity_propagation: Per-gateway override dict.
    """
    with sqlite3.connect(db_path) as conn:
        updated = conn.execute("UPDATE gateways SET identity_propagation = ? WHERE id = ?", (json.dumps(identity_propagation), gateway_id)).rowcount
    assert updated == 1, f"Gateway {gateway_id} not found in {db_path}"


def _call_whoami(client, token, db_path, upstream_url, gateway_name, identity_propagation):
    """Register the upstream, apply the override, and call its tool via MCP.

    Args:
        client: Authenticated client for the isolated gateway.
        token: Bearer token for the gateway's MCP transport.
        db_path: SQLite file of the isolated gateway.
        upstream_url: URL of the recording upstream.
        gateway_name: Unique gateway name.
        identity_propagation: Per-gateway override dict.
    """
    response = client.post("/gateways", json={"name": gateway_name, "url": upstream_url, "transport": "STREAMABLEHTTP"})
    assert response.status_code in (200, 201), response.text
    gateway_id = response.json()["id"]
    _set_gateway_override(db_path, gateway_id, identity_propagation)
    server_id = None
    try:
        tools = [t for t in client.get("/tools", params={"limit": 0}).json() if t.get("gatewayId") == gateway_id or t.get("gateway_id") == gateway_id]
        assert tools, "Gateway registration discovered no tools"
        server_id = create_virtual_server(client, name=f"{gateway_name}_server", tool_ids=[tools[0]["id"]])
        session_id = initialize_session(client, server_id=server_id, token=token)
        call = client.post(
            f"/servers/{server_id}/mcp/",
            headers=mcp_headers(token, session_id=session_id),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tools[0]["name"], "arguments": {}}},
        )
        assert call.status_code == 200, call.text
        assert "result" in call.json(), call.text
    finally:
        if server_id:
            client.delete(f"/servers/{server_id}")
        client.delete(f"/gateways/{gateway_id}")


def _tool_call_headers(recorded):
    """Return the identity-bearing header names seen by the upstream.

    Args:
        recorded: Header dicts captured by the upstream.
    """
    return {name for headers in recorded for name in headers if name.startswith(_IDENTITY_PREFIX)}


def test_gateway_override_disabled_sends_no_identity_headers(isolated_gateway, recording_upstream):
    """A gateway with ``enabled: false`` receives no identity headers although the global setting is on."""
    client, token, db_path = isolated_gateway
    upstream_url, recorded = recording_upstream

    _call_whoami(client, token, db_path, upstream_url, f"idp_off_{secrets.token_hex(4)}", {"enabled": False})

    assert recorded, "Upstream saw no requests"
    assert _tool_call_headers(recorded) == set(), recorded
    assert "admin@example.com" not in str(recorded)


def test_gateway_override_enabled_sends_identity_headers(isolated_gateway, recording_upstream):
    """A gateway with ``enabled: true`` receives identity headers, proving the probe can observe them."""
    client, token, db_path = isolated_gateway
    upstream_url, recorded = recording_upstream

    _call_whoami(client, token, db_path, upstream_url, f"idp_on_{secrets.token_hex(4)}", {"enabled": True})

    assert any(name.startswith(_IDENTITY_PREFIX) for name in _tool_call_headers(recorded)), recorded
