#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Black-box MCP Events dispatch on an isolated authenticated gateway.

Location: ./tests/live_gateway/mcp/test_mcp_events.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

The synthetic application provider exercises gateway protocol federation only.
It does not qualify durable subscription custody or external callback delivery.
"""

# Standard
from collections.abc import AsyncGenerator, Generator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
from threading import Thread
import time
from typing import Any

# Third-Party
from fastapi import FastAPI
import httpx
from mcp.shared.exceptions import MCPError
import pytest

# First-Party
from mcpgateway.services.mcp_events import EventRequestContext

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

_OWNER = "owner@example.test"
_OTHER = "other@example.test"
_SERVER = "events-fixture-server"
_ROOT = Path(__file__).resolve().parents[3]


class SyntheticEventOwner:
    """Expose one synthetic event without an external service or scheduler."""

    def __init__(self) -> None:
        """Initialize current fixture consent."""
        self.revoked = False

    async def authorize(self, context: EventRequestContext, method: str) -> bool:
        """Require the original fixture owner for every request."""
        return not self.revoked and context.user.get("email") == _OWNER

    async def request(self, context: EventRequestContext, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Return fixture results and exercise current authority failures."""
        if method == "events/list":
            return {"events": [{"name": "example.changed", "delivery": ["webhook"], "inputSchema": {"type": "object"}, "payloadSchema": {"type": "object"}}]}
        if params.get("name") not in {"example.changed", "fixture.error", "fixture.revoke"}:
            raise MCPError(-32602, "Unknown fixture event")
        if method == "events/unsubscribe":
            return {}
        if params.get("name") == "fixture.error":
            raise RuntimeError(params["delivery"]["secret"])
        if params.get("name") == "fixture.revoke":
            self.revoked = True
        if "cursor" not in params or params["cursor"] is not None or "ttlMs" not in params or params["ttlMs"] is not None:
            raise ValueError("Explicit protocol nulls were not preserved")
        assert context.headers.get("authorization", "").startswith("Bearer ")
        return {"id": "sub_original-owner", "refreshBefore": "2026-11-16T00:00:00Z", "cursor": None, "truncated": False}


@contextmanager
def legacy_tool_endpoint() -> Generator[str, None, None]:
    """Own a private HTTP provider for actual pre-existing tool dispatch.

    Yields:
        The fixed loopback URL; no external provider or platform record is used.
    """

    class LegacyToolHandler(BaseHTTPRequestHandler):
        """Return bounded fixture evidence from the real outbound HTTP call."""

        def do_POST(self) -> None:  # noqa: N802 - HTTP handler interface.
            """Echo only the reviewed synthetic tool argument."""
            size = int(self.headers.get("Content-Length", "0"))
            if self.path != "/legacy-read" or not 0 < size <= 1024:
                self.send_error(400)
                return
            payload = json.loads(self.rfile.read(size))
            response = json.dumps({"echo": payload["value"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: Any) -> None:
            """Keep provider bodies and arguments out of subprocess output."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), LegacyToolHandler)
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    try:
        worker.start()
        yield f"http://127.0.0.1:{server.server_port}/legacy-read"
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        assert not worker.is_alive()


def app_factory() -> FastAPI:
    """Wrap the real gateway lifespan with one synthetic application owner."""
    # First-Party
    from mcpgateway.db import EmailTeam, EmailTeamMember, EmailUser, Role, Server, SessionLocal, Tool, UserRole
    from mcpgateway.main import app
    from mcpgateway.services.mcp_events import event_provider

    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
        """Seed only the subprocess database and release provider registration."""
        with legacy_tool_endpoint() as legacy_url, event_provider(_SERVER, SyntheticEventOwner()):
            async with original(application):
                with SessionLocal() as db:
                    db.add(EmailUser(email=_OTHER, full_name="Fixture other", is_active=True, is_admin=False))
                    db.flush()
                    for team_id in ["events-team-a", "events-team-b"]:
                        db.add(EmailTeam(id=team_id, name=team_id, slug=team_id, created_by=_OWNER))
                    db.flush()
                    db.add(EmailTeamMember(team_id="events-team-b", user_email=_OTHER, role="member", is_active=True))
                    role = Role(name="events-fixture-role", scope="global", created_by=_OWNER, permissions=["servers.use", "tools.read", "events.read", "events.subscribe", "events.unsubscribe"])
                    db.add(role)
                    db.flush()
                    db.add(UserRole(user_email=_OTHER, role_id=role.id, scope="global", granted_by=_OWNER))
                    legacy_tool = Tool(
                        id="events-legacy-tool",
                        name="fixture-legacy-echo",
                        original_name="fixture-legacy-echo",
                        custom_name="fixture-legacy-echo",
                        custom_name_slug="fixture-legacy-echo",
                        url=legacy_url,
                        integration_type="REST",
                        request_type="POST",
                        visibility="team",
                        team_id="events-team-a",
                        owner_email=_OWNER,
                        input_schema={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"], "additionalProperties": False},
                    )
                    db.add(Server(id=_SERVER, name="Events fixture", visibility="team", team_id="events-team-a", owner_email=_OWNER, tools=[legacy_tool]))
                    db.add(Server(id="events-unconfigured", name="No provider", visibility="team", team_id="events-team-a", owner_email=_OWNER))
                    db.commit()
                yield

    app.router.lifespan_context = lifespan
    return app


@dataclass(frozen=True)
class IsolatedGateway:
    """Retain fixture handles without exposing the ephemeral signing key."""

    client: httpx.Client = field(repr=False)
    signing_key: str = field(repr=False)
    enabled: bool
    log_path: Path


@pytest.fixture(params=[True, False], ids=["enabled", "disabled"])
def isolated_gateway(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[IsolatedGateway]:
    """Start the real gateway with private fixture storage and current auth."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    lock_name = "contextforge-events-" + secrets.token_hex(12) + ".lock"
    lock_path = Path(tempfile.gettempdir()) / lock_name
    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(_ROOT),
        "PORT": str(port),
        "FILELOCK_NAME": lock_name,
        "PRIMARY_WORKER_LOCK_PATH": str(tmp_path / "primary.lock"),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_EMAIL": _OWNER,
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "AUTH_REQUIRED": "true",
        "MCP_REQUIRE_AUTH": "true",
        "REQUIRE_USER_IN_DB": "true",
        "MCPGATEWAY_MCP_EVENTS_ENABLED": str(request.param).lower(),
        "MCPGATEWAY_ADMIN_API_ENABLED": "false",
        "MCPGATEWAY_UI_ENABLED": "false",
        "LLMCHAT_ENABLED": "false",
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
        "RATE_LIMITING_ENABLED": "false",
        "AUTH_CACHE_ENABLED": "false",
        "SSRF_ALLOW_LOCALHOST": "true",  # Only this isolated fixture provider.
        "LOG_LEVEL": "DEBUG",
        "LOG_DETAILED_REQUESTS": "true",
        "JSON_RESPONSE_ENABLED": "true",
        "USE_STATELESS_SESSIONS": "true",
        "PYTHONUNBUFFERED": "1",
    }
    log_path = tmp_path / "gateway.log"
    with log_path.open("w") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.live_gateway.mcp.test_mcp_events:app_factory", "--factory", "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp_path,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 90
            with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()[-3000:]
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail("Isolated gateway startup timed out")
                yield IsolatedGateway(client, signing_key, request.param, log_path)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait(timeout=5)
            assert process.poll() is not None
            lock_path.unlink(missing_ok=True)


def test_events_black_box_authenticated_endpoint_and_denials(isolated_gateway: IsolatedGateway) -> None:
    """Exercise native methods, both handshakes, authorization, and safe errors."""
    client, key = isolated_gateway.client, isolated_gateway.signing_key
    enabled, log_path = isolated_gateway.enabled, isolated_gateway.log_path
    owner = make_test_jwt(_OWNER, is_admin=True, teams=None, secret=key)
    owner_headers = {**make_auth_headers(owner), "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28"}
    endpoint = f"/servers/{_SERVER}/mcp"

    def rpc(method: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, path: str = endpoint) -> httpx.Response:
        """Send raw JSON so protocol nulls reach the native dispatcher."""
        effective_headers = dict(headers if headers is not None else owner_headers)
        arguments = dict(params or {})
        if effective_headers.get("MCP-Protocol-Version") == "2026-07-28":
            effective_headers["Mcp-Method"] = method
            if method == "tools/call":
                effective_headers["Mcp-Name"] = str(arguments["name"])
            arguments["_meta"] = {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientInfo": {"name": "events-fixture", "version": "1"},
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": arguments}
        return client.post(path, headers=effective_headers, json=body)

    assert rpc("server/discover", headers={"Accept": "application/json, text/event-stream"}).status_code == 401
    discovery = rpc("server/discover").json()
    assert "result" in discovery, discovery
    assert ("events" in discovery["result"]["capabilities"]) is enabled
    legacy = rpc(
        "initialize",
        {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "events-fixture", "version": "1"}},
        headers={key: value for key, value in owner_headers.items() if key != "MCP-Protocol-Version"},
    ).json()
    assert ("events" in legacy["result"]["capabilities"]) is enabled
    tools = rpc("tools/list").json()["result"]["tools"]
    assert any(tool["name"] == "fixture-legacy-echo" for tool in tools)
    for value, headers in [("fixture-legacy-v2", owner_headers), ("fixture-legacy-v1", {key: value for key, value in owner_headers.items() if key != "MCP-Protocol-Version"})]:
        called = rpc("tools/call", {"name": "fixture-legacy-echo", "arguments": {"value": value}}, headers=headers).json()
        assert "result" in called and called["result"].get("isError") is not True, called
        assert any(json.loads(item["text"]) == {"echo": value} for item in called["result"]["content"] if item["type"] == "text"), called
    if not enabled:
        assert rpc("events/list").json()["error"]["code"] == -32601
        return
    assert rpc("events/list").json()["result"]["events"][0]["name"] == "example.changed"
    assert "events" not in rpc("server/discover", path="/servers/events-unconfigured/mcp").json()["result"]["capabilities"]
    assert rpc("events/list", path="/servers/events-unconfigured/mcp").json()["error"]["code"] == -32601
    assert rpc("events/unknown").json()["error"]["code"] == -32601
    event_read_only = make_test_jwt(_OWNER, is_admin=True, teams=None, secret=key, scopes={"permissions": ["events.read"]})
    event_read_headers = {**owner_headers, **make_auth_headers(event_read_only)}
    assert "events" in rpc("server/discover", headers=event_read_headers).json()["result"]["capabilities"]
    assert rpc("events/list", headers=event_read_headers).json()["result"]["events"][0]["name"] == "example.changed"
    assert rpc("events/subscribe", headers=event_read_headers).json()["error"]["code"] == -32001
    narrowed = make_test_jwt(_OWNER, is_admin=True, teams=None, secret=key, scopes={"permissions": ["servers.use", "tools.read"]})
    assert "events" not in rpc("server/discover", headers={**owner_headers, **make_auth_headers(narrowed)}).json()["result"]["capabilities"]
    assert "error" in rpc("events/subscribe", headers={**owner_headers, **make_auth_headers(narrowed)}).json()
    public_only = make_test_jwt(_OWNER, is_admin=True, teams=[], secret=key)
    public_response = rpc("events/list", headers={**owner_headers, **make_auth_headers(public_only)})
    assert public_response.status_code == 403 or "error" in public_response.json()
    assert "example.changed" not in public_response.text
    foreign = make_test_jwt(_OTHER, teams=["events-team-b"], secret=key)
    foreign_result = rpc("events/list", headers={**owner_headers, **make_auth_headers(foreign)})
    assert foreign_result.status_code in {200, 403}
    assert "example.changed" not in foreign_result.text
    assert foreign_result.status_code == 403 or "error" in foreign_result.json()
    sentinel = "whsec_synthetic-black-box-secret-not-a-credential"
    params: dict[str, Any] = {
        "name": "example.changed",
        "arguments": {"projectId": "synthetic-project"},
        "delivery": {"mode": "webhook", "url": "https://callback.example.test/opaque", "secret": sentinel},
        "cursor": None,
        "ttlMs": None,
    }
    assert rpc("events/subscribe", {**params, "name": "foreign.changed"}).json()["error"]["code"] == -32602
    accepted = rpc("events/subscribe", params).json()
    assert accepted["result"]["id"] == "sub_original-owner"
    assert accepted["result"]["cursor"] is None
    assert rpc("events/subscribe", {**params, "name": "fixture.error"}).json()["error"]["code"] == -32603
    assert sentinel not in log_path.read_text()
    unsubscribed = rpc("events/unsubscribe", {"name": params["name"], "arguments": params["arguments"], "delivery": {"mode": "webhook", "url": params["delivery"]["url"]}}).json()
    assert set(unsubscribed["result"]) <= {"resultType", "_meta"}
    assert rpc("events/subscribe", {**params, "name": "fixture.revoke"}).json()["error"]["code"] == -32001
    assert rpc("events/list").json()["error"]["code"] == -32001
    assert sentinel not in log_path.read_text()
