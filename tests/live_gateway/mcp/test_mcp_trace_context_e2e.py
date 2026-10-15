# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_mcp_trace_context_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box W3C trace-context check for MCP ``tools/call`` against an isolated gateway.

The gateway subprocess runs with a ``sitecustomize`` shim that installs an
``instana.tracer.InstanaTracer`` emulating ``instana < 3.12``: ``get_tracer``
returns it for every instrumentation name, so the gateway middleware, the MCP
Python SDK (``mcp-python-sdk``), and FastAPI telemetry all see a tracer without
the OpenTelemetry ``context`` parameter. The production compatibility layer must
patch that tracer so authenticated ``tools/call`` still completes. A valid W3C
``traceparent`` arrives with the call; the request-root span must adopt that
inbound parent, so the active span and every span beneath it stay in one trace.
A marker file records that the incompatible path ran.

Run with the observability extra installed. The gateway uses a private SQLite
DB, real REST tool invocation, real HTTP requests, and the SDK console exporter.
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
from typing import Any

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.plugins._helpers import create_virtual_server, initialize_session, mcp_headers, result_text

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]

INBOUND_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"  # pragma: allowlist secret
INBOUND_SPAN_ID = "b7ad6b7169203331"  # pragma: allowlist secret
TOOL_NAME = "trace-context-probe"

# Emulate the legacy Instana provider (``instana < 3.12``): a tracer whose
# ``start_span``/``start_as_current_span`` do not accept the OpenTelemetry
# ``context`` keyword. A real legacy Instana AutoTrace replaces the global tracer
# provider, so *every* consumer sees the incompatible tracer -- the gateway's own
# middleware, the MCP Python SDK (``mcp-python-sdk``), and FastAPI telemetry. The
# shim registers the emulated class as ``instana.tracer.InstanaTracer`` so the
# production compatibility layer patches it exactly as it would patch the real one.
_SITECUSTOMIZE = '''
import os
import sys
import types

try:
    import opentelemetry.trace as _trace
except Exception:
    _trace = None

if _trace is not None and hasattr(_trace, "get_tracer"):
    _orig_get_tracer = _trace.get_tracer
    _marker = os.environ.get("MCP_TRACE_INCOMPATIBLE_MARKER")

    def _record(name):
        if not _marker:
            return
        try:
            with open(_marker, "a", encoding="utf-8") as handle:
                handle.write(name + "\\n")
        except OSError:
            pass

    class InstanaTracer:
        """Emulate ``instana.tracer.InstanaTracer`` before 3.12: no ``context`` parameter."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def start_span(self, name, *args, **kwargs):
            if "context" in kwargs:
                raise TypeError("start_span() got an unexpected keyword argument 'context'")
            return self._inner.start_span(name, *args, **kwargs)

        def start_as_current_span(self, name, *args, **kwargs):
            _record(name)
            if "context" in kwargs:
                raise TypeError("start_as_current_span() got an unexpected keyword argument 'context'")
            return self._inner.start_as_current_span(name, *args, **kwargs)

    def _wrapped_get_tracer(*args, **kwargs):
        return InstanaTracer(_orig_get_tracer(*args, **kwargs))

    _trace.get_tracer = _wrapped_get_tracer

    _instana_pkg = types.ModuleType("instana")
    _instana_pkg.__path__ = []
    _tracer_mod = types.ModuleType("instana.tracer")
    _tracer_mod.InstanaTracer = InstanaTracer
    _instana_pkg.tracer = _tracer_mod
    sys.modules["instana"] = _instana_pkg
    sys.modules["instana.tracer"] = _tracer_mod
'''


class _ToolHandler(BaseHTTPRequestHandler):
    """Return a fixed JSON body and record inbound request headers."""

    captured: list[list[tuple[str, str]]] = []

    def do_GET(self):
        """Record headers, then answer 200 with a JSON body."""
        type(self).captured.append(list(self.headers.items()))
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Keep the upstream server quiet."""


def _console_spans(log_path: Path) -> list[dict[str, Any]]:
    """Read complete SDK span JSON objects, ignoring gateway log lines."""
    contents = log_path.read_text(encoding="utf-8")
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


def _hex_id(value: Any) -> Any:
    """Normalize a console-exporter hex identifier by dropping the 0x prefix."""
    return value[2:] if isinstance(value, str) and value.startswith("0x") else value


def _wait_for_spans(log_path: Path, predicate, deadline_seconds: float = 15.0) -> list[dict[str, Any]]:
    """Poll the gateway log until ``predicate(spans)`` returns truthy or time runs out."""
    deadline = time.monotonic() + deadline_seconds
    spans: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        spans = _console_spans(log_path)
        if predicate(spans):
            return spans
        time.sleep(0.1)
    return spans


def _find_request_span(spans: list[dict[str, Any]], server_id: str) -> dict[str, Any] | None:
    """Return the middleware request-root span for ``server_id`` in the inbound trace, if exported."""
    expected_name = f"POST /servers/{server_id}/mcp/"
    for span in spans:
        if span.get("name") == expected_name and _hex_id(span.get("context", {}).get("trace_id")) == INBOUND_TRACE_ID:
            return span
    return None


def _find_tool_call_span(spans: list[dict[str, Any]], tool_name: str) -> dict[str, Any] | None:
    """Return the MCP ``tools/call`` span for ``tool_name`` in the inbound trace, if exported."""
    expected_name = f"tools/call {tool_name}"
    for span in spans:
        if span.get("name") == expected_name and _hex_id(span.get("context", {}).get("trace_id")) == INBOUND_TRACE_ID:
            return span
    return None


@pytest.fixture
def isolated_incompatible_gateway(tmp_path):
    """Start an authenticated gateway whose tracer rejects the ``context`` kwarg.

    Registers a REST tool backed by a local capture server and a virtual server
    that exposes it.

    Yields:
        A tuple of the authenticated client, bearer token, gateway log path,
        incompatibility marker path, virtual server id, and tool name.
    """
    trace_sdk = pytest.importorskip("opentelemetry.sdk.trace")
    if not hasattr(trace_sdk, "TracerProvider"):
        pytest.skip("OpenTelemetry SDK is not installed")

    harness_dir = tmp_path / "harness"
    harness_dir.mkdir()
    (harness_dir / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    marker_path = tmp_path / "incompatible.marker"

    _ToolHandler.captured = []
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _ToolHandler)
    upstream_worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_worker.start()

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join([str(harness_dir), str(_REPO_ROOT), *[str(Path(path).resolve()) for path in os.getenv("PYTHONPATH", "").split(os.pathsep) if path]]),
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
        "OBSERVABILITY_ENABLED": "false",
        "OTEL_ENABLE_OBSERVABILITY": "true",
        "OTEL_TRACES_EXPORTER": "console",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "",
        "MCP_TRACE_INCOMPATIBLE_MARKER": str(marker_path),
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
    }
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    log_path = tmp_path / "gateway.log"
    tool_id = None
    server_id = None
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
                    assert process.poll() is None, log_path.read_text(encoding="utf-8")[-5000:]
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Gateway startup timed out: {log_path.read_text(encoding='utf-8')[-5000:]}")

                response = client.post(
                    "/tools",
                    json={
                        "tool": {
                            "name": TOOL_NAME,
                            "description": "Trace-context probe tool",
                            "integration_type": "REST",
                            "url": f"http://127.0.0.1:{upstream.server_port}/probe",
                            "request_type": "GET",
                            "visibility": "public",
                        },
                        "team_id": None,
                    },
                )
                assert response.status_code == 200, response.text
                tool_id = response.json()["id"]
                server_id = create_virtual_server(client, name="trace-context-server", tool_ids=[tool_id])

                yield client, token, log_path, marker_path, server_id, TOOL_NAME
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            upstream.shutdown()
            upstream.server_close()
            upstream_worker.join(timeout=5)


def test_mcp_tools_call_preserves_inbound_trace_with_incompatible_tracer(isolated_incompatible_gateway):
    """An authenticated ``tools/call`` keeps the inbound trace through an incompatible tracer."""
    client, token, log_path, marker_path, server_id, tool_name = isolated_incompatible_gateway
    session_id = initialize_session(client, server_id=server_id, token=token)
    _ToolHandler.captured.clear()

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {}},
    }
    headers = mcp_headers(token, session_id=session_id)
    headers["traceparent"] = f"00-{INBOUND_TRACE_ID}-{INBOUND_SPAN_ID}-01"
    response = client.post(f"/servers/{server_id}/mcp/", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    result = response.json().get("result", {})
    assert result.get("isError") is not True, response.text
    assert "ok" in result_text(result)

    # The incompatible tracer path ran: the middleware fell back to the standard
    # context API instead of passing the ``context`` keyword.
    assert marker_path.exists(), "context-rejecting tracer was never exercised"
    assert f"POST /servers/{server_id}/mcp/" in marker_path.read_text(encoding="utf-8")

    spans = _wait_for_spans(log_path, lambda current: _find_request_span(current, server_id) is not None)
    request_span = _find_request_span(spans, server_id)
    assert request_span is not None, f"No request span was exported; exported spans: {[span['name'] for span in spans]}"
    # Parent identity: the request-root span continues the inbound trace.
    assert _hex_id(request_span["context"]["trace_id"]) == INBOUND_TRACE_ID
    assert _hex_id(request_span["parent_id"]) == INBOUND_SPAN_ID
    request_span_id = _hex_id(request_span["context"]["span_id"])
    assert request_span_id not in (None, "")

    # Active-span consistency: the tool invocation runs beneath the request-root
    # span, in the same inbound trace, so any downstream span nests under it.
    tool_span = _find_tool_call_span(spans, tool_name)
    assert tool_span is not None, f"No tools/call span was exported; exported spans: {[span['name'] for span in spans]}"
    assert _hex_id(tool_span["parent_id"]) == request_span_id

    # The tool reached the real upstream REST server, proving the request was
    # not short-circuited by the incompatible tracer.
    assert _ToolHandler.captured, "the tool did not reach the upstream REST server"
