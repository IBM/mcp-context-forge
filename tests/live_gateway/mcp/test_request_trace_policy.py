# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_request_trace_policy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify request tracing and health suppression through a real OTLP collector.
"""

# Standard
from collections.abc import Callable, Iterator
from contextlib import ExitStack
import gzip
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

pytestmark = pytest.mark.e2e
_ROOT = Path(__file__).resolve().parents[3]
_UPSTREAM = '''
import json
from pathlib import Path
import sys
from mcp.server.mcpserver import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn
mcp = MCPServer("trace-policy")
@mcp.tool()
def echo(value: str) -> str:
    """Return the supplied value."""
    return value
class Capture(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        body = await request.body()
        with Path(sys.argv[2]).open("a") as output:
            output.write(json.dumps({"method": request.method, "body": body.decode()}) + "\\n")
        return await call_next(request)
app = mcp.streamable_http_app(stateless_http=True, json_response=True)
app.add_middleware(Capture)
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="error")
'''


def _port() -> int:
    """Reserve an ephemeral loopback port number."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait(predicate: Callable[[], bool], description: str, timeout: float = 30) -> None:
    """Poll a condition within a bounded deadline."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    pytest.fail(f"Timed out waiting for {description}")


def _stop(process: subprocess.Popen[Any]) -> None:
    """Terminate a child process and reap its exit status."""
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _ready(url: str, process: subprocess.Popen[Any]) -> bool:
    """Return whether an HTTP process responds, failing on an early exit."""
    assert process.poll() is None, "Server exited before readiness"
    try:
        return httpx.get(url, timeout=1, trust_env=False).status_code < 500
    except httpx.TransportError:
        return False


@pytest.fixture(params=[False, True], ids=["request-only", "system-traces"])
def traced_gateway(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Any]:
    """Start an authenticated gateway, MCP SDK upstream, and recording OTLP collector."""
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    batches: list[list[dict[str, Any]]] = []
    lock = threading.Lock()
    payload_path = tmp_path / "collector.jsonl"

    class Collector(BaseHTTPRequestHandler):
        """Decode and persist every exported OTLP span batch."""

        def do_POST(self) -> None:
            """Accept OTLP protobuf and return an empty success response."""
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if self.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            message = ExportTraceServiceRequest.FromString(body)
            spans = [
                {
                    "name": span.name,
                    "trace_id": span.trace_id.hex(),
                    "span_id": span.span_id.hex(),
                    "parent_span_id": span.parent_span_id.hex(),
                    "kind": span.kind,
                    "attributes": {item.key: item.value.string_value for item in span.attributes},
                }
                for resource in message.resource_spans
                for scope in resource.scope_spans
                for span in scope.spans
            ]
            with lock:
                batches.append(spans)
                with payload_path.open("a", encoding="utf-8") as output:
                    output.write(json.dumps(spans) + "\n")
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            """Suppress collector access logs."""

    def snapshot() -> list[list[dict[str, Any]]]:
        with lock:
            return [list(batch) for batch in batches]

    with ExitStack() as stack:
        collector = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
        worker = threading.Thread(target=collector.serve_forever, daemon=True)
        worker.start()
        stack.callback(collector.server_close)
        stack.callback(worker.join, 5)
        stack.callback(collector.shutdown)
        upstream_port, gateway_port = _port(), _port()
        upstream_events = tmp_path / "upstream.jsonl"
        upstream_log = stack.enter_context((tmp_path / "upstream.log").open("w", encoding="utf-8"))
        upstream = subprocess.Popen([sys.executable, "-c", _UPSTREAM, str(upstream_port), str(upstream_events)], stdout=upstream_log, stderr=subprocess.STDOUT, cwd=tmp_path)
        stack.callback(_stop, upstream)
        _wait(lambda: _ready(f"http://127.0.0.1:{upstream_port}/", upstream), "MCP upstream")
        signing_key = secrets.token_urlsafe(48)
        env = {
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(_ROOT),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
            "CACHE_TYPE": "memory",
            "REDIS_URL": "",
            "JWT_SECRET_KEY": signing_key,
            "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
            "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
            "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
            "PLATFORM_ADMIN_EMAIL": "admin@example.com",
            "AUTH_REQUIRED": "true",
            "MCP_REQUIRE_AUTH": "true",
            "REQUIRE_USER_IN_DB": "false",
            "MCPGATEWAY_ADMIN_API_ENABLED": "true",
            "MCPGATEWAY_UI_ENABLED": "false",
            "MCPGATEWAY_A2A_ENABLED": "false",
            "SSRF_ALLOW_LOCALHOST": "true",
            "PLUGINS_ENABLED": "false",
            "OBSERVABILITY_ENABLED": "false",
            "OTEL_ENABLE_OBSERVABILITY": "true",
            "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{collector.server_port}",
            "OTEL_BSP_SCHEDULE_DELAY": "100",
            "OTEL_SYSTEM_TRACES_ENABLED": str(request.param).lower(),
            "OTEL_HTTPX_INSTRUMENTATION_ENABLED": "true",
            "OTEL_SQLALCHEMY_INSTRUMENTATION_ENABLED": "false",
            "OTEL_REDIS_INSTRUMENTATION_ENABLED": "false",
            "OTEL_BAGGAGE_ENABLED": "true",
            "OTEL_BAGGAGE_HEADER_MAPPINGS": json.dumps([{"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"}, {"header_name": "X-Sensitive-Probe", "baggage_key": "password"}]),
            "HEALTH_CHECK_INTERVAL": "1",
            "AUTO_REFRESH_SERVERS": "false",
            "LOG_LEVEL": "ERROR",
            "PYTHONUNBUFFERED": "1",
        }
        gateway_log = stack.enter_context((tmp_path / "gateway.log").open("w", encoding="utf-8"))
        gateway = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)], env=env, cwd=tmp_path, stdout=gateway_log, stderr=subprocess.STDOUT
        )
        stack.callback(_stop, gateway)
        _wait(lambda: _ready(f"http://127.0.0.1:{gateway_port}/health", gateway), "gateway readiness", timeout=60)
        token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key)
        client = stack.enter_context(httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", headers=make_auth_headers(token), timeout=30, trust_env=False))
        response = client.post("/gateways", json={"name": "trace-upstream", "url": f"http://127.0.0.1:{upstream_port}/mcp", "transport": "STREAMABLEHTTP", "visibility": "public"})
        assert response.status_code in (200, 201), response.text
        tools = client.get("/tools").json()
        if isinstance(tools, dict):
            tools = tools["tools"]
        tool = next(tool for tool in tools if tool.get("originalName", tool.get("original_name")) == "echo" or tool["name"].endswith("echo"))
        response = client.post("/servers", json={"server": {"name": "trace-server", "associated_tools": [tool["id"]]}, "visibility": "public"})
        assert response.status_code in (200, 201), response.text
        yield client, response.json()["id"], tool["name"], snapshot, upstream_events, request.param, tmp_path


def _spans(snapshot: Callable[[], list[list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    """Flatten captured export batches."""
    return [span for batch in snapshot() for span in batch]


def _invoke(client: httpx.Client, server_id: str, tool_name: str, trace_id: str, sampled: str) -> None:
    """Invoke a federated MCP tool with explicit trace and baggage headers."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def invoke() -> None:
        headers = dict(client.headers)
        headers.update({"traceparent": f"00-{trace_id}-0123456789abcdef-{sampled}", "X-Tenant-ID": "tenant-a", "X-Sensitive-Probe": "private-probe-value"})
        import httpx2

        async with httpx2.AsyncClient(headers=headers, timeout=30, trust_env=False) as http_client:
            async with streamable_http_client(f"{str(client.base_url).rstrip('/')}/servers/{server_id}/mcp", http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, {"value": "trace-probe"})
                    assert not result.is_error, result
                    assert any(getattr(item, "text", "") == "trace-probe" for item in result.content)

    import asyncio

    asyncio.run(invoke())


def test_request_trace_policy(traced_gateway: Any) -> None:
    """Preserve request trees and suppress confirmed background health cycles by default."""
    client, server_id, tool_name, snapshot, events, system_enabled, artifacts = traced_gateway
    trace_id = secrets.token_hex(16)
    _invoke(client, server_id, tool_name, trace_id, "01")
    _wait(lambda: any(span["trace_id"] == trace_id and span["kind"] == 3 for span in _spans(snapshot)), "request HTTPX export")
    request_spans = [span for span in _spans(snapshot) if span["trace_id"] == trace_id]
    for kind in (1, 2, 3):
        matching = [span for span in request_spans if span["kind"] == kind]
        assert matching, (kind, artifacts)
        assert any(span["attributes"].get("baggage.tenant.id") == "tenant-a" for span in matching), matching
    service = next(span for span in request_spans if span["name"] == "tool.invoke")
    assert service["attributes"]["baggage.tenant.id"] == "tenant-a"
    httpx_spans = [span for span in request_spans if span["kind"] == 3 and span["name"] == "POST"]
    assert httpx_spans
    assert all(span["attributes"].get("baggage.tenant.id") == "tenant-a" for span in httpx_spans)
    span_ids = {span["span_id"] for span in request_spans}
    assert service["parent_span_id"] in span_ids
    assert all(span["parent_span_id"] in span_ids for span in httpx_spans)
    assert "private-probe-value" not in json.dumps(snapshot())
    unsampled_id = secrets.token_hex(16)
    _invoke(client, server_id, tool_name, unsampled_id, "00")
    time.sleep(1)
    assert not any(span["trace_id"] == unsampled_id for span in _spans(snapshot))
    before = events.read_text(encoding="utf-8").count("\n")
    baseline = len(snapshot())
    _wait(lambda: events.read_text(encoding="utf-8").count("\n") > before, "background health activity")
    time.sleep(1)
    captured = snapshot()
    assert all(batch for batch in captured), artifacts
    background = [span for span in _spans(snapshot) if span["name"].startswith("gateway.health_check")]
    if system_enabled:
        assert background, artifacts
    else:
        assert not background, artifacts
        assert len(captured) == baseline, artifacts
