# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_rate_limiter_multi_tenant.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for G1 + G2 — tenant-id end-to-end through the gateway.

Covers issue #4343:
  - G1: GlobalContext.tenant_id is populated so by_tenant rate limiting
    is not a silent no-op on the tool-service paths.
  - G2: Redis keys carry the tenant prefix (rl:{tenant_id}:user:{email}:...),
    so counters don't collide across teams in a shared-Redis deployment.

These tests go through the full gateway HTTP flow against a running
docker-compose stack (same harness as test_rate_limiter_dynamic_behavior.py),
enable the rate limiter in enforce mode with a high limit (so we observe
key creation without 429s), make a real tool call, and then inspect
Redis to verify the key shape.

Requirements:
    - Running gateway (docker-compose at http://localhost:8080)
    - Redis at localhost:6379 (or docker container)
    - fast-time-server or equivalent registered

Usage:
    uv run pytest tests/integration/test_rate_limiter_multi_tenant.py -v --with-integration
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid

import pytest
import requests

from tests.helpers.integration_constants import PLUGIN_MODE_PROPAGATION_WAIT_SECONDS

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
GATEWAY_EMAIL = os.environ.get("GATEWAY_EMAIL", "admin@example.com")
GATEWAY_PASSWORD = os.environ.get("GATEWAY_PASSWORD", "changeme")
PLUGIN_NAME = "RateLimiterPlugin"
PROPAGATION_WAIT = int(os.environ.get("PROPAGATION_WAIT", str(PLUGIN_MODE_PROPAGATION_WAIT_SECONDS)))
# docker-compose derives the container name from the project-name prefix + service
# name; anyone running under a non-default project name needs to override this.
REDIS_CONTAINER_NAME = os.environ.get("REDIS_CONTAINER_NAME", "mcp-context-forge-redis-1")


def _get_session_token() -> str:
    resp = requests.post(
        f"{GATEWAY_URL}/auth/login",
        json={"email": GATEWAY_EMAIL, "password": GATEWAY_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _fresh_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_session_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _is_gateway_running() -> bool:
    try:
        resp = requests.get(f"{GATEWAY_URL}/health", timeout=5)
        return resp.status_code == 200
    except requests.ConnectionError:
        return False


def _auto_detect_server_and_tool() -> tuple[str, str, str | None]:
    """Find a server+tool and return (server_id, tool_name, tool_team_id)."""
    headers = _fresh_headers()
    resp = requests.get(f"{GATEWAY_URL}/servers", headers=headers, timeout=10)
    resp.raise_for_status()
    for server in resp.json():
        tools = server.get("associatedTools", [])
        for tool in tools:
            if "echo" in tool.lower() or ("time" in tool.lower() and "convert" not in tool.lower()):
                team_id = server.get("teamId") or server.get("team_id")
                return server["id"], tool, team_id
    pytest.skip("No suitable server/tool found for multi-tenant rate limiter test")


def _set_plugin_mode(mode: str) -> None:
    resp = requests.put(
        f"{GATEWAY_URL}/admin/plugins/{PLUGIN_NAME}",
        json={"mode": mode},
        headers=_fresh_headers(),
        timeout=10,
    )
    resp.raise_for_status()


def _invoke_tool_once(server_id: str, tool_name: str) -> int:
    """Make a single MCP tool invocation and return its HTTP status."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"message": "multi-tenant-test"} if "echo" in tool_name else {},
        },
    }
    resp = requests.post(
        f"{GATEWAY_URL}/servers/{server_id}/mcp",
        json=payload,
        headers=_fresh_headers(),
        timeout=15,
    )
    return resp.status_code


def _redis_keys(pattern: str) -> list[str]:
    """Query Redis for keys matching the pattern via the running docker container.

    Uses docker exec rather than connecting directly to sidestep any auth
    differences between the gateway's Redis client and a test-side client.
    Returns a sorted list of key names (empty if no keys or docker unavailable).
    """
    try:
        result = subprocess.run(
            ["docker", "exec", REDIS_CONTAINER_NAME, "redis-cli", "-n", "0", "KEYS", pattern],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        pytest.skip("Docker or Redis container not reachable")
    if result.returncode != 0:
        pytest.skip(f"Redis key query failed: {result.stderr.strip() or 'unknown error'}")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return sorted(lines)


def _flush_rate_limiter_keys() -> None:
    """Delete any existing rl:* keys so we observe only keys from the current test."""
    keys = _redis_keys("rl:*")
    for key in keys:
        subprocess.run(
            ["docker", "exec", REDIS_CONTAINER_NAME, "redis-cli", "-n", "0", "DEL", key],
            capture_output=True,
            timeout=5,
            check=False,
        )
    remaining = _redis_keys("rl:*")
    if remaining:
        pytest.fail(f"Rate-limiter keys still present after flush: {remaining}")


pytestmark = pytest.mark.skipif(
    not _is_gateway_running(),
    reason=f"Gateway not running at {GATEWAY_URL}",
)


@pytest.fixture(scope="module")
def server_and_tool():
    return _auto_detect_server_and_tool()


@pytest.fixture(autouse=True)
def _isolate_rate_limiter_between_tests():
    """Flush rl:* keys and disable the plugin between tests."""
    _set_plugin_mode("disabled")
    time.sleep(PROPAGATION_WAIT)
    _flush_rate_limiter_keys()
    yield
    _set_plugin_mode("disabled")
    time.sleep(PROPAGATION_WAIT)


class TestTenantIdFlowsToPlugin:
    """G1 + G2 end-to-end: tenant_id reaches the plugin, tenant prefix lands in Redis."""

    def test_tool_invocation_creates_rate_limit_keys_in_redis(self, server_and_tool):
        """Sanity check: with the rate limiter enforcing, a tool call must
        leave at least one rate-limit key in Redis.

        If this test fails, the rate limiter isn't engaging on the tool
        path at all, and every other assertion below is meaningless.
        """
        server_id, tool_name, _team_id = server_and_tool
        _set_plugin_mode("enforce")
        time.sleep(PROPAGATION_WAIT)

        status = _invoke_tool_once(server_id, tool_name)
        assert status == 200, f"tool invocation must succeed under default limit, got HTTP {status}"

        keys = _redis_keys("rl:*")
        assert keys, (
            "no rl:* keys found in Redis after a rate-limited tool invocation — "
            "the rate limiter may not be engaged on this path. "
            "Check plugins/config.yaml has RateLimiterPlugin enabled and configured."
        )

    def test_rate_limit_keys_carry_tenant_prefix_when_tool_is_team_owned(self, server_and_tool):
        """G2 end-to-end: when the tool is team-owned, the Redis keys written by
        the rate limiter must start with `rl:{team_id}:...` — proving the
        main-repo change at tool_service.py propagated team_id into
        GlobalContext.tenant_id and that the cpex plugin then used that as
        the context prefix when building the Redis key.
        """
        server_id, tool_name, team_id = server_and_tool
        if not team_id:
            pytest.skip("Detected server has no team_id — this deployment uses platform-owned tools. " "Re-run against a deployment that has team-scoped servers to exercise G2.")

        _set_plugin_mode("enforce")
        time.sleep(PROPAGATION_WAIT)

        status = _invoke_tool_once(server_id, tool_name)
        assert status == 200, f"tool invocation must succeed under default limit, got HTTP {status}"

        # Look specifically for the tenant-prefixed format: rl:{team}:...:...
        prefixed_keys = _redis_keys(f"rl:{team_id}:*")
        unprefixed_keys = [k for k in _redis_keys("rl:*") if not k.startswith(f"rl:{team_id}:")]

        assert prefixed_keys, (
            f"expected at least one key matching 'rl:{team_id}:*' — tenant prefix missing from Redis keys. "
            f"All rl:* keys: {_redis_keys('rl:*')!r}. "
            f"This means GlobalContext.tenant_id is not reaching the plugin."
        )
        # Defensive assertion — if we see unprefixed keys alongside prefixed ones,
        # something is calling the plugin without populated tenant_id.
        assert not unprefixed_keys, f"Found rl:* keys without the team prefix: {unprefixed_keys!r}. " f"Some code path is invoking the plugin without populating tenant_id."
