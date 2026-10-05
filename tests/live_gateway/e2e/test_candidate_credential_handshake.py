# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_candidate_credential_handshake.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box tests for candidate-only credential handshake (PR #6877).

Verifies the complete gateway authentication and upstream handshake paths for
POST /v1/mcp-servers/test-handshake using real HTTP requests against a running
gateway subprocess and a local upstream HTTP stub.

Scenarios covered:
1. candidate_only success — form headers reach the upstream; stored credentials
   from the registered gateway are not forwarded (credentialSource=form).
2. hidden gateway denial — a team-A token cannot probe a team-B private gateway
   via gateway_id; no upstream probe is fired (success=false, failureClass=transport).
3. URL-mismatched gateway denial — exact gateway_id whose registered URL differs
   from base_url; handshake fails transport without touching the upstream.

Design notes
------------
The ``isolated_gateway`` fixture (copied from test_rest_non_json_output_schema_e2e.py)
starts a private uvicorn subprocess on a random free port backed by an in-memory
SQLite database.  This means:

* No Docker / compose stack is required.
* No ``fast_time_server`` dependency — the upstream for scenario 1 is a tiny
  ThreadingHTTPServer that always returns a valid MCP server/discover response.
* All three tests run in CI exactly as they run locally.

The ``isolated_upstream`` context-manager starts a second ephemeral HTTP server
that plays the role of the upstream MCP server, returning a minimal spec-shaped
server/discover response so the gateway considers the handshake successful.
"""

from __future__ import annotations

# Standard
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
import uuid

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_auth_headers, make_legacy_test_jwt, make_test_jwt

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Minimal upstream MCP stub
# ---------------------------------------------------------------------------
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


def _make_recording_handler() -> tuple[type, list]:
    """Return a fresh (handler_class, requests_list) pair for one upstream stub.

    Each call produces a *new* handler subclass with its own ``requests`` list so
    that tests never share state even when they run sequentially in the same worker.
    The list is passed by reference: the caller holds it and reads it after the
    upstream shuts down.
    """
    recorded: list = []

    class _Handler(BaseHTTPRequestHandler):
        """Serve a valid server/discover response and record every received request."""

        def do_POST(self):  # noqa: N802
            """Accept any POST and return a successful server/discover JSON-RPC result."""
            recorded.append((self.command, self.path, dict(self.headers)))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(_DISCOVER_SUCCESS_BODY)

        def do_GET(self):  # noqa: N802
            """Accept health probes."""
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):  # noqa: A002
            """Suppress per-request log lines."""

    return _Handler, recorded


# ---------------------------------------------------------------------------
# isolated_gateway fixture  (mirrors test_rest_non_json_output_schema_e2e.py)
# ---------------------------------------------------------------------------
@pytest.fixture
def isolated_gateway(tmp_path):
    """Start a private, single-tenant gateway subprocess for this test module.

    Uses SQLite + a random port so no compose stack is required.

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
        # Allow the handshake endpoint to probe our upstream stub on localhost.
        # ssrf_allow_localhost=true exempts the "localhost" hostname from the
        # SSRF loopback check before the IP-range block is reached.
        "SSRF_ALLOW_LOCALHOST": "true",
        "GATEWAY_TEST_ALLOW_REGISTERED_ONLY": "false",
        "GATEWAY_TEST_ALLOWED_HOSTS": '["localhost"]',
        # Require JTI is on by default; disable so the minimal legacy token
        # (no jti claim) used for the public-only user is accepted.
        "REQUIRE_JTI": "false",
        "MCP_CLIENT_CONNECT_MODE": "auto",
        # Skip the synchronous upstream probe on POST /gateways — the async
        # lifecycle worker would normally do this in the background, but for
        # these tests we only need the gateway row to exist so the handshake
        # endpoint can look it up by id.
        "GATEWAY_ASYNC_LIFECYCLE_ENABLED": "true",
        "PLUGINS_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
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
# isolated_upstream  — ephemeral MCP stub server
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _isolated_upstream():
    """Start an ephemeral ThreadingHTTPServer acting as an upstream MCP server.

    Each call creates a *fresh* handler class and requests list via
    ``_make_recording_handler()``, so sequential tests in the same worker
    never share recorded state.

    Yields:
        ``(url: str, requests: list)`` — the full base URL and the per-call
        list that accumulates ``(method, path, headers_dict)`` tuples.
    """
    handler_cls, recorded = _make_recording_handler()
    # Bind to localhost so ssrf_allow_localhost=true exempts the hostname
    # from the SSRF loopback check before the IP-range block is reached.
    upstream = ThreadingHTTPServer(("localhost", 0), handler_cls)
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://localhost:{upstream.server_address[1]}", recorded
    finally:
        upstream.shutdown()
        upstream.server_close()
        worker.join(timeout=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_GW_PREFIX = "e2e-candidate-cred"
_HANDSHAKE_PATH = "/v1/mcp-servers/test-handshake"
_GATEWAYS_PATH = "/gateways"


def _register_gateway(
    client: httpx.Client,
    *,
    name: str,
    url: str,
    transport: str = "STREAMABLEHTTP",
    visibility: str = "public",
    team_id: str | None = None,
    auth_headers_list: list[dict] | None = None,
) -> str:
    """Register a gateway and return its ``id``.

    Uses ``auth_headers`` (list of ``{"key": ..., "value": ...}`` dicts) for
    authheaders auth type, which is the correct format accepted by POST /gateways.
    """
    payload: dict = {
        "name": name,
        "url": url,
        "transport": transport,
        "visibility": visibility,
        "auth_type": "authheaders" if auth_headers_list else "none",
    }
    if team_id:
        payload["team_id"] = team_id
    if auth_headers_list:
        payload["auth_headers"] = auth_headers_list
    resp = client.post(_GATEWAYS_PATH, json=payload, timeout=30)
    assert resp.status_code in (200, 201, 202), f"POST /gateways failed {resp.status_code}: {resp.text[:500]}"
    body = resp.json()
    # 200/201 sync path → id at top level; 202 async path → id nested under "gateway"
    gw_id = body.get("id") or (body.get("gateway") or {}).get("id")
    assert gw_id, f"Could not extract gateway id from POST /gateways response: {body}"
    return gw_id


def _delete_gateway(client: httpx.Client, gateway_id: str) -> None:
    with contextlib.suppress(Exception):
        client.delete(f"{_GATEWAYS_PATH}/{gateway_id}", timeout=10)


def _post_handshake(client: httpx.Client, payload: dict, timeout: float = 30) -> httpx.Response:
    return client.post(_HANDSHAKE_PATH, json=payload, timeout=timeout)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCandidateCredentialHandshake:
    """Black-box handshake tests exercising the full gateway auth + upstream path.

    All three tests use:
    - ``isolated_gateway``: a private uvicorn subprocess on a random port, SQLite
      backed, no Docker/compose required — runs in CI as-is.
    - ``_isolated_upstream``: a tiny ThreadingHTTPServer that returns a valid MCP
      server/discover response, so scenario 1 can probe a real upstream without
      needing fast_time_server.
    """

    def test_candidate_only_succeeds_and_reports_form_source(self, isolated_gateway) -> None:
        """candidate_only handshake probes the upstream with only the supplied header.

        Registers a gateway with stored ``X-Stored-Key`` auth. Issues a
        ``credential_mode=candidate_only`` request with a *different* ``X-Candidate``
        header. The handshake must:
        - succeed (upstream stub returns a valid discover response)
        - report ``credentialSource=form`` (stored credentials were not forwarded)
        """
        client, _token, _base_url, _secret = isolated_gateway

        with _isolated_upstream() as (upstream_url, recorded):
            gw_name = f"{_GW_PREFIX}-success-{uuid.uuid4().hex[:8]}"
            gw_id = _register_gateway(
                client,
                name=gw_name,
                url=upstream_url,
                visibility="public",
                auth_headers_list=[{"key": "X-Stored-Key", "value": "stored-secret"}],  # pragma: allowlist secret
            )
            try:
                resp = _post_handshake(
                    client,
                    {
                        "base_url": upstream_url,
                        "gateway_id": gw_id,
                        "credential_mode": "candidate_only",
                        "headers": {"X-Candidate": "probe"},  # pragma: allowlist secret
                    },
                )
                assert resp.status_code == 200, f"Unexpected HTTP status: {resp.status_code} {resp.text[:500]}"
                body = resp.json()
                assert body["success"] is True, f"Handshake failed: {body.get('error')}"
                assert body["credentialSource"] == "form", f"Expected credentialSource=form (candidate_only must suppress stored headers), got {body['credentialSource']!r}"
                # Upstream stub must have been contacted at least once.
                assert len(recorded) >= 1, "Upstream was never contacted"
                # The upstream must NOT have received the stored credential header —
                # only the candidate header supplied in the request should appear.
                upstream_headers = recorded[0][2]  # (method, path, headers_dict)
                forwarded_keys = {k.lower() for k in upstream_headers}
                assert "x-stored-key" not in forwarded_keys, f"Stored credential was forwarded to upstream in candidate_only mode: {upstream_headers}"
                assert "x-candidate" in forwarded_keys, f"Candidate header was not forwarded to upstream: {upstream_headers}"
            finally:
                _delete_gateway(client, gw_id)

    def test_hidden_gateway_denied_no_upstream_probe(self, isolated_gateway) -> None:
        """A team-A token cannot probe a team-B private gateway via gateway_id.

        Registers a team-scoped gateway owned by team-B.  A caller whose token
        is limited to team-A requests it by gateway_id.  The handshake must:
        - fail with ``success=false``
        - report ``failureClass=transport``
        - not contact the upstream (the upstream stub records no requests)
        """
        client, _token, _base_url, signing_key = isolated_gateway

        with _isolated_upstream() as (upstream_url, recorded):
            # Create team-B via the API.
            team_b_name = f"{_GW_PREFIX}-team-b-{uuid.uuid4().hex[:8]}"
            team_resp = client.post(
                "/teams/",
                json={"name": team_b_name, "visibility": "private"},
                timeout=15,
            )
            assert team_resp.status_code in (200, 201), f"Failed to create team: {team_resp.status_code} {team_resp.text[:300]}"
            team_b_id = team_resp.json()["id"]

            gw_name = f"{_GW_PREFIX}-hidden-{uuid.uuid4().hex[:8]}"
            gw_id = _register_gateway(
                client,
                name=gw_name,
                url=upstream_url,
                visibility="team",
                team_id=team_b_id,
            )
            try:
                # Build a public-only token (teams=[]) for a different user.
                # make_legacy_test_jwt omits jti/env claims; REQUIRE_JTI=false in
                # the fixture env ensures the gateway accepts it.  A public-only
                # token passes team-membership validation but cannot see a
                # team-scoped private gateway — which is the isolation we assert.
                team_a_token = make_legacy_test_jwt(
                    f"public-user-{uuid.uuid4().hex[:6]}@example.com",
                    teams=[],
                    secret=signing_key,
                    algorithm="HS256",
                    include_email_claim=True,
                )
                # Post the handshake using team-A's token (not the admin client fixture).
                resp = httpx.post(
                    f"{_base_url}{_HANDSHAKE_PATH}",
                    json={
                        "base_url": upstream_url,
                        "gateway_id": gw_id,
                        "credential_mode": "candidate_only",
                        "headers": {"X-Candidate": "probe"},  # pragma: allowlist secret
                    },
                    headers={"Authorization": f"Bearer {team_a_token}"},  # pragma: allowlist secret
                    timeout=30,
                )
                assert resp.status_code == 200, f"Unexpected HTTP status: {resp.status_code} {resp.text[:500]}"
                body = resp.json()
                assert body["success"] is False, "Team-A token must not access team-B gateway — expected success=false"
                assert body.get("failureClass") == "transport", f"Expected failureClass=transport, got {body.get('failureClass')!r}"
                # The upstream stub must NOT have been contacted.
                assert recorded == [], f"Upstream was probed despite denied gateway: {recorded}"
            finally:
                _delete_gateway(client, gw_id)
                with contextlib.suppress(Exception):
                    client.delete(f"/teams/{team_b_id}", timeout=10)

    def test_url_mismatched_gateway_denied(self, isolated_gateway) -> None:
        """gateway_id whose registered URL differs from base_url is rejected transport-level.

        Registers a gateway at ``upstream_url``.  Issues a handshake with
        ``base_url`` pointing at a *different* host. The gateway must reject
        the mismatch before firing any outbound probe.
        """
        client, _token, _base_url, _secret = isolated_gateway

        with _isolated_upstream() as (upstream_url, recorded):
            gw_name = f"{_GW_PREFIX}-mismatch-{uuid.uuid4().hex[:8]}"
            # Register gateway at the real upstream URL.
            gw_id = _register_gateway(
                client,
                name=gw_name,
                url=upstream_url,
                visibility="public",
            )
            try:
                # Request a probe against a *different* URL while supplying gateway_id.
                resp = _post_handshake(
                    client,
                    {
                        "base_url": "http://other-host.example.com/mcp",
                        "gateway_id": gw_id,
                        "credential_mode": "candidate_only",
                        "headers": {},
                    },
                )
                assert resp.status_code == 200, f"Unexpected HTTP status: {resp.status_code} {resp.text[:500]}"
                body = resp.json()
                assert body["success"] is False, "URL mismatch must be rejected — expected success=false"
                assert body.get("failureClass") == "transport", f"Expected failureClass=transport for URL mismatch, got {body.get('failureClass')!r}"
                # The upstream stub must NOT have been contacted.
                assert recorded == [], f"Upstream was probed despite URL mismatch: {recorded}"
            finally:
                _delete_gateway(client, gw_id)
