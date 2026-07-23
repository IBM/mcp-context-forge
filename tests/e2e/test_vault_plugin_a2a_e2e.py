# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_vault_plugin_a2a_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live end-to-end test for the Vault plugin across BOTH invocation paths:

- MCP tool path  (``tool_pre_invoke``)  — the pre-existing behavior.
- A2A agent path (``agent_pre_invoke``) — the behavior added for A2A support.

The test boots two local echo backends and a gateway process configured with the Vault
plugin on both hooks, then drives real invocations carrying an ``X-Vault-Tokens`` header.
It asserts, for each path, that the vault token is injected as ``Authorization: Bearer``
for the upstream call AND that the ``X-Vault-Tokens`` header is stripped (never forwarded).

The A2A echo backend reflects the headers it received in its JSON response, so the A2A
assertions inspect exactly what the gateway forwarded upstream. The MCP echo server prints
received headers to its stdout (captured to a log file) for the tool-path assertions.

Gated behind ``@pytest.mark.e2e``. Requires: a free :4444/:8001/:8002, and the project
venv with fastmcp + uvicorn available.
"""

# Standard
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from typing import Optional

# Third-Party
import httpx
import pytest

pytestmark = pytest.mark.e2e

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PYBIN = sys.executable
BASE_URL = "http://localhost:4444"
JWT_SECRET = "my-test-key"  # pragma: allowlist secret
MCP_ACCEPT = "application/json, text/event-stream"
SYSTEM_TAG = "system:echo.local"
TOOL_TOKEN = "tok-tool-e2e"  # pragma: allowlist secret
A2A_TOKEN = "tok-a2a-e2e"  # pragma: allowlist secret

ECHO_MCP_LOG = "/tmp/vault_e2e_pytest_echo_mcp.log"
ECHO_A2A_LOG = "/tmp/vault_e2e_pytest_echo_a2a.log"
GATEWAY_LOG = "/tmp/vault_e2e_pytest_gateway.log"
E2E_DB = "/tmp/vault_e2e_pytest.db"


def _port_free(port: int) -> bool:
    """Return True when nothing is listening on localhost:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait_http(url: str, timeout: float = 45.0, headers: Optional[dict] = None) -> bool:
    """Poll a URL until it responds (any status) or the timeout elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(url, headers=headers or {}, timeout=3.0)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _mint_jwt() -> str:
    """Generate an admin JWT via the gateway helper."""
    out = subprocess.check_output(
        [PYBIN, "-m", "mcpgateway.utils.create_jwt_token", "--username", "admin@example.com", "--exp", "10080", "--secret", JWT_SECRET],
        cwd=REPO,
    )
    return out.decode().strip()


@pytest.fixture(scope="module")
def live_stack():
    """Boot echo backends + gateway with the Vault plugin on both hooks.

    Yields the admin bearer token once everything is reachable. Tears down all
    processes and the throwaway DB afterwards.
    """
    for port in (4444, 8001, 8002):
        if not _port_free(port):
            pytest.skip(f"port {port} is in use; cannot run live vault E2E")

    try:
        os.remove(E2E_DB)
    except FileNotFoundError:
        pass

    procs: list[subprocess.Popen] = []
    logs = [open(p, "w", encoding="utf-8") for p in (ECHO_MCP_LOG, ECHO_A2A_LOG, GATEWAY_LOG)]

    try:
        # Echo backends
        procs.append(subprocess.Popen([PYBIN, "plugins/vault/echo_mcp.py"], cwd=REPO, stdout=logs[0], stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([PYBIN, "plugins/vault/echo_a2a.py"], cwd=REPO, stdout=logs[1], stderr=subprocess.STDOUT))
        if not _wait_http("http://localhost:8002/health"):
            pytest.skip("echo_a2a backend did not become ready")

        # Gateway with E2E env: plugin on both hooks + sensitive header passthrough
        env = dict(os.environ)
        env.update(
            {
                "PLUGINS_ENABLED": "true",
                "PLUGINS_CONFIG_FILE": "plugins/vault/config_vault_e2e.yaml",
                "ENABLE_HEADER_PASSTHROUGH": "true",
                "ENABLE_SENSITIVE_HEADER_PASSTHROUGH": "true",
                "MCPGATEWAY_A2A_ENABLED": "true",
                "JWT_SECRET_KEY": JWT_SECRET,
                "DATABASE_URL": f"sqlite:///{E2E_DB}",
                "AUTH_REQUIRED": "true",
            }
        )
        procs.append(subprocess.Popen([PYBIN, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", "4444"], cwd=REPO, stdout=logs[2], stderr=subprocess.STDOUT, env=env))

        token = _mint_jwt()
        if not _wait_http(f"{BASE_URL}/health", headers={"Authorization": f"Bearer {token}"}):
            pytest.skip(f"gateway did not become ready (see {GATEWAY_LOG})")

        yield token
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        for f in logs:
            try:
                f.close()
            except Exception:
                pass


def test_tool_path_injects_token_and_strips_vault_header(live_stack):
    """MCP tool path (old behavior): Bearer injected upstream, X-Vault-Tokens stripped."""
    token = live_stack
    auth = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        # Register the SSE echo MCP server as a gateway, whitelisting the vault + auth headers
        r = client.post(
            "/gateways",
            headers={**auth, "Content-Type": "application/json"},
            json={"name": "vault_e2e_echo", "url": "http://localhost:8001/sse", "transport": "SSE", "tags": [SYSTEM_TAG], "passthrough_headers": ["X-Vault-Tokens", "Authorization"]},
        )
        assert r.status_code in (200, 201), r.text
        time.sleep(2)

        tools = client.get("/tools", headers=auth).json()
        items = tools.get("items", tools) if isinstance(tools, dict) else tools
        echo_tool = next((t for t in items if "echo" in str(t.get("name", "")).lower()), None)
        assert echo_tool, "echo tool not discovered from registered gateway"

        r = client.post("/servers", headers={**auth, "Content-Type": "application/json"}, json={"server": {"name": "vault_e2e_server", "associated_tools": [echo_tool["id"]]}})
        assert r.status_code in (200, 201), r.text
        server_id = r.json()["id"]

        mcp_path = f"/servers/{server_id}/mcp"
        sess = {"session_id": f"e2e-{int(time.time())}"}
        hdr = {**auth, "Content-Type": "application/json", "Accept": MCP_ACCEPT}
        client.post(mcp_path, params=sess, headers=hdr, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "e2e", "version": "1.0"}}})
        client.post(mcp_path, params=sess, headers=hdr, json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        client.post(
            mcp_path,
            params=sess,
            headers={**hdr, "X-Vault-Tokens": json.dumps({"echo.local": TOOL_TOKEN})},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": echo_tool["name"], "arguments": {"message": "hi"}}},
        )

    time.sleep(1)
    echo_log = open(ECHO_MCP_LOG, encoding="utf-8").read().lower() if os.path.exists(ECHO_MCP_LOG) else ""
    assert f"bearer {TOOL_TOKEN}".lower() in echo_log, "vault token was not injected as Bearer on the tool path"
    assert "x-vault-tokens" not in echo_log, "SECURITY: X-Vault-Tokens leaked to the upstream MCP server"


def test_a2a_path_injects_token_and_strips_vault_header(live_stack):
    """A2A agent path (new behavior): Bearer injected upstream, X-Vault-Tokens stripped."""
    token = live_stack
    auth = {"Authorization": f"Bearer {token}"}
    agent_name = "vault_e2e_agent"
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        r = client.post(
            "/a2a",
            headers={**auth, "Content-Type": "application/json"},
            json={
                "agent": {
                    "name": agent_name,
                    "endpoint_url": "http://localhost:8002/invoke",
                    "agent_type": "custom",  # plain-JSON POST, no jsonrpc envelope
                    "tags": [SYSTEM_TAG],
                    "passthrough_headers": ["X-Vault-Tokens", "Authorization"],
                },
                "visibility": "public",
            },
        )
        assert r.status_code in (200, 201), r.text

        r = client.post(
            f"/a2a/{agent_name}/invoke",
            headers={**auth, "Content-Type": "application/json", "X-Vault-Tokens": json.dumps({"echo.local": A2A_TOKEN})},
            json={"parameters": {"message": "hi"}, "interaction_type": "query"},
        )
        assert r.status_code == 200, r.text
        received = _find_received_headers(r.json())

    assert received is not None, "echo_a2a did not reflect received headers"
    assert str(received.get("authorization", "")).lower() == f"bearer {A2A_TOKEN}".lower(), "vault token was not injected as Bearer on the A2A path"
    assert "x-vault-tokens" not in received, "SECURITY: X-Vault-Tokens leaked to the upstream A2A agent"


def _find_received_headers(obj):
    """Recursively locate the reflected received_headers dict in a response body."""
    if isinstance(obj, dict):
        if "received_headers" in obj and isinstance(obj["received_headers"], dict):
            return obj["received_headers"]
        for v in obj.values():
            found = _find_received_headers(v)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_received_headers(v)
            if found is not None:
                return found
    return None
