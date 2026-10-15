# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_rate_limiter_per_server.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify per-user MCP catalog quotas through two live gateway replicas.

Run with --with-integration and fast-time MCP upstreams on ports 9080 and 9081.
Override them with FAST_TIME_SERVER_URL and SECOND_FAST_TIME_SERVER_URL.
The suite starts isolated gateways and reuses the Redis and MCP-session harness.
"""

from __future__ import annotations

# Standard
from collections.abc import Generator
from contextlib import ExitStack
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
import uuid

# Third-Party
import httpx
import pytest
import redis
import yaml

# First-Party
from tests.helpers.auth import make_test_jwt
from tests.integration.test_rate_limiter import redis_url_for_integration  # noqa: F401  # pylint: disable=unused-import
from tests.live_gateway.helpers.mcp_test_helpers import TEST_PASSWORD
from tests.live_gateway.plugins import _helpers
from tests.live_gateway.plugins.make_enforce_config import build_enforce_config

pytestmark = pytest.mark.integration


@dataclass
class ReplicaSet:
    """Hold isolated gateway clients, scoped identities, and limiter configuration."""

    clients: list[httpx.Client]
    tokens: dict[str, str]
    teams: list[str]
    stateful: bool
    global_ceiling: bool
    enforcement: str
    limiter_config: dict[str, Any]
    redis_url: str


@pytest.fixture(name="enforcement", scope="module", params=[os.environ["PLUGIN_ENFORCEMENT"]] if os.getenv("PLUGIN_ENFORCEMENT") else ["static", "binding"])
def _enforcement(request: pytest.FixtureRequest) -> str:
    """Select static enforcement or runtime bindings.

    Args:
        request: Enforcement parameter.

    Returns:
        Selected enforcement path.
    """
    assert request.param in {"static", "binding"}
    return str(request.param)


@pytest.fixture(
    name="replicas",
    scope="module",
    params=[(False, False, True), (True, False, True), (False, True, False), (True, True, False), (False, True, True), (True, True, True)],
    ids=["stateless", "stateful", "stateless-global", "stateful-global", "stateless-combined", "stateful-combined"],
)
def _replicas(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory, redis_url_for_integration: str, enforcement: str) -> Generator[ReplicaSet, None, None]:  # noqa: F811  # pylint: disable=redefined-outer-name
    """Start two gateways sharing a catalog database and an isolated Redis prefix.

    Args:
        request: Transport and global-ceiling parameters.
        tmp_path_factory: Isolated gateway file factory.
        redis_url_for_integration: Shared Redis harness URL.
        enforcement: Static configuration or runtime bindings.

    Yields:
        Gateway clients, scoped identities, teams, and limiter configuration.
    """
    stateful, global_ceiling, per_server_enabled = request.param
    root = tmp_path_factory.mktemp("per-server")
    prefix = f"rl-{uuid.uuid4().hex}"
    secret = uuid.uuid4().hex + uuid.uuid4().hex
    config = build_enforce_config(
        yaml.safe_load(Path("plugins/config.yaml").read_text(encoding="utf-8")),
        "RateLimiterPlugin",
        all_disabled=enforcement == "binding",
        config_overrides={
            "redis_url": redis_url_for_integration,
            "redis_key_prefix": prefix,
            "by_user": "2/h" if global_ceiling else None,
            "by_user_per_server": "2/h" if per_server_enabled else None,
            "by_tenant": None,
            "by_tool": {},
            "fail_mode": "closed",
        },
    )
    config["plugins"] = [p for p in config["plugins"] if p["name"] == "RateLimiterPlugin"]
    limiter_config = config["plugins"][0]["config"]
    config_path = root / "plugins.yaml"
    config_path.write_text(yaml.safe_dump(config))
    tokens = {"admin": make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=secret)}
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{root / 'gateway.db'}",
        "JWT_SECRET_KEY": secret,
        "AUTH_ENCRYPTION_SECRET": secret,
        "PLUGINS_ENABLED": "true",
        "PLUGIN_CONFIG_FILE": str(config_path),
        "PLUGINS_CONFIG_FILE": str(config_path),
        "REDIS_URL": redis_url_for_integration,
        "USE_STATEFUL_SESSIONS": str(stateful).lower(),
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "true",
        "SSRF_PROTECTION_ENABLED": "false",
        "REQUIRE_USER_IN_DB": "false",
        "EMAIL_AUTH_ENABLED": "true",
        "PLATFORM_ADMIN_PASSWORD": TEST_PASSWORD,
        "DEFAULT_USER_PASSWORD": TEST_PASSWORD,
        "ADMIN_REQUIRE_PASSWORD_CHANGE_ON_BOOTSTRAP": "false",
        "PASSWORD_CHANGE_ENFORCEMENT_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
    }
    with ExitStack() as stack:
        clients = []
        for index in range(2):
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            log_path = root / f"replica-{index}.log"
            log = stack.enter_context(log_path.open("w"))
            process = stack.enter_context(subprocess.Popen([sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)], env=env, stdout=log, stderr=log))
            stack.callback(_stop_gateway, process)
            client = stack.enter_context(httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=_helpers.api_headers(tokens["admin"]), timeout=30))
            for _ in range(120):
                assert process.poll() is None, log_path.read_text()
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.5)
            else:
                pytest.fail(f"Gateway startup timed out: {log_path.read_text()}")
            _helpers.assert_plugin_active(client, "RateLimiterPlugin", expected_mode="enforce" if enforcement == "static" else "disabled")
            clients.append(client)
        for user in ("alice", "bob"):
            response = clients[0].post("/auth/email/admin/users", json={"email": f"{user}@example.com", "password": TEST_PASSWORD, "is_admin": False})
            assert response.status_code == 201, response.text
        roles = clients[0].get("/rbac/roles")
        roles.raise_for_status()
        role_id = next(role["id"] for role in roles.json() if role["name"] == "developer")
        teams = [_helpers.create_team(clients[0], name=f"quota_team_{index}_{prefix}") for index in range(2)]
        for index, team_id in enumerate(teams):
            stack.callback(_helpers.delete_team, clients[0], team_id=team_id)
            for user in ("alice", "bob") if index == 0 else ("alice",):
                response = clients[0].post(f"/teams/{team_id}/members", json={"email": f"{user}@example.com", "role": "member"})
                assert response.status_code == 201, response.text
                response = clients[0].post(f"/rbac/users/{user}@example.com/roles", json={"role_id": role_id, "scope": "team", "scope_id": team_id})
                assert response.status_code in {200, 201}, response.text
                key = user if index == 0 else "alice_other_team"
                tokens[key] = make_test_jwt(f"{user}@example.com", is_admin=False, teams=[team_id], secret=secret)
        store = redis.from_url(redis_url_for_integration)
        try:
            yield ReplicaSet(clients, tokens, teams, stateful, global_ceiling, enforcement, limiter_config, redis_url_for_integration)
        finally:
            keys = list(store.scan_iter(match=f"{prefix}:*"))
            if keys:
                store.delete(*keys)
            store.close()


def _stop_gateway(process: subprocess.Popen[bytes]) -> None:
    """Stop a gateway subprocess and reap it.

    Args:
        process: Gateway subprocess.
    """
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_user_catalog_quota_across_replicas(replicas: ReplicaSet) -> None:
    """Check catalog isolation, user isolation, shared tools, replicas, and the global ceiling.

    Args:
        replicas: Isolated live gateway replicas and caller tokens.
    """
    clients, tokens = replicas.clients, replicas.tokens
    stateful, global_ceiling = replicas.stateful, replicas.global_ceiling
    suffix = uuid.uuid4().hex
    gateways = []
    servers = []
    with ExitStack() as cleanup:
        for index, label in enumerate(("a", "b", "c")):
            url = _helpers.FAST_TIME_URL if label != "b" else os.getenv("SECOND_FAST_TIME_SERVER_URL", "http://localhost:9081/mcp")
            response = clients[0].post("/gateways", json={"name": f"quota_{label}_{suffix}", "url": url, "transport": "STREAMABLEHTTP", "team_id": replicas.teams[index // 2], "visibility": "team"})
            response.raise_for_status()
            gateway_id = response.json()["id"]
            cleanup.callback(clients[0].delete, f"/gateways/{gateway_id}")
            tools = _helpers.wait_for_gateway_tools(clients[0], gateway_id)
            response = clients[0].post(
                "/servers",
                json={"server": {"name": f"quota_{label}_{suffix}", "associated_tools": [t["id"] for t in tools], "team_id": replicas.teams[index // 2], "visibility": "team"}},
            )
            response.raise_for_status()
            server_id = response.json()["id"]
            cleanup.callback(clients[0].delete, f"/servers/{server_id}")
            gateways.append(tools)
            servers.append(server_id)
        echo_a = _helpers.find_echo_tool(gateways[0])
        echo_b = _helpers.find_echo_tool(gateways[1])
        second_a = _helpers.find_flaky_tool(gateways[0])

        def invoke(replica: int, user: str, catalog: int, tool: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
            client = clients[replica]
            sid = _helpers.initialize_session(client, server_id=servers[catalog], token=tokens[user])
            assert bool(sid) == stateful, f"Unexpected session mode: {sid!r}"
            return _helpers.call_tool(client, server_id=servers[catalog], token=tokens[user], tool_name=tool["name"], arguments=arguments, session_id=sid)

        for user in ("alice", "bob"):
            headers = _helpers.api_headers(tokens[user])
            assert clients[0].get(f"/tools/{gateways[2][0]['id']}", headers=headers).status_code in {403, 404}
            assert clients[0].get(f"/servers/{servers[2]}", headers=headers).status_code in {403, 404}
            denied = clients[0].post(
                f"/servers/{servers[2]}/mcp/",
                headers=_helpers.mcp_headers(tokens[user]),
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": _helpers.MCP_PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "quota-denied", "version": "1"}},
                },
            )
            assert denied.status_code in {403, 404}, denied.text

        if replicas.enforcement == "binding":
            for _ in range(3):
                assert not invoke(0, "alice", 0, echo_a, {"message": "disabled"}).get("isError", False)
            for team_id in replicas.teams:
                binding = _helpers.create_tool_plugin_binding(
                    clients[0],
                    team_id=team_id,
                    tool_name="*",
                    plugin_id="RateLimiterPlugin",
                    config=replicas.limiter_config,
                )
                cleanup.callback(_helpers.delete_tool_plugin_binding, clients[0], binding_id=binding["id"])

        # A long fixed window prevents minute-boundary races during live calls.
        if time.time() % 3600 > 3540:
            time.sleep(3600 - time.time() % 3600 + 0.1)
        window = int(time.time() // 3600)
        assert not invoke(0, "alice", 0, echo_a, {"message": "first"}).get("isError", False)
        assert not invoke(1, "alice", 0, second_a, {"key": suffix, "fail_times": 0}).get("isError", False)
        blocked = invoke(0, "alice", 0, echo_a, {"message": "third"})
        assert blocked["isError"] is True
        assert "RATE_LIMIT" in str(blocked), blocked
        other_catalog = invoke(1, "alice", 1, echo_b, {"message": "independent"})
        if global_ceiling:
            assert other_catalog["isError"] is True
            assert "RATE_LIMIT" in str(other_catalog), other_catalog
        else:
            assert not other_catalog.get("isError", False), other_catalog
        assert not invoke(1, "bob", 0, echo_a, {"message": "bob"}).get("isError", False)
        other_team = invoke(1, "alice_other_team", 2, _helpers.find_echo_tool(gateways[2]), {"message": "other-team"})
        assert not other_team.get("isError", False), other_team
        with redis.from_url(replicas.redis_url, decode_responses=True) as store:
            for team_id in replicas.teams:
                assert list(store.scan_iter(match=f"{replicas.limiter_config['redis_key_prefix']}:{team_id}:*")), "Missing tenant-scoped counters"
        assert int(time.time() // 3600) == window, "Test crossed the fixed-window boundary"


@pytest.mark.parametrize("rest_method", ["GET", "POST"])
def test_prompt_limits_across_rest_and_mcp(replicas: ReplicaSet, rest_method: str) -> None:
    """Preserve global prompt limits and exclude prompts from catalog quotas.

    Args:
        replicas: Isolated live gateways and limiter configuration.
        rest_method: REST prompt retrieval method.
    """
    if replicas.enforcement == "binding":
        pytest.skip("Tool bindings do not activate prompt hooks")
    clients = replicas.clients
    suffix = uuid.uuid4().hex
    with ExitStack() as cleanup:
        prompt = _helpers.register_prompt(clients[0], name=f"quota_prompt_{suffix}", template="quota prompt", arguments=[])
        cleanup.callback(_helpers.delete_prompt, clients[0], prompt_id=prompt["id"])
        servers = []
        for index in range(2):
            server_id = _helpers.create_virtual_server(clients[0], name=f"quota_prompt_{index}_{suffix}", tool_ids=[], prompt_ids=[prompt["id"]])
            cleanup.callback(clients[0].delete, f"/servers/{server_id}")
            servers.append(server_id)
        with redis.from_url(replicas.redis_url) as store:
            keys = list(store.scan_iter(match=f"{replicas.limiter_config['redis_key_prefix']}:*"))
            if keys:
                store.delete(*keys)
        rest = clients[0].request(rest_method, f"/prompts/{prompt['id']}", json={} if rest_method == "POST" else None)
        assert rest.status_code == 200, rest.text
        for index, server_id in enumerate(servers):
            token = replicas.tokens["admin"]
            sid = _helpers.initialize_session(clients[index], server_id=server_id, token=token)
            response = clients[index].post(
                f"/servers/{server_id}/mcp/",
                headers=_helpers.mcp_headers(token, session_id=sid),
                json={"jsonrpc": "2.0", "id": index + 1, "method": "prompts/get", "params": {"name": prompt["name"], "arguments": {}}},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            if replicas.global_ceiling and index == 1:
                assert "error" in payload and "RATE_LIMIT" in str(payload), payload
                assert "RATE_LIMIT_CONTEXT_MISSING" not in str(payload), payload
            else:
                assert "result" in payload, payload
                assert _helpers.prompt_text(payload["result"]) == "quota prompt"
        rest = clients[1].request(rest_method, f"/prompts/{prompt['id']}", json={} if rest_method == "POST" else None)
        if replicas.global_ceiling:
            assert rest.status_code in {422, 429}, rest.text
            assert "RATE_LIMIT" in rest.text and "RATE_LIMIT_CONTEXT_MISSING" not in rest.text
        else:
            assert rest.status_code == 200, rest.text
            with redis.from_url(replicas.redis_url) as store:
                assert not list(store.scan_iter(match=f"{replicas.limiter_config['redis_key_prefix']}:*")), "Prompts consumed catalog quota"
