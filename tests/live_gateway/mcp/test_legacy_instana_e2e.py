# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_legacy_instana_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box regression for legacy Instana AutoTrace (``instana < 3.12``, issue #7208).

Legacy ``InstanaTracer`` rejects the OpenTelemetry ``context=`` keyword used by
FastAPI native telemetry (``start_span``), the MCP SDK 2.x (``start_as_current_span``),
and ContextForge. This test boots an isolated gateway subprocess under the real
Instana AutoTrace bootstrap (``AUTOWRAPT_BOOTSTRAP=instana``), registers a real
streamable-HTTP MCP upstream, and verifies ``/health`` plus an authenticated MCP
``tools/call`` succeed with no escaping context-keyword ``TypeError``.

Run (opt-in; fails rather than skips when ``LEGACY_INSTANA_E2E=1``)::

    LEGACY_INSTANA_E2E=1 uv run --extra observability \\
        --with "instana==3.11.1" \\
        pytest tests/live_gateway/mcp/test_legacy_instana_e2e.py -v

No Instana backend is needed; the agent host points at an unused loopback port.
The gateway uses a private SQLite DB and per-run ephemeral signing keys.
"""

# Standard
import asyncio
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import re
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

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]
_OPT_IN = os.getenv("LEGACY_INSTANA_E2E", "").lower() in {"1", "true", "yes"}
_CONTEXT_TYPE_ERROR = re.compile(r"TypeError:.*unexpected keyword argument '?context'?")


def _unavailable(reason):
    """Fail when explicitly enabled; otherwise skip."""
    if _OPT_IN:
        pytest.fail(reason)
    pytest.skip(reason)


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture(scope="module")
def upstream_mcp_server():
    """Serve a real streamable-HTTP MCP upstream exposing an ``echo`` tool."""
    # Third-Party
    from mcp.server.mcpserver import MCPServer
    import uvicorn

    app = MCPServer("legacy-instana-upstream")

    @app.tool()
    def echo(text: str) -> str:
        """Return the supplied text."""
        return f"echo:{text}"

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app.streamable_http_app(host="127.0.0.1", stateless_http=True, json_response=True), host="127.0.0.1", port=port, log_level="error"))
    worker = threading.Thread(target=server.run, daemon=True)
    worker.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "upstream MCP server failed to start"
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    worker.join(timeout=5)


@pytest.fixture(scope="module")
def legacy_instana_gateway(tmp_path_factory, upstream_mcp_server):
    """Boot a gateway under legacy Instana AutoTrace and register the upstream."""
    try:
        instana_version = version("instana")
    except PackageNotFoundError:
        _unavailable("instana is not installed; run with --with 'instana==3.11.1'")
    if tuple(int(part) for part in instana_version.split(".")[:2]) >= (3, 12):
        _unavailable(f"instana {instana_version} supports `context=`; a legacy (< 3.12) sensor is required")

    tmp_path = tmp_path_factory.mktemp("legacy-instana-gateway")
    gateway_port = _free_port()
    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(_REPO_ROOT),
        "AUTOWRAPT_BOOTSTRAP": "instana",
        "INSTANA_SERVICE_NAME": "contextforge-legacy-instana-e2e",
        "INSTANA_AGENT_HOST": "127.0.0.1",
        "INSTANA_AGENT_PORT": str(_free_port()),
        # gevent is only present in dev envs (via locust); production images lack it.
        # Instana would otherwise gevent.monkey.patch_all(), which breaks anyio.
        "INSTANA_GEVENT_MONKEY_OPTIONS": "no-socket,no-dns,no-time,no-select,no-thread,no-os,no-ssl,no-subprocess,no-sys,no-aggressive,no-event,no-builtins,no-signal,no-queue,no-contextvars",
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
        "SSRF_ALLOW_LOCALHOST": "true",
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
        # ContextForge's own request-root middleware runs on the Instana global provider.
        "OTEL_ENABLE_OBSERVABILITY": "true",
        "OTEL_TRACES_EXPORTER": "console",
        "LOG_LEVEL": "INFO",
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
            base_url = f"http://127.0.0.1:{gateway_port}"
            with httpx.Client(base_url=base_url, headers=make_auth_headers(token), timeout=15, trust_env=False) as client:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()[-5000:]
                    try:
                        client.get("/health")
                        break
                    except httpx.TransportError:
                        time.sleep(0.2)
                else:
                    pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-5000:]}")

                response = client.post(
                    "/gateways",
                    json={"name": "legacy-instana-upstream", "url": upstream_mcp_server, "transport": "STREAMABLEHTTP", "visibility": "public"},
                )
                assert response.status_code in (200, 201), response.text
                gateway_id = response.json()["id"]

                tool_name = None
                deadline = time.monotonic() + 30
                while tool_name is None and time.monotonic() < deadline:
                    tools = client.get("/tools", params={"limit": 0, "gateway_id": gateway_id})
                    if tools.status_code == 200:
                        tool_name = next((tool["name"] for tool in tools.json() if tool.get("name", "").endswith("echo")), None)
                    if tool_name is None:
                        time.sleep(0.5)
                assert tool_name, f"upstream echo tool was not discovered: {log_path.read_text()[-3000:]}"

                yield {"client": client, "base_url": base_url, "token": token, "tool_name": tool_name, "log_path": log_path}
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_gateway_runs_under_legacy_instana(legacy_instana_gateway):
    """The gateway process is actually instrumented by the legacy Instana sensor and adapter."""
    log = legacy_instana_gateway["log_path"].read_text()
    assert "Adapted legacy InstanaTracer.start_span" in log, log[-3000:]
    assert "Adapted legacy InstanaTracer.start_as_current_span" in log, log[-3000:]


def test_health_ok_under_legacy_instana(legacy_instana_gateway):
    """FastAPI native telemetry calls ``start_span(context=...)`` on every request."""
    response = legacy_instana_gateway["client"].get("/health")
    assert response.status_code == 200, response.text


def test_mcp_tools_call_under_legacy_instana(legacy_instana_gateway):
    """Authenticated streamable-HTTP MCP ``tools/call`` completes with no context TypeError."""
    # Third-Party
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    async def _call():
        http_client = create_mcp_http_client(headers=make_auth_headers(legacy_instana_gateway["token"]), timeout=httpx2.Timeout(15.0))
        async with streamable_http_client(f"{legacy_instana_gateway['base_url']}/mcp/", http_client=http_client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream, read_timeout_seconds=15.0) as session:
                await session.initialize()
                return await session.call_tool(legacy_instana_gateway["tool_name"], {"text": "instana"})

    result = asyncio.run(_call())
    assert not result.is_error, result
    assert any("echo:instana" in getattr(item, "text", "") for item in result.content), result

    log = legacy_instana_gateway["log_path"].read_text()
    assert not _CONTEXT_TYPE_ERROR.search(log), log[-5000:]


def test_unauthenticated_mcp_rejected_under_legacy_instana(legacy_instana_gateway):
    """Deny path: unauthenticated MCP requests are still rejected."""
    with httpx.Client(base_url=legacy_instana_gateway["base_url"], timeout=15, trust_env=False) as anonymous:
        response = anonymous.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 401, response.text
