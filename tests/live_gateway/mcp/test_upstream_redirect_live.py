# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_upstream_redirect_live.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box regression for upstream 3xx handling (issue #7163) against an isolated running gateway.

The upstream answers every request with a 307 to a second server. The gateway must report the
redirect target in an actionable error and must never send a request to that target.
"""

from __future__ import annotations

# Standard
from collections.abc import Generator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from typing import cast

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REDIRECT_COPY = "update the gateway URL to the redirect target."


class _RedirectingUpstream(BaseHTTPRequestHandler):
    """Answer every request with a 307 to the redirect target."""

    requests: list[tuple[str, str]] = []

    def _redirect(self) -> None:
        """Record the request and redirect it."""
        self.requests.append((self.command, self.path))
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        target = cast(str, getattr(self.server, "redirect_target"))
        self.send_response(307)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_DELETE = _redirect  # noqa: N815

    def log_message(self, format: str, *args: object) -> None:
        """Keep test HTTP server quiet."""


class _RedirectTarget(BaseHTTPRequestHandler):
    """Record requests that must never arrive."""

    requests: list[tuple[str, str]] = []

    def _record(self) -> None:
        """Record the unexpected request."""
        self.requests.append((self.command, self.path))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_DELETE = _record  # noqa: N815

    def log_message(self, format: str, *args: object) -> None:
        """Keep test HTTP server quiet."""


@dataclass(frozen=True)
class _LiveStack:
    """Resources exposed by the live fixture."""

    client: httpx.Client
    upstream_url: str
    target_url: str


def _free_port() -> int:
    """Reserve and return one free TCP port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return cast(tuple[str, int], listener.getsockname())[1]


@pytest.fixture
def live_stack(tmp_path: Path) -> Generator[_LiveStack, None, None]:
    """Start the redirecting upstream, the redirect target, and an isolated gateway."""
    _RedirectingUpstream.requests.clear()
    _RedirectTarget.requests.clear()
    target = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectTarget)
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectingUpstream)
    target_url = f"http://127.0.0.1:{target.server_port}/mcp/"
    upstream.redirect_target = target_url  # type: ignore[attr-defined]
    workers = [threading.Thread(target=server.serve_forever, daemon=True) for server in (target, upstream)]
    for worker in workers:
        worker.start()

    gateway_port = _free_port()
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
        "SSRF_PROTECTION_ENABLED": "false",
        "SSRF_ALLOW_LOCALHOST": "true",
        "SSRF_ALLOW_PRIVATE_NETWORKS": "true",
        "SSRF_BLOCKED_NETWORKS": "[]",
        "SSRF_BLOCKED_HOSTS": "[]",
        "GATEWAY_TEST_ALLOW_REGISTERED_ONLY": "false",
        "GATEWAY_TEST_ALLOWED_HOSTS": '["127.0.0.1"]',
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
    }
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key)
    log_path = tmp_path / "gateway.log"
    with log_path.open("w") as log_file:
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        client = httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", headers=make_auth_headers(token), timeout=30, trust_env=False, follow_redirects=False)
        try:
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
            yield _LiveStack(client=client, upstream_url=f"http://127.0.0.1:{upstream.server_port}/mcp", target_url=target_url)
        finally:
            client.close()
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            for server, worker in zip((target, upstream), workers):
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)


def test_test_connection_reports_redirect_and_does_not_follow(live_stack: _LiveStack) -> None:
    """Test Connection returns the 3xx with an actionable error and the redirect target is never contacted."""
    response = live_stack.client.post("/v1/mcp-servers/test", json={"base_url": live_stack.upstream_url, "method": "GET", "path": ""})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["statusCode"] == 307
    assert body["body"]["error"] == f"Upstream redirected to {live_stack.target_url}; {_REDIRECT_COPY}"
    assert _RedirectTarget.requests == []


def test_handshake_reports_redirect_once_and_does_not_follow(live_stack: _LiveStack) -> None:
    """The handshake names the redirect target a single time and never contacts it."""
    response = live_stack.client.post("/v1/mcp-servers/test-handshake", json={"base_url": live_stack.upstream_url})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is False
    assert body["failureClass"] == "transport"
    assert body["error"].count("Upstream redirected") == 1
    assert live_stack.target_url in body["error"]
    assert _RedirectTarget.requests == []


@pytest.mark.parametrize("transport", ["SSE", "STREAMABLEHTTP"])
def test_registration_rejects_redirecting_upstream_with_actionable_error(live_stack: _LiveStack, transport: str) -> None:
    """Registration fails before saving, names the redirect target, and never contacts it."""
    response = live_stack.client.post("/gateways", json={"name": f"redirecting-{transport.lower()}", "url": live_stack.upstream_url, "transport": transport})
    assert response.status_code >= 400, response.text
    assert live_stack.target_url in response.text
    assert _REDIRECT_COPY in response.text
    assert _RedirectTarget.requests == []
    assert _RedirectingUpstream.requests, "the gateway never probed the upstream"
