# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_auto_refresh_last_refresh_at.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box regression for #7095: auto-refresh throttle skip-every-other-cycle.

Boots an isolated gateway subprocess with a short health-check interval, registers
a real MCP server via mcpgateway.translate --stdio, waits for two consecutive
auto-refresh cycles, and confirms that last_refresh_at advances after each cycle.
"""

# Future
from __future__ import annotations

# Standard
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_test_jwt

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CYCLE_INTERVAL = 4  # seconds — short enough to observe two cycles quickly
_STARTUP_TIMEOUT = 60  # seconds for gateway and translate server startup


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_http(url: str, deadline: float) -> bool:
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def isolated_refresh_gateway():
    """Start a private gateway and a translate-wrapped stdio MCP server.

    The gateway runs with a 4-second health-check and auto-refresh interval
    so two cycles complete in under 10 seconds.  The translate server exposes
    a minimal JSON-RPC stdio script that responds to MCP initialize.
    """
    gateway_port = _free_port()
    translate_port = _free_port()
    signing_key = secrets.token_urlsafe(48)
    tmp = Path(tempfile.mkdtemp(prefix=f"refresh-gw-{gateway_port}-"))

    # Minimal stdio MCP server script: answers initialize and tools/list.
    stdio_script = tmp / "echo_mcp.py"
    stdio_script.write_text(
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    req = json.loads(line)\n"
        "    m = req.get('method', '')\n"
        "    rid = req.get('id')\n"
        "    if m == 'initialize':\n"
        "        r = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'echo', 'version': '1.0'}}\n"
        "    elif m == 'tools/list':\n"
        "        r = {'tools': [{'name': 'echo', 'description': 'echo', 'inputSchema': {'type': 'object', 'properties': {}}}]}\n"
        "    else:\n"
        "        r = {}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': r}), flush=True)\n"
    )

    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join(
            [str(_REPO_ROOT)] + [p for p in os.getenv("PYTHONPATH", "").split(os.pathsep) if p]
        ),
        "DATABASE_URL": f"sqlite:///{tmp / 'gw.db'}",
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
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
        # Short cycles so the test completes quickly.
        "GW_HEALTH_CHECK_INTERVAL": str(_CYCLE_INTERVAL),
        "GATEWAY_AUTO_REFRESH_INTERVAL": str(_CYCLE_INTERVAL),
        "AUTO_REFRESH_SERVERS": "true",
    }

    log_path = tmp / "gateway.log"
    translate_log = tmp / "translate.log"

    # Start translate server first so the gateway can reach it on registration.
    with translate_log.open("w") as tlog:
        translate_proc = subprocess.Popen(
            [sys.executable, "-m", "mcpgateway.translate", "--stdio", str(stdio_script), "--port", str(translate_port)],
            cwd=str(tmp),
            env={**env, "PYTHONPATH": env["PYTHONPATH"]},
            stdout=tlog,
            stderr=subprocess.STDOUT,
        )

    translate_deadline = time.monotonic() + _STARTUP_TIMEOUT
    if not _wait_http(f"http://127.0.0.1:{translate_port}/healthz", translate_deadline):
        translate_proc.terminate()
        pytest.skip(f"translate server failed to start on port {translate_port}")

    with log_path.open("w") as log_file:
        gw_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)],
            cwd=str(tmp),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    gw_deadline = time.monotonic() + _STARTUP_TIMEOUT
    if not _wait_http(f"http://127.0.0.1:{gateway_port}/health", gw_deadline):
        gw_proc.terminate()
        translate_proc.terminate()
        pytest.skip(f"gateway failed to start on port {gateway_port}: {log_path.read_text()[-2000:]}")

    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"http://127.0.0.1:{gateway_port}"

    # Register the translate server as a gateway.
    reg = httpx.post(
        f"{base}/v1/gateways",
        headers=headers,
        json={"name": "regression-7095", "url": f"http://127.0.0.1:{translate_port}/sse", "transport": "sse", "enabled": True},
        timeout=15.0,
    )
    if reg.status_code not in (200, 201):
        gw_proc.terminate()
        translate_proc.terminate()
        pytest.skip(f"gateway registration failed ({reg.status_code}): {reg.text}")

    gw_id = reg.json()["id"]

    try:
        yield base, headers, gw_id
    finally:
        gw_proc.terminate()
        translate_proc.terminate()
        for p in (gw_proc, translate_proc):
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)


def test_auto_refresh_writes_last_refresh_at(isolated_refresh_gateway):
    """Auto-refresh must write last_refresh_at after each health cycle.

    Waits for two health-check cycles to complete and asserts that
    last_refresh_at is non-null and advances between cycles — confirming
    that the production write path in _refresh_gateway_tools_resources_prompts
    commits the cycle_started_at value the throttle will read next cycle.
    """
    base, headers, gw_id = isolated_refresh_gateway

    def _get_last_refresh():
        resp = httpx.get(f"{base}/v1/gateways/{gw_id}", headers=headers, timeout=10.0)
        assert resp.status_code == 200, resp.text
        return resp.json().get("lastRefreshAt")

    # Wait for the first auto-refresh cycle to fire.
    deadline = time.monotonic() + _CYCLE_INTERVAL * 4
    first_ts = None
    while time.monotonic() < deadline:
        ts = _get_last_refresh()
        if ts is not None:
            first_ts = ts
            break
        time.sleep(0.5)

    assert first_ts is not None, "last_refresh_at was never written after the first auto-refresh cycle"

    # Wait for a second cycle to advance the timestamp.
    deadline = time.monotonic() + _CYCLE_INTERVAL * 4
    second_ts = None
    while time.monotonic() < deadline:
        ts = _get_last_refresh()
        if ts is not None and ts != first_ts:
            second_ts = ts
            break
        time.sleep(0.5)

    assert second_ts is not None, (
        f"last_refresh_at did not advance after the second cycle "
        f"(stuck at {first_ts!r}); auto-refresh may be throttled or broken"
    )
