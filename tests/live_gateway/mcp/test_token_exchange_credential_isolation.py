# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_token_exchange_credential_isolation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Prove token-exchange cache isolation through authenticated live RPC calls.
"""

from __future__ import annotations

# Standard
from collections.abc import Iterator
import contextlib
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from typing import Any, cast
import uuid

# Third-Party
import httpx
import jwt
import redis
from mcp.server import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent, Tool
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AUDIENCE = "https://credential-isolation-upstream.test"
_ACCESS_TOKEN = "credential-isolation-exchanged-token"  # pragma: allowlist secret - test-only AS bearer
_PASSWORD = "CredentialIsolation!42"  # pragma: allowlist secret


class _Store:
    """Keep token-exchange decisions and protected upstream calls thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: list[dict[str, Any]] = []
        self._requests: list[str] = []

    def record(self, **row: Any) -> None:
        with self._lock:
            self._rows.append(row)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._rows)

    def record_request(self, authorization: str) -> None:
        with self._lock:
            self._requests.append(authorization)

    def request_snapshot(self) -> list[str]:
        with self._lock:
            return list(self._requests)


def _free_port() -> int:
    """Select a currently free loopback port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve(app: Any, tag: str) -> tuple[uvicorn.Server, threading.Thread, int]:
    """Start a local stub server and wait until uvicorn is ready."""
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    worker = threading.Thread(target=server.run, daemon=True, name=f"token-exchange-{tag}")
    worker.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not worker.is_alive() or time.monotonic() >= deadline:
            server.should_exit = True
            worker.join(timeout=2)
            raise RuntimeError(f"{tag} stub did not start")
        time.sleep(0.05)
    return server, worker, port


def _stop(server: uvicorn.Server, worker: threading.Thread) -> None:
    """Stop one test-owned uvicorn server."""
    server.should_exit = True
    worker.join(timeout=5)


def _token_endpoint(store: _Store, signing_key: str, issuer: str) -> Starlette:
    """Verify each subject JWT and accept only user sessions or the setup admin."""

    async def exchange(request: Request) -> JSONResponse:
        form = await request.form()
        subject = str(form.get("subject_token", ""))
        accepted = False
        try:
            claims = jwt.decode(subject, signing_key, algorithms=["HS256"], issuer=issuer, audience="mcpgateway-api", options={"require": ["exp", "iss", "aud", "sub"]})
            accepted = claims.get("token_use") == "session" and claims.get("sub") in {request.app.state.accepted_user_id, request.app.state.accepted_admin_id}
        except jwt.PyJWTError:
            claims = {}
        store.record(subject_token=subject, accepted=accepted)
        if not accepted:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        return JSONResponse({"access_token": _ACCESS_TOKEN, "token_type": "Bearer", "expires_in": 3600, "audience": _AUDIENCE})

    app = Starlette(routes=[Route("/token", exchange, methods=["POST"])])
    app.state.accepted_user_id = ""
    app.state.accepted_admin_id = ""
    return app


def _upstream(store: _Store) -> Any:
    """Expose one protected tool and reject any inbound ContextForge JWT."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:  # noqa: ARG001
        return ListToolsResult(tools=[Tool(name="protected", description="Protected test tool", input_schema={"type": "object", "properties": {}})])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:  # noqa: ARG001
        store.record(executed=True)
        return CallToolResult(content=[TextContent(type="text", text="protected tool ran")])

    server = Server("credential-isolation-upstream", version="1.0", on_list_tools=list_tools, on_call_tool=call_tool)
    app = server.streamable_http_app(streamable_http_path="/mcp", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    async def guarded(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"] == "/mcp":
            headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
            authorization = headers.get("authorization", "")
            store.record_request(authorization)
            if authorization != f"Bearer {_ACCESS_TOKEN}":
                response = JSONResponse({"error": "inbound subject token rejected"}, status_code=401)
                await response(scope, receive, send)
                return
        await app(scope, receive, send)

    return guarded


@pytest.fixture
def live_stack(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """Start the AS, protected MCP server, and a one-worker SQLite gateway."""
    cache_url = os.getenv("TOKEN_EXCHANGE_TEST_REDIS_URL", "")
    if cache_url:
        redis_client = redis.Redis.from_url(cache_url)
        try:
            assert redis_client.ping(), "Configured token-exchange Redis is unavailable"
        finally:
            redis_client.close()
    signing_key = secrets.token_urlsafe(48)
    issuer = "mcpgateway"
    as_store, upstream_store = _Store(), _Store()
    user_id = ""
    admin_id = ""
    as_server = upstream_server = None
    as_worker = upstream_worker = None
    gateway_process = None
    api = None
    admin = None
    session_client = None
    owned_gateway_ids: list[str] = []
    owned_user_emails: list[str] = []
    owned_token_ids: list[str] = []
    owned_team_ids: list[str] = []
    owned_assignments: list[tuple[str, str, str]] = []
    owned_memberships: list[tuple[str, str]] = []
    user_email = f"credential-user-{uuid.uuid4().hex[:10]}@example.com"
    owned_user_emails.append(user_email)
    admin_email = "credential-admin@example.com"
    admin_password = secrets.token_urlsafe(24)

    # Start upstream first, then bind its actual token URL into the gateway record.
    try:
        upstream_server, upstream_worker, upstream_port = _serve(_upstream(upstream_store), "mcp")
        as_app = _token_endpoint(as_store, signing_key, issuer)
        as_server, as_worker, as_port = _serve(as_app, "as")
        gateway_port = _free_port()
        env = {
            "PATH": os.environ["PATH"],
            "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), *[str(Path(p).resolve()) for p in os.getenv("PYTHONPATH", "").split(os.pathsep) if p]]),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
            "CACHE_TYPE": "memory" if not cache_url else "redis",
            "REDIS_URL": cache_url,
            "JWT_SECRET_KEY": signing_key,
            "JWT_ISSUER": issuer,
            "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
            "PLATFORM_ADMIN_EMAIL": admin_email,
            "PLATFORM_ADMIN_PASSWORD": admin_password,
            "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(24),
            "AUTH_REQUIRED": "true",
            "REQUIRE_USER_IN_DB": "true",
            "MCPGATEWAY_ADMIN_API_ENABLED": "true",
            "MCPGATEWAY_UI_ENABLED": "false",
            "MCPGATEWAY_A2A_ENABLED": "false",
            "SSRF_PROTECTION_ENABLED": "true",
            "SSRF_ALLOW_LOCALHOST": "true",
            "SSRF_ALLOW_PRIVATE_NETWORKS": "false",
            "LOG_LEVEL": "ERROR",
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
            api = httpx.Client(base_url=base_url, timeout=15, trust_env=False)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                assert gateway_process.poll() is None, f"Gateway exited: {log_path.read_text()[-3000:]}"
                try:
                    if api.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-3000:]}")

            admin_login = api.post("/auth/email/login", json={"email": admin_email, "password": admin_password})
            assert admin_login.status_code == 200, admin_login.text[:500]
            admin_payload = admin_login.json()
            admin_id = str(jwt.decode(admin_payload["access_token"], options={"verify_signature": False})["sub"])
            admin = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {admin_payload['access_token']}"}, timeout=15, trust_env=False)

            user_create = admin.post(
                "/auth/email/admin/users",
                json={"email": user_email, "password": _PASSWORD, "full_name": "Credential Isolation User", "is_admin": False, "is_active": True, "password_change_required": False},
            )
            assert user_create.status_code == 201, user_create.text[:500]
            team = admin.post("/teams/", json={"name": f"credential-isolation-{uuid.uuid4().hex[:8]}", "visibility": "private"})
            assert team.status_code in {200, 201}, team.text[:500]
            team_id = team.json()["id"]
            owned_team_ids.append(team_id)
            membership = admin.post(f"/teams/{team_id}/members", json={"email": user_email, "role": "member"})
            assert membership.status_code in {200, 201}, membership.text[:500]
            owned_memberships.append((user_email, team_id))
            roles = admin.get("/rbac/roles")
            assert roles.status_code == 200, roles.text[:500]
            developer_id = next(row["id"] for row in roles.json() if row["name"] == "developer")
            assigned = admin.post(f"/rbac/users/{user_email}/roles", json={"role_id": developer_id, "scope": "team", "scope_id": team_id})
            assert assigned.status_code in {200, 201}, assigned.text[:500]
            owned_assignments.append((user_email, developer_id, team_id))

            user_login = api.post("/auth/email/login", json={"email": user_email, "password": _PASSWORD})
            assert user_login.status_code == 200, user_login.text[:500]
            session_jwt = user_login.json()["access_token"]
            session_claims = jwt.decode(session_jwt, options={"verify_signature": False})
            user_id = str(session_claims["sub"])
            assert session_claims["token_use"] == "session"
            session_client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {session_jwt}"}, timeout=15, trust_env=False)
            tokens: list[tuple[str, str]] = []
            for name in ("credential-isolation-api-a", "credential-isolation-api-b"):
                token_response = session_client.post("/tokens", json={"name": name + "-" + uuid.uuid4().hex[:8], "expires_in_days": 1, "team_id": team_id, "scope": {"permissions": ["tools.execute"]}})
                assert token_response.status_code == 201, token_response.text[:500]
                payload = token_response.json()
                token = payload["access_token"]
                token_obj = payload.get("token", payload)
                token_id = str(token_obj["id"])
                owned_token_ids.append(token_id)
                tokens.append((token, token_id))

            # Add a no-permission user for a route-level authorization denial.
            denied_email = f"credential-denied-{uuid.uuid4().hex[:10]}@example.com"
            owned_user_emails.append(denied_email)
            denied_create = admin.post(
                "/auth/email/admin/users",
                json={"email": denied_email, "password": _PASSWORD, "full_name": "Credential Denied User", "is_admin": False, "is_active": True, "password_change_required": False},
            )
            assert denied_create.status_code == 201, denied_create.text[:500]
            denied_login = api.post("/auth/email/login", json={"email": denied_email, "password": _PASSWORD})
            assert denied_login.status_code == 200, denied_login.text[:500]
            denied_jwt = denied_login.json()["access_token"]

            as_app.state.accepted_user_id = user_id
            as_app.state.accepted_admin_id = admin_id

            def register_gateway(name: str, visibility: str, private_team_id: str | None = None) -> str:
                gateway_payload = {
                    "name": name,
                    "url": f"http://127.0.0.1:{upstream_port}/mcp",
                    "transport": "STREAMABLEHTTP",
                    "visibility": visibility,
                    "auth_type": "oauth",
                    "oauth_config": {
                        "grant_type": "token-exchange",
                        "client_id": "credential-isolation-live",
                        "subject_token_source": "inbound_user_jwt",
                        "target_audience": _AUDIENCE,
                        "token_url": f"http://127.0.0.1:{as_port}/token",
                    },
                }
                if private_team_id:
                    gateway_payload["team_id"] = private_team_id
                response = admin.post("/gateways", json=gateway_payload)
                assert response.status_code in {200, 201}, response.text[:1000]
                gateway_id = str(response.json().get("id") or response.json().get("gateway", {}).get("id"))
                owned_gateway_ids.append(gateway_id)
                refreshed = admin.post(f"/gateways/{gateway_id}/tools/refresh")
                assert refreshed.status_code in {200, 201}, refreshed.text[:1000]
                return gateway_id

            public_id = register_gateway(f"credential-isolation-{uuid.uuid4().hex}", "public")
            private_team = admin.post("/teams/", json={"name": f"credential-hidden-{uuid.uuid4().hex[:8]}", "visibility": "private"})
            assert private_team.status_code in {200, 201}, private_team.text[:500]
            private_team_id = private_team.json()["id"]
            owned_team_ids.append(private_team_id)
            private_id = register_gateway(f"credential-private-{uuid.uuid4().hex}", "team", private_team_id)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                tools_response = admin.get("/tools")
                assert tools_response.status_code == 200, tools_response.text[:500]
                tool_rows = tools_response.json()
                public_tool_row = next(
                    (row for row in tool_rows if row.get("gateway_id", row.get("gatewayId")) == public_id and row.get("original_name", row.get("originalName")) == "protected"), None
                )
                private_tool_row = next(
                    (row for row in tool_rows if row.get("gateway_id", row.get("gatewayId")) == private_id and row.get("original_name", row.get("originalName")) == "protected"), None
                )
                if public_tool_row and private_tool_row:
                    break
                time.sleep(0.2)
            else:
                pytest.fail("Discovered tools did not appear before the deadline")
            assert public_tool_row and private_tool_row
            public_tool = public_tool_row["name"]
            private_tool = private_tool_row["name"]

            yield {
                "api": api,
                "admin": admin,
                "session": session_client,
                "base_url": base_url,
                "admin_jwt": admin_payload["access_token"],
                "session_jwt": session_jwt,
                "api_jwt": tokens[0][0],
                "second_api_jwt": tokens[1][0],
                "denied_jwt": denied_jwt,
                "user_id": user_id,
                "admin_id": admin_id,
                "admin_email": admin_email,
                "user_email": user_email,
                "denied_email": denied_email,
                "public_id": public_id,
                "private_id": private_id,
                "tool_name": public_tool,
                "private_tool_name": private_tool,
                "as_store": as_store,
                "upstream_store": upstream_store,
                "cache_url": cache_url,
            }
    finally:
        if admin is not None:
            for token_id in owned_token_ids:
                with contextlib.suppress(Exception):
                    admin.delete(f"/tokens/admin/{token_id}")
            for gateway_id in owned_gateway_ids:
                with contextlib.suppress(Exception):
                    admin.delete(f"/gateways/{gateway_id}")
            for email, role_id, team_id in owned_assignments:
                with contextlib.suppress(Exception):
                    admin.delete(f"/rbac/users/{email}/roles/{role_id}", params={"scope": "team", "scope_id": team_id})
            for email, team_id in owned_memberships:
                with contextlib.suppress(Exception):
                    admin.delete(f"/teams/{team_id}/members/{email}")
            for email in owned_user_emails:
                with contextlib.suppress(Exception):
                    admin.delete(f"/auth/email/admin/users/{email}")
            for team_id in owned_team_ids:
                with contextlib.suppress(Exception):
                    admin.delete(f"/teams/{team_id}")
            admin.close()
        if session_client is not None:
            session_client.close()
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


def test_rpc_token_exchange_isolates_subject_credentials(live_stack: dict[str, Any]) -> None:
    """Keep API subjects denied through cold, warm, and expired cache states."""
    api = live_stack["api"]
    api_jwt = live_stack["api_jwt"]
    second_api_jwt = live_stack["second_api_jwt"]
    session_jwt = live_stack["session_jwt"]
    admin_jwt = live_stack["admin_jwt"]
    as_store = live_stack["as_store"]
    upstream_store = live_stack["upstream_store"]
    tool_name = live_stack["tool_name"]

    def call_tool(token: str, name: str = tool_name) -> dict[str, Any]:
        response = api.post("/rpc", headers={"Authorization": f"Bearer {token}"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {}}})
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    def rpc_failed(payload: dict[str, Any]) -> bool:
        return "error" in payload or payload.get("result", {}).get("isError") is True

    def rpc_succeeded(payload: dict[str, Any]) -> bool:
        return "result" in payload and not rpc_failed(payload)

    def as_attempts() -> int:
        return len(as_store.snapshot())

    def as_denials_for_api(token: str = api_jwt) -> int:
        return sum(row["subject_token"] == token and not row["accepted"] for row in as_store.snapshot())

    def protected_executions() -> int:
        return len(upstream_store.snapshot())

    cold_api = call_tool(api_jwt)
    assert rpc_failed(cold_api)
    assert as_denials_for_api() > 0
    assert protected_executions() == 0

    before = as_attempts()
    assert rpc_succeeded(call_tool(session_jwt))
    assert as_attempts() > before
    assert protected_executions() == 1

    assert rpc_failed(call_tool(api_jwt))
    assert protected_executions() == 1

    before_repeat = as_attempts()
    assert rpc_succeeded(call_tool(session_jwt))
    assert as_attempts() == before_repeat
    assert protected_executions() == 2

    before_second_api = as_attempts()
    assert rpc_failed(call_tool(second_api_jwt))
    assert as_attempts() > before_second_api
    assert as_denials_for_api(second_api_jwt) > 0
    assert protected_executions() == 2

    before_denials = as_attempts()
    unauthenticated = api.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": {}}})
    assert unauthenticated.status_code in {401, 403}
    assert as_attempts() == before_denials
    assert rpc_failed(call_tool(session_jwt, live_stack["private_tool_name"]))
    assert as_attempts() == before_denials
    assert rpc_failed(call_tool(live_stack["denied_jwt"]))
    assert as_attempts() == before_denials
    assert protected_executions() == 2

    time.sleep(11)
    before_expired = as_attempts()
    assert rpc_failed(call_tool(api_jwt))
    assert as_attempts() > before_expired
    assert as_denials_for_api() >= 2
    assert protected_executions() == 2

    captured_subjects = {row["subject_token"] for row in as_store.snapshot()}
    admin_discovery_accepted = any(row["subject_token"] == admin_jwt and row["accepted"] for row in as_store.snapshot())
    upstream_auth = upstream_store.request_snapshot()
    observed_api_and_session = all(token in captured_subjects for token in (api_jwt, session_jwt))
    inbound_token_forwarded = any(f"Bearer {token}" in upstream_auth for token in (api_jwt, second_api_jwt, session_jwt))
    assert observed_api_and_session, "The AS did not verify both API and session subjects"
    assert live_stack["admin_email"] != live_stack["user_email"]
    assert admin_discovery_accepted, "The AS did not accept the separate discovery administrator"
    assert not inbound_token_forwarded, "An inbound ContextForge JWT reached the upstream MCP server"
