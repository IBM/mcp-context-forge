# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_environment_settings.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify file configuration against an isolated gateway started through the CLI.
"""

# Standard
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.plugins._helpers import create_virtual_server

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("name", ["HOST", "MCG_HOST"])
@pytest.mark.parametrize("source", ["process", "file"])
def test_cli_rejects_empty_configured_host_before_startup(tmp_path, name, source):
    """Empty host defaults cause a clean CLI exit before loading an application."""
    environment = {"PATH": os.environ["PATH"], "PYTHONPATH": str(_REPO_ROOT), "PYTHONUNBUFFERED": "1"}
    if source == "process":
        environment[name] = ""
    else:
        (tmp_path / ".env").write_text(f"{name}=\n")
    result = subprocess.run(
        [sys.executable, "-B", "-m", "mcpgateway.cli", "unloaded_app:app", "--port=0"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    assert "Invalid listener configuration" in result.stderr
    assert "host" in result.stderr
    assert "at least 1 character" in result.stderr
    assert "Error loading ASGI app" not in result.stderr
    assert "Uvicorn running" not in result.stderr
    assert "Traceback" not in result.stderr


class _HeaderEchoHandler(BaseHTTPRequestHandler):
    """Return received headers for file-only allowlist verification."""

    def do_GET(self):
        """Return upstream request headers as JSON."""
        body = json.dumps(dict(self.headers)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Suppress fixture access logs."""


def _verify_file_header_allowlist(client, token):
    """Check allowed forwarding and denied headers through authenticated tool calls."""
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _HeaderEchoHandler)
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    try:
        headers = make_auth_headers(token)
        response = client.post(
            "/tools",
            headers=headers,
            json={"tool": {"name": "file_header_echo", "integration_type": "REST", "url": f"http://127.0.0.1:{upstream.server_port}/", "request_type": "GET", "visibility": "public"}},
        )
        assert response.status_code == 200, response.text
        tool = response.json()
        client.headers.update(headers)
        server_id = create_virtual_server(client, name="file_header_server", tool_ids=[tool["id"]])
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool["name"], "server_id": server_id, "arguments": {}}}
        client.headers.clear()
        assert client.post("/rpc", json=payload).status_code in (401, 403)
        response = client.post("/rpc", json=payload, headers={**headers, "X-File-Allowed": "allowed-sentinel", "X-File-Denied": "denied-sentinel"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert "error" not in result, result
        assert not result["result"].get("isError"), result
        assert "allowed-sentinel" in response.text
        assert "denied-sentinel" not in response.text
    finally:
        upstream.shutdown()
        upstream.server_close()
        worker.join(timeout=5)


@pytest.mark.parametrize("options", [["--port", "0"], ["--port=0"]])
def test_cli_explicit_ephemeral_port(tmp_path, options):
    """Uvicorn binds an ephemeral port through the CLI despite invalid unused defaults."""
    (tmp_path / ".env").write_text("PORT=invalid\nMCG_PORT=invalid\n")
    (tmp_path / "ephemeral_app.py").write_text(
        'async def app(scope, receive, send):\n    await send({"type": "http.response.start", "status": 200, "headers": []})\n    await send({"type": "http.response.body", "body": b"ready"})\n'
    )
    environment = {"PATH": os.environ["PATH"], "PYTHONPATH": os.pathsep.join((str(_REPO_ROOT), str(tmp_path))), "PORT": "invalid", "PYTHONUNBUFFERED": "1"}
    log_path = tmp_path / "ephemeral.log"
    with log_path.open("w") as log_file:
        with subprocess.Popen(
            [sys.executable, "-B", "-m", "mcpgateway.cli", "ephemeral_app:app", "--host=127.0.0.1", *options, "--lifespan=off", "--log-level=info"],
            cwd=tmp_path,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        ) as process:
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    output = log_path.read_text()
                    assert process.poll() is None, output
                    address = re.search(r"Uvicorn running on (http://127\.0\.0\.1:(\d+))", output)
                    if address:
                        assert int(address.group(2)) > 0
                        with httpx.Client(trust_env=False) as client:
                            response = client.get(address.group(1))
                        assert response.status_code == 200
                        assert response.text == "ready"
                        break
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Ephemeral listener startup timed out: {output}")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@pytest.mark.parametrize("enabled", [True, False])
def test_cli_file_configuration_and_metrics_authorization(tmp_path, unused_tcp_port, enabled):
    """File values control listener and metrics while preserving authentication and feature gates."""
    signing_key = secrets.token_urlsafe(48)
    config = {
        "HOST": "127.0.0.1",
        "PORT": str(unused_tcp_port),
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
        "PLUGINS_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
        "LOG_TO_FILE": "false",
        "ENABLE_METRICS": str(enabled).lower(),
        "METRICS_CUSTOM_LABELS": "region=environment-test",
        "OTEL_ENABLE_OBSERVABILITY": "false",
        "METRICS_CLEANUP_ENABLED": "false",
        "METRICS_ROLLUP_ENABLED": "false",
        "TOOLOPS_ENABLED": "false",
        "OPENAI_MAX_RETRIES": "invalid",
        "SQLALCHEMY_ECHO": "",
        "ENABLE_HEADER_PASSTHROUGH": "true",
        "DEFAULT_PASSTHROUGH_HEADERS": '["X-File-Allowed"]',
        "SSRF_ALLOW_LOCALHOST": "true",
    }
    (tmp_path / ".env").write_text("\n".join(f"{key}={value}" for key, value in config.items()) + "\n")
    environment = {"PATH": os.environ["PATH"], "PYTHONPATH": str(_REPO_ROOT), "PYTHONUNBUFFERED": "1"}
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    log_path = tmp_path / "startup.log"
    with log_path.open("w") as log_file:
        with subprocess.Popen(
            [sys.executable, "-B", "-m", "mcpgateway.cli"],
            cwd=tmp_path,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        ) as process:
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{unused_tcp_port}", timeout=15, trust_env=False) as client:
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
                    assert client.get("/metrics/prometheus").status_code in (401, 403)
                    assert client.get("/metrics/prometheus", headers=make_auth_headers("invalid-token")).status_code in (401, 403)
                    response = client.get("/metrics/prometheus", headers=make_auth_headers(token))
                    assert response.status_code == (200 if enabled else 503), response.text
                    if enabled:
                        assert 'region="environment-test"' in response.text
                        assert 'engine="sqlite"' in response.text
                        _verify_file_header_allowlist(client, token)
                    else:
                        assert response.json()["error"] == "Metrics collection is disabled"
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
