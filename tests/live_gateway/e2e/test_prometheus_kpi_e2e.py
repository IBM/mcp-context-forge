# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_prometheus_kpi_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks for the operator KPI Prometheus metrics (issue #6880).

The gateway uses a temporary SQLite database and accepts only this test's
traffic. No existing gateway, Redis instance, or credentials are used.
"""

from __future__ import annotations

# Standard
from collections.abc import Callable, Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.plugins._helpers import call_tool, create_virtual_server, initialize_session, result_text

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]


class _UpstreamHandler(BaseHTTPRequestHandler):
    """Tiny upstream returning a fixed JSON payload."""

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        """Answer every GET with a small JSON document."""
        body = b'{"results": [1, 2, 3]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Silence request logging; the test output stays readable."""


def _wait_for_gateway(process: subprocess.Popen[bytes], client: httpx.Client, log_path: Path) -> None:
    """Wait until an isolated gateway becomes healthy.

    Args:
        process: Gateway subprocess.
        client: Client for the isolated gateway.
        log_path: Gateway log path for startup failures.
    """
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        assert process.poll() is None, log_path.read_text(encoding="utf-8")[-5000:]
        try:
            if client.get("/health").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    pytest.fail(f"Gateway startup timed out: {log_path.read_text(encoding='utf-8')[-5000:]}")


@pytest.fixture(name="prometheus_kpi_gateway")
def _prometheus_kpi_gateway(tmp_path: Path, unused_tcp_port_factory: Callable[[], int]) -> Generator[tuple[httpx.Client, str, str], None, None]:
    """Start a gateway with ENABLE_METRICS=true and a private database.

    Args:
        tmp_path: Temporary directory owned by pytest.
        unused_tcp_port_factory: Factory that selects an available TCP port.

    Yields:
        A tuple of an admin-authenticated client, the gateway base URL and the
        admin bearer token.
    """
    port = unused_tcp_port_factory()
    base_url = f"http://127.0.0.1:{port}"
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
        "MCP_REQUIRE_AUTH": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        "PLUGINS_ENABLED": "false",
        "ENABLE_METRICS": "true",
        "SSRF_ALLOW_LOCALHOST": "true",
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
    }
    admin_token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    log_path = tmp_path / "gateway.log"
    with log_path.open("w") as log_file:
        with subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        ) as process:
            try:
                with httpx.Client(base_url=base_url, headers=make_auth_headers(admin_token), timeout=15, trust_env=False) as client:
                    _wait_for_gateway(process, client, log_path)
                    yield client, base_url, admin_token
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _scrape(client: httpx.Client) -> str:
    """Fetch the Prometheus exposition and assert it succeeded.

    Args:
        client: Admin-authenticated client.

    Returns:
        The exposition text.
    """
    response = client.get("/metrics/prometheus", headers={"Accept-Encoding": "identity"})
    assert response.status_code == 200, response.text
    return response.text


def test_prometheus_kpi_metrics_exposed(prometheus_kpi_gateway: tuple[httpx.Client, str, str]) -> None:
    """Requests and a virtual-server tool call produce the KPI metric samples."""
    client, _base_url, token = prometheus_kpi_gateway

    # Produce one success and one templated 4xx through the gateway. An
    # unrouted path is skipped by the instrumentator, so the 4xx must come
    # from a registered route (/tools/{tool_id} on a missing id yields 404).
    assert client.get("/health").status_code == 200
    assert client.get(f"/tools/{uuid.uuid4()}").status_code == 404

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    tool_name = f"kpi_probe_{uuid.uuid4().hex[:8]}"
    try:
        created = client.post(
            "/tools",
            json={
                "tool": {
                    "name": tool_name,
                    "description": "KPI probe tool",
                    "integration_type": "REST",
                    "url": f"http://127.0.0.1:{upstream.server_port}/probe",
                    "request_type": "GET",
                    "visibility": "public",
                },
                "team_id": None,
            },
        )
        assert created.status_code == 200, created.text
        tool_id = created.json()["id"]

        server_id = create_virtual_server(client, name=f"{tool_name}_server", tool_ids=[tool_id])
        session_id = initialize_session(client, server_id=server_id, token=token)
        result = call_tool(client, server_id=server_id, token=token, tool_name=tool_name, arguments={}, session_id=session_id)
        assert result.get("isError") is not True, result_text(result)
        assert "results" in result_text(result)
    finally:
        upstream.shutdown()
        upstream.server_close()
        worker.join(timeout=5)

    text = _scrape(client)

    assert "e2e_request_duration_seconds_bucket{" in text
    assert 'requests_total{method="get",route_group="other"' in text
    assert 'request_errors_total{route_group="tools",server_id="",server_name="",status_class="4xx"' in text
    # The tool call ran through the virtual server, so its upstream duration
    # must carry the real server labels.
    assert 'virtual_server_upstream_duration_seconds_count{call_type="tools/call",server_id="' in text
    assert f',server_name="{tool_name}_server"' in text


def test_prometheus_kpi_metrics_denied_without_auth(prometheus_kpi_gateway: tuple[httpx.Client, str, str]) -> None:
    """Unauthenticated scrapes of the KPI endpoint are rejected."""
    client, base_url, _token = prometheus_kpi_gateway

    response = httpx.get(f"{base_url}/metrics/prometheus", timeout=15, trust_env=False)

    assert response.status_code in (401, 403), response.text
