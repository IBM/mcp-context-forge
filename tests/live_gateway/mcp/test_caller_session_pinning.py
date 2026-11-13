# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_caller_session_pinning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify session-less caller continuity through real gateway and upstream processes."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from threading import Barrier

import httpx
import pytest

from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.mcp.test_request_trace_policy import _port, _ready, _stop, _wait

pytestmark = pytest.mark.e2e
_ROOT = Path(__file__).resolve().parents[3]
_UPSTREAM = '''
from mcp.server.mcpserver import MCPServer, Context
from mcp.server.lowlevel.helper_types import ReadResourceContents
from starlette.middleware.base import BaseHTTPMiddleware
from pathlib import Path
import asyncio
import json
import sys
import uvicorn
class CounterServer(MCPServer):
    async def read_resource(self, uri, context=None):
        if str(uri) == "counter://state":
            return [ReadResourceContents(content=str(current_state(context)[1]), mime_type="text/plain")]
        return await super().read_resource(uri, context)
mcp = CounterServer("caller-counter")
counters = {}
def record(event):
    with Path(sys.argv[3]).open("a") as output:
        output.write(json.dumps(event) + "\\n")
def current_state(ctx):
    connection = getattr(ctx.session, "_connection", ctx.session)
    if id(connection) not in counters:
        counters[id(connection)] = [connection, 0]
    return counters[id(connection)]
@mcp.tool()
async def increment(ctx: Context, hold: bool = False) -> str:
    """Increment the counter owned by this MCP session."""
    state = current_state(ctx)
    state[1] += 1
    record({"event": "dispatch", "connection": id(state[0]), "hold": hold})
    if hold:
        while not Path(sys.argv[3]).with_suffix(".release").exists():
            await asyncio.sleep(0.01)
    return str(state[1])
@mcp.resource("counter://state")
def counter_state() -> str:
    """Read the counter without incrementing it."""
    return "0"
@mcp.prompt()
def state(ctx: Context) -> str:
    """Render the counter owned by this MCP session."""
    return str(current_state(ctx)[1])
from mcp.server import runner
original_connection = runner.Connection.for_loop
def observed_connection(*args, **kwargs):
    connection = original_connection(*args, **kwargs)
    record({"event": "created", "connection": id(connection)})
    return connection
runner.Connection.for_loop = staticmethod(observed_connection)
app = mcp.sse_app() if sys.argv[2] == "SSE" else mcp.streamable_http_app(stateless_http=False, json_response=True)
class Capture(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method == "POST":
            body = json.loads(await request.body())
            if body.get("method") == "tools/call":
                with Path(sys.argv[3]).open("a") as output:
                    output.write(json.dumps({"event": "http", "traceparent": request.headers.get("traceparent")}) + "\\n")
        return await call_next(request)
app.add_middleware(Capture)
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="error")
'''

_GATEWAY = """
from pathlib import Path
import json
import sys
import uvicorn
from mcpgateway.services import upstream_session_registry as registry
original_entry = registry._CallerEntry
class ObservedLock:
    def __init__(self, lock, route):
        self.lock, self.route = lock, route
    async def __aenter__(self):
        if self.lock.locked():
            with Path(sys.argv[2]).open("a") as output:
                output.write(json.dumps({"route": self.route}) + "\\n")
        return await self.lock.__aenter__()
    async def __aexit__(self, *args):
        return await self.lock.__aexit__(*args)
def observed_entry(*args, **kwargs):
    entry = original_entry(*args, **kwargs)
    entry.lock = ObservedLock(entry.lock, entry.binding.routing_key)
    return entry
registry._CallerEntry = observed_entry
uvicorn.run("mcpgateway.main:app", host="127.0.0.1", port=int(sys.argv[1]), log_level="error")
"""


@pytest.fixture(params=["SSE", "STREAMABLEHTTP"])
def counter_gateway(request, tmp_path):
    """Start an isolated authenticated gateway and a legacy stateful counter upstream."""
    with ExitStack() as stack:
        transport = request.param[0] if isinstance(request.param, tuple) else request.param
        multi_worker = isinstance(request.param, tuple) and request.param[1]
        traced = isinstance(request.param, tuple) and len(request.param) > 2 and request.param[2]
        stateful = isinstance(request.param, tuple) and len(request.param) > 3 and request.param[3]
        if traced:
            pytest.importorskip("opentelemetry.sdk")
        redis_url = ""
        if multi_worker:
            import redis

            executable = shutil.which("redis-server")
            if executable is None:
                pytest.fail("redis-server is required for the caller ownership test")
            redis_port = _port()
            redis_log = stack.enter_context((tmp_path / "redis.log").open("w"))
            redis_process = subprocess.Popen(
                [executable, "--bind", "127.0.0.1", "--port", str(redis_port), "--save", "", "--appendonly", "no", "--dir", str(tmp_path)], stdout=redis_log, stderr=subprocess.STDOUT
            )
            stack.callback(_stop, redis_process)
            redis_url = f"redis://127.0.0.1:{redis_port}/0"
            probe = redis.Redis.from_url(redis_url)
            stack.callback(probe.close)

            def redis_ready():
                try:
                    return probe.ping()
                except redis.ConnectionError:
                    return False

            _wait(redis_ready, "ownership Redis")
        upstream_port, gateway_port = _port(), _port()
        upstream_log = stack.enter_context((tmp_path / "upstream.log").open("w"))
        upstream_events = tmp_path / "upstream-events.jsonl"
        upstream = subprocess.Popen([sys.executable, "-c", _UPSTREAM, str(upstream_port), transport, str(upstream_events)], stdout=upstream_log, stderr=subprocess.STDOUT, cwd=tmp_path)
        stack.callback(_stop, upstream)
        _wait(lambda: _ready(f"http://127.0.0.1:{upstream_port}/", upstream), "counter upstream")
        signing_key = secrets.token_urlsafe(48)
        env = {
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(_ROOT),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
            "CACHE_TYPE": "redis" if multi_worker else "memory",
            "REDIS_URL": redis_url,
            "MCPGATEWAY_SESSION_AFFINITY_ENABLED": str(bool(multi_worker)).lower(),
            "JWT_SECRET_KEY": signing_key,
            "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
            "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
            "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
            "PLATFORM_ADMIN_EMAIL": "admin@example.com",
            "AUTH_REQUIRED": "true",
            "MCP_REQUIRE_AUTH": "false",
            "REQUIRE_USER_IN_DB": "false",
            "MCPGATEWAY_ADMIN_API_ENABLED": "true",
            "MCPGATEWAY_UI_ENABLED": "false",
            "MCPGATEWAY_A2A_ENABLED": "false",
            "SSRF_ALLOW_LOCALHOST": "true",
            "PLUGINS_ENABLED": "false",
            "OTEL_ENABLE_OBSERVABILITY": str(bool(traced)).lower(),
            "OTEL_TRACES_EXPORTER": "console",
            "OTEL_HTTPX_INSTRUMENTATION_ENABLED": "true",
            "OTEL_SQLALCHEMY_INSTRUMENTATION_ENABLED": "false",
            "OBSERVABILITY_ENABLED": "false",
            "USE_STATEFUL_SESSIONS": str(bool(stateful)).lower(),
            "MCP_CLIENT_CONNECT_MODE": "legacy",
            "AUTO_REFRESH_SERVERS": "false",
            "LOG_LEVEL": "ERROR",
            "PYTHONUNBUFFERED": "1",
        }
        gateway_log = stack.enter_context((tmp_path / "gateway.log").open("w"))
        queue_events = tmp_path / "queue-events.jsonl"
        gateway_command = (
            [sys.executable, "-c", _GATEWAY, str(gateway_port), str(queue_events)]
            if multi_worker
            else [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)]
        )
        gateway = subprocess.Popen(gateway_command, env=env, cwd=tmp_path, stdout=gateway_log, stderr=subprocess.STDOUT)
        stack.callback(_stop, gateway)
        _wait(lambda: _ready(f"http://127.0.0.1:{gateway_port}/health", gateway), "gateway readiness", timeout=60)
        tokens = [make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key) for _ in range(2)]
        client = stack.enter_context(httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", headers=make_auth_headers(tokens[0]), timeout=30, trust_env=False))
        client.signing_key = signing_key
        client.upstream_events = upstream_events
        client.queue_events = queue_events
        client.release_upstream = upstream_events.with_suffix(".release")
        if multi_worker:
            client.redis_probe = probe
        suffix = "sse" if transport == "SSE" else "mcp"
        response = client.post("/gateways", json={"name": "caller-counter", "url": f"http://127.0.0.1:{upstream_port}/{suffix}", "transport": transport, "visibility": "public"})
        assert response.status_code in (200, 201), response.text
        gateway_id = response.json()["id"]
        tools = client.get("/tools").json()
        if isinstance(tools, dict):
            tools = tools["tools"]
        tool = next(tool for tool in tools if tool["name"].endswith("increment"))
        resources = client.get("/resources").json()
        prompts = client.get("/prompts").json()
        resources = resources["resources"] if isinstance(resources, dict) else resources
        prompts = prompts["prompts"] if isinstance(prompts, dict) else prompts
        client.prompt_name = next(prompt["name"] for prompt in prompts if prompt["name"].endswith("state"))
        response = client.post(
            "/servers",
            json={
                "server": {
                    "name": "caller-server",
                    "associated_tools": [tool["id"]],
                    "associated_resources": [resource["id"] for resource in resources],
                    "associated_prompts": [prompt["id"] for prompt in prompts],
                },
                "visibility": "public",
            },
        )
        assert response.status_code in (200, 201), response.text
        if multi_worker:
            peer_port = _port()
            peer_log = stack.enter_context((tmp_path / "peer.log").open("w"))
            peer = subprocess.Popen([sys.executable, "-c", _GATEWAY, str(peer_port), str(queue_events)], env=env, cwd=tmp_path, stdout=peer_log, stderr=subprocess.STDOUT)
            stack.callback(_stop, peer)
            _wait(lambda: _ready(f"http://127.0.0.1:{peer_port}/health", peer), "peer readiness", timeout=60)
            client.peer = stack.enter_context(httpx.Client(base_url=f"http://127.0.0.1:{peer_port}", timeout=30, trust_env=False))
        yield client, gateway_id, response.json()["id"], tool["name"], tokens


def _response(client, endpoint, name, *, token, server_id=None, key=None, extra_meta=None, traceparent=None, arguments=None):
    """Send a wire-format request without downstream session headers."""
    params = {"name": name, "arguments": arguments or {}}
    if server_id:
        params["server_id"] = server_id
    if key is not None:
        params["_meta"] = {"io.contextforge/sessionKey": key}
    if extra_meta:
        params.setdefault("_meta", {}).update(extra_meta)
    if endpoint != "/rpc":
        params.setdefault("_meta", {}).update({"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}})
    trace_headers = {"traceparent": traceparent} if traceparent else {}
    return client.post(
        endpoint,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
        headers={
            **trace_headers,
            "Authorization": f"Bearer {token}" if token else "",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call",
            "Mcp-Name": name,
        },
    )


def _call(client, endpoint, name, **kwargs):
    """Read a successful counter result from the gateway response."""
    response = _response(client, endpoint, name, **kwargs)
    assert response.status_code == 200, response.text
    result = response.json()
    assert "error" not in result, result
    assert not result["result"].get("isError"), result
    return int(result["result"]["content"][0]["text"])


def test_sessionless_continuity_and_token_isolation(counter_gateway):
    """Defaults stay fresh; metadata and gateway opt-in provide isolated continuity."""
    client, gateway_id, server_id, name, tokens = counter_gateway
    assert [_call(client, "/rpc", name, token=tokens[0], server_id=server_id) for _ in range(3)] == [1, 1, 1]
    for endpoint in ("/rpc", f"/servers/{server_id}/mcp/"):
        kwargs = {"server_id": server_id} if endpoint == "/rpc" else {}
        assert [_call(client, endpoint, name, token=tokens[0], key=endpoint, **kwargs) for _ in range(3)] == [1, 2, 3]
        assert _call(client, endpoint, name, token=tokens[1], key=endpoint, **kwargs) == 1
        assert _call(client, endpoint, name, token=tokens[0], key=endpoint + "-other", **kwargs) == 1
    response = client.put(f"/gateways/{gateway_id}", json={"pin_sessions_by_caller": True})
    assert response.status_code == 200, response.text
    assert response.json()["pinSessionsByCaller"] is True
    for endpoint in ("/rpc", f"/servers/{server_id}/mcp/"):
        kwargs = {"server_id": server_id} if endpoint == "/rpc" else {}
        # Both endpoints use the same authenticated caller and virtual server binding.
        expected = [1, 2, 3] if endpoint == "/rpc" else [4, 5, 6]
        assert [_call(client, endpoint, name, token=tokens[0], **kwargs) for _ in range(3)] == expected
    assert _call(client, "/rpc", name, token=tokens[1], server_id=server_id) == 1
    endpoint = f"/servers/{server_id}/mcp/"
    assert [_call(client, endpoint, name, token=None, key="anonymous") for _ in range(3)] == [1, 1, 1]
    for target in ("/rpc", endpoint):
        kwargs = {"server_id": server_id} if target == "/rpc" else {}
        invalid = _response(client, target, name, token=tokens[0], key=42, **kwargs)
        assert invalid.json()["error"]["code"] == -32602, invalid.text
        denied_tokens = [
            "invalid-bearer-token",
            make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=client.signing_key, expires_in_minutes=-1),
            make_test_jwt("admin@example.com", is_admin=True, teams=["other-team"], secret=client.signing_key),
            make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=client.signing_key, scopes={"permissions": ["tools.read"]}),
        ]
        for denied_token in denied_tokens:
            denied = _response(client, target, name, token=denied_token, key="protected", **kwargs)
            assert denied.status_code in (401, 403) or "error" in denied.json(), denied.text


@pytest.mark.parametrize("counter_gateway", [("STREAMABLEHTTP", True)], indirect=True)
def test_caller_continuity_across_workers(counter_gateway):
    """Alternating ingress workers execute one caller binding on its registered owner."""
    client, _, server_id, name, tokens = counter_gateway
    counts = [_call(client if index % 2 == 0 else client.peer, "/rpc", name, token=tokens[0], server_id=server_id, key="shared-conversation") for index in range(6)]
    assert counts == [1, 2, 3, 4, 5, 6]
    assert _call(client.peer, "/rpc", name, token=tokens[1], server_id=server_id, key="shared-conversation") == 1


@pytest.mark.parametrize("counter_gateway", [("SSE", False, True), ("STREAMABLEHTTP", False, True)], indirect=True)
def test_pinned_calls_use_current_trace_context(counter_gateway):
    """Each traced call retains counter continuity and forwards its own trace identity."""
    client, _, server_id, name, tokens = counter_gateway
    traces = [f"{index:032x}" for index in (101, 102, 103)]
    counts = [_call(client, "/rpc", name, token=tokens[0], server_id=server_id, key="traced", traceparent=f"00-{trace_id}-1234567890abcdef-01") for trace_id in traces]
    assert counts == [1, 2, 3]
    events = [json.loads(line) for line in client.upstream_events.read_text().splitlines()]
    assert [event["traceparent"].split("-")[1] for event in events if event["event"] == "http"] == traces


def test_tools_resources_and_prompts_share_the_caller_binding(counter_gateway):
    """Prompt and resource operations observe the state created by a tool call."""
    client, _, server_id, name, tokens = counter_gateway
    key = "cross-operation"
    assert _call(client, "/rpc", name, token=tokens[0], server_id=server_id, key=key) == 1
    for method, operation in (("resources/read", {"uri": "counter://state"}), ("prompts/get", {"name": client.prompt_name, "arguments": {}})):
        response = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": {**operation, "server_id": server_id, "_meta": {"io.contextforge/sessionKey": key}}})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert "error" not in payload, payload
        text = payload["result"]["contents"][0]["text"] if method == "resources/read" else payload["result"]["messages"][0]["content"]["text"]
        assert text == "1"


@pytest.mark.parametrize("counter_gateway", [("STREAMABLEHTTP", False, False, True)], indirect=True)
def test_existing_downstream_sessions_survive_caller_policy_changes(counter_gateway):
    """Legacy clients retain isolated upstream state while session-less callers opt in separately."""
    client, gateway_id, server_id, name, tokens = counter_gateway
    endpoint = f"/servers/{server_id}/mcp/"
    protocol_headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}

    def initialize():
        response = client.post(
            endpoint,
            headers=protocol_headers,
            json={"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "legacy-counter-client", "version": "1"}}},
        )
        assert response.status_code == 200, response.text
        session_id = response.headers["mcp-session-id"]
        initialized = client.post(endpoint, headers={**protocol_headers, "Mcp-Session-Id": session_id}, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert initialized.status_code in (200, 202), initialized.text
        return session_id

    def increment(session_id):
        response = client.post(
            endpoint, headers={**protocol_headers, "Mcp-Session-Id": session_id}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {}}}
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert "error" not in payload, payload
        return int(payload["result"]["content"][0]["text"])

    first = initialize()
    assert [increment(first) for _ in range(3)] == [1, 2, 3]
    response = client.put(f"/gateways/{gateway_id}", json={"pin_sessions_by_caller": True})
    assert response.status_code == 200, response.text
    assert increment(first) == 4
    second = initialize()
    assert [increment(second) for _ in range(2)] == [1, 2]
    assert increment(first) == 5
    assert [_call(client, endpoint, name, token=tokens[0]) for _ in range(3)] == [1, 2, 3]


def _events(path, kind):
    """Read complete fixture observations emitted before the next synchronization point."""
    return [event for line in path.read_text().splitlines() if (event := json.loads(line)).get("event") == kind] if path.exists() else []


@pytest.mark.parametrize("counter_gateway", [("SSE", True), ("STREAMABLEHTTP", True)], indirect=True)
@pytest.mark.parametrize("endpoint_kind", ["rpc", "mcp"])
def test_concurrent_first_calls_share_one_owned_session(counter_gateway, endpoint_kind):
    """A first-use burst across workers preserves one session and every increment."""
    client, _, server_id, name, tokens = counter_gateway
    endpoint = "/rpc" if endpoint_kind == "rpc" else f"/servers/{server_id}/mcp/"
    barrier = Barrier(8)
    initial_creates = len(_events(client.upstream_events, "created"))
    initial_dispatches = len(_events(client.upstream_events, "dispatch"))

    def call(index):
        barrier.wait(timeout=10)
        return _call(client if index % 2 == 0 else client.peer, endpoint, name, token=tokens[0], server_id=server_id, key="concurrent-first-use")

    with ThreadPoolExecutor(max_workers=8) as executor:
        counts = list(executor.map(call, range(8)))
    assert sorted(counts) == list(range(1, 9))
    assert len(_events(client.upstream_events, "created")) - initial_creates == 1
    assert len(_events(client.upstream_events, "dispatch")) - initial_dispatches == 8
    keys = list(client.redis_probe.scan_iter("mcpgw:caller_owner:v1:*"))
    assert len(keys) == 1
    owner = client.redis_probe.hgetall(keys[0])
    assert owner[b"generation"]
    assert _call(client.peer, endpoint, name, token=tokens[0], server_id=server_id, key="concurrent-first-use") == 9
    assert client.redis_probe.hgetall(keys[0]) == owner


@pytest.mark.parametrize("counter_gateway", [("SSE", True), ("STREAMABLEHTTP", True)], indirect=True)
def test_queued_call_rejects_transferred_ownership(counter_gateway):
    """Observed lock contention allows deterministic ownership loss through real Redis and HTTP."""
    client, _, server_id, name, tokens = counter_gateway
    arguments = {"token": tokens[0], "server_id": server_id, "key": "ownership-transfer"}
    assert _call(client, "/rpc", name, **arguments) == 1
    probe = client.redis_probe
    key = next(probe.scan_iter("mcpgw:caller_owner:v1:*"))
    old_owner = probe.hgetall(key)
    assert _call(client.peer, "/rpc", name, token=tokens[1], server_id=server_id, key="unaffected") == 1
    other_key = next(candidate for candidate in probe.scan_iter("mcpgw:caller_owner:v1:*") if candidate != key)
    new_owner = probe.hget(other_key, "owner")
    assert new_owner != old_owner[b"owner"]
    creates = len(_events(client.upstream_events, "created"))
    dispatches = len(_events(client.upstream_events, "dispatch"))
    with ThreadPoolExecutor(max_workers=2) as executor:
        active = executor.submit(_call, client, "/rpc", name, arguments={"hold": True}, **arguments)
        try:
            _wait(lambda: len(_events(client.upstream_events, "dispatch")) == dispatches + 1, "held upstream call")
            queued = executor.submit(_response, client, "/rpc", name, **arguments)
            _wait(lambda: client.queue_events.exists() and key.decode().endswith(json.loads(client.queue_events.read_text().splitlines()[-1])["route"]), "queued caller admission")
            probe.hset(key, mapping={"owner": new_owner, "generation": "transferred-generation"})
        finally:
            client.release_upstream.touch()
        assert active.result(timeout=15) == 2
        rejected = queued.result(timeout=15).json()
    assert rejected["error"] == {"code": -32000, "message": "Caller session ownership lost"}
    assert len(_events(client.upstream_events, "created")) == creates
    assert len(_events(client.upstream_events, "dispatch")) == dispatches + 1
    assert probe.hget(key, "generation") == b"transferred-generation"
    assert _call(client.peer, "/rpc", name, token=tokens[1], server_id=server_id, key="unaffected") == 2
    assert _call(client.peer, "/rpc", name, **arguments) == 1
    assert _call(client, "/rpc", name, **arguments) == 2


@pytest.mark.parametrize("counter_gateway", [("STREAMABLEHTTP", True)], indirect=True)
def test_same_worker_reacquires_new_generation_after_expiry(counter_gateway):
    """Old caller records reject claims; expiry creates a new generation without changing legacy records."""
    client, _, server_id, name, tokens = counter_gateway
    arguments = {"token": tokens[0], "server_id": server_id, "key": "expiry"}
    assert _call(client, "/rpc", name, **arguments) == 1
    probe = client.redis_probe
    key = next(probe.scan_iter("mcpgw:caller_owner:v1:*"))
    previous = probe.hgetall(key)
    route = key.decode().removeprefix("mcpgw:caller_owner:v1:")
    old_key = f"mcpgw:pool_owner:{route}"
    legacy_key = "mcpgw:pool_owner:legacy-session"
    probe.set(legacy_key, "legacy-owner", ex=300)
    probe.set(old_key, previous[b"owner"], ex=300)
    dispatches = len(_events(client.upstream_events, "dispatch"))
    rejected = _response(client, "/rpc", name, **arguments).json()
    assert rejected["error"] == {"code": -32000, "message": "Caller session ownership lost"}
    assert len(_events(client.upstream_events, "dispatch")) == dispatches
    probe.delete(old_key)
    probe.pexpire(key, 1)
    _wait(lambda: not probe.exists(key), "caller lease expiry")
    assert _call(client, "/rpc", name, **arguments) == 1
    current = probe.hgetall(key)
    assert current[b"owner"] == previous[b"owner"]
    assert current[b"generation"] != previous[b"generation"]
    assert _call(client.peer, "/rpc", name, **arguments) == 2
    assert probe.get(legacy_key) == b"legacy-owner"
