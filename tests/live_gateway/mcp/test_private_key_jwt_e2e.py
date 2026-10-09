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
from datetime import datetime, timedelta, timezone
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

# httpx for this module's own admin calls: it is the declared dependency
# (pyproject.toml "httpx>=0.28.1"). httpx2 only where the mcp SDK's signature
# requires it -- create_mcp_http_client is typed (timeout: httpx2.Timeout) and
# returns httpx2.AsyncClient. The two are separate installed packages, not
# aliases, and httpx2 reaches the environment transitively through mcp, cpex and
# starlette rather than through a direct declaration.
import httpx
import httpx2
import jwt as pyjwt
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

# Local
from ..helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway
from tests.helpers.auth import make_test_jwt

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.e2e, skip_no_gateway]

_SYNC_DEADLINE = float(os.getenv("MCP_E2E_GATEWAY_SYNC_DEADLINE", "30.0"))
_STUB_CLIENT_ID = "private-key-jwt-e2e-client"
_STUB_ACCESS_TOKEN = "e2e-stub-access-token-value"  # pragma: allowlist secret - stub AS fixture, not a real credential
_STUB_KEY_ID = "e2e-test-kid"
_MAX_ASSERTION_TTL_SECONDS = 300

# Composed at runtime rather than written literally. The pre-commit
# detect-private-key hook matches these markers as substrings and cannot tell a
# negative assertion or a placeholder from real key material. Composing them
# lets the hook keep scanning this file for genuine keys rather than excluding
# the whole file, which is what it did before.
_PEM_HEADER = "-----" + "BEGIN" + " PRIVATE KEY-----"
_PEM_FOOTER = "-----" + "END" + " PRIVATE KEY-----"
_PEM_HEADER_RSA = "-----" + "BEGIN" + " RSA PRIVATE KEY-----"


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


def _make_token_endpoint_app(store: _CaptureStore, public_pem: str, expected_audience: str) -> Starlette:
    """Stub Authorization Server token endpoint that verifies the assertion before granting.

    A stub that grants unconditionally proves only that some string arrived in
    ``client_assertion``. It would mint a token for a garbage assertion, an
    unsigned one, or one signed by the wrong key, so the test could not tell a
    working signature from a broken one. This endpoint instead performs the
    checks a real authorization server performs (RFC 7523 Section 3): verify the
    signature against the registered public key, require RS256, and validate
    ``aud``, ``iss``, ``sub``, and ``exp``.

    Rejections are recorded too, so a test can assert the gateway was refused
    and read back why.

    Args:
        store: Capture store for request bodies and verification outcomes.
        public_pem: The registered public key, used to verify the assertion.
        expected_audience: The ``aud`` the assertion must carry, which is the
            ``token_url`` the gateway was configured with.

    Returns:
        Starlette: ASGI app exposing ``POST /token``.
    """
    # Every jti the endpoint has honoured, so a replayed assertion is refused the
    # way a real authorization server refuses one.
    seen_jtis: set[str] = set()

    async def token(request: Request):
        form = OrderedDict((key, value) for key, value in (await request.form()).items())

        assertion = form.get("client_assertion")
        if not assertion:
            store.record(OrderedDict(list(form.items()) + [("_verified", False), ("_reason", "missing client_assertion")]))
            return JSONResponse({"error": "invalid_client", "error_description": "missing client_assertion"}, status_code=401)

        try:
            # algorithms is pinned so an assertion claiming alg=none, or an HS*
            # assertion forged with the public key as the shared secret, is
            # rejected rather than accepted.
            claims = pyjwt.decode(
                assertion,
                public_pem,
                algorithms=["RS256"],
                audience=expected_audience,
                options={"require": ["exp", "iat", "iss", "sub", "aud", "jti"]},
            )
        except Exception as exc:  # noqa: BLE001 - any failure is a refusal
            store.record(OrderedDict(list(form.items()) + [("_verified", False), ("_reason", f"{type(exc).__name__}: {exc}")]))
            return JSONResponse({"error": "invalid_client", "error_description": "assertion verification failed"}, status_code=401)

        if claims.get("iss") != _STUB_CLIENT_ID or claims.get("sub") != _STUB_CLIENT_ID:
            store.record(OrderedDict(list(form.items()) + [("_verified", False), ("_reason", "iss/sub mismatch")]))
            return JSONResponse({"error": "invalid_client", "error_description": "iss/sub mismatch"}, status_code=401)

        # Replay rejection (RFC 7523 Section 3, clause 7). A real authorization
        # server refuses a jti it has already seen within the assertion's validity
        # window. Enforcing it here is what proves the gateway mints a fresh
        # assertion per attempt rather than reusing one across retries; a stub
        # that only verifies signatures would accept a replayed assertion and the
        # retry-refresh behaviour would be untested.
        jti = claims["jti"]
        if jti in seen_jtis:
            store.record(OrderedDict(list(form.items()) + [("_verified", False), ("_reason", f"replayed jti {jti}")]))
            return JSONResponse({"error": "invalid_client", "error_description": "assertion jti already used"}, status_code=401)
        seen_jtis.add(jti)

        store.record(OrderedDict(list(form.items()) + [("_verified", True), ("_reason", "")]))
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
    # The compose gateway reaches this stub through host.docker.internal, so the
    # Host header never matches the SDK's default 127.0.0.1 allowlist and the
    # request is rejected with 421 Misdirected Request. DNS-rebinding protection
    # is off here because the stub is bound to an ephemeral port on the test
    # host for the duration of one module.
    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

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
def admin_api() -> Generator[httpx.Client, None, None]:
    """Admin API client using a ContextForge-issued JWT.

    Uses httpx rather than Playwright's ``APIRequestContext``, which this module
    used originally. Playwright's ``playwright`` fixture drives a synchronous
    greenlet event loop, and once it is instantiated in a module, every async
    fixture in that module fails setup with "Runner.run() cannot be called from
    a running event loop". This module needs an async MCP client session
    alongside the admin HTTP calls, so Playwright is no longer used here at all.

    httpx is also the declared dependency (``pyproject.toml``), where
    ``APIRequestContext`` arrived through a test-only plugin.
    """
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30.0) as client:
        yield client


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
    # The gateway sets aud to the configured token_url, so the stub must expect
    # that exact string, including the host.docker.internal hostname it dials.
    expected_audience = f"http://host.docker.internal:{token_port}/token"
    token_server, token_thread = _serve_uvicorn(_make_token_endpoint_app(token_store, rsa_keypair["public"], expected_audience), token_port, "as")
    mcp_server, mcp_thread = _serve_uvicorn(_make_upstream_mcp_app(mcp_store), mcp_port, "upstream")
    try:
        yield {
            "token_url": expected_audience,
            "mcp_url": f"http://host.docker.internal:{mcp_port}/mcp",
            "public_pem": rsa_keypair["public"],
            "token_store": token_store,
            "mcp_store": mcp_store,
        }
    finally:
        _stop_uvicorn(mcp_server, mcp_thread, "upstream")
        _stop_uvicorn(token_server, token_thread, "as")


@pytest.fixture(scope="module")
def private_key_jwt_gateway(admin_api: httpx.Client, stub_stack: dict[str, Any], rsa_keypair: dict[str, str]) -> Generator[dict[str, Any], None, None]:
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
    resp = admin_api.post("/gateways", json=payload)
    assert resp.status_code in (200, 201), f"Failed to register private_key_jwt gateway: {resp.status_code} {resp.text}"
    gateway = resp.json()
    gateway_id = gateway["id"]
    logger.info("Registered private_key_jwt gateway %s (id=%s)", name, gateway_id)

    # The row exists from here on, so every exit path must delete it. Without the
    # try/finally, the tool-sync timeout below raises after creation and leaves an
    # orphaned gateway that the next run collides with on the unique name.
    try:
        deadline = time.monotonic() + _SYNC_DEADLINE
        tool_name = None
        while time.monotonic() < deadline:
            tools_resp = admin_api.get("/tools")
            if tools_resp.status_code == 200:
                tools = tools_resp.json()
                matched = [tool for tool in tools if tool.get("name", "").endswith("-stub-echo")]
                if matched:
                    tool_name = matched[0]["name"]
                    break
            time.sleep(1.0)
        if tool_name is None:
            raise AssertionError(f"Gateway {name} did not publish stub_echo within {_SYNC_DEADLINE}s")

        yield {"id": gateway_id, "name": name, "tool_name": tool_name}
    finally:
        try:
            admin_api.delete(f"/gateways/{gateway_id}")
        except Exception:  # noqa: BLE001
            logger.warning("Failed to delete gateway %s during teardown", gateway_id)


@pytest.fixture
async def hub_client():
    """An MCP client session against the live hub endpoint (``/mcp/``).

    Declares no fixture dependencies on purpose. Any synchronous fixture that
    drives its own event loop — Playwright's ``playwright`` fixture is the one
    this module previously used — makes every async fixture in the same module
    fail setup with "Runner.run() cannot be called from a running event loop".
    Keeping this fixture dependency-free, and the admin client on httpx, is what
    lets an async MCP session and the admin HTTP calls coexist here.
    ``tests/live_gateway/e2e/test_e2e.py`` keeps its async ``client`` fixture
    free of such fixtures for the same reason.

    Tests that also need the registered gateway request
    ``private_key_jwt_gateway`` themselves.
    """
    # Standard
    import asyncio  # noqa: PLC0415

    # Third-Party
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
def _gateway_named(admin_api: httpx.Client, name: str) -> bool:
    """Return whether a gateway with *name* exists.

    A rejected registration must leave nothing behind. Asserting on the status
    code alone would pass even if the row had been created and the error raised
    afterwards.

    Args:
        admin_api: Authenticated admin HTTP client.
        name: Gateway name to look for.

    Returns:
        bool: True when a gateway with that name is listed.
    """
    resp = admin_api.get("/gateways")
    if resp.status_code != 200:
        raise AssertionError(f"could not list gateways to confirm rollback: {resp.status_code} {resp.text}")
    return any(gateway.get("name") == name for gateway in resp.json())


def _verify_assertion(stub_stack: dict[str, Any], token_request: OrderedDict[str, Any]) -> None:
    """Decode and verify the client assertion the gateway sent, asserting RFC 7523 claims."""
    assert token_request.get("grant_type") == "client_credentials"
    assert token_request.get("client_id") == _STUB_CLIENT_ID
    assert token_request.get("client_assertion_type") == "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    assertion = token_request.get("client_assertion")
    assert assertion and isinstance(assertion, str), "missing client_assertion"

    # The stub AS verified the signature, aud, iss, sub and exp before issuing.
    # Asserting that here is what separates "a token came back" from "a valid
    # assertion was accepted"; the stub records its reason on refusal.
    assert token_request.get("_verified") is True, f"stub AS refused the assertion: {token_request.get('_reason')}"

    # The point of private_key_jwt is that no shared secret crosses the wire.
    # Asserting the assertion is present does not prove that, since a fallback
    # could send both.
    assert "client_secret" not in token_request, "private_key_jwt must not send a client_secret"

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
    # HS* or "none" would mean the gateway signed with something other than the
    # configured asymmetric key.
    assert header.get("alg") not in ("none", "HS256", "HS384", "HS512")


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

    def test_registration_masks_private_key(self, admin_api: httpx.Client, private_key_jwt_gateway: dict[str, Any]) -> None:
        """The saved gateway never echoes the raw signing key back through the API."""
        resp = admin_api.get(f"/gateways/{private_key_jwt_gateway['id']}")
        assert resp.status_code == 200, resp.text
        body = resp.text
        assert _PEM_HEADER not in body and _PEM_HEADER_RSA not in body, "private_key leaked through API"

    def test_invalid_method_rejected_with_422(self, admin_api: httpx.Client) -> None:
        """An unsupported token_endpoint_auth_method fails closed at the live API boundary.

        Also asserts the gateway was not created. A 422 alone does not prove
        nothing persisted, and a partially-created row would be the real damage.
        """
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
        resp = admin_api.post("/gateways", json=payload)
        assert resp.status_code == 422, f"expected 422 for unsupported method, got {resp.status_code} {resp.text}"
        assert not _gateway_named(admin_api, name), "a rejected config must not leave a gateway row behind"

    def test_hs256_signing_alg_rejected_with_422(self, admin_api: httpx.Client) -> None:
        """An HMAC signing algorithm for assertions fails closed at the live API boundary.

        HS* would let a shared secret masquerade as a signed assertion, so this
        rejection is the downgrade guard. Asserts the submitted key material is
        absent from the error body and that no gateway row was created.
        """
        name = f"pkce-e2e-invalid-alg-{uuid.uuid4().hex[:8]}"
        sentinel = "SENTINEL-HS256-KEY-MATERIAL"
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
                "private_key": sentinel,  # pragma: allowlist secret - fixture literal
            },
        }
        resp = admin_api.post("/gateways", json=payload)
        assert resp.status_code == 422, f"expected 422 for HS256, got {resp.status_code} {resp.text}"
        assert sentinel not in resp.text, "the rejection echoed the submitted key material"
        assert not _gateway_named(admin_api, name), "a rejected config must not leave a gateway row behind"

    def test_unauthenticated_registration_is_rejected(self) -> None:
        """An unauthenticated caller cannot register a private_key_jwt gateway.

        ``POST /gateways`` is gated on ``gateways.create``. AGENTS.md requires a
        deny-path test for security-sensitive changes, and this is the one that
        matters most here: the request body carries signing key material, so the
        rejection must happen before anything is persisted and the key must not
        come back in the error.
        """
        sentinel = "SENTINEL-UNAUTH-KEY-MATERIAL"
        payload = {
            "name": f"pkce-e2e-unauth-{uuid.uuid4().hex[:8]}",
            "url": "https://mcp.example.com/mcp",
            "transport": "STREAMABLEHTTP",
            "auth_type": "oauth",
            "oauth_config": {
                "grant_type": "client_credentials",
                "client_id": _STUB_CLIENT_ID,
                "token_url": "https://idp.example.com/token",
                "token_endpoint_auth_method": "private_key_jwt",
                "private_key": f"{_PEM_HEADER}\n{sentinel}\n{_PEM_FOOTER}",
            },
        }
        # A client with no Authorization header, unlike the admin_api fixture.
        with httpx.Client(base_url=BASE_URL, timeout=30.0) as anonymous:
            resp = anonymous.post("/gateways", json=payload)

        assert resp.status_code == 401, f"expected 401 for an unauthenticated caller, got {resp.status_code} {resp.text}"
        assert sentinel not in resp.text, "the rejection echoed the submitted key material"


class TestStubAuthorizationServerRejections:
    """The stub AS must refuse what a real one refuses.

    ``_verify_assertion`` asserts the happy path was accepted, which only proves
    the stub accepts a good assertion. These cases drive the stub directly with
    deliberately bad assertions, so a stub that silently stopped checking -- and
    would therefore pass the happy path regardless -- fails here instead.
    """

    @staticmethod
    def _assertion(private_pem: str, audience: str, **overrides) -> str:
        """Mint a client assertion, with claim overrides for the negative cases.

        Args:
            private_pem: Key to sign with.
            audience: Default ``aud`` claim.
            **overrides: Claim values to replace.

        Returns:
            str: Encoded JWT.
        """
        now = datetime.now(timezone.utc)
        claims = {
            "iss": _STUB_CLIENT_ID,
            "sub": _STUB_CLIENT_ID,
            "aud": audience,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=60)).timestamp()),
            "jti": uuid.uuid4().hex,
        }
        claims.update(overrides)
        return pyjwt.encode(claims, private_pem, algorithm="RS256")

    @staticmethod
    def _post(token_url: str, assertion: str) -> httpx.Response:
        """POST a client assertion to the stub token endpoint.

        Args:
            token_url: Stub endpoint URL.
            assertion: Assertion to send.

        Returns:
            httpx.Response: The stub's response.
        """
        # The stub binds 0.0.0.0 on the test host; reach it over loopback rather
        # than the host.docker.internal name the compose gateway uses.
        local_url = token_url.replace("host.docker.internal", "127.0.0.1")
        with httpx.Client(timeout=15.0) as client:
            return client.post(
                local_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": _STUB_CLIENT_ID,
                    "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                    "client_assertion": assertion,
                },
            )

    def test_valid_assertion_is_accepted(self, stub_stack: dict[str, Any], rsa_keypair: dict[str, str]) -> None:
        resp = self._post(stub_stack["token_url"], self._assertion(rsa_keypair["private"], stub_stack["token_url"]))
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"] == _STUB_ACCESS_TOKEN

    def test_assertion_signed_with_the_wrong_key_is_rejected(self, stub_stack: dict[str, Any]) -> None:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pem = other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        resp = self._post(stub_stack["token_url"], self._assertion(other_pem, stub_stack["token_url"]))
        assert resp.status_code == 401, resp.text
        assert "InvalidSignature" in str(stub_stack["token_store"].latest().get("_reason"))

    def test_assertion_for_the_wrong_audience_is_rejected(self, stub_stack: dict[str, Any], rsa_keypair: dict[str, str]) -> None:
        resp = self._post(stub_stack["token_url"], self._assertion(rsa_keypair["private"], stub_stack["token_url"], aud="https://attacker.example.com/token"))
        assert resp.status_code == 401, resp.text
        assert "InvalidAudience" in str(stub_stack["token_store"].latest().get("_reason"))

    def test_expired_assertion_is_rejected(self, stub_stack: dict[str, Any], rsa_keypair: dict[str, str]) -> None:
        past = datetime.now(timezone.utc) - timedelta(seconds=120)
        resp = self._post(
            stub_stack["token_url"],
            self._assertion(rsa_keypair["private"], stub_stack["token_url"], iat=int(past.timestamp()), exp=int((past + timedelta(seconds=30)).timestamp())),
        )
        assert resp.status_code == 401, resp.text
        assert "ExpiredSignature" in str(stub_stack["token_store"].latest().get("_reason"))

    def test_replayed_jti_is_rejected(self, stub_stack: dict[str, Any], rsa_keypair: dict[str, str]) -> None:
        # RFC 7523 Section 3 clause 7. This is what makes the retry-refresh
        # behaviour observable: reusing an assertion across attempts would be
        # refused by a real provider.
        assertion = self._assertion(rsa_keypair["private"], stub_stack["token_url"])

        first = self._post(stub_stack["token_url"], assertion)
        assert first.status_code == 200, first.text

        second = self._post(stub_stack["token_url"], assertion)
        assert second.status_code == 401, "a replayed assertion must be refused"
        assert "replayed jti" in str(stub_stack["token_store"].latest().get("_reason"))

    def test_unsigned_assertion_is_rejected(self, stub_stack: dict[str, Any]) -> None:
        # The stub pins algorithms to RS256, so an alg=none assertion carries no
        # signature to verify and is refused.
        now = datetime.now(timezone.utc)
        claims = {
            "iss": _STUB_CLIENT_ID,
            "sub": _STUB_CLIENT_ID,
            "aud": stub_stack["token_url"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=60)).timestamp()),
            "jti": uuid.uuid4().hex,
        }
        unsigned = pyjwt.encode(claims, key="", algorithm="none")
        assert self._post(stub_stack["token_url"], unsigned).status_code == 401
        assert "InvalidAlgorithm" in str(stub_stack["token_store"].latest().get("_reason"))

    def test_hs256_forgery_with_the_public_key_cannot_even_be_minted(self, stub_stack: dict[str, Any]) -> None:
        # The classic attack on a verifier that does not pin algorithms: sign HS256
        # using the victim's public key as the shared secret. PyJWT refuses to
        # mint it, so the attack is blocked before the wire -- which is why
        # pinning `algorithms` on the verify side still matters for any client
        # that is not PyJWT.
        now = datetime.now(timezone.utc)
        claims = {
            "iss": _STUB_CLIENT_ID,
            "sub": _STUB_CLIENT_ID,
            "aud": stub_stack["token_url"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=60)).timestamp()),
            "jti": uuid.uuid4().hex,
        }
        with pytest.raises(pyjwt.InvalidKeyError, match="should not be used as an HMAC secret"):
            pyjwt.encode(claims, stub_stack["public_pem"], algorithm="HS256")

    def test_assertion_without_a_jti_is_rejected(self, stub_stack: dict[str, Any], rsa_keypair: dict[str, str]) -> None:
        # The stub requires jti, so replay protection cannot be sidestepped by
        # omitting the claim.
        now = datetime.now(timezone.utc)
        no_jti = pyjwt.encode(
            {
                "iss": _STUB_CLIENT_ID,
                "sub": _STUB_CLIENT_ID,
                "aud": stub_stack["token_url"],
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(seconds=60)).timestamp()),
            },
            rsa_keypair["private"],
            algorithm="RS256",
        )
        assert self._post(stub_stack["token_url"], no_jti).status_code == 401
