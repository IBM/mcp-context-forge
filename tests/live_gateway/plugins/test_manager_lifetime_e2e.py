# -*- coding: utf-8 -*-
"""Verify plugin manager lifetime through an isolated live gateway.

Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
import uuid

# Third-Party
from cpex.framework import Plugin, PluginResult, PluginViolation
import httpx
import pytest
import yaml

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]


class LifetimeProbePlugin(Plugin):
    """Expose plugin instance identity through a deterministic denial."""

    async def initialize(self) -> None:
        """Assign a fresh identity when the manager initializes this plugin."""
        self.instance_id = uuid.uuid4().hex

    async def tool_pre_invoke(self, payload, context):
        """Return the instance identity without dispatching the upstream tool."""
        return PluginResult(
            continue_processing=False,
            violation=PluginViolation(reason="Lifetime probe", description="Intentional test denial", code=f"CACHE_PROBE_{self.instance_id}", http_status_code=403),
        )


@pytest.fixture
def lifetime_gateway(tmp_path):
    """Start an authenticated gateway with an isolated database and probe plugin."""
    config_path = tmp_path / "plugins.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "plugins": [
                    {
                        "name": "LifetimeProbe",
                        "kind": f"{__name__}.LifetimeProbePlugin",
                        "description": "Plugin manager lifetime probe",
                        "version": "1.0",
                        "author": "ContextForge",
                        "hooks": ["tool_pre_invoke"],
                        "tags": [],
                        "mode": "sequential",
                        "priority": 1,
                        "config": {},
                    }
                ],
                "plugin_dirs": [],
                "plugin_settings": {"plugin_timeout": 30, "fail_on_plugin_error": True},
            }
        ),
        encoding="utf-8",
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(_REPO_ROOT),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32) + "!Aa1",
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32) + "!Aa1",
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "AUTH_REQUIRED": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        "SSRF_ALLOW_LOCALHOST": "true",
        "PLUGINS_ENABLED": "true",
        "PLUGINS_CONFIG_FILE": str(config_path),
        "OBSERVABILITY_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
    }
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    log_path = tmp_path / "gateway.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=make_auth_headers(token), timeout=15, trust_env=False) as client:
                deadline = time.monotonic() + 120
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
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _probe_instance(client: httpx.Client, tool_name: str) -> str:
    """Read the plugin instance identity through an authenticated tool call.

    Args:
        client: Client for the isolated gateway.
        tool_name: Registered tool name.
    """
    response = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": {}}})
    assert response.status_code in (200, 400, 403, 422), response.text
    match = re.search(r"CACHE_PROBE_([0-9a-f]{32})", response.text)
    assert match is not None, response.text
    return match.group(1)


def test_manager_survives_elapsed_time_and_reloads_explicitly(lifetime_gateway):
    """Keep the same manager past the former TTL, then rebuild on a mode update."""
    client = lifetime_gateway
    response = client.post(
        "/tools",
        json={
            "tool": {
                "name": "lifetime_probe",
                "description": "Plugin manager lifetime probe",
                "integrationType": "REST",
                "url": "http://127.0.0.1:9/probe",
                "requestType": "POST",
                "visibility": "public",
            },
            "team_id": None,
        },
    )
    assert response.status_code == 200, response.text
    tool_name = response.json()["name"]
    original_instance = _probe_instance(client, tool_name)
    time.sleep(31)
    assert _probe_instance(client, tool_name) == original_instance
    response = client.put("/admin/plugins/LifetimeProbe", json={"mode": "enforce"})
    assert response.status_code == 200, response.text
    assert _probe_instance(client, tool_name) != original_instance
