# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_auto_refresh_last_refresh_at.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box regression for #7095: auto-refresh throttle skip-every-other-cycle.

Boots an isolated gateway subprocess with a 60-second health-check and auto-refresh
interval, registers a real MCP server via mcpgateway.translate --stdio, and confirms:

1. last_refresh_at is written after the first cycle.
2. last_refresh_at advances after each subsequent cycle within a single-interval window.
3. The upstream catalog change (adding a second tool between cycles) is discovered
   within one refresh interval — ruling out the every-other-cycle defect.
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
# Minimum value allowed by Settings.gateway_auto_refresh_interval (ge=60).
_CYCLE_INTERVAL = 60
_STARTUP_TIMEOUT = 90  # seconds for gateway and translate server startup


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
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def isolated_refresh_gateway():
    """Start a private gateway and a translate-wrapped stdio MCP server.

    The gateway runs with a 60-second health-check and auto-refresh interval
    (the minimum allowed by the Settings validator).  The translate server exposes
    a phase-aware stdio script: before the phase file exists it returns one tool;
    after the phase file is created it returns two tools.  The test writes the phase
    file between cycles to trigger a catalog change the gateway must discover.
    """
    gateway_port = _free_port()
    translate_port = _free_port()
    signing_key = secrets.token_urlsafe(48)
    tmp = Path(tempfile.mkdtemp(prefix=f"refresh-gw-{gateway_port}-"))
    phase_file = tmp / "phase2"

    # Phase-aware stdio MCP server script.
    # Phase 1 (phase_file absent): returns tool "echo".
    # Phase 2 (phase_file present): returns tools "echo" and "echo2".
    stdio_script = tmp / "echo_mcp.py"
    stdio_script.write_text(
        "import sys, json, os\n"
        "from pathlib import Path\n"
        f"phase_file = Path({str(phase_file)!r})\n"
        "for line in sys.stdin:\n"
        "    req = json.loads(line)\n"
        "    m = req.get('method', '')\n"
        "    rid = req.get('id')\n"
        "    if m == 'initialize':\n"
        "        r = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'echo', 'version': '1.0'}}\n"
        "    elif m == 'tools/list':\n"
        "        tools = [{'name': 'echo', 'description': 'echo', 'inputSchema': {'type': 'object', 'properties': {}}}]\n"
        "        if phase_file.exists():\n"
        "            tools.append({'name': 'echo2', 'description': 'echo2', 'inputSchema': {'type': 'object', 'properties': {}}})\n"
        "        r = {'tools': tools}\n"
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
        # HEALTH_CHECK_INTERVAL (not GW_HEALTH_CHECK_INTERVAL) controls the scheduler.
        "HEALTH_CHECK_INTERVAL": str(_CYCLE_INTERVAL),
        "GATEWAY_AUTO_REFRESH_INTERVAL": str(_CYCLE_INTERVAL),
        "AUTO_REFRESH_SERVERS": "true",
    }

    log_path = tmp / "gateway.log"
    translate_log = tmp / "translate.log"

    # Start translate server first so the gateway can reach it on registration.
    with translate_log.open("w") as tlog:
        translate_proc = subprocess.Popen(
            [
                sys.executable, "-m", "mcpgateway.translate",
                "--stdio", f"{sys.executable} {stdio_script}",
                "--port", str(translate_port),
            ],
            cwd=str(tmp),
            env=env,
            stdout=tlog,
            stderr=subprocess.STDOUT,
        )

    translate_deadline = time.monotonic() + _STARTUP_TIMEOUT
    if not _wait_http(f"http://127.0.0.1:{translate_port}/healthz", translate_deadline):
        translate_proc.terminate()
        pytest.fail(
            f"translate server failed to start on port {translate_port}; "
            f"log: {translate_log.read_text()[-2000:]}"
        )

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
        pytest.fail(
            f"gateway failed to start on port {gateway_port}; "
            f"log: {log_path.read_text()[-2000:]}"
        )

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
        pytest.fail(f"gateway registration failed ({reg.status_code}): {reg.text}")

    gw_id = reg.json()["id"]

    try:
        yield base, headers, gw_id, phase_file
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
    """Auto-refresh must write last_refresh_at and pick up catalog changes each cycle.

    Cycle 1: wait for last_refresh_at to appear within one interval window.
    Between cycles: create the phase file so the upstream returns a second tool.
    Cycle 2: wait for last_refresh_at to advance within one interval window.
             Assert that the new tool is now visible in the gateway's tool list.

    Using a single-interval window (1.5 × _CYCLE_INTERVAL) means the every-other-cycle
    defect (which requires 2 × interval to fire) causes the second assertion to fail.
    """
    base, headers, gw_id, phase_file = isolated_refresh_gateway

    def _get_last_refresh() -> str | None:
        resp = httpx.get(f"{base}/v1/gateways/{gw_id}", headers=headers, timeout=10.0)
        assert resp.status_code == 200, resp.text
        return resp.json().get("lastRefreshAt")

    def _get_tool_names() -> list[str]:
        resp = httpx.get(f"{base}/v1/tools", headers=headers, timeout=10.0)
        assert resp.status_code == 200, resp.text
        # Tools from gateway "regression-7095" are stored as "regression-7095-{tool}"
        # (gateway slug + separator + tool slug, default separator is "-").
        # Filter to tools owned by this gateway and return their names as-is.
        return [t["name"] for t in resp.json() if t.get("gatewayId") == gw_id or t.get("gateway_id") == gw_id]

    # Cycle 1: wait up to 1.5 × interval for the first auto-refresh write.
    window = _CYCLE_INTERVAL * 1.5
    deadline = time.monotonic() + window
    first_ts = None
    while time.monotonic() < deadline:
        ts = _get_last_refresh()
        if ts is not None:
            first_ts = ts
            break
        time.sleep(1.0)

    assert first_ts is not None, (
        f"last_refresh_at was never written within {window:.0f}s of the first auto-refresh cycle"
    )

    # Trigger catalog change: phase 2 adds tool "echo2".
    phase_file.touch()

    # Cycle 2: wait up to 1.5 × interval for timestamp advancement.
    # The every-other-cycle defect would hold last_refresh_at constant for 2 × interval,
    # so this window is tight enough to catch the regression.
    deadline = time.monotonic() + window
    second_ts = None
    while time.monotonic() < deadline:
        ts = _get_last_refresh()
        if ts is not None and ts != first_ts:
            second_ts = ts
            break
        time.sleep(1.0)

    assert second_ts is not None, (
        f"last_refresh_at did not advance within {window:.0f}s of cycle 2 "
        f"(stuck at {first_ts!r}); auto-refresh is throttled or the scheduler is broken"
    )

    # Assert the catalog change was picked up in the same cycle.
    # The gateway-prefixed name for tool "echo2" from gateway "regression-7095"
    # is "regression-7095-echo2" (slugified-gateway + separator + slugified-tool).
    tool_names = _get_tool_names()
    assert any("echo2" in name for name in tool_names), (
        f"No tool containing 'echo2' found after cycle 2 (tools: {tool_names}); "
        "auto-refresh did not pick up the upstream catalog change"
    )
