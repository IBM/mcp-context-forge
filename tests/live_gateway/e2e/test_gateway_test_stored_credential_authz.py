# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_gateway_test_stored_credential_authz.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box tests for stored-credential authorization on gateway connectivity tests.

POST /v1/mcp-servers/test sends the registered gateway's stored credentials to
the upstream. These tests run against a real gateway subprocess and a local
recording upstream and verify that:

1. A caller without ``gateways.update`` (default ``platform_viewer``) receives 403
   and the stored credential never reaches the upstream.
2. A platform admin still reaches the upstream with the stored credential.
3. A bare handshake with ``gateways.read`` still works.
"""

from __future__ import annotations

# Standard
from collections.abc import Iterator
import contextlib
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
from typing import Any
import uuid

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RecordedRequest = tuple[str, str, dict[str, str]]
_GatewayFixture = tuple[httpx.Client, str, str, str]
_STORED_AUTH = "Bearer live-stored"  # pragma: allowlist secret

# Minimal upstream stub
_DISCOVER_SUCCESS_BODY = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "resultType": "complete",
            "supportedVersions": ["2026-07-28"],
            "_meta": {
                "io.modelcontextprotocol/serverInfo": {
                    "name": "stub-upstream",
                    "version": "1.0",
                }
            },
        },
    }
).encode()


class _DualStackThreadingHTTPServer(ThreadingHTTPServer):
    """Accept IPv4 and IPv6 localhost connections through one test server."""

    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        """Enable dual-stack loopback access before binding."""
        with contextlib.suppress(OSError):
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def _make_recording_handler() -> tuple[type[BaseHTTPRequestHandler], list[_RecordedRequest]]:
    """Return a handler class that records every POST and a list holding the records."""
    recorded: list[_RecordedRequest] = []

    class _Handler(BaseHTTPRequestHandler):
        """Answer any POST with a valid server/discover result."""

        def do_POST(self):  # noqa: N802
            """Record the request and return a discover result."""
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length:
                self.rfile.read(content_length)
            recorded.append((self.command, self.path, dict(self.headers)))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(_DISCOVER_SUCCESS_BODY)))
            self.end_headers()
            self.wfile.write(_DISCOVER_SUCCESS_BODY)

        def log_message(self, format, *args):  # noqa: A002
            """Suppress per-request log lines."""

    return _Handler, recorded


# ---------------------------------------------------------------------------
# isolated_gateway fixture (mirrors test_candidate_credential_handshake.py)
# ---------------------------------------------------------------------------
@pytest.fixture
def isolated_gateway(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[_GatewayFixture]:
    """Start a private, single-tenant gateway subprocess for this test module.

    Uses SQLite + a random port so no compose stack is required. Indirect
    parametrization may pass a dict of environment overrides as ``request.param``.

    Yields:
        A tuple of ``(httpx.Client, admin_token_str, base_url, signing_key)``.
    """
    with socket.socket() as _sock:
        _sock.bind(("127.0.0.1", 0))
        port = _sock.getsockname()[1]

    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join(
            [
                str(_REPO_ROOT),
                *[str(Path(p).resolve()) for p in os.getenv("PYTHONPATH", "").split(os.pathsep) if p],
            ]
        ),
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
        # Restrict the isolated subprocess to localhost while permitting its test stub.
        "SSRF_PROTECTION_ENABLED": "false",
        "SSRF_ALLOW_LOCALHOST": "true",
        "GATEWAY_TEST_ALLOW_REGISTERED_ONLY": "false",
        "GATEWAY_TEST_ALLOWED_HOSTS": '["localhost"]',
        "MCP_CLIENT_CONNECT_MODE": "auto",
        "GATEWAY_ASYNC_LIFECYCLE_ENABLED": "true",
        "PLUGINS_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
        "NO_PROXY": "localhost,127.0.0.1",
        "PYTHONUNBUFFERED": "1",
        **getattr(request, "param", {}),
    }

    token = make_test_jwt(
        "admin@example.com",
        is_admin=True,
        teams=None,
        secret=signing_key,
        algorithm="HS256",
    )
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
            base_url = f"http://127.0.0.1:{port}"
            with httpx.Client(
                base_url=base_url,
                headers=make_auth_headers(token),
                timeout=20,
                trust_env=False,
            ) as client:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    assert process.poll() is None, f"Gateway crashed:\n{log_path.read_text()[-5000:]}"
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Gateway startup timed out:\n{log_path.read_text()[-5000:]}")
                yield client, token, base_url, signing_key
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _isolated_upstream() -> Iterator[tuple[str, list[_RecordedRequest]]]:
    """Start a recording upstream and yield its base URL and request list."""
    handler_cls, recorded = _make_recording_handler()
    upstream = _DualStackThreadingHTTPServer(("::", 0), handler_cls)
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://localhost:{upstream.server_address[1]}", recorded
    finally:
        upstream.shutdown()
        upstream.server_close()
        worker.join(timeout=5)


def _request_json(client: httpx.Client, method: str, path: str, *, expected: tuple[int, ...] = (200, 201), **kwargs: Any) -> Any:
    """Send an API request and return its JSON response."""
    response = client.request(method, path, **kwargs)
    assert response.status_code in expected, f"{method} {path} returned {response.status_code}: {response.text[:500]}"
    return response.json() if response.content else None


def _register_gateway(client: httpx.Client, *, name: str, url: str) -> str:
    """Register a public gateway with a stored authheaders credential and return its ID."""
    payload = {
        "name": name,
        "url": url,
        "transport": "STREAMABLEHTTP",
        "visibility": "public",
        "auth_type": "authheaders",
        "auth_headers": [{"key": "Authorization", "value": _STORED_AUTH}],
    }
    body = _request_json(client, "POST", "/gateways", json=payload, expected=(200, 201, 202), timeout=30)
    gw_id = body.get("id") or (body.get("gateway") or {}).get("id")
    assert isinstance(gw_id, str) and gw_id, f"Could not extract gateway id: {body}"
    return gw_id


def _create_viewer(client: httpx.Client, signing_key: str) -> tuple[str, httpx.Client]:
    """Create a persisted user with the default platform_viewer role and return its email and client."""
    email = f"stored-cred-viewer-{uuid.uuid4().hex[:8]}@example.com"
    _request_json(
        client,
        "POST",
        "/auth/email/admin/users",
        json={
            "email": email,
            "password": "E2eCandidate!42",  # pragma: allowlist secret
            "full_name": "Stored Credential Viewer",
            "is_admin": False,
            "is_active": True,
            "password_change_required": False,
        },
        expected=(201,),
    )
    token = make_test_jwt(email, teams=[], secret=signing_key, algorithm="HS256", include_email_claim=True)
    viewer = httpx.Client(base_url=str(client.base_url), headers=make_auth_headers(token), timeout=30, trust_env=False)
    return email, viewer


def _has_stored_auth(recorded: list[_RecordedRequest]) -> bool:
    """Return whether any recorded upstream request carried the stored credential."""
    return any(headers.get("Authorization") == _STORED_AUTH for _method, _path, headers in recorded)


_TEST_PAYLOAD = {"method": "POST", "path": "/mutate", "body": {"op": "x"}}


@pytest.fixture
def registered_gateway(isolated_gateway: _GatewayFixture) -> Iterator[tuple[str, list[_RecordedRequest], httpx.Client]]:
    """Register a stored-credential gateway and yield the upstream URL, its request log and a viewer client."""
    client, _token, _base_url, signing_key = isolated_gateway
    email, viewer = _create_viewer(client, signing_key)
    with _isolated_upstream() as (upstream_url, recorded):
        gw_id = _register_gateway(client, name=f"e2e-stored-cred-{uuid.uuid4().hex[:8]}", url=upstream_url)
        recorded.clear()
        try:
            yield upstream_url, recorded, viewer
        finally:
            viewer.close()
            with contextlib.suppress(Exception):
                client.delete(f"/gateways/{gw_id}", timeout=10)
                client.delete(f"/auth/email/admin/users/{email}", timeout=10)


def test_platform_viewer_cannot_send_credentialed_post(isolated_gateway: _GatewayFixture, registered_gateway) -> None:
    """A caller without gateways.update gets 403 and the stored credential is never sent."""
    upstream_url, recorded, viewer = registered_gateway

    resp = viewer.post("/v1/mcp-servers/test", json={**_TEST_PAYLOAD, "base_url": upstream_url})

    assert resp.status_code == 403, resp.text[:500]
    assert "gateways.update" in resp.text
    assert not _has_stored_auth(recorded)


def test_admin_can_still_send_credentialed_post(isolated_gateway: _GatewayFixture, registered_gateway) -> None:
    """A platform admin still tests a gateway with its stored credential."""
    client, _token, _base_url, _key = isolated_gateway
    upstream_url, recorded, _viewer = registered_gateway

    resp = client.post("/v1/mcp-servers/test", json={**_TEST_PAYLOAD, "base_url": upstream_url})

    assert resp.status_code == 200, resp.text[:500]
    assert ("POST", "/mutate") in [(method, path) for method, path, _headers in recorded]
    assert _has_stored_auth(recorded)


def test_platform_viewer_bare_handshake_still_works(isolated_gateway: _GatewayFixture, registered_gateway) -> None:
    """A bare handshake needs only gateways.read."""
    upstream_url, _recorded, viewer = registered_gateway

    resp = viewer.post("/v1/mcp-servers/test-handshake", json={"base_url": upstream_url})

    assert resp.status_code == 200, resp.text[:500]
