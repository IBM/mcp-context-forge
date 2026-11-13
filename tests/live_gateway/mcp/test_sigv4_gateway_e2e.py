# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_sigv4_gateway_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box test for AWS Signature Version 4 (``auth_type: "sigv4"``) gateways
against a running gateway.

The test drives the full runtime path end to end:

1. A stub upstream MCP server (mcp SDK ``Server.streamable_http_app`` over
   uvicorn) runs on the test host. A verifying ASGI wrapper in front of it
   checks every request's SigV4 signature with an independent implementation
   of the AWS algorithm. The wrapper refuses a request that is unsigned, signed
   with the wrong secret, tampered with, or stale. It records every outcome.
2. A gateway is registered through the live ``POST /gateways`` API with
   ``auth_type=sigv4`` and AWS credentials held by the gateway.
3. The test lists and calls the upstream tool through the hub MCP endpoint
   (``{BASE_URL}/mcp/``). The stub accepts the calls only when the gateway
   signed each upstream request.

The verifier is independent on purpose. A verifier that reused the gateway's
signer would pass for any consistent bug in that signer.

Requirements:
    - ContextForge running with ``make testing-up`` (default:
      http://localhost:8080). The compose stack maps ``host.docker.internal``
      to the host under ``extra_hosts``. Set ``MCP_SIGV4_UPSTREAM_HOST`` when
      the gateway reaches the host under another name.

Usage:
    make test-sigv4-live
    # or directly
    pytest tests/live_gateway/mcp/test_sigv4_gateway_e2e.py -v -s --tb=short
"""

# Future
from __future__ import annotations

# Standard
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
import os
import re
import socket
import threading
import time
from typing import Any, Generator
from urllib.parse import parse_qsl, quote, urlsplit
import uuid

# Third-Party
import httpx
import httpx2
from mcp.server import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent, Tool
import pytest
from starlette.responses import PlainTextResponse
import uvicorn

# First-Party
from mcpgateway.utils.sigv4 import build_sigv4_signer, SigV4HttpxAuth

# Local
from ..helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway
from tests.helpers.auth import make_test_jwt

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.e2e]

_SYNC_DEADLINE = float(os.getenv("MCP_E2E_GATEWAY_SYNC_DEADLINE", "30.0"))
_UPSTREAM_HOST = os.getenv("MCP_SIGV4_UPSTREAM_HOST", "host.docker.internal")
_BIND_HOST = os.getenv("MCP_SIGV4_STUB_BIND_HOST", "0.0.0.0")  # noqa: S104 - the compose gateway dials the host through host.docker.internal
_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret
_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret - stub upstream fixture, not a real credential
_WRONG_SECRET_ACCESS_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # pragma: allowlist secret - deliberately wrong fixture value
_SESSION_TOKEN = "E2E-STUB-SESSION-TOKEN-VALUE"  # pragma: allowlist secret - stub upstream fixture, not a real credential
_REGION = "us-east-1"
_SERVICE = "execute-api"
_MAX_CLOCK_SKEW = timedelta(minutes=5)
_AUTH_PATTERN = re.compile(r"^AWS4-HMAC-SHA256 Credential=(?P<access_key>[^/]+)/(?P<scope>[^,]+), SignedHeaders=(?P<signed>[^,]+), Signature=(?P<signature>[0-9a-f]{64})$")


# ---------------------------------------------------------------------------
# Independent SigV4 verifier
# ---------------------------------------------------------------------------
def _hmac(key: bytes, message: str) -> bytes:
    """Return HMAC-SHA256 of ``message`` under ``key``."""
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _canonical_query(raw_query: str) -> str:
    """Return the SigV4 canonical query string."""
    pairs = sorted((quote(key, safe="-_.~"), quote(value, safe="-_.~")) for key, value in parse_qsl(raw_query, keep_blank_values=True))
    return "&".join(f"{key}={value}" for key, value in pairs)


def verify_sigv4(method: str, raw_path: str, raw_query: str, headers: dict[str, str], body: bytes, *, secret_access_key: str, now: datetime | None = None) -> str | None:
    """Verify a SigV4 request the way an AWS service does.

    Args:
        method: HTTP method.
        raw_path: Request path as received (already percent-encoded once).
        raw_query: Raw query string.
        headers: Received headers with lower-case names.
        body: Received body bytes.
        secret_access_key: The secret the access key resolves to.
        now: Reference time, defaults to the current UTC time.

    Returns:
        str | None: ``None`` when the signature is valid, otherwise the refusal reason.
    """
    authorization = headers.get("authorization", "")
    match = _AUTH_PATTERN.match(authorization)
    if not match:
        return "missing or malformed Authorization header"
    if match["access_key"] != _ACCESS_KEY_ID:
        return "unknown access key"

    scope = match["scope"]
    datestamp, region, service, terminator = (scope.split("/") + ["", "", "", ""])[:4]
    if (region, service, terminator) != (_REGION, _SERVICE, "aws4_request"):
        return f"unexpected credential scope {scope}"

    amz_date = headers.get("x-amz-date", "")
    try:
        signed_at = datetime.strptime(amz_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return "missing or malformed x-amz-date"
    if abs((now or datetime.now(timezone.utc)) - signed_at) > _MAX_CLOCK_SKEW:
        return "request time outside the allowed clock skew"
    if not amz_date.startswith(datestamp):
        return "credential date does not match x-amz-date"

    payload_hash = hashlib.sha256(body).hexdigest()
    if headers.get("x-amz-content-sha256") != payload_hash:
        return "x-amz-content-sha256 does not match the body"

    signed_names = match["signed"].split(";")
    if "host" not in signed_names or "x-amz-date" not in signed_names:
        return "host and x-amz-date must be signed"
    if headers.get("x-amz-security-token") and "x-amz-security-token" not in signed_names:
        return "x-amz-security-token must be signed"
    canonical_headers = "".join(f"{name}:{' '.join(headers.get(name, '').split())}\n" for name in signed_names)
    canonical_uri = quote(raw_path or "/", safe="/-_.~")
    canonical_request = "\n".join([method.upper(), canonical_uri, _canonical_query(raw_query), canonical_headers, match["signed"], payload_hash])
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()])

    key = _hmac(("AWS4" + secret_access_key).encode("utf-8"), datestamp)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    expected = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, match["signature"]):
        return "signature mismatch"
    return None


# ---------------------------------------------------------------------------
# Stub infrastructure
# ---------------------------------------------------------------------------
def _free_port() -> int:
    """Return a currently-free TCP port on the host (small race acceptable)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve_uvicorn(app: Any, port: int, tag: str) -> tuple[uvicorn.Server, threading.Thread]:
    """Start ``app`` on ``port`` in a daemon thread and wait until ready."""
    config = uvicorn.Config(app, host=_BIND_HOST, port=port, log_level="error")
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


class _RequestLog:
    """Thread-safe record of every request the verifying stub received."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[OrderedDict[str, Any]] = []

    def record(self, record: OrderedDict[str, Any]) -> None:
        with self._lock:
            self._records.append(record)

    def snapshot(self) -> list[OrderedDict[str, Any]]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


def _make_upstream_app(log: _RequestLog, secret_access_key: str) -> Any:
    """Build a stub upstream MCP server behind a SigV4-verifying ASGI wrapper.

    Args:
        log: Receives one record per request with the verification outcome.
        secret_access_key: The secret an access key resolves to.

    Returns:
        Any: ASGI application.
    """

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
        return CallToolResult(content=[TextContent(type="text", text=str((params.arguments or {}).get("message", "")))])

    server = Server("sigv4-e2e-upstream", version="1.0.0", on_list_tools=list_tools, on_call_tool=call_tool)
    # The gateway reaches this stub through a host name outside the SDK's default
    # Host allowlist. DNS-rebinding protection is off for the lifetime of this module.
    mcp_app = server.streamable_http_app(streamable_http_path="/mcp", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    async def verifying_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["path"] != "/mcp":
            await mcp_app(scope, receive, send)
            return

        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)

        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}
        reason = verify_sigv4(scope["method"], scope.get("raw_path", scope["path"].encode()).decode(), scope.get("query_string", b"").decode(), headers, body, secret_access_key=secret_access_key)
        log.record(
            OrderedDict(method=scope["method"], signed=bool(headers.get("authorization")), verified=reason is None, reason=reason, session_token=headers.get("x-amz-security-token"), rpc=body[:200])
        )
        if reason is not None:
            await PlainTextResponse("signature rejected", status_code=403)(scope, receive, send)
            return

        replayed = False

        async def replay() -> dict[str, Any]:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await mcp_app(scope, replay, send)

    return verifying_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_api() -> Generator[httpx.Client, None, None]:
    """Admin API client using a ContextForge-issued JWT."""
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="module")
def stub_upstream() -> Generator[dict[str, Any], None, None]:
    """Start the SigV4-verifying stub upstream on a host port."""
    log = _RequestLog()
    port = _free_port()
    server, thread = _serve_uvicorn(_make_upstream_app(log, _SECRET_ACCESS_KEY), port, "sigv4-upstream")
    try:
        yield {"mcp_url": f"http://{_UPSTREAM_HOST}:{port}/mcp", "log": log}
    finally:
        _stop_uvicorn(server, thread, "sigv4-upstream")


def _sigv4_payload(name: str, url: str, **config_overrides: Any) -> dict[str, Any]:
    """Return a ``POST /gateways`` body for a SigV4 gateway."""
    return {
        "name": name,
        "url": url,
        "transport": "STREAMABLEHTTP",
        "visibility": "public",
        "auth_type": "sigv4",
        "sigv4_config": {
            "access_key_id": _ACCESS_KEY_ID,
            "secret_access_key": _SECRET_ACCESS_KEY,
            "session_token": _SESSION_TOKEN,
            "region": _REGION,
            "service": _SERVICE,
            **config_overrides,
        },
    }


@pytest.fixture(scope="module")
def sigv4_gateway(admin_api: httpx.Client, stub_upstream: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    """Register a SigV4 gateway against the stub upstream and wait for its tools."""
    name = f"sigv4-e2e-{uuid.uuid4().hex[:8]}"
    resp = admin_api.post("/gateways", json=_sigv4_payload(name, stub_upstream["mcp_url"]))
    assert resp.status_code in (200, 201), f"Failed to register SigV4 gateway: {resp.status_code} {resp.text}"
    gateway = resp.json()
    gateway_id = gateway["id"]
    logger.info("Registered SigV4 gateway %s (id=%s)", name, gateway_id)

    # The row exists from here on, so every exit path must delete it.
    try:
        deadline = time.monotonic() + _SYNC_DEADLINE
        tool_name = None
        while time.monotonic() < deadline:
            tools_resp = admin_api.get(f"/tools?limit=0&gateway_id={gateway_id}")
            if tools_resp.status_code == 200:
                matched = [tool for tool in tools_resp.json() if tool.get("name", "").endswith("-stub-echo")]
                if matched:
                    tool_name = matched[0]["name"]
                    break
            time.sleep(1.0)
        if tool_name is None:
            raise AssertionError(f"Gateway {name} did not publish stub_echo within {_SYNC_DEADLINE}s")
        yield {"id": gateway_id, "name": name, "tool_name": tool_name, "registration": gateway}
    finally:
        try:
            admin_api.delete(f"/gateways/{gateway_id}")
        except Exception:  # noqa: BLE001
            logger.warning("Failed to delete gateway %s during teardown", gateway_id)


@pytest.fixture
async def hub_client():
    """An MCP client session against the live hub endpoint (``/mcp/``)."""
    # Standard
    import asyncio  # noqa: PLC0415

    # Third-Party
    from mcp import ClientSession  # noqa: PLC0415
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client  # noqa: PLC0415

    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"}, timeout=httpx2.Timeout(10.0))
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


def _gateway_named(admin_api: httpx.Client, name: str) -> bool:
    """Return whether a gateway with ``name`` exists.

    A rejected registration must leave nothing behind, so a status code alone is not enough.
    """
    resp = admin_api.get("/gateways")
    if resp.status_code != 200:
        raise AssertionError(f"could not list gateways to confirm rollback: {resp.status_code} {resp.text}")
    return any(gateway.get("name") == name for gateway in resp.json())


# ---------------------------------------------------------------------------
# Verifier self-tests (no gateway needed)
# ---------------------------------------------------------------------------
class TestStubVerifier:
    """The stub must refuse what AWS refuses, or the live tests prove nothing."""

    URL = "http://stub.example.com/mcp?b=2&a=1"
    BODY = b'{"jsonrpc":"2.0","method":"tools/list","id":1}'

    def _signed(self, secret: str = _SECRET_ACCESS_KEY, **extra_headers: str) -> httpx.Request:
        signer = build_sigv4_signer({"access_key_id": _ACCESS_KEY_ID, "secret_access_key": secret, "region": _REGION, "service": _SERVICE, "session_token": _SESSION_TOKEN})
        request = httpx.Request("POST", self.URL, content=self.BODY, headers={"content-type": "application/json", **extra_headers})
        next(SigV4HttpxAuth(signer).auth_flow(request))
        return request

    def _verify(self, request: httpx.Request, body: bytes | None = None, now: datetime | None = None) -> str | None:
        parts = urlsplit(str(request.url))
        headers = {key.lower(): value for key, value in request.headers.items()}
        return verify_sigv4(request.method, parts.path, parts.query, headers, self.BODY if body is None else body, secret_access_key=_SECRET_ACCESS_KEY, now=now)

    def test_valid_signature_is_accepted(self) -> None:
        assert self._verify(self._signed()) is None

    def test_wrong_secret_is_refused(self) -> None:
        assert self._verify(self._signed(secret=_WRONG_SECRET_ACCESS_KEY)) == "signature mismatch"

    def test_tampered_body_is_refused(self) -> None:
        assert self._verify(self._signed(), body=b'{"jsonrpc":"2.0","method":"tools/call","id":1}') is not None

    def test_unsigned_request_is_refused(self) -> None:
        request = httpx.Request("POST", self.URL, content=self.BODY)
        assert self._verify(request) == "missing or malformed Authorization header"

    def test_stale_signature_is_refused(self) -> None:
        assert self._verify(self._signed(), now=datetime.now(timezone.utc) + timedelta(minutes=30)) == "request time outside the allowed clock skew"

    def test_replaced_authorization_is_refused(self) -> None:
        request = self._signed()
        request.headers["authorization"] = "Bearer attacker"
        assert self._verify(request) == "missing or malformed Authorization header"


# ---------------------------------------------------------------------------
# Live tests
# ---------------------------------------------------------------------------
@skip_no_gateway
class TestSigV4LiveFlow:
    """Black-box verification of SigV4 signing on a live gateway."""

    async def test_every_upstream_request_is_signed(self, hub_client, sigv4_gateway: dict[str, Any], stub_upstream: dict[str, Any]) -> None:
        """Registration, discovery and a tool call reach the upstream only with valid signatures."""
        stub_upstream["log"].clear()

        result = await hub_client.call_tool(sigv4_gateway["tool_name"], {"message": "hello-from-sigv4"})

        assert result.is_error is False, f"tool call failed: {result.content}"
        assert "hello-from-sigv4" in (result.content[0].text if result.content else "")
        records = stub_upstream["log"].snapshot()
        assert records, "the stub upstream received no request for the tool call"
        refused = [record for record in records if not record["verified"]]
        assert not refused, f"the gateway sent a request the verifier refused: {refused}"
        assert all(record["signed"] for record in records), "an upstream request carried no signature"
        assert any(b"tools/call" in record["rpc"] for record in records), "the tool call never reached the upstream"

    async def test_session_token_is_signed_and_forwarded(self, hub_client, sigv4_gateway: dict[str, Any], stub_upstream: dict[str, Any]) -> None:
        """Temporary credentials add a signed ``x-amz-security-token`` to every request."""
        stub_upstream["log"].clear()

        result = await hub_client.call_tool(sigv4_gateway["tool_name"], {"message": "token-check"})

        assert result.is_error is False, f"tool call failed: {result.content}"
        records = stub_upstream["log"].snapshot()
        assert records and all(record["session_token"] == _SESSION_TOKEN for record in records)

    def test_registration_response_masks_secrets(self, admin_api: httpx.Client, sigv4_gateway: dict[str, Any]) -> None:
        """No read of the gateway returns the secret access key or the session token."""
        single = admin_api.get(f"/gateways/{sigv4_gateway['id']}")
        bodies = [str(sigv4_gateway["registration"]), single.text, admin_api.get("/gateways").text]
        for body in bodies:
            assert _SECRET_ACCESS_KEY not in body, "secret_access_key leaked through the API"
            assert _SESSION_TOKEN not in body, "session_token leaked through the API"
        read = single.json()
        assert read["authType"] == "sigv4"
        assert read["sigv4Config"]["access_key_id"] == _ACCESS_KEY_ID
        assert read["sigv4Config"]["secret_access_key"] != _SECRET_ACCESS_KEY
        assert read["sigv4Config"]["session_token"] != _SESSION_TOKEN

    def test_wrong_secret_registration_is_rejected(self, admin_api: httpx.Client, stub_upstream: dict[str, Any]) -> None:
        """The upstream refuses the signature, so registration fails and leaves no row or echo of the secret."""
        name = f"sigv4-e2e-wrong-secret-{uuid.uuid4().hex[:8]}"
        # A public duplicate check matches the module gateway. A private gateway compares only private gateways.
        payload = {**_sigv4_payload(name, stub_upstream["mcp_url"], secret_access_key=_WRONG_SECRET_ACCESS_KEY), "visibility": "private"}

        resp = admin_api.post("/gateways", json=payload)

        assert resp.status_code >= 400, f"a gateway with the wrong secret was accepted: {resp.status_code} {resp.text}"
        assert _WRONG_SECRET_ACCESS_KEY not in resp.text, "the rejection echoed the submitted secret"
        assert not _gateway_named(admin_api, name), "a rejected registration must not leave a gateway row behind"
        assert any(record["reason"] == "signature mismatch" for record in stub_upstream["log"].snapshot()), "the gateway never sent a signed probe"

    @pytest.mark.parametrize(
        "bad_config",
        [
            {"region": ""},
            {"service": "not a service"},
            {"access_key_id": "short"},
            {"unexpected_key": "value"},
        ],
    )
    def test_invalid_config_is_rejected_with_422(self, admin_api: httpx.Client, stub_upstream: dict[str, Any], bad_config: dict[str, str]) -> None:
        """A malformed ``sigv4_config`` fails closed at the API boundary and persists nothing."""
        name = f"sigv4-e2e-invalid-{uuid.uuid4().hex[:8]}"

        resp = admin_api.post("/gateways", json=_sigv4_payload(name, stub_upstream["mcp_url"], **bad_config))

        assert resp.status_code == 422, f"expected 422, got {resp.status_code} {resp.text}"
        assert _SECRET_ACCESS_KEY not in resp.text, "the rejection echoed the submitted secret"
        assert not _gateway_named(admin_api, name), "a rejected config must not leave a gateway row behind"

    def test_unauthenticated_registration_is_rejected(self, stub_upstream: dict[str, Any]) -> None:
        """An unauthenticated caller cannot register a SigV4 gateway, and the secret does not come back."""
        with httpx.Client(base_url=BASE_URL, timeout=30.0) as anonymous:
            resp = anonymous.post("/gateways", json=_sigv4_payload(f"sigv4-e2e-unauth-{uuid.uuid4().hex[:8]}", stub_upstream["mcp_url"]))

        assert resp.status_code == 401, f"expected 401 for an unauthenticated caller, got {resp.status_code} {resp.text}"
        assert _SECRET_ACCESS_KEY not in resp.text, "the rejection echoed the submitted secret"

    def test_caller_without_gateway_permission_is_rejected(self, admin_api: httpx.Client, stub_upstream: dict[str, Any]) -> None:
        """A token scoped away from ``gateways.create`` cannot register a SigV4 gateway."""
        name = f"sigv4-e2e-noperm-{uuid.uuid4().hex[:8]}"
        token = make_test_jwt("nobody@example.com", is_admin=False, teams=[], scopes={"permissions": ["tools.read"]}, secret=JWT_SECRET)

        with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30.0) as limited:
            resp = limited.post("/gateways", json=_sigv4_payload(name, stub_upstream["mcp_url"]))

        assert resp.status_code in (401, 403), f"expected a deny for a caller without gateways.create, got {resp.status_code} {resp.text}"
        assert _SECRET_ACCESS_KEY not in resp.text, "the rejection echoed the submitted secret"
        assert not _gateway_named(admin_api, name), "a denied registration must not leave a gateway row behind"

    async def test_rotated_secret_takes_effect_without_stale_sessions(self, admin_api: httpx.Client, hub_client, sigv4_gateway: dict[str, Any], stub_upstream: dict[str, Any]) -> None:
        """A credential update the upstream refuses breaks the next call; restoring the secret recovers it.

        A pooled upstream session signs per request and the update evicts it, so
        the new credentials apply to the very next call.
        """
        url = f"/gateways/{sigv4_gateway['id']}"
        restore_body = {
            "auth_type": "sigv4",
            "sigv4_config": {"access_key_id": _ACCESS_KEY_ID, "secret_access_key": _SECRET_ACCESS_KEY, "session_token": _SESSION_TOKEN, "region": _REGION, "service": _SERVICE},
        }
        broken_body = {"auth_type": "sigv4", "sigv4_config": {"access_key_id": _ACCESS_KEY_ID, "secret_access_key": _WRONG_SECRET_ACCESS_KEY, "region": _REGION, "service": _SERVICE}}

        broken = admin_api.put(url, json=broken_body)
        try:
            if broken.status_code < 400:
                stub_upstream["log"].clear()
                result = await hub_client.call_tool(sigv4_gateway["tool_name"], {"message": "after-rotation"})
                assert result.is_error is True, "a call succeeded although the gateway signs with a secret the upstream refuses"
                assert any(record["reason"] == "signature mismatch" for record in stub_upstream["log"].snapshot())
        finally:
            restored = admin_api.put(url, json=restore_body)
            assert restored.status_code < 400, f"could not restore the SigV4 credentials: {restored.status_code} {restored.text}"

        stub_upstream["log"].clear()
        result = await hub_client.call_tool(sigv4_gateway["tool_name"], {"message": "after-restore"})
        assert result.is_error is False, f"tool call failed after restoring the secret: {result.content}"
        assert all(record["verified"] for record in stub_upstream["log"].snapshot())
