# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_plugin_bindings_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify agent binding isolation through an authenticated gateway and HTTP upstream.
"""

# Standard
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from typing import Any

# Third-Party
import httpx
import pytest
import yaml

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MARKERS = {"x-agent-policy": "agent", "x-tool-policy": "tool", "x-wildcard-policy": "wildcard"}


class _EchoHeaders(BaseHTTPRequestHandler):
    """Return received headers through the real upstream HTTP response."""

    def do_POST(self) -> None:
        """Consume the request and return its headers."""
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.dumps({"headers": dict(self.headers)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress upstream access logs."""


def _request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    """Require a successful response and return the JSON body."""
    response = client.request(method, path, **kwargs)
    assert response.is_success, response.text
    return response.json()


@contextmanager
def _gateway_client(directory: Path, env: dict[str, str], key: str) -> Generator[httpx.Client, None, None]:
    """Run one isolated gateway and close its process tree after the test."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=key, algorithm="HS256")
    log_path = directory / "gateway.log"
    with log_path.open("w") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=make_auth_headers(token), timeout=30, follow_redirects=True, trust_env=False) as client:
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()[-8000:]
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(log_path.read_text()[-8000:])
                yield client
        finally:
            if os.name == "nt":
                subprocess.run(
                    [str(Path(os.environ["SYSTEMROOT"]) / "System32" / "taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture(scope="module")
def binding_gateway(tmp_path_factory: pytest.TempPathFactory) -> Generator[tuple[httpx.Client, str, str, dict[str, str]], None, None]:
    """Start a gateway with an isolated database and an optional Redis backend."""
    directory = tmp_path_factory.mktemp("agent-binding-gateway")
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHeaders)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    config = directory / "plugins.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "plugins": [
                    {
                        "name": "HeaderFilter",
                        "kind": "plugins.header_filter.header_filter_plugin.HeaderFilter",
                        "hooks": ["agent_pre_invoke", "tool_pre_invoke"],
                        "mode": "disabled",
                        "priority": 10,
                        "config": {"filter_headers": []},
                    }
                ]
            }
        )
    )
    key = secrets.token_urlsafe(48)
    redis_url = os.getenv("A2A_BINDING_TEST_REDIS_URL", "")
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), os.getenv("PYTHONPATH", "")]),
        "DATABASE_URL": f"sqlite:///{directory / 'gateway.db'}",
        "CACHE_TYPE": "redis" if redis_url else "memory",
        "REDIS_URL": redis_url,
        "JWT_SECRET_KEY": key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "AUTH_REQUIRED": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "true",
        "SSRF_ALLOW_LOCALHOST": "true",
        "PLUGINS_ENABLED": "true",
        "PLUGINS_CONFIG_FILE": str(config),
        "OBSERVABILITY_ENABLED": "false",
        "OTEL_ENABLE_OBSERVABILITY": "false",
        "LOG_LEVEL": "INFO",
        "PYTHONUNBUFFERED": "1",
    }
    try:
        with _gateway_client(directory, env, key) as client:
            team = _request(client, "POST", "/teams/", json={"name": "binding-regression-team"})["id"]
            for name, team_id in [("search", team), ("other", team), ("teamless", None)]:
                _request(
                    client,
                    "POST",
                    "/a2a",
                    json={
                        "agent": {"name": name, "agent_type": "generic", "endpoint_url": f"http://127.0.0.1:{upstream.server_port}/", "passthrough_headers": list(_MARKERS)},
                        "visibility": "public",
                        "team_id": team_id,
                    },
                )
            yield client, team, key, env
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def binding_peer(binding_gateway: tuple[httpx.Client, str, str, dict[str, str]], tmp_path_factory: pytest.TempPathFactory) -> Generator[httpx.Client, None, None]:
    """Start a second process with the same database, Redis, and signing key."""
    _, _, key, env = binding_gateway
    with _gateway_client(tmp_path_factory.mktemp("agent-binding-peer"), env, key) as client:
        yield client


def _bind(client: httpx.Client, team: str, name: str, header: str) -> Any:
    """Save an agent binding through the public API."""
    return _request(
        client, "POST", "/v1/a2a-agents/plugin-bindings/", params={"team_id": team}, json={"agent_name": name, "plugin_id": "HeaderFilter", "mode": "enforce", "config": {"filter_headers": [header]}}
    )


def _invoke(client: httpx.Client, name: str) -> str:
    """Return the headers received by the upstream agent."""
    result = _request(client, "POST", f"/a2a/{name}/invoke", json={"parameters": {"prompt": "check binding"}}, headers=_MARKERS)
    return json.dumps(result).lower()


def test_agent_bindings_control_real_outgoing_requests(binding_gateway: tuple[httpx.Client, str, str, dict[str, str]]) -> None:
    """Verify collisions, precedence, updates, deletion, concurrency, and teamless calls."""
    client, team, key, _ = binding_gateway
    tool_body = {"teams": {team: {"policies": [{"tool_names": ["search", "*"], "plugin_id": "HeaderFilter", "mode": "enforce", "config": {"filter_headers": ["x-tool-policy"]}}]}}}
    _request(client, "POST", "/v1/tools/plugin_bindings/", json=tool_body)
    for name in ("search", "other", "teamless"):
        baseline = _invoke(client, name)
        assert all(marker in baseline for marker in _MARKERS), baseline

    wildcard = _bind(client, team, "*", "x-wildcard-policy")
    specific = _bind(client, team, "search", "x-agent-policy")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: _invoke(client, "search"), range(12)))
    for result in results:
        assert "x-agent-policy" not in result, result
        assert "x-tool-policy" in result and "x-wildcard-policy" in result, result
    other = _invoke(client, "other")
    assert "x-wildcard-policy" not in other and "x-agent-policy" in other, other
    assert all(marker in _invoke(client, "teamless") for marker in _MARKERS)

    filtered = _request(client, "GET", f"/v1/a2a-agents/plugin-bindings/{team}", params={"agent_name": "search"})
    assert filtered["total"] == 1
    assert filtered["bindings"][0]["agentName"] == "search"
    global_filtered = _request(client, "GET", "/v1/a2a-agents/plugin-bindings/", params={"agent_name": "search"})
    assert global_filtered["total"] == 1
    narrowed = make_test_jwt("admin@example.com", is_admin=True, teams=[], secret=key, algorithm="HS256")
    hidden = _request(client, "GET", f"/v1/a2a-agents/plugin-bindings/{team}", params={"agent_name": "search"}, headers=make_auth_headers(narrowed))
    assert hidden["total"] == 0 and hidden["bindings"] == []
    denied = client.post(
        "/v1/a2a-agents/plugin-bindings/", params={"team_id": team}, headers=make_auth_headers(narrowed), json={"agent_name": "search", "plugin_id": "HeaderFilter", "mode": "enforce"}
    )
    assert denied.status_code == 403, denied.text
    _request(
        client,
        "POST",
        "/v1/a2a-agents/plugin-bindings/",
        params={"team_id": team},
        json={"agent_name": "search", "plugin_id": "HeaderFilter", "mode": "disabled", "config": {"filter_headers": ["x-agent-policy"]}},
    )
    disabled = _invoke(client, "search")
    assert all(marker in disabled for marker in _MARKERS), disabled
    _bind(client, team, "search", "x-tool-policy")
    updated = _invoke(client, "search")
    assert "x-tool-policy" not in updated and "x-agent-policy" in updated, updated
    response = client.delete(f"/v1/a2a-agents/plugin-bindings/{specific['id']}")
    assert response.is_success, response.text
    inherited = _invoke(client, "search")
    assert "x-wildcard-policy" not in inherited and "x-tool-policy" in inherited, inherited
    response = client.delete(f"/v1/a2a-agents/plugin-bindings/{wildcard['id']}")
    assert response.is_success, response.text
    assert all(marker in _invoke(client, "search") for marker in _MARKERS)

    with httpx.Client(base_url=str(client.base_url), trust_env=False) as anonymous:
        response = anonymous.post("/a2a/search/invoke", json={"parameters": {}})
        assert response.status_code in (401, 403), response.text


@pytest.mark.parametrize("agent_name", ["search", "*"])
def test_admin_binding_writes_refresh_warm_agent_cache(binding_gateway: tuple[httpx.Client, str, str, dict[str, str]], agent_name: str) -> None:
    """Apply admin form changes to existing agent managers."""
    client, team, _, _ = binding_gateway
    assert all(marker in _invoke(client, "search") for marker in _MARKERS)
    form = {"team_id": team, "agent_name": agent_name, "plugin_id": "HeaderFilter", "mode": "enforce", "priority": "10", "config": json.dumps({"filter_headers": ["x-agent-policy"]})}
    response = client.post("/admin/a2a/plugin-bindings", data=form)
    assert response.status_code == 200, response.text
    applied = _invoke(client, "search")
    assert "x-agent-policy" not in applied and "x-tool-policy" in applied, applied
    other = _invoke(client, "other")
    assert ("x-agent-policy" not in other) == (agent_name == "*"), other
    listed = _request(client, "GET", f"/v1/a2a-agents/plugin-bindings/{team}", params={"agent_name": agent_name})
    assert listed["total"] == 1
    binding_id = listed["bindings"][0]["id"]
    form["config"] = json.dumps({"filter_headers": ["x-tool-policy"]})
    response = client.post("/admin/a2a/plugin-bindings", data=form)
    assert response.status_code == 200, response.text
    updated = _invoke(client, "search")
    assert "x-tool-policy" not in updated and "x-agent-policy" in updated, updated
    response = client.post(f"/admin/a2a/plugin-bindings/{binding_id}/delete")
    assert response.status_code == 200, response.text
    restored = _invoke(client, "search")
    assert all(marker in restored for marker in _MARKERS), restored
    assert all(marker in _invoke(client, "teamless") for marker in _MARKERS)


@pytest.mark.skipif(not os.getenv("A2A_BINDING_TEST_REDIS_URL"), reason="requires an isolated real Redis URL")
def test_agent_binding_changes_reach_peer_worker(
    binding_gateway: tuple[httpx.Client, str, str, dict[str, str]],
    binding_peer: httpx.Client,
) -> None:
    """Verify signed invalidation across two real gateway processes."""
    import redis

    client, team, _, env = binding_gateway
    with redis.Redis.from_url(env["REDIS_URL"]) as backend:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if backend.pubsub_numsub("plugin:invalidation")[0][1] >= 2:
                break
            time.sleep(0.1)
        else:
            pytest.fail("Both gateway invalidation subscribers must connect to Redis")
        assert backend.info("server")["redis_version"]

    for worker in (client, binding_peer):
        assert all(marker in _invoke(worker, "search") for marker in _MARKERS)
        assert all(marker in _invoke(worker, "other") for marker in _MARKERS)

    def wait_for_policy(worker: httpx.Client, name: str, removed: str | None) -> str:
        """Poll received headers until the peer applies its updated policy."""
        deadline = time.monotonic() + 15
        observed = ""
        while time.monotonic() < deadline:
            observed = _invoke(worker, name)
            if removed is None and all(marker in observed for marker in _MARKERS):
                return observed
            if removed is not None and removed not in observed:
                return observed
            time.sleep(0.1)
        pytest.fail(f"Policy propagation failed for {name}: {observed}")

    specific = _bind(client, team, "search", "x-agent-policy")
    propagated = wait_for_policy(binding_peer, "search", "x-agent-policy")
    assert "x-tool-policy" in propagated and "x-wildcard-policy" in propagated, propagated

    response = binding_peer.post(
        "/admin/a2a/plugin-bindings",
        data={
            "team_id": team,
            "agent_name": "search",
            "plugin_id": "HeaderFilter",
            "mode": "enforce",
            "priority": "10",
            "config": json.dumps({"filter_headers": ["x-tool-policy"]}),
        },
    )
    assert response.status_code == 200, response.text
    reverse = wait_for_policy(client, "search", "x-tool-policy")
    assert "x-agent-policy" in reverse, reverse

    wildcard = _bind(client, team, "*", "x-wildcard-policy")
    wait_for_policy(binding_peer, "other", "x-wildcard-policy")
    response = client.delete(f"/v1/a2a-agents/plugin-bindings/{specific['id']}")
    assert response.is_success, response.text
    inherited = wait_for_policy(binding_peer, "search", "x-wildcard-policy")
    assert "x-tool-policy" in inherited and "x-agent-policy" in inherited, inherited
    response = binding_peer.post(f"/admin/a2a/plugin-bindings/{wildcard['id']}/delete")
    assert response.status_code == 200, response.text
    for worker in (client, binding_peer):
        wait_for_policy(worker, "search", None)
        wait_for_policy(worker, "other", None)
        assert all(marker in _invoke(worker, "teamless") for marker in _MARKERS)
