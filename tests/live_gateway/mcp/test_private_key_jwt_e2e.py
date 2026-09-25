# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_private_key_jwt_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box test for RFC 7523 ``private_key_jwt`` token endpoint client
authentication against a running gateway.

The test drives the full runtime path end to end:

1. A stub Authorization Server (Starlette ``POST /token``) runs on the test
   host and records every token request it receives.
2. A stub upstream MCP server (mcp SDK ``Server.streamable_http_app`` over
   uvicorn) runs on the test host and records the ``Authorization`` header it
   receives on its requests.
3. A gateway row is registered through the live ``POST /gateways`` API. Its
   ``oauth_config`` uses ``token_endpoint_auth_method=private_key_jwt`` and a
   runtime-generated RSA key pair. The ``token_url`` and gateway ``url`` point
   at ``host.docker.internal`` ports, which the compose gateway reaches
   (compose maps ``host.docker.internal`` to the host under ``extra_hosts``).
4. The test calls the gateway's tool through the hub MCP endpoint
   (``{BASE_URL}/mcp/``). ``tool_service`` fetches a client_credentials token
   first, so the gateway signs a client assertion with the private key and
   POSTs it to the stub AS. The stub AS then mints an access token the gateway
   forwards upstream.

Requirements:
    - ContextForge running with ``make testing-up`` (default:
      http://localhost:8080). The compose stack maps ``host.docker.internal``
      to the host under ``extra_hosts``.

Usage:
    make test-private-key-jwt-live
    # or directly
    pytest tests/live_gateway/mcp/test_private_key_jwt_e2e.py -v -s --tb=short
"""

# Future
from __future__ import annotations

# Standard
from collections import OrderedDict
from datetime import datetime, timezone
import logging
import os
import socket
import threading
import time
from typing import Any, Generator
import uuid

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx2
import jwt as pyjwt
from mcp.server import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent, Tool
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn

pw = pytest.importorskip("playwright", reason="playwright is not installed – pip install playwright")
# Third-Party
from playwright.sync_api import APIRequestContext, Playwright  # noqa: E402

# Local
from tests.helpers.auth import make_playwright_api_context, make_test_jwt  # noqa: E402
from ..helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway  # noqa: E402

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.e2e, skip_no_gateway]

_SYNC_DEADLINE = float(os.getenv("MCP_E2E_GATEWAY_SYNC_DEADLINE", "30.0"))
_STUB_CLIENT_ID = "private-key-jwt-e2e-client"
_STUB_ACCESS_TOKEN = "e2e-stub-access-token-value"  # pragma: allowlist secret - stub AS fixture, not a real credential
_STUB_KEY_ID = "e2e-test-kid"
_MAX_ASSERTION_TTL_SECONDS = 300


# ---------------------------------------------------------------------------
# Stub infrastructure
# ---------------------------------------------------------------------------
def _free_port() -> int:
    """Return a currently-free TCP port on the host (small race acceptable)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve_uvicorn(app: Any, port: int, tag: str) -> tuple[uvicorn.Server, threading.Thread]:
    """Start ``app`` on ``0.0.0.0:port`` in a daemon thread and wait until ready."""
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name=f"stub-{tag}")
    thread.start()
    deadline = time.monotonic() + 15.0
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError(f"Stub '{tag}' exited before becoming ready")
        if time.monotonic() > deadline:
            raise RuntimeError(f"Stub '{tag}' did not become ready within 15s")
        time.sleep(0.05)
    return server, thread


def _stop_uvicorn(server: uvicorn.Server, thread: threading.Thread, tag: str) -> None:
    """Request a clean shutdown and join the stub thread."""
    server.should_exit = True
    thread.join(timeout=10.0)
    if thread.is_alive():
        logger.warning("Stub '%s' did not stop cleanly", tag)


class _CaptureStore:
    """Thread-safe capture of the form bodies and headers a stub receives."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[OrderedDict[str, Any]] = []

    def record(self, record: OrderedDict[str, Any]) -> None:
        with self._lock:
            self._records.append(record)

    def latest(self) -> OrderedDict[str, Any] | None:
        with self._lock:
            if not self._records:
                return None
            return self._records[-1]


def _make_token_endpoint_app(store: _CaptureStore) -> Starlette:
    """Stub Authorization Server token endpoint that always grants and records requests."""

    async def token(request: Request):
        form = OrderedDict((key, value) for key, value in (await request.form()).items())
        store.record(form)
        return JSONResponse(
            {
                "access_token": _STUB_ACCESS_TOKEN,
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "read",
            }
        )

    return Starlette(routes=[Route("/token", token, methods=["POST"])])


def _make_upstream_mcp_app(store: _CaptureStore) -> Any:
    """Stub upstream MCP server exposing one echo tool and recording what auth header it receives."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:  # noqa: ARG001
        return ListToolsResult(
            tools=[
                Tool(
                    name="stub_echo",
                    description="Echoes back the message that was sent to the tool.",
                    inputSchema={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:  # noqa: ARG001
        arguments = params.arguments or {}
        message = str(arguments.get("message", ""))
        return CallToolResult(content=[TextContent(type="text", text=message)])

    server = Server(
        "private-key-jwt-e2e-upstream",
        version="1.0.0",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    mcp_app = server.streamable_http_app(streamable_http_path="/mcp")

    async def wrapped_mcp_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"] == "/mcp":
            authorization = next((value.decode() for key, value in scope.get("headers", []) if key == b"authorization"), "")
            if authorization:
                store.record(OrderedDict([("authorization", authorization)]))  # pragma: allowlist secret - captured fixture value
        await mcp_app(scope, receive, send)

    return wrapped_mcp_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin API context using a ContextForge-issued JWT."""
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    ctx = make_playwright_api_context(playwright, BASE_URL, token)
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def rsa_keypair() -> dict[str, str]:
    """A runtime-generated RSA key pair used to sign and verify assertions."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return {"private": private_pem, "public": public_pem}


@pytest.fixture(scope="module")
def stub_stack(rsa_keypair: dict[str, str]) -> Generator[dict[str, Any], None, None]:
    """Start the stub AS and stub upstream MCP server, both bound to host ports."""
    token_store = _CaptureStore()
    mcp_store = _CaptureStore()
    token_port = _free_port()
    mcp_port = _free_port()
    token_server, token_thread = _serve_uvicorn(_make_token_endpoint_app(token_store), token_port, "as")
    mcp_server, mcp_thread = _serve_uvicorn(_make_upstream_mcp_app(mcp_store), mcp_port, "upstream")
    try:
        yield {
            "token_url": f"http://host.docker.internal:{token_port}/token",
            "mcp_url": f"http://host.docker.internal:{mcp_port}/mcp",
            "public_pem": rsa_keypair["public"],
            "token_store": token_store,
            "mcp_store": mcp_store,
        }
    finally:
        _stop_uvicorn(mcp_server, mcp_thread, "upstream")
        _stop_uvicorn(token_server, token_thread, "as")


@pytest.fixture(scope="module")
def private_key_jwt_gateway(admin_api: APIRequestContext, stub_stack: dict[str, Any], rsa_keypair: dict[str, str]) -> Generator[dict[str, Any], None, None]:
    """Register a private_key_jwt OAuth gateway against the stub upstream and wait for its tools."""
    name = f"pkce-e2e-{uuid.uuid4().hex[:8]}"
    payload = {
        "name": name,
        "url": stub_stack["mcp_url"],
        "transport": "STREAMABLEHTTP",
        "visibility": "public",
        "auth_type": "oauth",
        "oauth_config": {
            "grant_type": "client_credentials",
            "client_id": _STUB_CLIENT_ID,
            "token_url": stub_stack["token_url"],
            "scopes": ["read"],
            "token_endpoint_auth_method": "private_key_jwt",
            "private_key": rsa_keypair["private"],
            "token_endpoint_auth_signing_alg": "RS256",
            "private_key_jwt_kid": _STUB_KEY_ID,
        },
    }
    resp = admin_api.post("/gateways", data=payload)
    assert resp.status in (200, 201), f"Failed to register private_key_jwt gateway: {resp.status} {resp.text()}"
    gateway = resp.json()
    gateway_id = gateway["id"]
    logger.info("Registered private_key_jwt gateway %s (id=%s)", name, gateway_id)

    deadline = time.monotonic() + _SYNC_DEADLINE
    tool_name: str | None = None
    while time.monotonic() < deadline:
        tools_resp = admin_api.get(f"/tools?limit=0&gateway_id={gateway_id}")
        if tools_resp.status == 200:
            tools = tools_resp.json()
            matched = [tool for tool in tools if tool.get("name", "").endswith("-stub-echo")]
            if matched:
                tool_name = matched[0]["name"]
                break
        time.sleep(1.0)
    if tool_name is None:
        raise AssertionError(f"Gateway {name} did not publish stub_echo within {_SYNC_DEADLINE}s")

    yield {"id": gateway_id, "name": name, "tool_name": tool_name}

    try:
        admin_api.delete(f"/gateways/{gateway_id}")
    except Exception:  # noqa: BLE001
        logger.warning("Failed to delete gateway %s during teardown", gateway_id)


@pytest.fixture
async def hub_client(private_key_jwt_gateway: dict[str, Any]):
    """An MCP client session against the live hub endpoint (``/mcp/``)."""
    import asyncio  # noqa: PLC0415

    from mcp import ClientSession  # noqa: PLC0415
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client  # noqa: PLC0415

    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    timeout = httpx2.Timeout(10.0)
    http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
    ready = asyncio.Event()
    release = asyncio.Event()
    holder: dict[str, Any] = {}

    async def _session_runner() -> None:
        try:
            async with streamable_http_client(f"{BASE_URL}/mcp/", http_client=http_client) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream, read_timeout_seconds=10.0) as session:
                    await session.initialize()
                    holder["session"] = session
                    ready.set()
                    await release.wait()
        except BaseException as exc:  # noqa: BLE001
            holder["error"] = exc
            ready.set()

    runner = asyncio.create_task(_session_runner())
    try:
        await ready.wait()
        if "error" in holder:
            raise holder["error"]
        yield holder["session"]
    finally:
        release.set()
        if "session" not in holder and not runner.done():
            runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------
def _verify_assertion(stub_stack: dict[str, Any], token_request: OrderedDict[str, Any]) -> None:
    """Decode and verify the client assertion the gateway sent, asserting RFC 7523 claims."""
    assert token_request.get("grant_type") == "client_credentials"
    assert token_request.get("client_id") == _STUB_CLIENT_ID
    assert token_request.get("client_assertion_type") == "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    assertion = token_request.get("client_assertion")
    assert assertion and isinstance(assertion, str), "missing client_assertion"

    claims = pyjwt.decode(assertion, stub_stack["public_pem"], algorithms=["RS256"], audience=stub_stack["token_url"])
    assert claims["iss"] == _STUB_CLIENT_ID
    assert claims["sub"] == _STUB_CLIENT_ID
    assert claims["aud"] == stub_stack["token_url"]
    assert claims.get("jti"), "missing jti"
    now = datetime.now(timezone.utc).timestamp()
    assert claims["iat"] <= now + 30
    assert claims["exp"] > now
    assert claims["exp"] - claims["iat"] <= _MAX_ASSERTION_TTL_SECONDS
    header = pyjwt.get_unverified_header(assertion)
    assert header.get("alg") == "RS256"
    assert header.get("kid") == _STUB_KEY_ID


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestPrivateKeyJwtLiveFlow:
    """Black-box verification of the private_key_jwt runtime path on a live gateway."""

    async def test_client_credentials_token_fetched_with_valid_assertion(
        self,
        hub_client,
        private_key_jwt_gateway: dict[str, Any],
        stub_stack: dict[str, Any],
    ) -> None:
        """A real tool call makes the gateway sign and send a verifiable assertion, then use the minted token upstream."""
        result = await hub_client.call_tool(private_key_jwt_gateway["tool_name"], {"message": "hello-from-private-key-jwt"})

        assert result.is_error is False, f"tool call failed: {result.content}"
        text = result.content[0].text if result.content else ""
        assert "hello-from-private-key-jwt" in text, f"stub_echo did not return the message: {text!r}"

        token_request = stub_stack["token_store"].latest()
        assert token_request is not None, "the stub AS never received a token request"
        _verify_assertion(stub_stack, token_request)

        mcp_capture = stub_stack["mcp_store"].latest()
        assert mcp_capture is not None, "the stub upstream never received an MCP request"
        assert mcp_capture.get("authorization") == f"Bearer {_STUB_ACCESS_TOKEN}", f"upstream auth header mismatch: {mcp_capture.get('authorization')!r}"

    def test_registration_masks_private_key(self, admin_api: APIRequestContext, private_key_jwt_gateway: dict[str, Any]) -> None:
        """The saved gateway never echoes the raw signing key back through the API."""
        resp = admin_api.get(f"/gateways/{private_key_jwt_gateway['id']}")
        assert resp.status == 200, resp.text()
        body = resp.text()
        assert "BEGIN PRIVATE KEY" not in body and "BEGIN RSA PRIVATE KEY" not in body, "private_key leaked through API"

    def test_invalid_method_rejected_with_422(self, admin_api: APIRequestContext) -> None:
        """An unsupported token_endpoint_auth_method fails closed at the live API boundary."""
        name = f"pkce-e2e-invalid-{uuid.uuid4().hex[:8]}"
        payload = {
            "name": name,
            "url": "https://mcp.example.com/mcp",
            "transport": "STREAMABLEHTTP",
            "auth_type": "oauth",
            "oauth_config": {
                "grant_type": "client_credentials",
                "client_id": _STUB_CLIENT_ID,
                "token_url": "https://idp.example.com/token",
                "token_endpoint_auth_method": "client_secret_digest",
            },
        }
        resp = admin_api.post("/gateways", data=payload)
        assert resp.status == 422, f"expected 422 for unsupported method, got {resp.status} {resp.text()}"

    def test_hs256_signing_alg_rejected_with_422(self, admin_api: APIRequestContext) -> None:
        """An HMAC signing algorithm for assertions fails closed at the live API boundary."""
        name = f"pkce-e2e-invalid-alg-{uuid.uuid4().hex[:8]}"
        payload = {
            "name": name,
            "url": "https://mcp.example.com/mcp",
            "transport": "STREAMABLEHTTP",
            "auth_type": "oauth",
            "oauth_config": {
                "grant_type": "client_credentials",
                "client_id": _STUB_CLIENT_ID,
                "token_url": "https://idp.example.com/token",
                "token_endpoint_auth_method": "private_key_jwt",
                "token_endpoint_auth_signing_alg": "HS256",
                "private_key": "not-a-real-key",  # pragma: allowlist secret - fixture literal
            },
        }
        resp = admin_api.post("/gateways", data=payload)
        assert resp.status == 422, f"expected 422 for HS256, got {resp.status} {resp.text()}"
