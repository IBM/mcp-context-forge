# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_oauth_dual_stack_live.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise OAuth address fallback through an isolated, running gateway.
"""

# Standard
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def ipv4_oauth_provider() -> Iterator[tuple[str, list[dict[str, list[str]]]]]:
    """Start an IPv4-only provider when localhost resolves to IPv6 first.

    Yields:
        Provider origin and captured token forms.
    """
    addresses = list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo("localhost", None, socket.AF_UNSPEC, socket.SOCK_STREAM)))
    if addresses[:2] != ["::1", "127.0.0.1"]:
        pytest.skip(f"This regression requires IPv6-first dual-stack localhost; resolved {addresses}")
    forms: list[dict[str, list[str]]] = []
    access_token = secrets.token_urlsafe(32)

    class ProviderHandler(BaseHTTPRequestHandler):
        """Serve authorization redirects and an IPv4-only token endpoint."""

        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            """Redirect an authorization request with its original state."""
            parsed = urlsplit(self.path)
            if parsed.path != "/authorize":
                self.send_error(404)
                return
            query = parse_qs(parsed.query)
            location = query["redirect_uri"][0] + "?" + urlencode({"code": "test-code", "state": query["state"][0]})
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            """Return an OAuth token or the minimal MCP initialization response."""
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/token":
                forms.append(parse_qs(body.decode()))
                payload = {"access_token": access_token, "token_type": "Bearer", "expires_in": 3600, "scope": "read"}
            elif self.path == "/mcp":
                request = json.loads(body)
                if "id" not in request:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                result = (
                    {"protocolVersion": request["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "oauth-test", "version": "1"}}
                    if request["method"] == "initialize"
                    else {"tools": []}
                )
                payload = {"jsonrpc": "2.0", "id": request["id"], "result": result}
            else:
                self.send_error(404)
                return
            encoded = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            """Suppress provider access logs.

            Args:
                format: Access log format.
                *args: Access log values.
            """

    server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
    port = server.server_port
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        assert probe.connect_ex(("::1", port)) != 0, "The provider port must refuse IPv6"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://localhost:{port}", forms
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def oauth_gateway(tmp_path: Path) -> Iterator[httpx.Client]:
    """Start an authenticated gateway with a private database and localhost SSRF access.

    Args:
        tmp_path: Temporary directory for the gateway database and log.

    Yields:
        Authenticated HTTP client connected to the gateway.
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
        "JWT_ALGORITHM": "HS256",
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "AUTH_REQUIRED": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        "LLMCHAT_ENABLED": "false",
        "SSRF_PROTECTION_ENABLED": "true",
        "SSRF_ALLOW_LOCALHOST": "true",
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
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
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=make_auth_headers(token), timeout=15, trust_env=False) as client:
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


def test_authorization_code_falls_back_to_ipv4(ipv4_oauth_provider: tuple[str, list[dict[str, list[str]]]], oauth_gateway: httpx.Client) -> None:
    """Complete OAuth through a dual-stack name whose token endpoint refuses IPv6.

    Args:
        ipv4_oauth_provider: IPv4-only provider origin and captured token forms.
        oauth_gateway: Authenticated client for the isolated running gateway.
    """
    origin, forms = ipv4_oauth_provider
    payload = {
        "name": "dual-stack-oauth",
        "url": f"{origin}/mcp",
        "transport": "STREAMABLEHTTP",
        "visibility": "public",
        "auth_type": "oauth",
        "oauth_config": {
            "grant_type": "authorization_code",
            "client_id": "dual-stack-client",
            "token_endpoint_auth_method": "none",
            "authorization_url": f"{origin}/authorize",
            "token_url": f"{origin}/token",
            "redirect_uri": str(oauth_gateway.base_url.join("/oauth/callback")),
            "scopes": ["read"],
        },
    }
    response = oauth_gateway.post("/gateways", json=payload)
    assert response.status_code in (200, 201), response.text
    gateway_id = response.json()["id"]
    before = oauth_gateway.get(f"/oauth/status/{gateway_id}")
    assert before.status_code == 200, before.text
    assert before.json()["user_token_status"]["authorized"] is False

    authorization = oauth_gateway.get(f"/oauth/authorize/{gateway_id}")
    assert authorization.status_code == 307, authorization.text
    with httpx.Client(trust_env=False) as browser:
        provider = browser.get(authorization.headers["location"])
        assert provider.status_code == 302, provider.text
        callback = browser.get(provider.headers["location"])
    assert callback.status_code == 200, callback.text
    assert "OAuth Authorization Successful" in callback.text
    assert len(forms) == 1
    assert forms[0]["grant_type"] == ["authorization_code"]
    assert forms[0]["code"] == ["test-code"]
    assert forms[0]["code_verifier"]

    status = oauth_gateway.get(f"/oauth/status/{gateway_id}")
    assert status.status_code == 200, status.text
    assert status.json()["user_token_status"]["authorized"] is True
