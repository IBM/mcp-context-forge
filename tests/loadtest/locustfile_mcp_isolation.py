# -*- coding: utf-8 -*-
"""Location: ./tests/loadtest/locustfile_mcp_isolation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Rust MCP session/auth isolation correctness load test.
This Locust harness is intentionally separate from the throughput benchmarks.
It validates that a live Rust MCP session remains usable for the owner while
same-team peers and outsiders cannot hijack it under concurrent traffic.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime
import json
import os
from pathlib import Path
import random
import uuid

# Third-Party
from locust import HttpUser, between, events, task
from locust.runners import MasterRunner, WorkerRunner
import requests

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token

BASE_URL = os.getenv("MCP_CLI_BASE_URL", "http://localhost:8080")
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
TEST_PASSWORD = "SecureTestPass123!"
MCP_PROTOCOL_VERSION = "2025-11-25"
ISOLATION_PREFIX = "mcp-iso-load"

_ENV_CACHE: dict[str, str] | None = None
_STATE: dict[str, object] = {}


def _load_env_file() -> dict[str, str]:
    """Load .env values from the project root when present."""
    global _ENV_CACHE  # pylint: disable=global-statement
    if _ENV_CACHE is not None:
        return _ENV_CACHE

    env_vars: dict[str, str] = {}
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",
    ]
    for path in search_paths:
        if path.exists():
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip().strip("\"'")
            break
    _ENV_CACHE = env_vars
    return env_vars


def _cfg(key: str, default: str = "") -> str:
    env_vars = _load_env_file()
    return os.environ.get(key) or env_vars.get(key) or default


def _make_jwt(email: str, is_admin: bool = False, teams=None) -> str:
    """Create a JWT suitable for compose-backed setup calls."""
    return _create_jwt_token(
        {"sub": email},
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
        teams=teams,
        secret=JWT_SECRET,
    )


def _json_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _request_json(
    client: requests.Session,
    method: str,
    path: str,
    *,
    expected: tuple[int, ...] = (200, 201),
    **kwargs,
):
    response = client.request(method, f"{BASE_URL}{path}", timeout=20, **kwargs)
    assert response.status_code in expected, f"{method} {path} expected {expected}, got {response.status_code}: {response.text}"
    return response.json() if response.content else None


def _resolve_role_id(admin_client: requests.Session, role_name: str) -> str:
    roles = _request_json(admin_client, "GET", "/rbac/roles")
    for role in roles:
        if role.get("name") == role_name:
            return role["id"]
    raise AssertionError(f"RBAC role '{role_name}' not found")


def _select_time_gateway(gateways: list[dict], tools: list[dict]) -> dict:
    tool_counts_by_gateway: dict[str, int] = {}
    for tool in tools:
        gateway_id = tool.get("gatewayId")
        if gateway_id:
            tool_counts_by_gateway[gateway_id] = tool_counts_by_gateway.get(gateway_id, 0) + 1

    for preferred_name in ("fast_time", "fast_test"):
        for gateway in gateways:
            if gateway.get("name") == preferred_name and gateway.get("transport") == "STREAMABLEHTTP" and tool_counts_by_gateway.get(gateway.get("id"), 0) > 0:
                return gateway

    raise AssertionError("No compose-backed time-capable STREAMABLEHTTP gateway found")


def _create_user(
    admin_client: requests.Session,
    *,
    email: str,
    team_id: str | None,
    role_name: str | None,
    is_admin: bool = False,
) -> dict[str, str | None]:
    _request_json(
        admin_client,
        "POST",
        "/auth/email/admin/users",
        json={
            "email": email,
            "password": TEST_PASSWORD,
            "full_name": f"Isolation Load {email.split('@', maxsplit=1)[0]}",
            "is_admin": is_admin,
            "is_active": True,
            "password_change_required": False,
        },
    )

    role_id = None
    if team_id:
        _request_json(
            admin_client,
            "POST",
            f"/teams/{team_id}/members",
            json={"email": email, "role": "member"},
        )
    if role_name and team_id:
        role_id = _resolve_role_id(admin_client, role_name)
        _request_json(
            admin_client,
            "POST",
            f"/rbac/users/{email}/roles",
            json={"role_id": role_id, "scope": "team", "scope_id": team_id},
        )

    jwt_token = _make_jwt(email, is_admin=is_admin, teams=[team_id] if team_id else None)
    user_client = requests.Session()
    user_client.headers.update(_json_headers(jwt_token))
    token_payload: dict[str, object] = {
        "name": f"{ISOLATION_PREFIX}-token-{uuid.uuid4().hex[:8]}",
        "expires_in_days": 1,
    }
    if team_id:
        token_payload["team_id"] = team_id
    token_response = _request_json(user_client, "POST", "/tokens", json=token_payload)
    token_obj = token_response.get("token", token_response)
    return {
        "email": email,
        "access_token": token_response["access_token"],
        "token_id": token_obj.get("id") or token_obj.get("token_id"),
        "team_id": team_id,
        "role_id": role_id,
    }


def _cleanup_state() -> None:
    if not _STATE:
        return

    admin_client = requests.Session()
    admin_client.headers.update(_json_headers(_STATE["admin_token"]))  # type: ignore[index]
    for user in _STATE.get("users", {}).values():  # type: ignore[union-attr]
        token_id = user.get("token_id")
        if token_id:
            admin_client.delete(f"{BASE_URL}/tokens/admin/{token_id}", timeout=10)
        admin_client.delete(f"{BASE_URL}/auth/email/admin/users/{user['email']}", timeout=10)

    server_id = _STATE.get("server_id")
    if server_id:
        admin_client.delete(f"{BASE_URL}/servers/{server_id}", timeout=10)
    team_id = _STATE.get("team_id")
    if team_id:
        admin_client.delete(f"{BASE_URL}/teams/{team_id}", timeout=10)
    _STATE.clear()


def _contains_iso8601_timestamp(value) -> bool:
    """Return True when any nested string value parses as an ISO-8601 timestamp."""
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return False
        try:
            datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True
    if isinstance(value, dict):
        return any(_contains_iso8601_timestamp(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_iso8601_timestamp(item) for item in value)
    return False


def _bootstrap_state() -> None:
    if _STATE:
        return

    health = requests.get(f"{BASE_URL}/health", timeout=10)
    health.raise_for_status()
    assert health.headers.get("x-contextforge-mcp-runtime-mode") == "rust-managed", f"Rust MCP runtime is not active at {BASE_URL}"

    admin_token = _make_jwt(_cfg("PLATFORM_ADMIN_EMAIL", "admin@example.com"), is_admin=True, teams=None)
    admin_client = requests.Session()
    admin_client.headers.update(_json_headers(admin_token))

    team = _request_json(
        admin_client,
        "POST",
        "/teams/",
        json={
            "name": f"{ISOLATION_PREFIX}-team-{uuid.uuid4().hex[:8]}",
            "description": "Rust MCP isolation load team",
            "visibility": "private",
        },
    )
    team_id = team["id"]

    tools = _request_json(admin_client, "GET", "/tools")
    gateways = _request_json(admin_client, "GET", "/gateways")
    gateway = _select_time_gateway(gateways, tools)
    gateway_id = gateway["id"]
    tool_ids = [tool["id"] for tool in tools if tool.get("gatewayId") == gateway_id]
    server = _request_json(
        admin_client,
        "POST",
        "/servers",
        json={
            "server": {
                "name": f"{ISOLATION_PREFIX}-server-{uuid.uuid4().hex[:8]}",
                "description": "Rust MCP isolation load server",
                "associated_tools": tool_ids,
                "associated_resources": [],
                "associated_prompts": [],
            },
            "team_id": team_id,
            "visibility": "team",
        },
    )
    server_id = server["id"]

    owner = _create_user(
        admin_client,
        email=f"{ISOLATION_PREFIX}-owner-{uuid.uuid4().hex[:8]}@test.com",
        team_id=team_id,
        role_name="developer",
        is_admin=True,
    )
    peer = _create_user(
        admin_client,
        email=f"{ISOLATION_PREFIX}-peer-{uuid.uuid4().hex[:8]}@test.com",
        team_id=team_id,
        role_name="developer",
    )
    outsider = _create_user(
        admin_client,
        email=f"{ISOLATION_PREFIX}-outsider-{uuid.uuid4().hex[:8]}@test.com",
        team_id=None,
        role_name=None,
    )

    owner_headers = {
        "Authorization": f"Bearer {owner['access_token']}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    initialize = requests.post(
        f"{BASE_URL}/servers/{server_id}/mcp/",
        headers=owner_headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-isolation-load", "version": "1.0.0"},
            },
        },
        timeout=20,
    )
    initialize.raise_for_status()
    session_id = initialize.headers["mcp-session-id"]

    tools_list = requests.post(
        f"{BASE_URL}/servers/{server_id}/mcp/",
        headers={**owner_headers, "mcp-session-id": session_id},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        timeout=20,
    )
    tools_list.raise_for_status()
    tool_names = [tool["name"] for tool in tools_list.json()["result"]["tools"]]
    time_tool = next(name for name in tool_names if "get-system-time" in name)

    _STATE.update(
        {
            "admin_token": admin_token,
            "team_id": team_id,
            "server_id": server_id,
            "session_id": session_id,
            "time_tool": time_tool,
            "users": {"owner": owner, "peer": peer, "outsider": outsider},
        }
    )


@events.test_start.add_listener
def _on_test_start(environment, **_kwargs) -> None:
    runner = environment.runner
    if isinstance(runner, WorkerRunner):
        return
    _bootstrap_state()


@events.test_stop.add_listener
def _on_test_stop(environment, **_kwargs) -> None:
    runner = environment.runner
    if isinstance(runner, MasterRunner):
        return
    _cleanup_state()


class BaseIsolationUser(HttpUser):
    abstract = True
    wait_time = between(0.1, 0.5)

    @property
    def server_id(self) -> str:
        return str(_STATE["server_id"])

    @property
    def session_id(self) -> str:
        return str(_STATE["session_id"])

    @property
    def time_tool(self) -> str:
        return str(_STATE["time_tool"])

    def _headers(self, token: str, *, include_session: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if include_session:
            headers["mcp-session-id"] = self.session_id
        return headers


class McpIsolationOwnerUser(BaseIsolationUser):
    weight = 3

    @task(3)
    def tools_list_owner_session(self) -> None:
        owner = _STATE["users"]["owner"]  # type: ignore[index]
        with self.client.post(
            f"/servers/{self.server_id}/mcp/",
            headers=self._headers(owner["access_token"], include_session=True),
            json={"jsonrpc": "2.0", "id": random.randint(10, 10000), "method": "tools/list", "params": {}},
            catch_response=True,
            name="MCP isolation owner tools/list",
        ) as response:
            if response.status_code != 200:
                response.failure(f"Owner tools/list failed: {response.status_code} {response.text}")
                return
            payload = response.json()
            tool_names = [tool["name"] for tool in payload.get("result", {}).get("tools", [])]
            if self.time_tool not in tool_names:
                response.failure(f"Owner did not see expected tool list: {tool_names}")
            else:
                response.success()

    @task(1)
    def tools_call_owner_session(self) -> None:
        owner = _STATE["users"]["owner"]  # type: ignore[index]
        with self.client.post(
            f"/servers/{self.server_id}/mcp/",
            headers=self._headers(owner["access_token"], include_session=True),
            json={
                "jsonrpc": "2.0",
                "id": random.randint(10, 10000),
                "method": "tools/call",
                "params": {"name": self.time_tool, "arguments": {"timezone": "UTC"}},
            },
            catch_response=True,
            name="MCP isolation owner tools/call",
        ) as response:
            if response.status_code != 200:
                response.failure(f"Owner tools/call failed: {response.status_code} {response.text}")
                return
            payload = response.json()
            if payload.get("result", {}).get("isError", False):
                response.failure(f"Owner tools/call unexpectedly errored: {payload}")
                return
            if _contains_iso8601_timestamp(payload.get("result", {})):
                response.success()
            else:
                response.failure(f"Owner tools/call returned non-time payload: {json.dumps(payload)}")


class McpIsolationHijackUser(BaseIsolationUser):
    weight = 2

    @task(2)
    def same_team_peer_hijack(self) -> None:
        peer = _STATE["users"]["peer"]  # type: ignore[index]
        with self.client.post(
            f"/servers/{self.server_id}/mcp/",
            headers=self._headers(peer["access_token"], include_session=True),
            json={"jsonrpc": "2.0", "id": random.randint(10, 10000), "method": "tools/list", "params": {}},
            catch_response=True,
            name="MCP isolation peer hijack",
        ) as response:
            if response.status_code in (403, 404):
                response.success()
                return
            if response.status_code == 200:
                payload = response.json()
                denied = "error" in payload or payload.get("result", {}).get("isError", False)
                if denied:
                    response.success()
                    return
            response.failure(f"Peer hijack unexpectedly succeeded: {response.status_code} {response.text}")

    @task(1)
    def outsider_hijack(self) -> None:
        outsider = _STATE["users"]["outsider"]  # type: ignore[index]
        with self.client.post(
            f"/servers/{self.server_id}/mcp/",
            headers=self._headers(outsider["access_token"], include_session=True),
            json={"jsonrpc": "2.0", "id": random.randint(10, 10000), "method": "tools/list", "params": {}},
            catch_response=True,
            name="MCP isolation outsider hijack",
        ) as response:
            if response.status_code in (403, 404):
                response.success()
                return
            if response.status_code == 200:
                payload = response.json()
                denied = "error" in payload or payload.get("result", {}).get("isError", False)
                if denied:
                    response.success()
                    return
            response.failure(f"Outsider hijack unexpectedly succeeded: {response.status_code} {response.text}")
