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
from tests.integration.test_rate_limiter import redis_url_for_integration  # noqa: F401
from tests.live_gateway.helpers.mcp_test_helpers import TEST_PASSWORD
from tests.live_gateway.plugins import _helpers
from tests.live_gateway.plugins.make_enforce_config import build_enforce_config

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", params=[(False, False), (True, False), (False, True), (True, True)], ids=["stateless", "stateful", "stateless-global", "stateful-global"])
def replicas(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory, redis_url_for_integration: str) -> Generator[tuple[list[httpx.Client], dict[str, str], bool, bool], None, None]:  # noqa: F811
    """Start two gateways sharing a catalog database and an isolated Redis prefix.

    Args:
        request: Transport and global-ceiling parameters.
        tmp_path_factory: Isolated gateway file factory.
        redis_url_for_integration: Shared Redis harness URL.

    Yields:
        Clients, caller tokens, transport mode, and global-ceiling mode.
    """
    stateful, global_ceiling = request.param
    root = tmp_path_factory.mktemp("per-server")
    prefix = f"rl-{uuid.uuid4().hex}"
    secret = uuid.uuid4().hex + uuid.uuid4().hex
    config = build_enforce_config(
        yaml.safe_load(Path("plugins/config.yaml").read_text(encoding="utf-8")),
        "RateLimiterPlugin",
        config_overrides={
            "redis_url": redis_url_for_integration,
            "redis_key_prefix": prefix,
            "by_user": "2/h" if global_ceiling else None,
            "by_user_per_server": None if global_ceiling else "2/h",
            "by_tenant": None,
            "by_tool": {},
            "fail_mode": "closed",
        },
    )
    config["plugins"] = [p for p in config["plugins"] if p["name"] == "RateLimiterPlugin"]
    config_path = root / "plugins.yaml"
    config_path.write_text(yaml.safe_dump(config))
    tokens = {user: make_test_jwt(f"{user}@example.com", is_admin=True, teams=None, secret=secret) for user in ("admin", "alice", "bob")}
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
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)], env=env, stdout=log, stderr=log)
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
            _helpers.assert_plugin_active(client, "RateLimiterPlugin")
            clients.append(client)
        for user in ("alice", "bob"):
            response = clients[0].post("/auth/email/admin/users", json={"email": f"{user}@example.com", "password": TEST_PASSWORD, "is_admin": True})
            assert response.status_code == 201, response.text
        store = redis.from_url(redis_url_for_integration)
        try:
            yield clients, tokens, stateful, global_ceiling
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


def test_user_catalog_quota_across_replicas(replicas: tuple[list[httpx.Client], dict[str, str], bool, bool]) -> None:
    """Check catalog isolation, user isolation, shared tools, replicas, and the global ceiling.

    Args:
        replicas: Isolated live gateway replicas and caller tokens.
    """
    clients, tokens, stateful, global_ceiling = replicas
    suffix = uuid.uuid4().hex
    gateways = []
    servers = []
    with ExitStack() as cleanup:
        for label in ("a", "b"):
            url = _helpers.FAST_TIME_URL if label == "a" else os.getenv("SECOND_FAST_TIME_SERVER_URL", "http://localhost:9081/mcp")
            response = clients[0].post("/gateways", json={"name": f"quota_{label}_{suffix}", "url": url, "transport": "STREAMABLEHTTP"})
            response.raise_for_status()
            gateway_id = response.json()["id"]
            cleanup.callback(clients[0].delete, f"/gateways/{gateway_id}")
            tools = _helpers.wait_for_gateway_tools(clients[0], gateway_id)
            server_id = _helpers.create_virtual_server(clients[0], name=f"quota_{label}_{suffix}", tool_ids=[t["id"] for t in tools])
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
        assert int(time.time() // 3600) == window, "Test crossed the fixed-window boundary"
