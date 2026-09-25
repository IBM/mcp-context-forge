# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_rest_non_json_output_schema_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box check for a REST tool that declares an outputSchema against an
isolated gateway with a fixed REST_RESPONSE_TEXT_MAX_LENGTH.

Starts a private gateway subprocess, registers a REST tool pointing at a
local HTTP server, adds the tool to a virtual server, and calls it over the
server's MCP transport. Two scenarios:

- An invalid (unterminated) JSON body longer than the configured limit
  reports a parse error truncated to that exact limit, not a generic
  output-validation failure.
- A valid JSON body longer than the configured limit still validates and
  returns structured content: the limit only bounds the echoed error text,
  never a successful parse.
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

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.plugins._helpers import create_virtual_server, initialize_session, mcp_headers, result_text

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]

# The gateway subprocess pins REST_RESPONSE_TEXT_MAX_LENGTH to this value, so
# both bodies below (longer than the limit) exercise the same truncation path.
_MAX_LENGTH = 2000

# Invalid, truncated JSON: an unterminated string inside a "results" array.
_TRUNCATED_BODY = ('{"results": ["' + "x" * 6000).encode()

# Valid JSON, also longer than _MAX_LENGTH: proves the limit only bounds the
# echoed error text and never blocks a successful parse of a large body.
_LARGE_VALID_BODY = json.dumps({"results": ["x" * 6000]}).encode()


class _RecordingHandler(BaseHTTPRequestHandler):
    """Serve a fixed body, recording each request before responding.

    Subclasses set ``body`` and override ``content_type`` as needed. Recording
    happens first so a test can rely on ``requests`` the instant its response
    has been read, with no window where the response beat the recording.
    """

    requests: list = []
    body: bytes = b""

    def do_GET(self):
        """Record the request, then return 200 with the configured body."""
        self.requests.append((self.command, self.path))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format, *args):
        """Keep the fixture HTTP server quiet."""


class _TruncatedJSONHandler(_RecordingHandler):
    """Serve a truncated JSON body for the schema-tool parse-error probe."""

    requests: list = []
    body = _TRUNCATED_BODY


class _LargeValidJSONHandler(_RecordingHandler):
    """Serve a large but valid JSON body for the schema-tool size-boundary probe."""

    requests: list = []
    body = _LARGE_VALID_BODY


@pytest.fixture
def isolated_gateway(tmp_path):
    """Start a private, unauthenticated-plugin gateway subprocess for this test.

    Yields:
        A tuple of an authenticated ``httpx.Client`` and the admin bearer token.
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
        "PLUGINS_ENABLED": "false",
        "REST_RESPONSE_TEXT_MAX_LENGTH": str(_MAX_LENGTH),
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
                yield client, token
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@contextlib.contextmanager
def _call_schema_tool(client, token, handler_cls, *, tool_name):
    """Register a REST tool backed by ``handler_cls``, then call it via MCP.

    Cleanup (deleting the server/tool, stopping the upstream) always runs on
    exit, including when the caller's assertions raise.

    Args:
        client: Authenticated client for the isolated gateway.
        token: Bearer token for the gateway's MCP transport.
        handler_cls: Upstream handler class; ``handler_cls.requests`` is
            cleared before the call and holds the recorded requests after.
        tool_name: Unique tool name for this scenario.

    Yields:
        A tuple of the raw ``call_response`` and its decoded ``result``.
    """
    handler_cls.requests.clear()
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    tool_id = None
    server_id = None
    try:
        response = client.post(
            "/tools",
            json={
                "tool": {
                    "name": tool_name,
                    "description": "outputSchema size-boundary probe",
                    "integration_type": "REST",
                    "url": f"http://127.0.0.1:{upstream.server_port}/probe",
                    "request_type": "GET",
                    "visibility": "public",
                    "outputSchema": {
                        "type": "object",
                        "properties": {"results": {"type": "array"}},
                        "required": ["results"],
                    },
                },
                "team_id": None,
            },
        )
        assert response.status_code == 200, response.text
        tool = response.json()
        tool_id = tool["id"]

        server_id = create_virtual_server(client, name=f"{tool_name}_server", tool_ids=[tool_id])
        session_id = initialize_session(client, server_id=server_id, token=token)

        call_response = client.post(
            f"/servers/{server_id}/mcp/",
            headers=mcp_headers(token, session_id=session_id),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool["name"], "arguments": {}}},
        )
        assert call_response.status_code == 200, call_response.text
        payload = call_response.json()
        assert "result" in payload, payload
        assert handler_cls.requests == [("GET", "/probe")], handler_cls.requests
        yield call_response, payload["result"]
    finally:
        try:
            if server_id:
                client.delete(f"/servers/{server_id}")
            if tool_id:
                client.delete(f"/tools/{tool_id}")
        finally:
            upstream.shutdown()
            upstream.server_close()
            worker.join(timeout=5)


def test_non_json_body_with_output_schema_reports_parse_error(isolated_gateway):
    """An invalid, truncated JSON body on a schema tool reports a bounded parse error."""
    client, token = isolated_gateway
    body_len = len(_TRUNCATED_BODY)
    expected_echo = _TRUNCATED_BODY.decode()[:_MAX_LENGTH]
    with _call_schema_tool(client, token, _TruncatedJSONHandler, tool_name="rest_non_json_output_schema_probe") as (call_response, result):
        text = result_text(result)

        assert result["isError"] is True
        assert "Output validation error" not in call_response.text
        assert f"Showing the first {_MAX_LENGTH} of {body_len} characters" in text
        # The echoed body is exactly the configured limit, not the full 6000-x body.
        assert text.endswith(expected_echo)
        assert "x" * 6000 not in text


def test_large_valid_json_with_output_schema_succeeds(isolated_gateway):
    """A valid JSON body longer than the limit still validates and returns structured content."""
    client, token = isolated_gateway
    with _call_schema_tool(client, token, _LargeValidJSONHandler, tool_name="rest_large_valid_output_schema_probe") as (call_response, result):
        assert result.get("isError") is not True, call_response.text
        assert result.get("structuredContent") == {"results": ["x" * 6000]}
