# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_token_exchange_discovery_credential.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Prove the token-exchange discovery credential against a running gateway.

The mock upstream accepts the discovery service token only for ``initialize``
and the list methods, and accepts only an exchanged user token for
``tools/call``. The mock authorization server issues the service token through
``client_credentials`` and records every token-exchange subject token.
"""

# Future
from __future__ import annotations

# Standard
from collections.abc import Iterator
import contextlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from typing import Any, cast
import uuid

# Third-Party
import httpx
import jwt
from mcp.server import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent, Tool
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# Local
from tests.live_gateway.mcp.test_token_exchange_credential_isolation import _free_port, _serve, _stop, _Store

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AUDIENCE = "https://discovery-upstream.test"
_CLIENT_ID = "discovery-live"
_CLIENT_SECRET = secrets.token_urlsafe(24)
_SERVICE_TOKEN = "discovery-live-service-token"  # pragma: allowlist secret - test-only AS bearer
_USER_TOKEN = "discovery-live-user-token"  # pragma: allowlist secret - test-only AS bearer
_LIST_METHODS = {"initialize", "notifications/initialized", "tools/list", "resources/list", "prompts/list", "ping"}


def _token_endpoint(store: _Store, signing_key: str, issuer: str) -> Starlette:
    """Issue the service token for client_credentials and a user token for a verified session subject."""

    async def token(request: Request) -> JSONResponse:
        form = await request.form()
        grant_type = str(form.get("grant_type", ""))
        if str(form.get("client_id", "")) != _CLIENT_ID or str(form.get("client_secret", "")) != _CLIENT_SECRET:
            store.record(grant_type=grant_type, accepted=False)
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        if grant_type == "client_credentials":
            store.record(grant_type=grant_type, scope=str(form.get("scope", "")), accepted=True)
            return JSONResponse({"access_token": _SERVICE_TOKEN, "token_type": "Bearer", "expires_in": 3600})
        subject = str(form.get("subject_token", ""))
        try:
            claims = jwt.decode(subject, signing_key, algorithms=["HS256"], issuer=issuer, audience="mcpgateway-api", options={"require": ["exp", "iss", "aud", "sub"]})
            accepted = claims.get("token_use") == "session"
        except jwt.PyJWTError:
            accepted = False
        store.record(grant_type=grant_type, subject_token=subject, accepted=accepted)
        if not accepted:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        return JSONResponse({"access_token": _USER_TOKEN, "token_type": "Bearer", "expires_in": 3600, "audience": _AUDIENCE})

    return Starlette(routes=[Route("/token", token, methods=["POST"])])


def _upstream(store: _Store) -> Any:
    """Expose one tool; accept the service token for list methods and only the user token for calls."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:  # noqa: ARG001
        return ListToolsResult(tools=[Tool(name="discovered", description="Discovered test tool", input_schema={"type": "object", "properties": {}})])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:  # noqa: ARG001
        return CallToolResult(content=[TextContent(type="text", text="discovered tool ran")])

    server = Server("discovery-upstream", version="1.0", on_list_tools=list_tools, on_call_tool=call_tool)
    app = server.streamable_http_app(streamable_http_path="/mcp", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    async def guarded(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["path"] != "/mcp":
            await app(scope, receive, send)
            return
        headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
        token = headers.get("authorization", "").removeprefix("Bearer ")
        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        method = ""
        with contextlib.suppress(ValueError, AttributeError):
            method = str(json.loads(body or b"{}").get("method", ""))
        allowed = {_SERVICE_TOKEN, _USER_TOKEN} if method in _LIST_METHODS or not body else {_USER_TOKEN}
        store.record_request(f"{method or scope['method']}:{token}")
        if token not in allowed:
            await JSONResponse({"error": "token not allowed for this method"}, status_code=401)(scope, receive, send)
            return
        replayed = False

        async def replay() -> dict[str, Any]:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await app(scope, replay, send)

    return guarded


@pytest.fixture
def discovery_stack(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """Start the AS, the policy upstream, and a one-worker SQLite gateway."""
    signing_key = secrets.token_urlsafe(48)
    issuer = "mcpgateway"
    as_store, upstream_store = _Store(), _Store()
    as_server = upstream_server = as_worker = upstream_worker = None
    gateway_process = api = admin = None
    owned_gateway_ids: list[str] = []
    admin_email = "discovery-admin@example.com"
    admin_password = secrets.token_urlsafe(24)

    try:
        upstream_server, upstream_worker, upstream_port = _serve(_upstream(upstream_store), "discovery-mcp")
        as_server, as_worker, as_port = _serve(_token_endpoint(as_store, signing_key, issuer), "discovery-as")
        gateway_port = _free_port()
        env = {
            "PATH": os.environ["PATH"],
            "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), *[str(Path(p).resolve()) for p in os.getenv("PYTHONPATH", "").split(os.pathsep) if p]]),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
            "CACHE_TYPE": "memory",
            "REDIS_URL": "",
            "JWT_SECRET_KEY": signing_key,
            "JWT_ISSUER": issuer,
            "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
            "PLATFORM_ADMIN_EMAIL": admin_email,
            "PLATFORM_ADMIN_PASSWORD": admin_password,  # pragma: allowlist secret
            "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(24),
            "AUTH_REQUIRED": "true",
            "REQUIRE_USER_IN_DB": "true",
            "MCPGATEWAY_ADMIN_API_ENABLED": "true",
            "MCPGATEWAY_UI_ENABLED": "false",
            "MCPGATEWAY_A2A_ENABLED": "false",
            "APP_DOMAIN": f"http://127.0.0.1:{gateway_port}",
            "SSRF_PROTECTION_ENABLED": "true",
            "SSRF_ALLOW_LOCALHOST": "true",
            "SSRF_ALLOW_PRIVATE_NETWORKS": "false",
            "LOG_LEVEL": os.getenv("DISCOVERY_LIVE_LOG_LEVEL", "ERROR"),
            "PYTHONUNBUFFERED": "1",
        }
        log_path = tmp_path / "gateway.log"
        with log_path.open("w") as log_file:
            gateway_process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port), "--workers", "1"],
                cwd=tmp_path,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )  # noqa: S603
            base_url = f"http://127.0.0.1:{gateway_port}"
            api = httpx.Client(base_url=base_url, timeout=30, trust_env=False)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                assert gateway_process.poll() is None, f"Gateway exited: {log_path.read_text()[-3000:]}"
                with contextlib.suppress(httpx.TransportError):
                    if api.get("/health").status_code == 200:
                        break
                time.sleep(0.1)
            else:
                pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-3000:]}")

            login = api.post("/auth/email/login", json={"email": admin_email, "password": admin_password})  # pragma: allowlist secret
            assert login.status_code == 200, login.text[:500]
            session_jwt = login.json()["access_token"]
            assert jwt.decode(session_jwt, options={"verify_signature": False})["token_use"] == "session"
            admin = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {session_jwt}"}, timeout=30, trust_env=False)

            response = admin.post(
                "/gateways",
                json={
                    "name": f"discovery-live-{uuid.uuid4().hex[:10]}",
                    "url": f"http://127.0.0.1:{upstream_port}/mcp",
                    "transport": "STREAMABLEHTTP",
                    "visibility": "public",
                    "auth_type": "oauth",
                    "oauth_config": {
                        "grant_type": "token-exchange",
                        "client_id": _CLIENT_ID,
                        "client_secret": _CLIENT_SECRET,
                        "token_url": f"http://127.0.0.1:{as_port}/token",
                        "target_audience": _AUDIENCE,
                        "discovery": {"grant_type": "client_credentials", "scopes": ["mcp.discover"]},
                    },
                },
            )
            assert response.status_code in {200, 201}, response.text[:1000]
            gateway_id = str(response.json().get("id") or response.json().get("gateway", {}).get("id"))
            owned_gateway_ids.append(gateway_id)

            yield {
                "api": api,
                "admin": admin,
                "base_url": base_url,
                "session_jwt": session_jwt,
                "gateway_id": gateway_id,
                "as_store": as_store,
                "upstream_store": upstream_store,
                "log_path": log_path,
            }
    finally:
        if admin is not None:
            for gateway_id in owned_gateway_ids:
                with contextlib.suppress(Exception):
                    admin.delete(f"/gateways/{gateway_id}")
            admin.close()
        if api is not None:
            api.close()
        if gateway_process is not None:
            gateway_process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                gateway_process.wait(timeout=10)
            if gateway_process.poll() is None:
                gateway_process.kill()
                gateway_process.wait(timeout=5)
        if as_server is not None and as_worker is not None:
            _stop(as_server, as_worker)
        if upstream_server is not None and upstream_worker is not None:
            _stop(upstream_server, upstream_worker)


def _gateway_tools(admin: httpx.Client, gateway_id: str) -> list[dict[str, Any]]:
    """Return the catalog tools of one gateway."""
    response = admin.get("/tools", params={"include_inactive": "true"})
    assert response.status_code == 200, response.text[:500]
    return [row for row in response.json() if row.get("gateway_id", row.get("gatewayId")) == gateway_id]


def test_discovery_credential_registration_fetch_tools_and_invocation(discovery_stack: dict[str, Any]) -> None:
    """Registration and Fetch Tools discover with the service token; tool calls use the exchanged user token."""
    api = discovery_stack["api"]
    admin = discovery_stack["admin"]
    gateway_id = discovery_stack["gateway_id"]
    session_jwt = discovery_stack["session_jwt"]
    as_store = discovery_stack["as_store"]
    upstream_store = discovery_stack["upstream_store"]

    def exchanges() -> list[dict[str, Any]]:
        return [row for row in as_store.snapshot() if row.get("grant_type") == "urn:ietf:params:oauth:grant-type:token-exchange"]

    # Registration discovered the tool with the service token, without any user exchange.
    tools = _gateway_tools(admin, gateway_id)
    assert [row.get("original_name", row.get("originalName")) for row in tools] == ["discovered"], discovery_stack["log_path"].read_text()[-3000:]
    assert any(row.get("grant_type") == "client_credentials" and row["accepted"] and row.get("scope") == "mcp.discover" for row in as_store.snapshot())
    assert exchanges() == []

    # Fetch Tools with only the ContextForge session cookie (the Admin UI shape): no bearer header.
    csrf = secrets.token_urlsafe(16)
    fetch = httpx.post(
        f"{discovery_stack['base_url']}/oauth/fetch-tools/{gateway_id}",
        cookies={"jwt_token": session_jwt, "mcpgateway_csrf_token": csrf},
        # Same headers as the Admin UI fetch: cookie auth requires a same-origin /admin referer.
        headers={"x-csrf-token": csrf, "Origin": discovery_stack["base_url"], "Referer": f"{discovery_stack['base_url']}/admin/"},
        timeout=30,
        trust_env=False,
    )
    assert fetch.status_code == 200, f"{fetch.text[:500]}\n{discovery_stack['log_path'].read_text()[-3000:]}"
    assert fetch.json()["success"] is True
    assert exchanges() == [], "Fetch Tools exchanged the session cookie JWT"
    assert not any(row.get("subject_token") == session_jwt for row in as_store.snapshot())
    assert _gateway_tools(admin, gateway_id)

    # Every upstream request so far used the service token, and none carried the session JWT.
    upstream_requests = upstream_store.request_snapshot()
    assert upstream_requests
    assert all(entry.endswith(f":{_SERVICE_TOKEN}") for entry in upstream_requests), upstream_requests
    assert not any(session_jwt in entry for entry in upstream_requests)

    # A tool call exchanges the caller's session JWT; the upstream receives only the exchanged user token.
    tool_name = tools[0]["name"]
    call = api.post(
        "/rpc",
        headers={"Authorization": f"Bearer {session_jwt}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": {}}},
    )
    assert call.status_code == 200, call.text[:1000]
    payload = cast(dict[str, Any], call.json())
    assert "error" not in payload and payload.get("result", {}).get("isError") is not True, payload
    assert any(row.get("subject_token") == session_jwt and row["accepted"] for row in exchanges())
    call_requests = [entry for entry in upstream_store.request_snapshot() if entry.startswith("tools/call:")]
    assert call_requests == [f"tools/call:{_USER_TOKEN}"], upstream_store.request_snapshot()

    # Without a usable user JWT the call is rejected and the upstream sees no tools/call.
    before = len(upstream_store.request_snapshot())
    unauthenticated = api.post("/rpc", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool_name, "arguments": {}}})
    assert unauthenticated.status_code in {401, 403}
    assert not any(entry.startswith("tools/call:") for entry in upstream_store.request_snapshot()[before:])
