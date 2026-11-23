# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_token_exchange_delegation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Prove RFC 8693 delegation against a running gateway.

The mock authorization server issues a client-credentials actor token and adds
an ``act`` claim to the exchanged token only when the exchange carries that
actor token. The mock upstream accepts a ``tools/call`` only with an exchanged
token whose ``act.sub`` names the gateway client, and records the claims it saw.
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
_AUDIENCE = "https://delegation-upstream.test"
_CLIENT_ID = "delegation-live"
_CLIENT_SECRET = secrets.token_urlsafe(24)
_AS_SIGNING_KEY = secrets.token_urlsafe(48)
_SERVICE_TOKEN = "delegation-live-service-token"  # pragma: allowlist secret - test-only AS bearer
_ACTOR_TOKEN = "delegation-live-actor-token"  # pragma: allowlist secret - test-only AS bearer
_LIST_METHODS = {"initialize", "notifications/initialized", "server/discover", "tools/list", "resources/list", "prompts/list", "ping"}


def _token_endpoint(store: _Store, signing_key: str, issuer: str) -> Starlette:
    """Issue discovery and actor tokens, and exchanged tokens with ``act`` only when an actor token is sent."""

    async def token(request: Request) -> JSONResponse:
        form = await request.form()
        grant_type = str(form.get("grant_type", ""))
        if str(form.get("client_id", "")) != _CLIENT_ID or str(form.get("client_secret", "")) != _CLIENT_SECRET:
            store.record(grant_type=grant_type, accepted=False)
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        if grant_type == "client_credentials":
            scope = str(form.get("scope", ""))
            store.record(grant_type=grant_type, scope=scope, accepted=True)
            issued = _SERVICE_TOKEN if scope == "mcp.discover" else _ACTOR_TOKEN
            return JSONResponse({"access_token": issued, "token_type": "Bearer", "expires_in": 3600})
        subject = str(form.get("subject_token", ""))
        try:
            subject_claims = jwt.decode(subject, signing_key, algorithms=["HS256"], issuer=issuer, audience="mcpgateway-api", options={"require": ["exp", "iss", "aud", "sub"]})
        except jwt.PyJWTError:
            store.record(grant_type=grant_type, accepted=False)
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        actor_token = str(form.get("actor_token", ""))
        store.record(grant_type=grant_type, subject_token=subject, actor_token=actor_token, actor_token_type=str(form.get("actor_token_type", "")), accepted=True)
        claims: dict[str, Any] = {"sub": subject_claims["sub"], "aud": _AUDIENCE, "exp": int(time.time()) + 3600}
        if actor_token == _ACTOR_TOKEN:
            claims["act"] = {"sub": _CLIENT_ID}
        return JSONResponse({"access_token": jwt.encode(claims, _AS_SIGNING_KEY, algorithm="HS256"), "token_type": "Bearer", "expires_in": 3600})

    return Starlette(routes=[Route("/token", token, methods=["POST"])])


def _upstream(store: _Store) -> Any:
    """Expose one tool; accept the service token for list methods and only a delegated token for calls."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:  # noqa: ARG001
        return ListToolsResult(tools=[Tool(name="delegated", description="Delegation test tool", input_schema={"type": "object", "properties": {}})])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:  # noqa: ARG001
        return CallToolResult(content=[TextContent(type="text", text="delegated tool ran")])

    server = Server("delegation-upstream", version="1.0", on_list_tools=list_tools, on_call_tool=call_tool)
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
        try:
            claims = jwt.decode(token, _AS_SIGNING_KEY, algorithms=["HS256"], audience=_AUDIENCE)
        except jwt.PyJWTError:
            claims = {}
        delegated = claims.get("act", {}).get("sub") == _CLIENT_ID
        if method in _LIST_METHODS or not body:
            allowed = token == _SERVICE_TOKEN or delegated
        else:
            store.record(method=method, act=claims.get("act"), sub=claims.get("sub"))
            allowed = delegated
        if not allowed:
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
def delegation_stack(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """Start the AS, the delegation-checking upstream, and a one-worker SQLite gateway."""
    signing_key = secrets.token_urlsafe(48)
    issuer = "mcpgateway"
    as_store, upstream_store = _Store(), _Store()
    as_server = upstream_server = as_worker = upstream_worker = None
    gateway_process = api = admin = None
    owned_gateway_ids: list[str] = []
    admin_email = "delegation-admin@example.com"
    admin_password = secrets.token_urlsafe(24)

    try:
        upstream_server, upstream_worker, upstream_port = _serve(_upstream(upstream_store), "delegation-mcp")
        as_server, as_worker, as_port = _serve(_token_endpoint(as_store, signing_key, issuer), "delegation-as")
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
            "LOG_LEVEL": os.getenv("DELEGATION_LIVE_LOG_LEVEL", "ERROR"),
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
            admin = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {session_jwt}"}, timeout=30, trust_env=False)

            response = admin.post(
                "/gateways",
                json={
                    "name": f"delegation-live-{uuid.uuid4().hex[:10]}",
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
                        "actor_token_source": "client_credentials",
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


def test_delegation_tool_call_carries_act_claim(delegation_stack: dict[str, Any]) -> None:
    """A tool call on a delegation gateway sends an actor token, and the upstream sees ``act.sub`` naming the gateway client."""
    api = delegation_stack["api"]
    admin = delegation_stack["admin"]
    session_jwt = delegation_stack["session_jwt"]
    as_store = delegation_stack["as_store"]
    upstream_store = delegation_stack["upstream_store"]

    stored = admin.get(f"/gateways/{delegation_stack['gateway_id']}")
    assert stored.status_code == 200, stored.text[:500]
    oauth_config = stored.json().get("oauth_config") or stored.json().get("oauthConfig")
    assert oauth_config["actor_token_source"] == "client_credentials"
    assert oauth_config["actor_token_type"] == "urn:ietf:params:oauth:token-type:access_token"

    tools = [row for row in admin.get("/tools").json() if row.get("gateway_id", row.get("gatewayId")) == delegation_stack["gateway_id"]]
    assert tools, delegation_stack["log_path"].read_text()[-3000:]
    call = api.post(
        "/rpc",
        headers={"Authorization": f"Bearer {session_jwt}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tools[0]["name"], "arguments": {}}},
    )
    assert call.status_code == 200, call.text[:1000]
    payload = cast(dict[str, Any], call.json())
    assert "error" not in payload and payload.get("result", {}).get("isError") is not True, f"{payload}\n{delegation_stack['log_path'].read_text()[-3000:]}"

    exchanges = [row for row in as_store.snapshot() if row.get("grant_type") == "urn:ietf:params:oauth:grant-type:token-exchange"]
    assert exchanges and all(row["actor_token"] == _ACTOR_TOKEN for row in exchanges), exchanges
    assert all(row["actor_token_type"] == "urn:ietf:params:oauth:token-type:access_token" for row in exchanges)
    assert any(row["subject_token"] == session_jwt for row in exchanges)
    assert [row for row in upstream_store.snapshot() if row["method"] == "tools/call"] == [{"method": "tools/call", "act": {"sub": _CLIENT_ID}, "sub": jwt.decode(session_jwt, options={"verify_signature": False})["sub"]}]

    # A second call reuses the cached exchanged token: no new actor or exchange request.
    before = len(as_store.snapshot())
    again = api.post(
        "/rpc",
        headers={"Authorization": f"Bearer {session_jwt}"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tools[0]["name"], "arguments": {}}},
    )
    assert again.status_code == 200 and "error" not in again.json()
    assert len(as_store.snapshot()) == before
