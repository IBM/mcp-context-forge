# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_trace_context_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box W3C trace-context checks against an isolated gateway subprocess.

Run with the observability extra installed. The gateway uses a private SQLite
DB, real A2A invocation, real HTTP requests, and the SDK console exporter.
No existing gateway, Redis instance, or credentials are used.
"""

# Standard
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

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]

INBOUND_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"  # pragma: allowlist secret
INBOUND_SPAN_ID = "b7ad6b7169203331"  # pragma: allowlist secret
AGENT_NAME = "trace-e2e-agent"


def _console_spans(log_path):
    """Read complete SDK span JSON objects, ignoring gateway log lines."""
    contents = log_path.read_text()
    decoder = json.JSONDecoder()
    spans = []
    offset = 0
    while (offset := contents.find('{\n    "name":', offset)) >= 0:
        try:
            span, length = decoder.raw_decode(contents[offset:])
        except json.JSONDecodeError:
            break
        spans.append(span)
        offset += length
    return spans


def _hex_id(value):
    """Normalize a console-exporter hex identifier by dropping the 0x prefix."""
    return value[2:] if isinstance(value, str) and value.startswith("0x") else value


class HeaderCaptureHandler(BaseHTTPRequestHandler):
    """Record inbound POST headers and return a minimal JSON response."""

    captured = []

    def do_POST(self):
        """Capture request headers and answer 200 with a JSON body."""
        type(self).captured.append(list(self.headers.items()))
        body = b'{"response": "ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Keep the capture server quiet."""


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture(params=[False, True], ids=["baggage-external-disabled", "baggage-external-enabled"], scope="module")
def isolated_a2a_gateway(request, tmp_path_factory):
    """Start an authenticated gateway with OTEL console export and a registered A2A agent.

    The agent endpoint is a local header-capture server. Baggage propagation
    to external services is parametrized so the disabled policy and the
    sanitized enabled path are both exercised against the real SDK.
    """
    trace_sdk = pytest.importorskip("opentelemetry.sdk.trace")
    if not hasattr(trace_sdk, "TracerProvider"):
        pytest.skip("OpenTelemetry SDK is not installed")

    tmp_path = tmp_path_factory.mktemp("a2a-trace-gateway")
    propagate_external = request.param

    HeaderCaptureHandler.captured = []
    capture_server = ThreadingHTTPServer(("127.0.0.1", 0), HeaderCaptureHandler)
    capture_worker = threading.Thread(target=capture_server.serve_forever, daemon=True)
    capture_worker.start()

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
        "MCPGATEWAY_A2A_ENABLED": "true",
        "SSRF_ALLOW_LOCALHOST": "true",
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
        "OTEL_ENABLE_OBSERVABILITY": "true",
        "OTEL_TRACES_EXPORTER": "console",
        "OTEL_BAGGAGE_ENABLED": str(propagate_external).lower(),
        "OTEL_BAGGAGE_PROPAGATE_TO_EXTERNAL": str(propagate_external).lower(),
        "OTEL_BAGGAGE_HEADER_MAPPINGS": '[{"header_name": "X-Review-Marker", "baggage_key": "review-marker"}]',
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

                response = client.post(
                    "/a2a",
                    json={
                        "agent": {
                            "name": AGENT_NAME,
                            "description": "Header-capture agent for trace context tests",
                            "endpoint_url": f"http://127.0.0.1:{capture_server.server_port}/invoke",
                            "agent_type": "generic",
                        },
                        "visibility": "public",
                    },
                )
                assert response.status_code in (200, 201), response.text

                yield client, log_path, propagate_external
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            capture_server.shutdown()
            capture_server.server_close()
            capture_worker.join(timeout=5)


def _wait_for_spans(log_path, names, deadline_seconds=15):
    """Poll the gateway log until spans with the given names are exported."""
    deadline = time.monotonic() + deadline_seconds
    by_name = {}
    while time.monotonic() < deadline:
        spans = _console_spans(log_path)
        by_name = {}
        for span in spans:
            by_name.setdefault(span["name"], []).append(span)
        if all(name in by_name for name in names):
            break
        time.sleep(0.1)
    missing = [name for name in names if name not in by_name]
    if missing:
        pytest.fail(f"Timed out waiting for spans {names}; got {sorted(by_name)} from {log_path}")
    return by_name


def test_a2a_invoke_continues_incoming_trace(isolated_a2a_gateway):
    """One trace spans the inbound request, the a2a.invoke span, and the downstream call."""
    client, log_path, propagate_external = isolated_a2a_gateway
    HeaderCaptureHandler.captured.clear()

    response = client.post(
        f"/a2a/{AGENT_NAME}/invoke",
        json={"parameters": {"prompt": "trace me"}},
        headers={
            "traceparent": f"00-{INBOUND_TRACE_ID}-{INBOUND_SPAN_ID}-01",  # pragma: allowlist secret
            "baggage": "review-marker=internal",
            "X-Review-Marker": "internal",
        },
    )
    assert response.status_code == 200, response.text

    by_name = _wait_for_spans(log_path, [f"POST /a2a/{AGENT_NAME}/invoke", "a2a.invoke"])
    request_span = by_name[f"POST /a2a/{AGENT_NAME}/invoke"][-1]
    invoke_span = by_name["a2a.invoke"][-1]

    request_trace_id = _hex_id(request_span["context"]["trace_id"])
    request_span_id = _hex_id(request_span["context"]["span_id"])
    invoke_span_id = _hex_id(invoke_span["context"]["span_id"])

    # The inbound W3C parent is adopted: one trace ID end to end.
    assert request_trace_id == INBOUND_TRACE_ID
    assert _hex_id(request_span["parent_id"]) == INBOUND_SPAN_ID
    assert _hex_id(invoke_span["context"]["trace_id"]) == INBOUND_TRACE_ID
    assert _hex_id(invoke_span["parent_id"]) == request_span_id
    # Inbound, request, and invocation span IDs are distinct.
    assert len({INBOUND_SPAN_ID, request_span_id, invoke_span_id}) == 3

    # The downstream agent received exactly one traceparent, parented at the
    # a2a.invoke span — proving injection of the real active span, not a copy.
    assert len(HeaderCaptureHandler.captured) == 1
    downstream = HeaderCaptureHandler.captured[0]
    traceparents = [value for key, value in downstream if key.lower() == "traceparent"]
    assert traceparents == [f"00-{INBOUND_TRACE_ID}-{invoke_span_id}-01"]

    # Context baggage crosses to the external agent only when policy permits.
    # With baggage disabled at ingress, the raw inbound header reaches the
    # OTEL context via propagator extraction and must still be withheld.
    # With baggage enabled, the mapped X-Review-Marker header lands in the
    # context through the allowlisted conversion and must propagate.
    baggage_headers = [value for key, value in downstream if key.lower() == "baggage"]
    if propagate_external:
        assert any("review-marker=internal" in value for value in baggage_headers)
    else:
        assert baggage_headers == []


def test_unauthenticated_invoke_sends_no_outbound_request(isolated_a2a_gateway):
    """An unauthenticated invoke is rejected before any dispatch to the agent."""
    client, _log_path, _propagate_external = isolated_a2a_gateway
    HeaderCaptureHandler.captured.clear()

    with httpx.Client(base_url=str(client.base_url), timeout=15, trust_env=False) as anonymous:
        response = anonymous.post(f"/a2a/{AGENT_NAME}/invoke", json={"parameters": {"prompt": "deny me"}})
    assert response.status_code in (401, 403), response.text
    assert not HeaderCaptureHandler.captured
