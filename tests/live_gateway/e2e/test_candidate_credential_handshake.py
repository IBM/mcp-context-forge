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
starts a private uvicorn subprocess on a random free port backed by a temporary
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


class _DualStackThreadingHTTPServer(ThreadingHTTPServer):
    """Accept IPv4 and IPv6 localhost connections through one test server."""

    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        """Enable dual-stack loopback access before binding."""
        with contextlib.suppress(OSError):
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def _make_recording_handler(expected_candidate: str) -> tuple[type[BaseHTTPRequestHandler], list[_RecordedRequest]]:
    """Return a fresh (handler_class, requests_list) pair for one upstream stub.

    Each call produces a *new* handler subclass with its own ``requests`` list so
    that tests never share state even when they run sequentially in the same worker.
    The list is passed by reference: the caller holds it and reads it after the
    upstream shuts down.
    """
    recorded: list[_RecordedRequest] = []

    class _Handler(BaseHTTPRequestHandler):
        """Serve a valid server/discover response and record every received request."""

        def do_POST(self):  # noqa: N802
            """Return success only when the request supplies the expected candidate."""
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length:
                self.rfile.read(content_length)
            recorded.append((self.command, self.path, dict(self.headers)))
            candidate = self.headers.get("X-Candidate")
            stored = self.headers.get("X-Stored-Key")
            authorized = candidate == expected_candidate or stored == "stored-secret" or (candidate is None and stored is None)
            response_body = _DISCOVER_SUCCESS_BODY if authorized else b'{"error":"unauthorized"}'
            self.send_response(200 if authorized else 401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

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
# isolated_upstream  — ephemeral MCP stub server
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _isolated_upstream(expected_candidate: str = "valid-candidate") -> Iterator[tuple[str, list[_RecordedRequest]]]:
    """Start an ephemeral ThreadingHTTPServer acting as an upstream MCP server.

    Each call creates a *fresh* handler class and requests list via
    ``_make_recording_handler()``, so sequential tests in the same worker
    never share recorded state.

    Yields:
        ``(url: str, requests: list)`` — the full base URL and the per-call
        list that accumulates ``(method, path, headers_dict)`` tuples.
    """
    handler_cls, recorded = _make_recording_handler(expected_candidate)
    upstream = _DualStackThreadingHTTPServer(("::", 0), handler_cls)
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
    auth_headers_list: list[dict[str, str]] | None = None,
) -> str:
    """Register a gateway and return its ``id``.

    Uses ``auth_headers`` (list of ``{"key": ..., "value": ...}`` dicts) for
    authheaders auth type, which is the correct format accepted by POST /gateways.
    """
    payload: dict[str, Any] = {
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
    assert isinstance(gw_id, str) and gw_id, f"Could not extract gateway id from POST /gateways response: {body}"
    return gw_id


def _delete_gateway(client: httpx.Client, gateway_id: str) -> None:
    with contextlib.suppress(Exception):
        client.delete(f"{_GATEWAYS_PATH}/{gateway_id}", timeout=10)


def _post_handshake(client: httpx.Client, payload: dict[str, Any], timeout: float = 30) -> httpx.Response:
    return client.post(_HANDSHAKE_PATH, json=payload, timeout=timeout)


def _request_json(client: httpx.Client, method: str, path: str, *, expected: tuple[int, ...] = (200, 201), **kwargs: Any) -> Any:
    """Send an API request and return its JSON response."""
    response = client.request(method, path, **kwargs)
    assert response.status_code in expected, f"{method} {path} returned {response.status_code}: {response.text[:500]}"
    return response.json() if response.content else None


def _create_team(client: httpx.Client, label: str) -> str:
    """Create a private team and return its ID."""
    team = _request_json(client, "POST", "/teams/", json={"name": f"{_GW_PREFIX}-{label}-{uuid.uuid4().hex[:8]}", "visibility": "private"})
    team_id = team["id"]
    assert isinstance(team_id, str)
    return team_id


def _create_team_user(client: httpx.Client, signing_key: str, team_id: str) -> tuple[str, str]:
    """Create a persisted team viewer and return its email and scoped JWT."""
    email = f"candidate-viewer-{uuid.uuid4().hex[:8]}@example.com"
    _request_json(
        client,
        "POST",
        "/auth/email/admin/users",
        json={
            "email": email,
            "password": "E2eCandidate!42",  # pragma: allowlist secret
            "full_name": "Candidate Handshake Viewer",
            "is_admin": False,
            "is_active": True,
            "password_change_required": False,
        },
        expected=(201,),
    )
    _request_json(client, "POST", f"/teams/{team_id}/members", json={"email": email, "role": "member"})
    token = make_test_jwt(email, teams=[team_id], secret=signing_key, algorithm="HS256", include_email_claim=True)
    return email, token


def _candidate_payload(base_url: str, gateway_id: str, candidate: str = "valid-candidate") -> dict[str, Any]:
    """Build a candidate-only handshake request."""
    return {
        "base_url": base_url,
        "gateway_id": gateway_id,
        "credential_mode": "candidate_only",
        "headers": {"X-Candidate": candidate},  # pragma: allowlist secret
    }


def _assert_success(response: httpx.Response) -> None:
    """Assert that a candidate-only handshake succeeded through the HTTP API."""
    assert response.status_code == 200, response.text[:500]
    body = response.json()
    assert body["success"] is True, body.get("error")
    assert body["credentialSource"] == "form"


def _assert_candidate_requests(recorded: list[_RecordedRequest], expected_candidate: str) -> None:
    """Assert that all upstream requests contain only the expected candidate credential."""
    assert recorded, "Upstream was never contacted"
    for _method, _path, headers in recorded:
        normalized = {key.lower(): value for key, value in headers.items()}
        assert normalized.get("x-candidate") == expected_candidate
        assert "x-stored-key" not in normalized


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

    def test_candidate_only_succeeds_and_reports_form_source(self, isolated_gateway: _GatewayFixture) -> None:
        """Candidate-only handshakes succeed only with the valid supplied credential."""
        client, _token, _base_url, _secret = isolated_gateway

        with _isolated_upstream(expected_candidate="valid-candidate") as (upstream_url, recorded):
            gw_name = f"{_GW_PREFIX}-success-{uuid.uuid4().hex[:8]}"
            gw_id = _register_gateway(
                client,
                name=gw_name,
                url=upstream_url,
                visibility="public",
                auth_headers_list=[{"key": "X-Stored-Key", "value": "stored-secret"}],  # pragma: allowlist secret
            )
            try:
                recorded.clear()
                valid_response = _post_handshake(client, _candidate_payload(upstream_url, gw_id))
                _assert_success(valid_response)
                _assert_candidate_requests(recorded, "valid-candidate")

                recorded.clear()
                invalid_response = _post_handshake(client, _candidate_payload(upstream_url, gw_id, "invalid-candidate"))
                assert invalid_response.status_code == 200, invalid_response.text[:500]
                invalid_body = invalid_response.json()
                assert invalid_body["success"] is False
                assert invalid_body["failureClass"] == "auth"
                _assert_candidate_requests(recorded, "invalid-candidate")
            finally:
                _delete_gateway(client, gw_id)

    def test_hidden_gateway_denied_no_upstream_probe(self, isolated_gateway: _GatewayFixture) -> None:
        """A permitted team-A caller cannot probe a team-B gateway by ID."""
        client, _token, _base_url, signing_key = isolated_gateway

        team_a_id = _create_team(client, "team-a")
        team_b_id = _create_team(client, "team-b")
        user_email, team_a_token = _create_team_user(client, signing_key, team_a_id)
        with _isolated_upstream() as (visible_url, visible_recorded), _isolated_upstream() as (hidden_url, hidden_recorded):
            visible_gateway_id = _register_gateway(client, name=f"{_GW_PREFIX}-visible-{uuid.uuid4().hex[:8]}", url=visible_url, visibility="team", team_id=team_a_id)
            hidden_gateway_id = _register_gateway(client, name=f"{_GW_PREFIX}-hidden-{uuid.uuid4().hex[:8]}", url=hidden_url, visibility="team", team_id=team_b_id)
            try:
                visible_recorded.clear()
                hidden_recorded.clear()
                with httpx.Client(base_url=_base_url, headers=make_auth_headers(team_a_token), timeout=30, trust_env=False) as team_a_client:
                    visible_response = _post_handshake(team_a_client, _candidate_payload(visible_url, visible_gateway_id))
                    _assert_success(visible_response)
                    _assert_candidate_requests(visible_recorded, "valid-candidate")

                    visible_recorded.clear()
                    hidden_recorded.clear()
                    resp = _post_handshake(team_a_client, _candidate_payload(hidden_url, hidden_gateway_id))

                assert resp.status_code == 200, resp.text[:500]
                body = resp.json()
                assert body["success"] is False, "Team-A token must not access team-B gateway — expected success=false"
                assert body.get("failureClass") == "transport", f"Expected failureClass=transport, got {body.get('failureClass')!r}"
                assert visible_recorded == []
                assert hidden_recorded == []
            finally:
                _delete_gateway(client, visible_gateway_id)
                _delete_gateway(client, hidden_gateway_id)
                with contextlib.suppress(Exception):
                    client.delete(f"/teams/{team_b_id}", timeout=10)
                    client.delete(f"/teams/{team_a_id}", timeout=10)
                    client.delete(f"/auth/email/admin/users/{user_email}", timeout=10)

    def test_url_mismatched_gateway_denied(self, isolated_gateway: _GatewayFixture) -> None:
        """An allowed URL paired with a different gateway ID is denied before probing."""
        client, _token, _base_url, _secret = isolated_gateway

        with _isolated_upstream() as (upstream_a_url, recorded_a), _isolated_upstream() as (upstream_b_url, recorded_b):
            gateway_a_id = _register_gateway(client, name=f"{_GW_PREFIX}-mismatch-a-{uuid.uuid4().hex[:8]}", url=upstream_a_url, visibility="public")
            gateway_b_id = _register_gateway(client, name=f"{_GW_PREFIX}-mismatch-b-{uuid.uuid4().hex[:8]}", url=upstream_b_url, visibility="public")
            try:
                recorded_a.clear()
                recorded_b.clear()
                _assert_success(_post_handshake(client, _candidate_payload(upstream_a_url, gateway_a_id)))
                _assert_candidate_requests(recorded_a, "valid-candidate")
                assert recorded_b == []

                recorded_a.clear()
                _assert_success(_post_handshake(client, _candidate_payload(upstream_b_url, gateway_b_id)))
                _assert_candidate_requests(recorded_b, "valid-candidate")
                assert recorded_a == []

                recorded_a.clear()
                recorded_b.clear()
                resp = _post_handshake(client, _candidate_payload(upstream_b_url, gateway_a_id))
                assert resp.status_code == 200, resp.text[:500]
                body = resp.json()
                assert body["success"] is False, "URL mismatch must be rejected — expected success=false"
                assert body.get("failureClass") == "transport", f"Expected failureClass=transport for URL mismatch, got {body.get('failureClass')!r}"
                assert recorded_a == []
                assert recorded_b == []
            finally:
                _delete_gateway(client, gateway_a_id)
                _delete_gateway(client, gateway_b_id)


@contextlib.contextmanager
def _oauth_validation_upstream(legacy: bool):
    """Serve OAuth tokens and MCP requests for a real post-authorization flow.

    Args:
        legacy: Reject discovery to exercise initialize negotiation.

    Yields:
        Upstream URL and mutable listing behavior with request counters.
    """
    state = {"token_calls": 0, "tools_calls": 0, "scope_error": False, "empty": False}
    access_token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        """Serve a local OAuth provider and an authenticated MCP endpoint."""

        def do_POST(self):  # noqa: N802
            """Issue tokens or dispatch authenticated MCP JSON-RPC requests."""
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/token":
                state["token_calls"] += 1
                self.reply(200, {"access_token": access_token, "token_type": "Bearer", "expires_in": 3600, "scope": "tools:read"})
                return
            if self.headers.get("Authorization") != f"Bearer {access_token}":
                self.reply(401, {"error": "invalid_token"})
                return
            request = json.loads(body)
            method = request.get("method")
            if method == "notifications/initialized":
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if method == "server/discover":
                if legacy:
                    self.reply(404, {})
                    return
                result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}}
            elif method == "initialize":
                result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "oauth-validation", "version": "1"}}
            elif method == "tools/list":
                state["tools_calls"] += 1
                if state["scope_error"]:
                    self.reply(200, {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32000, "message": "Listing denied", "data": {"error": "insufficient_scope"}}})
                    return
                result = {"tools": [] if state["empty"] else [{"name": "validation_echo", "inputSchema": {"type": "object"}}]}
            else:
                result = {}
            self.reply(200, {"jsonrpc": "2.0", "id": request["id"], "result": result})

        def reply(self, status, body):
            """Return a JSON response with a bounded content length."""
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format, *args):
            """Keep request details out of test output."""

    server = _DualStackThreadingHTTPServer(("::", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://localhost:{server.server_address[1]}", state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.parametrize("legacy", [False, True])
def test_post_authorization_live_stored_token_validation(isolated_gateway: _GatewayFixture, legacy: bool):
    """A real OAuth callback stores the caller token before strict validation lists tools."""
    from urllib.parse import parse_qs, urlparse

    client, _token, base_url, signing_key = isolated_gateway
    with _oauth_validation_upstream(legacy) as (upstream, state):
        response = client.post(_GATEWAYS_PATH, json={
            "name": f"oauth-validation-{uuid.uuid4().hex[:8]}", "url": f"{upstream}/mcp", "transport": "STREAMABLEHTTP",
            "visibility": "public", "auth_type": "oauth", "oauth_config": {
                "grant_type": "authorization_code", "client_id": "validation-client", "authorization_url": f"{upstream}/authorize",
                "token_url": f"{upstream}/token", "redirect_uri": f"{base_url}/oauth/callback", "scopes": ["tools:read"],
            },
        })
        assert response.status_code in (200, 201, 202), response.text
        body = response.json()
        gateway_id = body.get("id") or body["gateway"]["id"]
        payload = {"base_url": f"{upstream}/mcp", "gateway_id": gateway_id, "validation_mode": "post_authorization"}
        try:
            missing = _post_handshake(client, payload)
            assert missing.status_code == 200, missing.text
            assert missing.json()["errorCode"] == "authorization_missing", missing.text
            authorization = client.get(f"/oauth/authorize/{gateway_id}", params={"popup": "true"}, follow_redirects=False)
            assert authorization.status_code in (302, 307), authorization.text
            oauth_state = parse_qs(urlparse(authorization.headers["location"]).query)["state"][0]
            callback = client.get("/oauth/callback", params={"code": "consented-code", "state": oauth_state})
            assert callback.status_code == 200 and '"status": "success"' in callback.text, callback.text
            token_calls = state["token_calls"]
            components_before = {path: _request_json(client, "GET", path) for path in ("/tools", "/resources", "/prompts")}
            for empty in (False, True):
                state["empty"] = empty
                before = state["tools_calls"]
                result = _post_handshake(client, payload)
                assert result.status_code == 200, result.text
                outcome = result.json()
                assert outcome["success"], outcome
                assert outcome["componentCounts"]["tools"] == (0 if empty else 1)
                assert outcome["stages"] == {"token": "ok", "negotiation": "ok", "tools_list": "ok"}
                assert outcome["negotiationPath"] == ("initialize" if legacy else "server_discover")
                assert state["tools_calls"] == before + 1
                assert state["token_calls"] == token_calls
            other_email = f"validation-other-{uuid.uuid4().hex[:8]}@example.com"
            _request_json(client, "POST", "/auth/email/admin/users", json={
                "email": other_email, "password": "E2eCandidate!42", "full_name": "Validation Other", "is_admin": False,  # pragma: allowlist secret
                "is_active": True, "password_change_required": False,
            }, expected=(201,))
            roles = _request_json(client, "GET", "/rbac/roles")
            role_id = next(role["id"] for role in roles if role["name"] == "platform_admin")
            _request_json(client, "POST", f"/rbac/users/{other_email}/roles", json={"role_id": role_id, "scope": "global"})
            other_token = make_test_jwt(other_email, teams=[], secret=signing_key, algorithm="HS256", include_email_claim=True)
            before = state["tools_calls"]
            with httpx.Client(base_url=base_url, headers=make_auth_headers(other_token), trust_env=False, timeout=20) as other_client:
                other = _post_handshake(other_client, payload)
            assert other.status_code == 200, other.text
            assert other.json()["errorCode"] == "authorization_missing", other.text
            assert state["tools_calls"] == before
            state["scope_error"] = True
            denied = _post_handshake(client, payload)
            assert denied.status_code == 200, denied.text
            assert not denied.json()["success"]
            assert denied.json()["failedStage"] == "tools_list"
            assert denied.json()["errorCode"] == "insufficient_scope", denied.text
            assert {path: _request_json(client, "GET", path) for path in components_before} == components_before
            override = _post_handshake(client, {**payload, "headers": {"Authorization": "Bearer override"}})
            assert override.status_code == 422
            anonymous = client.post(_HANDSHAKE_PATH, json=payload, headers={"Authorization": ""})
            assert anonymous.status_code == 401
        finally:
            _delete_gateway(client, gateway_id)
