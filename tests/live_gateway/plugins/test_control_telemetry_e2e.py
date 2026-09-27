# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_control_telemetry_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box denial telemetry checks against an isolated gateway subprocess.

Run with the observability extra installed. The gateway uses a private SQLite
DB, real plugin dispatch, real HTTP requests, and the SDK console exporter.
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
from cpex.framework import Plugin, PluginResult, PluginViolation
import httpx
import pytest
import yaml

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]


class TelemetryProbePlugin(Plugin):
    """A deterministic allowing or denying control loaded by the real gateway."""

    async def tool_pre_invoke(self, payload, context):
        """Deny only the final configured control, with explicitly opted-in metrics."""
        if self.config.name != "DenyingPlugin":
            return PluginResult(continue_processing=True)
        return PluginResult(
            continue_processing=False,
            violation=PluginViolation(reason="Policy matched", description="Blocked", code="POLICY_DENIED", http_status_code=403),
            metadata={"ordinary": "must-not-export"},
            denial_metadata={"rejected_count": 1, "score": 0.75, "matched": False, "remaining": 0, "backend": "must-not-export"},
        )


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


@pytest.fixture(params=[False, True], ids=["otel-only", "db-and-otel"])
def isolated_denial_gateway(request, tmp_path):
    """Start an authenticated gateway with 32 allowing controls followed by a denial."""
    pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")
    config_path = tmp_path / "plugins.yaml"
    entries = []
    for index in range(33):
        entries.append(
            {
                "name": "DenyingPlugin" if index == 32 else f"Allow{index}",
                "kind": f"{__name__}.TelemetryProbePlugin",
                "description": "Denial telemetry probe",
                "version": "1.0",
                "author": "ContextForge",
                "hooks": ["tool_pre_invoke"],
                "tags": [],
                "mode": "sequential",
                "priority": index,
                "config": {},
            }
        )
    config_path.write_text(yaml.safe_dump({"plugins": entries, "plugin_dirs": [], "plugin_settings": {"plugin_timeout": 30, "fail_on_plugin_error": True}}))
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
        "PLUGINS_ENABLED": "true",
        "PLUGINS_CONFIG_FILE": str(config_path),
        "OBSERVABILITY_ENABLED": str(request.param).lower(),
        "CPEX_CONTROL_TELEMETRY_ENABLED": "true",
        "CPEX_CONTROL_TELEMETRY_MAX_RESULTS": "32",
        "OTEL_ENABLE_OBSERVABILITY": "true",
        "OTEL_TRACES_EXPORTER": "console",
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
                yield client, log_path, request.param
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_denier_exported_once_without_upstream_dispatch(isolated_denial_gateway):
    """A late denial retains identity and safe metrics in real exported spans."""
    client, log_path, db_enabled = isolated_denial_gateway
    upstream_calls = []

    class UpstreamHandler(BaseHTTPRequestHandler):
        """Count any unexpected upstream dispatch after a pre-hook denial."""

        def do_POST(self):
            """Record a dispatch and respond so a regression fails without hanging."""
            upstream_calls.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, format, *args):
            """Keep the fixture HTTP server quiet."""

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    try:
        response = client.post(
            "/tools",
            json={
                "tool": {
                    "name": "denial_probe",
                    "description": "Denial telemetry",
                    "integrationType": "REST",
                    "url": f"http://127.0.0.1:{upstream.server_port}/probe",
                    "requestType": "POST",
                    "visibility": "public",
                },
                "team_id": None,
            },
        )
        assert response.status_code == 200, response.text
        response = client.post("/rpc", json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": response.json()["name"], "arguments": {"input": "sensitive-argument-marker"}}, "id": 1})
        assert response.status_code in (200, 400, 403, 422), response.text
        assert "POLICY_DENIED" in response.text, response.text
        assert upstream_calls == []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            spans = _console_spans(log_path)
            summaries = [span for span in spans if span["name"] == "cpex.control.summary"]
            if summaries:
                break
            time.sleep(0.05)
        assert len(summaries) == 1
        results = [span for span in spans if span["name"] == "cpex.control.result"]
        assert len(results) == 32
        denied = [span for span in results if span["attributes"]["cpex.control.result.allowed"] is False]
        assert len(denied) == 1
        attrs = denied[0]["attributes"]
        assert attrs["cpex.control.name"] == "DenyingPlugin"
        assert attrs["cpex.control.plugin_id"]
        assert attrs["cpex.control.hook_name"] == "tool_pre_invoke"
        assert denied[0]["parent_id"] == summaries[0]["context"]["span_id"]
        assert summaries[0]["attributes"]["cpex.control.result.allowed"] is False
        assert summaries[0]["attributes"]["cpex.control.truncated"] == 1
        if "denial_metadata" in PluginResult.model_fields:
            assert attrs["cpex.control.result.error_code"] == "POLICY_DENIED"
            assert attrs["cpex.control.result.http_status_code"] == 403
            assert attrs["cpex.control.result.metadata.rejected_count"] == 1
            assert attrs["cpex.control.result.metadata.score"] == 0.75
            assert attrs["cpex.control.result.metadata.matched"] is False
            assert attrs["cpex.control.result.metadata.remaining"] == 0
        assert "must-not-export" not in json.dumps([span["attributes"] for span in results])
        assert "sensitive-argument-marker" not in json.dumps([span["attributes"] for span in results])
        if db_enabled:
            # The internal DB trace ID is independent of the SDK trace ID.
            response = client.get("/observability/traces", params={"limit": 20})
            assert response.status_code == 200, response.text
            traces = response.json()
            if isinstance(traces, dict):
                traces = traces["traces"]
            rpc_trace = next(trace for trace in traces if trace["name"] == "POST /rpc")
            response = client.get(f"/observability/traces/{rpc_trace['trace_id']}")
            assert response.status_code == 200, response.text
            db_results = [span for span in response.json()["spans"] if span["name"] == "cpex.control.result"]
            assert [span["attributes"]["cpex.control.plugin_id"] for span in db_results] == [span["attributes"]["cpex.control.plugin_id"] for span in results]
    finally:
        upstream.shutdown()
        upstream.server_close()
        worker.join(timeout=5)
