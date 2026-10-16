# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_stale_catalog_recovery.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box regression for preserving gateway tool state across catalog refreshes.
"""

# Future
from __future__ import annotations

# Standard
from collections.abc import Iterator
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid

# Third-Party
import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import Tool
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
import uvicorn

# First-Party
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolMetric

# Local
from tests.helpers.auth import make_test_jwt

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STARTUP_TIMEOUT = 60


def _free_port() -> int:
    """Return a loopback port that is free for a local test process."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _wait_http(url: str, deadline: float, accepted_statuses: tuple[int, ...] = (200,)) -> bool:
    """Wait until a local gateway endpoint responds successfully."""
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code in accepted_statuses:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    return False


@pytest.fixture
def isolated_catalog_gateway(tmp_path: Path) -> Iterator[tuple[str, dict[str, str], dict[str, bool], str, Path]]:
    """Start a real gateway and a mutable local MCP peer for catalog refreshes."""
    state = {"present": True}

    class CatalogMCPServer(MCPServer):
        """Expose a tool that can disappear and return between refreshes."""

        async def list_tools(self) -> list[Tool]:
            tools = await super().list_tools()
            return [tool for tool in tools if state["present"] or tool.name != "recoverable_tool"]

    upstream = CatalogMCPServer("catalog-recovery")

    @upstream.tool(name="recoverable_tool")
    def recoverable_tool() -> str:
        """Return a stable response for the recovered tool."""
        return "available"

    @upstream.tool(name="stable_tool")
    def stable_tool() -> str:
        """Keep catalog refreshes authoritative while the target tool is absent."""
        return "stable"

    upstream_listener = socket.socket()
    upstream_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    upstream_listener.bind(("127.0.0.1", 0))
    upstream_port = upstream_listener.getsockname()[1]
    upstream_app = upstream.streamable_http_app(host="127.0.0.1", stateless_http=True, json_response=True)
    upstream_server = uvicorn.Server(uvicorn.Config(upstream_app, log_level="error", access_log=False))
    upstream_thread = threading.Thread(target=upstream_server.run, kwargs={"sockets": [upstream_listener]}, daemon=True)
    upstream_thread.start()

    gateway_port = _free_port()
    signing_key = secrets.token_urlsafe(48)
    gateway_env = {
        "PATH": os.environ["PATH"],
        "SYSTEMROOT": os.environ["SYSTEMROOT"],
        "WINDIR": os.environ["WINDIR"],
        "TEMP": os.environ["TEMP"],
        "TMP": os.environ["TMP"],
        "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), *filter(None, os.getenv("PYTHONPATH", "").split(os.pathsep))]),
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
        "DATABASE_URL": f"sqlite:///{(tmp_path / 'gateway.db').as_posix()}",
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
        "AUTO_REFRESH_SERVERS": "false",
        "HEALTH_CHECK_INTERVAL": "3600",
        "GATEWAY_AUTO_REFRESH_INTERVAL": "3600",
        "LOG_LEVEL": "ERROR",
    }
    gateway_log = tmp_path / "gateway.log"
    with gateway_log.open("w", encoding="utf-8") as log_file:
        gateway_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)],
            cwd=tmp_path,
            env=gateway_env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    gateway_url = f"http://127.0.0.1:{gateway_port}"
    try:
        upstream_deadline = time.monotonic() + _STARTUP_TIMEOUT
        assert upstream_server.started or _wait_http(f"http://127.0.0.1:{upstream_port}/health", upstream_deadline, accepted_statuses=(404,)), "MCP stub failed to start"
        gateway_deadline = time.monotonic() + _STARTUP_TIMEOUT
        if not _wait_http(f"{gateway_url}/health", gateway_deadline):
            pytest.fail(f"Gateway failed to start; log: {gateway_log.read_text(encoding='utf-8')[-3000:]}")

        token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key)
        yield gateway_url, {"Authorization": f"Bearer {token}"}, state, f"http://127.0.0.1:{upstream_port}/mcp", tmp_path / "gateway.db"
    finally:
        upstream_server.should_exit = True
        upstream_thread.join(timeout=10)
        upstream_listener.close()
        if gateway_process.poll() is None:
            gateway_process.terminate()
        try:
            gateway_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gateway_process.kill()
            gateway_process.wait(timeout=5)
        assert not upstream_thread.is_alive(), "MCP stub failed to stop"


def _gateway_tool(client: httpx.Client, gateway_id: str, original_name: str) -> dict:
    """Return a named tool exposed by the test gateway."""
    response = client.get("/v1/tools", params={"gateway_id": gateway_id, "limit": 0})
    assert response.status_code == 200, response.text
    tools = response.json()
    assert isinstance(tools, list), f"Expected a tool list, got {tools!r}"
    matches = [tool for tool in tools if tool.get("gatewayId", tool.get("gateway_id")) == gateway_id and tool.get("originalName", tool.get("original_name")) == original_name]
    assert len(matches) == 1, f"Expected one {original_name!r} tool for gateway {gateway_id}, got {matches!r}"
    return matches[0]


def _stored_tool_state(database_path: Path, tool_id: str, server_id: str) -> tuple[bool, bool, bool, list[str], int]:
    """Read durable tool state after a gateway API request commits."""
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with Session(engine) as db:
            tool = db.get(DbTool, tool_id)
            assert tool is not None, f"Tool row {tool_id} was deleted"
            server = db.get(DbServer, server_id)
            assert server is not None, f"Virtual server row {server_id} was deleted"
            metric_count = db.scalar(select(func.count(ToolMetric.id)).where(ToolMetric.tool_id == tool_id)) or 0
            server_tool_ids = [associated_tool.id for associated_tool in server.tools]
            return tool.deprecated, tool.catalog_stale, tool.enabled, server_tool_ids, metric_count
    finally:
        engine.dispose()


def test_refresh_retains_tool_identity_and_virtual_server_association(isolated_catalog_gateway: tuple[str, dict[str, str], dict[str, bool], str, Path]) -> None:
    """A stale tool remains attached and recovers under its original ID."""
    base_url, headers, state, upstream_url, database_path = isolated_catalog_gateway
    with httpx.Client(base_url=base_url, headers=headers, timeout=20.0) as client:
        gateway_name = f"catalog-recovery-{uuid.uuid4().hex[:8]}"
        registration = client.post(
            "/v1/gateways",
            json={"name": gateway_name, "url": upstream_url, "transport": "STREAMABLEHTTP"},
        )
        assert registration.status_code in (200, 201), registration.text
        gateway_id = registration.json()["id"]

        initial_refresh = client.post(f"/v1/gateways/{gateway_id}/tools/refresh")
        assert initial_refresh.status_code == 200, initial_refresh.text
        tool_id = _gateway_tool(client, gateway_id, "recoverable_tool")["id"]

        server_registration = client.post(
            "/v1/servers",
            json={
                "server": {
                    "name": f"catalog-recovery-server-{uuid.uuid4().hex[:8]}",
                    "description": "Stale catalog recovery regression",
                    "associated_tools": [tool_id],
                    "associated_resources": [],
                    "associated_prompts": [],
                },
                "visibility": "public",
            },
        )
        assert server_registration.status_code == 201, server_registration.text
        server_id = server_registration.json()["id"]

        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        try:
            with Session(engine) as db:
                tool = db.get(DbTool, tool_id)
                assert tool is not None
                tool.enabled = False
                db.add(ToolMetric(tool_id=tool_id, response_time=0.125, is_success=True))
                db.commit()
        finally:
            engine.dispose()

        state["present"] = False
        stale_refresh = client.post(f"/v1/gateways/{gateway_id}/tools/refresh")
        assert stale_refresh.status_code == 200, stale_refresh.text
        assert _stored_tool_state(database_path, tool_id, server_id) == (True, True, False, [tool_id], 1)

        repeated_refresh = client.post(f"/v1/gateways/{gateway_id}/tools/refresh")
        assert repeated_refresh.status_code == 200, repeated_refresh.text
        assert _stored_tool_state(database_path, tool_id, server_id) == (True, True, False, [tool_id], 1)

        state["present"] = True
        recovered_refresh = client.post(f"/v1/gateways/{gateway_id}/tools/refresh")
        assert recovered_refresh.status_code == 200, recovered_refresh.text
        assert _stored_tool_state(database_path, tool_id, server_id) == (False, False, False, [tool_id], 1)
