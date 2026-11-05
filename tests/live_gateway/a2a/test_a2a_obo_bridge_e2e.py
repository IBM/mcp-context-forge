# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_obo_bridge_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box validation of the authenticated A2A OBO bearer bridge.
"""

# Standard
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs

# Third-Party
from cpex.framework import AgentPreInvokePayload, AgentPreInvokeResult, HttpHeaderPayload, Plugin, PluginConfig, PluginContext, PluginViolation
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]
_AGENT_NAME = "obo-bridge-e2e-agent"


class MockOBOPlugin(Plugin):
    """Exchange the plugin bearer through the test token endpoint."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the test plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._token_url = os.environ["TEST_OBO_TOKEN_URL"]

    async def agent_pre_invoke(self, payload: AgentPreInvokePayload, context: PluginContext) -> AgentPreInvokeResult:
        """Replace the authenticated caller bearer with the mock exchanged bearer.

        Args:
            payload: Agent invocation payload.
            context: Plugin context.

        Returns:
            Modified payload or a blocking violation.
        """
        del context
        headers = dict(payload.headers.root) if payload.headers else {}
        authorization = next((value for name, value in headers.items() if name.lower() == "authorization"), "")
        scheme, _, assertion = authorization.partition(" ")
        if scheme.lower() != "bearer" or not assertion:
            return AgentPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(code="TEST_OBO_NO_TOKEN", reason="Missing bearer", description="The authenticated bearer did not reach the plugin."),
            )
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(self._token_url, data={"assertion": assertion}, timeout=5)
            response.raise_for_status()
            exchanged_token = response.json()["access_token"]
        headers = {name: value for name, value in headers.items() if name.lower() != "authorization"}
        headers["Authorization"] = f"Bearer {exchanged_token}"
        return AgentPreInvokeResult(modified_payload=payload.model_copy(update={"headers": HttpHeaderPayload(root=headers)}))


class _TokenHandler(BaseHTTPRequestHandler):
    """Capture the OBO assertion and return a deterministic token."""

    assertions: list[str] = []

    def do_POST(self) -> None:
        """Capture one token exchange request."""
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode())
        type(self).assertions.extend(form.get("assertion", []))
        body = b'{"access_token":"exchanged-token"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Keep the mock token endpoint quiet."""


class _AgentHandler(BaseHTTPRequestHandler):
    """Capture downstream authorization and return an A2A response."""

    authorizations: list[str] = []

    def do_POST(self) -> None:
        """Capture one downstream request."""
        authorization = self.headers.get("Authorization")
        if authorization:
            type(self).authorizations.append(authorization)
        body = b'{"response":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Keep the mock agent quiet."""


def _free_port() -> int:
    """Return an available loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _start_server(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start a loopback HTTP server.

    Args:
        handler: Request handler class.

    Returns:
        Server and worker thread.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


def test_authenticated_bearer_is_exchanged_before_a2a_dispatch(tmp_path: Path) -> None:
    """Send one bearer and prove that the downstream agent receives only its replacement."""
    _TokenHandler.assertions = []
    _AgentHandler.authorizations = []
    token_server, token_worker = _start_server(_TokenHandler)
    agent_server, agent_worker = _start_server(_AgentHandler)
    gateway_port = _free_port()
    signing_key = secrets.token_urlsafe(48)
    plugin_config = tmp_path / "plugins.yaml"
    plugin_config.write_text("""
plugins:
  - name: MockOBO
    kind: tests.live_gateway.a2a.test_a2a_obo_bridge_e2e.MockOBOPlugin
    hooks: [agent_pre_invoke]
    mode: sequential
    on_error: fail
    priority: 5
""".strip())
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
        "MCPGATEWAY_A2A_ENABLED": "true",
        "SSRF_ALLOW_LOCALHOST": "true",
        "PLUGINS_ENABLED": "true",
        "PLUGINS_CONFIG_FILE": str(plugin_config),
        "A2A_OBO_BEARER_BRIDGE_ENABLED": "true",
        "ENABLE_SENSITIVE_HEADER_PASSTHROUGH": "false",
        "TEST_OBO_TOKEN_URL": f"http://127.0.0.1:{token_server.server_port}/token",
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
    }
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    log_path = tmp_path / "gateway.log"
    with log_path.open("w") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", headers=make_auth_headers(token), timeout=15, trust_env=False) as client:
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

                registration = client.post(
                    "/a2a",
                    json={
                        "agent": {
                            "name": _AGENT_NAME,
                            "endpoint_url": f"http://127.0.0.1:{agent_server.server_port}/invoke",
                            "agent_type": "generic",
                            "auth_type": "none",
                            "passthrough_headers": ["Authorization"],
                        },
                        "visibility": "public",
                    },
                )
                assert registration.status_code in (200, 201), registration.text
                response = client.post(f"/a2a/{_AGENT_NAME}/invoke", json={"parameters": {"query": "exchange me"}})
                assert response.status_code == 200, response.text

                exchange_count = len(_TokenHandler.assertions)
                dispatch_count = len(_AgentHandler.authorizations)
                with httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", timeout=15, trust_env=False) as anonymous:
                    denied = anonymous.post(f"/a2a/{_AGENT_NAME}/invoke", json={"parameters": {"query": "deny me"}})
                assert denied.status_code in (401, 403), denied.text
                assert len(_TokenHandler.assertions) == exchange_count
                assert len(_AgentHandler.authorizations) == dispatch_count
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            token_server.shutdown()
            token_server.server_close()
            token_worker.join(timeout=5)
            agent_server.shutdown()
            agent_server.server_close()
            agent_worker.join(timeout=5)

    assert _TokenHandler.assertions == [token]
    assert _AgentHandler.authorizations == ["Bearer exchanged-token"]
    assert token not in _AgentHandler.authorizations
    assert token not in log_path.read_text()
