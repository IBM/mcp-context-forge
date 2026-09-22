# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

End-to-end MCP protocol and RBAC transport tests against a live ContextForge gateway.

Exercises tools, resources, prompts, raw transport behavior, server visibility,
RBAC roles, and token scopes. Protocol tests use an async MCP SDK client;
RBAC tests use Playwright API setup plus synchronous MCP SDK helpers.

Requirements:
    - Gateway running (default: http://localhost:8080 via docker-compose)
    - Upstream ``fast_time_server`` registered
      (provided by the default compose stack)
    - Environment variables (or defaults):
        MCP_CLI_BASE_URL       Gateway URL (default: http://localhost:8080)
        JWT_SECRET_KEY         JWT signing secret
        PLATFORM_ADMIN_EMAIL   Admin email (default: admin@example.com)
        MCPGATEWAY_MCP_APPS_ENABLED
                               Set true in both gateway and test process to run MCP Apps cases

Usage:
    make test-e2e
    pytest tests/live_gateway/e2e/test_e2e.py -v -s --tb=short
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from collections.abc import AsyncIterator, Callable
import concurrent.futures
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import subprocess
import sys
import time
from typing import Any, Generator
import uuid

# Third-Party
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError
from mcp.types import InitializeResult
import pytest

pw = pytest.importorskip("playwright", reason="playwright is not installed – pip install playwright")
from playwright.sync_api import APIRequestContext, APIResponse, Error as PlaywrightError, Playwright

# Local
from mcpgateway.services.mcp_apps import MCP_UI_EXTENSION

# Local
from tests.helpers.api_helpers import ApiTestHelper
from tests.helpers.auth import make_playwright_api_context, make_test_jwt
from ..helpers.mcp_test_helpers import (
    ADMIN_EMAIL,
    BASE_URL,
    build_initialize,
    JWT_SECRET,
    skip_no_gateway,
    skip_no_rust_mcp_gateway,
    TEST_PASSWORD,
    TOKEN_EXPIRY,
)

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.e2e, skip_no_gateway]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def jwt_token() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "mcpgateway.utils.create_jwt_token", "--username", ADMIN_EMAIL, "--exp", TOKEN_EXPIRY, "--secret", JWT_SECRET],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"JWT generation failed: {result.stderr}"
    token = result.stdout.strip().strip('"')
    print(f"\n  JWT token generated for {ADMIN_EMAIL} (expires in {TOKEN_EXPIRY}m)")
    return token


@pytest.fixture(scope="module")
def mcp_url() -> str:
    # Trailing slash matters: ContextForge's MCPPathRewriteMiddleware rewrites
    # /mcp to /mcp/, but the rewrite doesn't survive a streaming POST cleanly
    # (surfaces as httpx.ReadError during initialize). Send /mcp/ directly.
    return f"{BASE_URL}/mcp/"


# Cap the client's wait budget so a misconfigured or partially-booted gateway
# fails fast (~5s) instead of hanging on MCP SDK defaults. Override via
# MCP_E2E_CLIENT_TIMEOUT for slow CI.
_CLIENT_TIMEOUT = float(os.getenv("MCP_E2E_CLIENT_TIMEOUT", "5.0"))
_MCP_APPS_E2E_ENABLED = os.getenv("MCPGATEWAY_MCP_APPS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
skip_no_mcp_apps = pytest.mark.skipif(
    not _MCP_APPS_E2E_ENABLED,
    reason="MCP Apps E2E requires a gateway started with MCPGATEWAY_MCP_APPS_ENABLED=true",
)


class GatewayClientSession(ClientSession):
    """``ClientSession`` that retains the ``InitializeResult`` for assertions."""

    initialize_result: InitializeResult

    async def initialize(self) -> InitializeResult:
        """Initialize the session and stash the result on the instance."""
        self.initialize_result = await super().initialize()
        return self.initialize_result


@pytest.fixture
async def client(jwt_token: str, mcp_url: str):
    timeout = timedelta(seconds=_CLIENT_TIMEOUT)
    headers = {"Authorization": f"Bearer {jwt_token}"}

    # anyio task groups (inside streamablehttp_client / ClientSession) must be
    # entered and exited from the same task. pytest-asyncio drives async-gen
    # fixture setup and teardown in separate tasks, so run the whole session
    # lifecycle in a dedicated runner task and hand the session to the test.
    ready = asyncio.Event()
    release = asyncio.Event()
    holder: dict[str, Any] = {}

    async def _session_runner() -> None:
        try:
            async with streamablehttp_client(mcp_url, headers=headers, timeout=timeout, sse_read_timeout=timeout) as (read_stream, write_stream, _):
                async with GatewayClientSession(read_stream, write_stream, read_timeout_seconds=timeout) as session:
                    await session.initialize()
                    holder["session"] = session
                    ready.set()
                    await release.wait()
        except Exception as exc:  # surface connection/init failures in the test
            # Exception, not BaseException: a cancelled runner must see
            # CancelledError propagate, not have it stashed as a result.
            holder["error"] = exc
            ready.set()

    runner = asyncio.create_task(_session_runner())
    try:
        await ready.wait()
        if "error" in holder:
            raise holder["error"]
        yield holder["session"]
    finally:
        # Always unwind the runner, even when setup is cancelled (Ctrl-C,
        # timeout, GeneratorExit) before the session is handed over —
        # otherwise it stays parked at release.wait() holding an open HTTP
        # connection. If setup never completed, the runner may instead be
        # stuck mid-initialize, so cancel it rather than waiting it out.
        release.set()
        if "session" not in holder and not runner.done():
            runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass
        # Teardown errors land in holder["error"] only after release.set();
        # the pre-yield check above can't see them, so re-check here or
        # they'd be silently swallowed (the old FastMCP client propagated
        # __aexit__ failures). Skip the re-raise when an exception is
        # already in flight so it isn't masked by the same object.
        if "error" in holder and sys.exc_info()[0] is None:
            raise holder["error"]


# ---------------------------------------------------------------------------
# Connectivity / lifecycle
# ---------------------------------------------------------------------------
class TestConnectivity:

    async def test_ping(self, client: GatewayClientSession) -> None:
        """Ping roundtrips via the live gateway session."""
        await client.send_ping()
        print("    -> ping OK")

    async def test_initialize_reports_server_info(self, client: GatewayClientSession) -> None:
        """Initialize exposes protocolVersion, capabilities, and serverInfo."""
        init = client.initialize_result
        assert init.protocolVersion, f"missing protocolVersion: {init}"
        assert init.capabilities, f"missing capabilities: {init}"
        assert init.serverInfo, f"missing serverInfo: {init}"
        print(f"    -> Protocol: {init.protocolVersion}, Server: {init.serverInfo.name} v{init.serverInfo.version}")

    async def test_server_capabilities_include_core_surfaces(self, client: GatewayClientSession) -> None:
        """Gateway advertises tools, resources, and prompts capabilities."""
        caps = client.initialize_result.capabilities
        assert caps.tools is not None, f"tools capability missing: {caps}"
        assert caps.resources is not None, f"resources capability missing: {caps}"
        assert caps.prompts is not None, f"prompts capability missing: {caps}"
        advertised = [k for k in ("tools", "resources", "prompts", "logging", "completions") if getattr(caps, k, None) is not None]
        print(f"    -> Capabilities: {advertised}")

    async def test_multiple_calls_in_one_session(self, client: GatewayClientSession) -> None:
        """A single session supports interleaved tools/resources/prompts calls."""
        tools = (await client.list_tools()).tools
        resources = (await client.list_resources()).resources
        prompts = (await client.list_prompts()).prompts
        assert tools, "tools empty"
        # resources / prompts may legitimately be empty depending on upstreams
        print(f"    -> tools={len(tools)} resources={len(resources)} prompts={len(prompts)}")


# ---------------------------------------------------------------------------
# Discovery — tools / resources / prompts
# ---------------------------------------------------------------------------
class TestTools:

    async def test_tools_list_nonempty(self, client: GatewayClientSession) -> None:
        tools = (await client.list_tools()).tools
        assert len(tools) > 0, "no tools registered on gateway"
        print(f"    -> {len(tools)} tools: {[t.name for t in tools][:10]}")

    async def test_tools_have_required_fields(self, client: GatewayClientSession) -> None:
        tools = (await client.list_tools()).tools
        for tool in tools:
            assert tool.name, f"tool missing name: {tool}"
            assert tool.description, f"tool {tool.name} missing description"
            assert tool.inputSchema is not None, f"tool {tool.name} missing inputSchema"
        print(f"    -> all {len(tools)} tools have name/description/inputSchema")

    async def test_tools_include_gateway_prefixed(self, client: GatewayClientSession) -> None:
        """Federated tools surface under a hyphenated ``<server>-<tool>`` name."""
        tools = (await client.list_tools()).tools
        prefixed = [t.name for t in tools if "-" in t.name]
        assert prefixed, f"expected gateway-prefixed tools, got: {[t.name for t in tools]}"
        print(f"    -> {len(prefixed)} gateway-prefixed tools present")

    async def test_tool_input_schemas_are_json_schema_objects(self, client: GatewayClientSession) -> None:
        for tool in (await client.list_tools()).tools:
            schema = tool.inputSchema
            if schema:
                assert schema.get("type") == "object", f"tool {tool.name} inputSchema not type=object: {schema}"
        print("    -> all tool inputSchemas validated as type=object")


class TestDiscovery:

    async def test_resources_list(self, client: GatewayClientSession) -> None:
        resources = (await client.list_resources()).resources
        print(f"    -> {len(resources)} resources")

    async def test_resources_read_roundtrip(self, client: GatewayClientSession) -> None:
        """Round-trip any advertised resource through resources/read.

        Listing without reading is weak coverage — this exercises the full
        read path (content encoding, mime negotiation, gateway decoration).
        Skips cleanly when no resources are registered on the stack.

        When the gateway federates multiple upstream servers the same
        resource URI can appear on more than one server.  Reading such a
        URI through the generic ``/mcp/`` endpoint (no server scope)
        raises an ambiguity error.  We iterate through the advertised
        resources so we can skip ambiguous URIs and still exercise the
        read path.
        """
        resources = (await client.list_resources()).resources
        if not resources:
            pytest.skip("No resources registered on gateway — nothing to read")
        last_error: McpError | None = None
        for target in resources:
            try:
                contents = (await client.read_resource(target.uri)).contents
            except McpError as exc:
                # URI is ambiguous across servers — try the next one
                last_error = exc
                continue
            assert contents, f"read_resource({target.uri}) returned empty contents"
            first = contents[0]
            # Empty string is still valid text content per spec; check attribute presence
            # rather than truthiness so empty bodies don't trip the assertion.
            assert hasattr(first, "text") or hasattr(first, "blob"), f"first content item has neither text nor blob attribute: {first}"
            print(f"    -> read {target.uri} -> {len(contents)} content item(s)")
            return
        pytest.skip(f"All {len(resources)} resource(s) returned errors via generic /mcp/ (last: {last_error})")

    async def test_prompts_list(self, client: GatewayClientSession) -> None:
        prompts = (await client.list_prompts()).prompts
        print(f"    -> {len(prompts)} prompts")

    async def test_prompt_get_renders(self, client: GatewayClientSession) -> None:
        """Render any advertised prompt via prompts/get.

        Prefers a prompt with no required arguments to avoid hard-coding
        fixture names. Skips cleanly when no suitable prompt is registered.
        """
        prompts = (await client.list_prompts()).prompts
        if not prompts:
            pytest.skip("No prompts registered on gateway — nothing to render")

        def _has_no_required_args(p) -> bool:
            args = getattr(p, "arguments", None) or []
            return all(not getattr(a, "required", False) for a in args)

        target = next((p for p in prompts if _has_no_required_args(p)), None)
        if target is None:
            pytest.skip("No prompt with optional-only arguments available")
        rendered = await client.get_prompt(target.name)
        assert rendered.messages, f"prompts/get({target.name}) returned no messages"
        print(f"    -> rendered {target.name} -> {len(rendered.messages)} message(s)")


# ---------------------------------------------------------------------------
# Tool invocation
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestToolCalls:
    """tools/call against live upstream servers.

    Marked flaky(reruns=1) because these hit live upstream MCP servers
    (fast_time_server) which may be transiently unavailable.
    """

    async def test_get_system_time(self, client: GatewayClientSession) -> None:
        result = await client.call_tool("fast-time-get-system-time", {"timezone": "UTC"})
        assert result.isError is False, f"get-system-time returned error (upstream may be down): {result.content}"
        assert result.content and result.content[0].type == "text"
        text = result.content[0].text
        assert text
        print(f"    -> get-system-time(UTC) = {text}")

    async def test_convert_time(self, client: GatewayClientSession) -> None:
        result = await client.call_tool(
            "fast-time-convert-time",
            {"time": "2025-01-15T12:00:00Z", "source_timezone": "UTC", "target_timezone": "America/New_York"},
        )
        assert result.isError is False, f"convert-time returned error (upstream may be down): {result.content}"
        assert result.content[0].type == "text"
        print(f"    -> convert-time(UTC->NY) = {result.content[0].text}")

    async def test_echo(self, client: GatewayClientSession) -> None:
        test_message = "hello-from-mcp-protocol-e2e"
        result = await client.call_tool("fast-time-echo", {"message": test_message})
        assert result.isError is False, f"echo returned error (upstream may be down): {result.content}"
        text = result.content[0].text
        assert test_message in text, f"echo did not return message: {text}"
        print(f"    -> echo('{test_message}') = {text}")

    async def test_get_stats(self, client: GatewayClientSession) -> None:
        result = await client.call_tool("fast-time-get-stats", {})
        assert result.isError is False, f"get-stats returned error (upstream may be down): {result.content}"
        print(f"    -> get-stats = {result.content[0].text[:120]}")

    async def test_schema_error_preserves_payload(self, client: GatewayClientSession) -> None:
        """End-to-end regression guard for ContextForge #4202.

        Drives the full MCP federation path through the retained fast-time
        server. Error responses with an output schema must preserve the
        original payload rather than replacing it with a validation error.
        """
        tool = await self._require_declared_output_schema(client, "fast-time-schema-error")
        assert tool is not None
        result = await client.call_tool("fast-time-schema-error", {})
        assert result.isError is True, f"expected isError=true, got: {result}"
        text = result.content[0].text if result.content else ""
        assert "200 points" in text, f"expected original error text preserved, got: {text!r}"
        assert '"validator"' not in text and '"required"' not in text, f"error payload appears to have been replaced by a validation error: {text!r}"
        print(f"    -> schema_error isError=true preserved: {text}")

    async def test_schema_success_validates_payload(self, client: GatewayClientSession) -> None:
        """Positive control proving valid output-schema responses still validate."""
        tool = await self._require_declared_output_schema(client, "fast-time-schema-success")
        assert tool is not None
        result = await client.call_tool("fast-time-schema-success", {})
        assert result.isError is False, f"expected success, got: {result}"
        payload = json.loads(result.content[0].text)
        assert payload.get("recognitionId") == "rec-123", f"unexpected payload: {payload}"
        structured = result.structuredContent
        assert structured is not None, f"expected structured content on successful validation: {result}"
        assert structured.get("recognitionId") == "rec-123", f"unexpected structured content: {structured}"
        print(f"    -> schema_success validated: {payload}")

    @staticmethod
    async def _require_declared_output_schema(client: GatewayClientSession, tool_name: str):
        """Require a synced tool with a declared output schema."""
        tools = (await client.list_tools()).tools
        match = next((tool for tool in tools if tool.name == tool_name), None)
        assert match is not None, (
            f"Tool {tool_name!r} is not registered in the gateway. "
            "Check that register_fast_time completed and gateway synchronization finished."
        )
        assert match.outputSchema, (
            f"Tool {tool_name!r} has no outputSchema declared in the gateway: {match}. "
            "Check that the upstream tool declares an output_schema and gateway synchronization completed successfully."
        )
        return match

    async def test_nonexistent_tool(self, client: GatewayClientSession) -> None:
        """Calling a nonexistent tool surfaces an error, via either path."""
        try:
            result = await client.call_tool("nonexistent-tool-xyz", {})
        except McpError as exc:
            print(f"    -> McpError (expected): {exc}")
            return
        assert result.isError is True, f"expected error for non-existent tool: {result}"
        print(f"    -> isError=True (expected): {result.content[0].text[:100] if result.content else ''}")


# ---------------------------------------------------------------------------
# Raw HTTP / transport parity — exercises paths the high-level client hides
# ---------------------------------------------------------------------------
class TestRawJsonRpc:
    """Direct JSON-RPC probes for behavior the high-level MCP SDK client hides."""

    def test_missing_auth_is_rejected(self) -> None:
        """A POST to /mcp/ without Authorization must be rejected at the transport edge."""
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "mcp-protocol-version": "2025-03-26",
        }
        with httpx.Client(timeout=10.0) as http:
            resp = http.post(f"{BASE_URL}/mcp/", headers=headers, json=build_initialize(1))
        assert resp.status_code in (401, 403), f"expected 401/403 without auth, got {resp.status_code}: {resp.text}"
        print(f"    -> unauthenticated /mcp/ -> status={resp.status_code}")

    def test_invalid_method_returns_error(self, jwt_token: str) -> None:
        """Unknown MCP method surfaces a JSON-RPC error envelope."""
        headers = {
            "authorization": f"Bearer {jwt_token}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "mcp-protocol-version": "2025-03-26",
        }
        with httpx.Client(timeout=10.0) as http:
            # Initialize first so the gateway accepts the session.
            init_resp = http.post(f"{BASE_URL}/mcp/", headers=headers, json=build_initialize(1))
            assert init_resp.status_code == 200, init_resp.text
            session_id = init_resp.headers.get("mcp-session-id")
            call_headers = dict(headers)
            if session_id:
                call_headers["mcp-session-id"] = session_id
            bad = http.post(
                f"{BASE_URL}/mcp/",
                headers=call_headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "nonexistent/method", "params": {}},
            )
            # Transport may accept with a JSON-RPC error body, or reject at HTTP layer.
            payload = bad.text
            assert "error" in payload.lower() or bad.status_code >= 400, f"expected error for invalid method, got {bad.status_code}: {payload}"
            print(f"    -> invalid method -> status={bad.status_code}")

    @skip_no_mcp_apps
    def test_mcp_apps_capability_advertised_when_enabled(self, jwt_token: str) -> None:
        """Assert an explicitly enabled gateway advertises the MCP Apps capability."""
        headers = {
            "authorization": f"Bearer {jwt_token}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "mcp-protocol-version": "2025-03-26",
        }
        with httpx.Client(timeout=10.0) as http:
            resp = http.post(f"{BASE_URL}/mcp/", headers=headers, json=build_initialize(1))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        caps = body.get("result", {}).get("capabilities", {})
        extensions = caps.get("extensions", {})
        assert "io.modelcontextprotocol/ui" in extensions, f"MCP Apps capability missing from explicitly enabled gateway: {extensions}"
        ui_cap = extensions["io.modelcontextprotocol/ui"]
        assert ui_cap.get("version") == "2026-01-26", f"unexpected MCP Apps capability version: {ui_cap}"
        assert ui_cap.get("resources") == {"schemes": ["ui://"]}, f"unexpected MCP Apps resource capability: {ui_cap}"
        bridge_methods = ui_cap.get("bridge", {}).get("methods", [])
        assert "tools/call" in bridge_methods, f"bridge.methods missing tools/call: {bridge_methods}"
        assert "ping" in bridge_methods, f"bridge.methods missing ping: {bridge_methods}"
        print(f"    -> MCP Apps capability: version={ui_cap['version']} bridge_methods={bridge_methods}")

    @skip_no_mcp_apps
    def test_appbridge_session_lifecycle(self, jwt_token: str) -> None:
        """AppBridge session create + ping round-trip against a live gateway.

        Registers a minimal ``ui://`` resource and virtual server, creates an
        AppBridge session, and pings through it. All persistent fixtures are
        cleaned up regardless of outcome.
        """
        mcp_headers = {
            "authorization": f"Bearer {jwt_token}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "mcp-protocol-version": "2025-03-26",
        }
        with httpx.Client(timeout=10.0) as http:
            # Step 1: initialize — confirm MCP Apps enabled and capture mcp-session-id.
            init_resp = http.post(f"{BASE_URL}/mcp/", headers=mcp_headers, json=build_initialize(1))
            assert init_resp.status_code == 200, init_resp.text
            body = init_resp.json()
            caps = body.get("result", {}).get("capabilities", {})
            assert "io.modelcontextprotocol/ui" in caps.get("extensions", {}), f"MCP Apps capability missing from explicitly enabled gateway: {caps}"
            mcp_session_id = init_resp.headers.get("mcp-session-id")
            assert mcp_session_id, "initialize did not return an mcp-session-id header"

            rest_headers = {
                "authorization": f"Bearer {jwt_token}",
                "content-type": "application/json",
                "mcp-session-id": mcp_session_id,
            }

            uid = uuid.uuid4().hex[:8]
            resource_id = None
            server_id = None
            try:
                # Step 2: register a minimal ui:// resource.
                resource_resp = http.post(
                    f"{BASE_URL}/resources",
                    headers=rest_headers,
                    json={
                        "resource": {
                            "name": f"mcp-apps-res-{uid}",
                            "uri": f"ui://mcp-apps-e2e-{uid}/index",
                            "mimeType": "text/html;profile=mcp-app",
                            "content": "<div>hello</div>",
                            "extensionMetadata": {
                                "io.modelcontextprotocol/ui": {
                                    "csp": {"connectDomains": ["https://example.com"]},
                                    "sandbox": ["allow-scripts"],
                                }
                            },
                        },
                        "visibility": "public",
                    },
                )
                assert resource_resp.status_code in (200, 201), f"Failed to create ui:// resource: {resource_resp.text}"
                resource_id = resource_resp.json()["id"]

                # Step 3: register a throwaway virtual server bound to the resource.
                server_resp = http.post(
                    f"{BASE_URL}/servers",
                    headers=rest_headers,
                    json={
                        "server": {
                            "name": f"mcp-apps-e2e-{uid}",
                            "description": "MCP Apps E2E test server",
                            "associated_resources": [resource_id],
                        },
                        "visibility": "public",
                    },
                )
                assert server_resp.status_code in (200, 201), f"Failed to create server: {server_resp.text}"
                server_id = server_resp.json()["id"]

                # Step 4: create an AppBridge session for that resource.
                session_resp = http.post(
                    f"{BASE_URL}/appbridge/sessions",
                    headers=rest_headers,
                    json={
                        "resourceUri": f"ui://mcp-apps-e2e-{uid}/index",
                        "serverId": server_id,
                    },
                )
                assert session_resp.status_code == 200, f"AppBridge session create failed: {session_resp.text}"
                session_body = session_resp.json()
                app_session_id = session_body["appSessionId"]
                assert session_body.get("resourceUri", "").startswith("ui://"), f"unexpected resourceUri: {session_body}"
                assert session_body.get("expiresAt"), f"AppBridge session missing expiresAt: {session_body}"
                print(f"    -> AppBridge session created: {app_session_id}")

                # Step 5: ping through the session — the simplest AppBridge RPC method.
                ping_resp = http.post(
                    f"{BASE_URL}/appbridge/sessions/{app_session_id}/rpc",
                    headers=rest_headers,
                    json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
                )
                assert ping_resp.status_code == 200, f"AppBridge ping failed: {ping_resp.text}"
                ping_body = ping_resp.json()
                assert "result" in ping_body, f"AppBridge ping returned no result: {ping_body}"
                assert "error" not in ping_body, f"AppBridge ping returned error: {ping_body}"
                print(f"    -> AppBridge ping OK: {ping_body['result']}")

            finally:
                # Best-effort cleanup so the gateway isn't left with test artifacts.
                if server_id:
                    http.delete(f"{BASE_URL}/servers/{server_id}", headers=rest_headers)
                if resource_id:
                    http.delete(f"{BASE_URL}/resources/{resource_id}", headers=rest_headers)


@skip_no_rust_mcp_gateway
class TestRawHttpTransportParity:
    """Direct HTTP checks for the Rust-fronted MCP transport."""

    def test_initialize_delete_flow_uses_rust_transport(self, jwt_token: str) -> None:
        """Raw initialize and DELETE should stay on the Rust MCP edge when enabled."""
        initialize_headers = {
            "authorization": f"Bearer {jwt_token}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "mcp-protocol-version": "2025-03-26",
        }

        with httpx.Client(timeout=10.0) as client:
            init_response = client.post(f"{BASE_URL}/mcp/", headers=initialize_headers, json=build_initialize())
            assert init_response.status_code == 200, init_response.text
            runtime_marker = init_response.headers.get("x-contextforge-mcp-runtime")
            if runtime_marker != "rust":
                pytest.skip("Rust MCP runtime not enabled on target gateway")

            print(f"    -> Raw HTTP initialize runtime header: {runtime_marker}")

            delete_headers = {
                "authorization": f"Bearer {jwt_token}",
                "accept": "application/json, text/event-stream",
            }
            delete_response = client.request("DELETE", f"{BASE_URL}/mcp/", headers=delete_headers)
            assert delete_response.status_code == 405, delete_response.text
            assert delete_response.headers.get("x-contextforge-mcp-runtime") == "rust"
            print(f"    -> Raw HTTP DELETE runtime header: {delete_response.headers.get('x-contextforge-mcp-runtime')}")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RBAC_PREFIX = "mcp-rbac"
STREAMABLE_HTTP_GATEWAY_NAME = f"{RBAC_PREFIX}-streamable-http-gw"
# Must match docker-compose gateway JWT_SECRET_KEY
_JWT_SECRET = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
# The default covers one 60-second publish interval plus 15 seconds of slack.
_PER_SERVER_ACCESS_SYNC_DEADLINE_SECONDS = float(os.getenv("MCP_E2E_PUBLISHER_SYNC_DEADLINE", "75.0"))
_PER_SERVER_ACCESS_RETRY_DELAY_SECONDS = 1.0
# Replica propagation via Nginx is expected to be faster than the 60-second
# tool-catalog publish interval that _PER_SERVER_ACCESS_SYNC_DEADLINE_SECONDS covers.
_REPLICA_SYNC_DEADLINE_SECONDS = float(os.getenv("MCP_E2E_REPLICA_SYNC_DEADLINE", "30.0"))
# Revocation invalidates the Redis auth cache and publishes to the other replicas.
# One second matches TestDenyPaths.test_revoked_token_fails. Raise it under CI load.
_REVOCATION_PROPAGATION_SECONDS = float(os.getenv("MCP_E2E_REVOCATION_DELAY", "1.0"))


# ---------------------------------------------------------------------------
# JWT helper (for admin bootstrap only — all test users use POST /tokens)
# ---------------------------------------------------------------------------
def _make_jwt(email: str, is_admin: bool = False, teams=None) -> str:
    return make_test_jwt(email, is_admin=is_admin, teams=teams, secret=_JWT_SECRET)


def _api_context(playwright: Playwright, token: str) -> APIRequestContext:
    return make_playwright_api_context(playwright, BASE_URL, token)


def _replica_tools_path(gateway_id: str, probe: str) -> str:
    """Build a unique, unpaginated gateway-tool request for a replica probe."""
    return f"/tools?limit=0&gateway_id={gateway_id}&replica_probe={probe}"


def _assert_replica_response(response, read_index: int) -> list[dict[str, Any]]:
    """Assert a successful backend response that was not served from Nginx cache."""
    assert response.status == 200, f"Replica read {read_index} failed: {response.status} {response.text()}"
    cache_status = response.headers.get("x-cache-status")
    assert cache_status != "HIT", f"Replica read {read_index} was served from Nginx cache, not a gateway backend"
    payload = response.json()
    assert isinstance(payload, list), f"Replica read {read_index} returned unexpected payload: {payload!r}"
    return payload


def _get_gateway_tools(admin_api: APIRequestContext, gateway_id: str, probe: str, read_index: int) -> list[dict[str, Any]]:
    """Read all tools for one gateway through Nginx using a unique cache key."""
    response = admin_api.get(_replica_tools_path(gateway_id, probe))
    return _assert_replica_response(response, read_index)


# ---------------------------------------------------------------------------
# RBAC helper: resolve role name -> UUID
# ---------------------------------------------------------------------------
def _resolve_role_id(admin_api: APIRequestContext, role_name: str) -> str:
    resp = admin_api.get("/rbac/roles")
    assert resp.status == 200, f"Failed to list RBAC roles: {resp.status} {resp.text()}"
    for role in resp.json():
        if role.get("name") == role_name:
            return role["id"]
    raise AssertionError(f"RBAC role '{role_name}' not found. Available: {[r.get('name') for r in resp.json()]}")


# ---------------------------------------------------------------------------
# Token minting: POST /tokens as the token's own owner
# ---------------------------------------------------------------------------
def _mint_token(
    playwright: Playwright,
    email: str,
    *,
    is_admin: bool = False,
    team_id: str | None = None,
    scope: dict[str, Any] | None = None,
    expires_in_days: int = 1,
) -> dict[str, Any]:
    """Mint an API token for ``email`` through ``POST /tokens``.

    The call runs as the token's own owner. A short-lived JWT for ``email``
    authenticates a throwaway API context, so the created token is self-owned
    rather than admin-delegated.

    Args:
        playwright: Playwright entry point used to build the API context.
        email: Owner of the new token.
        is_admin: Set the ``is_admin`` claim on the minting JWT.
        team_id: Scope the token to this team. Omit for a personal token.
        scope: Token scope payload, for example ``{"permissions": ["tools.read"]}``.
        expires_in_days: Token lifetime in days.

    Returns:
        dict: Keys ``access_token``, ``token_id``, ``token_name``.
    """
    user_jwt = _make_jwt(email, is_admin=is_admin, teams=[team_id] if team_id else None)
    user_ctx = _api_context(playwright, user_jwt)
    token_name = f"{RBAC_PREFIX}-token-{uuid.uuid4().hex[:8]}"
    token_data: dict[str, Any] = {
        "name": token_name,
        "expires_in_days": expires_in_days,
    }
    if team_id:
        token_data["team_id"] = team_id
    if scope:
        token_data["scope"] = scope

    try:
        token_resp = user_ctx.post("/tokens", data=token_data)
        assert token_resp.status in (200, 201), f"Failed to create token for {email}: {token_resp.status} {token_resp.text()}"
        payload = token_resp.json()
        access_token = payload["access_token"]
        token_obj = payload.get("token", payload)
        token_id = token_obj.get("id") or token_obj.get("token_id")
    finally:
        user_ctx.dispose()

    logger.info("Created API token for %s (id=%s)", email, token_id)
    return {"access_token": access_token, "token_id": token_id, "token_name": token_name}


# ---------------------------------------------------------------------------
# User lifecycle: create, invite, accept, assign role, create token
# ---------------------------------------------------------------------------
def _create_user_with_token(
    admin_api: APIRequestContext,
    playwright: Playwright,
    email: str,
    *,
    team_id: str | None = None,
    rbac_role: str | None = None,
    is_admin: bool = False,
    token_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a user via API, optionally join a team, assign RBAC role, and create an API token.

    Returns dict with: email, access_token, token_id, token_name, team_id, role, is_admin.
    """
    # 1. Create user
    resp = admin_api.post(
        "/auth/email/admin/users",
        data={
            "email": email,
            "password": TEST_PASSWORD,
            "full_name": f"RBAC Test {email.split('@', maxsplit=1)[0]}",
            "is_admin": is_admin,
            "is_active": True,
            "password_change_required": False,
        },
    )
    if resp.status != 409:
        assert resp.status in (200, 201), f"Failed to create user {email}: {resp.status} {resp.text()}"
    logger.info("Created user %s (is_admin=%s)", email, is_admin)

    # 2. Add to team directly (admin is team owner/creator, so has teams.manage_members)
    if team_id:
        add_resp = admin_api.post(f"/teams/{team_id}/members", data={"email": email, "role": "member"})
        if add_resp.status not in (400, 409):
            assert add_resp.status in (200, 201), f"Failed to add {email} to team: {add_resp.status} {add_resp.text()}"
        logger.info("User %s joined team %s", email, team_id)

    # 3. Assign RBAC role (team-scoped only; platform_admin uses is_admin=True bypass)
    if rbac_role and rbac_role != "platform_admin" and team_id:
        role_uuid = _resolve_role_id(admin_api, rbac_role)
        role_data: dict[str, Any] = {"role_id": role_uuid, "scope": "team", "scope_id": team_id}
        role_resp = admin_api.post(f"/rbac/users/{email}/roles", data=role_data)
        if role_resp.status not in (409, 400):
            assert role_resp.status in (200, 201), f"Failed to assign {rbac_role} to {email}: {role_resp.status} {role_resp.text()}"
        logger.info("Assigned %s role to %s", rbac_role, email)

    # 4. Create API token via POST /tokens, acting as the user
    minted = _mint_token(playwright, email, is_admin=is_admin, team_id=team_id, scope=token_scope)

    return {
        "email": email,
        "access_token": minted["access_token"],
        "token_id": minted["token_id"],
        "token_name": minted["token_name"],
        "team_id": team_id,
        "role": rbac_role,
        "is_admin": is_admin,
    }


def _cleanup_user(admin_api: APIRequestContext, user_info: dict[str, Any]) -> None:
    """Best-effort cleanup: revoke token, remove role, remove from team, delete user."""
    email = user_info["email"]
    team_id = user_info.get("team_id")
    role = user_info.get("role")
    token_id = user_info.get("token_id")

    if token_id:
        with suppress(Exception):
            admin_api.delete(f"/tokens/admin/{token_id}")
    if role and role != "platform_admin" and team_id:
        with suppress(Exception):
            admin_api.delete(f"/rbac/users/{email}/roles/{role}?scope=team&scope_id={team_id}")
    if team_id:
        with suppress(Exception):
            admin_api.delete(f"/teams/{team_id}/members/{email}")
    with suppress(Exception):
        admin_api.delete(f"/auth/email/admin/users/{email}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin-authenticated API context using JWT (bootstrap only)."""
    token = _make_jwt("admin@example.com", is_admin=True, teams=None)
    ctx = make_playwright_api_context(playwright, BASE_URL, token)
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def rbac_team(admin_api: APIRequestContext) -> Generator[dict[str, Any], None, None]:
    """Create a private team for RBAC tests."""
    team_name = f"{RBAC_PREFIX}-team-{uuid.uuid4().hex[:8]}"
    helper = ApiTestHelper(admin_api)
    team = helper.create_team(team_name, description="MCP RBAC E2E test team", visibility="private")
    logger.info("Created RBAC team: %s (id=%s)", team_name, team["id"])
    yield team
    with suppress(Exception):
        admin_api.delete(f"/teams/{team['id']}")


@pytest.fixture(scope="module")
def streamable_http_gateway(admin_api: APIRequestContext) -> Generator[dict[str, Any], None, None]:
    """Register fast_time_server and wait for a stable Streamable HTTP tool catalog."""
    streamable_http_url = "http://fast_time_server:9080/mcp"

    # Delete any pre-existing gateway with same name or same URL (gateway_service
    # rejects a second public gateway at the same URL), but remember what was
    # displaced so it can be restored at teardown. Without this, deleting the
    # compose-seeded "fast_time" gateway here permanently breaks TestToolCalls'
    # fast-time-* tools on any subsequent run against the same stack.
    displaced_gateways: list[dict[str, Any]] = []
    with suppress(Exception):
        gateways = admin_api.get("/gateways").json()
        for gw in gateways:
            if gw.get("name") == STREAMABLE_HTTP_GATEWAY_NAME or gw.get("url") == streamable_http_url:
                displaced_gateways.append(gw)
                admin_api.delete(f"/gateways/{gw['id']}")

    gw_id: str | None = None
    try:
        resp = admin_api.post(
            "/gateways",
            data={
                "name": STREAMABLE_HTTP_GATEWAY_NAME,
                "url": streamable_http_url,
                "transport": "STREAMABLEHTTP",
            },
        )
        assert resp.status in (200, 201), f"Failed to register Streamable HTTP gateway: {resp.status} {resp.text()}"
        gw = resp.json()
        gw_id = gw["id"]
        logger.info("Registered Streamable HTTP gateway: %s (id=%s)", STREAMABLE_HTTP_GATEWAY_NAME, gw_id)

        deadline = time.monotonic() + _REPLICA_SYNC_DEADLINE_SECONDS
        previous_tool_ids: frozenset[str] | None = None
        read_index = 0
        while time.monotonic() < deadline:
            read_index += 1
            probe = f"gateway-sync-{uuid.uuid4().hex}"
            try:
                gateway_tools = _get_gateway_tools(admin_api, gw_id, probe, read_index)
                tool_ids = frozenset(str(tool["id"]) for tool in gateway_tools)
                if tool_ids and tool_ids == previous_tool_ids:
                    logger.info("Streamable HTTP gateway synchronized with %d stable tools", len(tool_ids))
                    yield {"id": gw_id, "name": STREAMABLE_HTTP_GATEWAY_NAME, "tool_ids": tool_ids}
                    return
                previous_tool_ids = tool_ids
            except (AssertionError, KeyError, TypeError, ValueError, PlaywrightError) as exc:
                logger.debug("Gateway tool synchronization probe %d did not succeed: %s", read_index, exc)
                previous_tool_ids = None
            time.sleep(_PER_SERVER_ACCESS_RETRY_DELAY_SECONDS)

        raise AssertionError(f"Streamable HTTP gateway {gw_id} did not produce a stable tool catalog within {_REPLICA_SYNC_DEADLINE_SECONDS}s")
    finally:
        if gw_id:
            with suppress(Exception):
                delete_response = admin_api.delete(f"/gateways/{gw_id}")
                if delete_response.status not in (200, 204, 404):
                    logger.warning("Failed to delete Streamable HTTP gateway %s: %s %s", gw_id, delete_response.status, delete_response.text())

        # Restore any displaced pre-existing registration (e.g. the compose-seeded
        # "fast_time" gateway) so other tests relying on it keep working.
        for gw in displaced_gateways:
            with suppress(Exception):
                admin_api.post(
                    "/gateways",
                    data={
                        "name": gw["name"],
                        "url": gw["url"],
                        "transport": gw.get("transport", "STREAMABLEHTTP"),
                        "description": gw.get("description"),
                    },
                )


@pytest.fixture(scope="module")
def cross_replica_user(admin_api: APIRequestContext, playwright: Playwright, streamable_http_gateway: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    """Create a token-owning user for replica consistency checks and always clean it up."""
    del streamable_http_gateway
    email = f"{RBAC_PREFIX}-replica-{uuid.uuid4().hex[:8]}@test.com"
    user_info: dict[str, Any] = {"email": email, "team_id": None, "role": None, "token_id": None}
    try:
        user_info.update(_create_user_with_token(admin_api, playwright, email))
        time.sleep(1)
        yield user_info
    finally:
        _cleanup_user(admin_api, user_info)


@pytest.fixture(scope="module")
def visibility_servers(admin_api: APIRequestContext, rbac_team: dict, streamable_http_gateway: dict) -> Generator[dict[str, Any], None, None]:
    """Create 3 virtual servers (public, team, private) with Streamable HTTP gateway tools."""
    gw_id = streamable_http_gateway["id"]
    team_id = rbac_team["id"]

    # Fetch Streamable HTTP tools for association
    tools = admin_api.get("/tools").json()
    gateway_tool_ids = [t["id"] for t in tools if t.get("gatewayId") == gw_id]

    # Also fetch resources/prompts
    resources = admin_api.get("/resources").json()
    gateway_resource_ids = [r["id"] for r in resources if r.get("gatewayId") == gw_id] if resources else []
    prompts = admin_api.get("/prompts").json()
    gateway_prompt_ids = [p["id"] for p in prompts if p.get("gatewayId") == gw_id] if prompts else []

    uid = uuid.uuid4().hex[:8]
    servers: dict[str, dict[str, Any]] = {}

    for vis, vis_team_id in [("public", None), ("team", team_id), ("private", team_id)]:
        name = f"{RBAC_PREFIX}-{vis}-streamable-http-{uid}"
        payload: dict[str, Any] = {
            "server": {
                "name": name,
                "description": f"RBAC test {vis} Streamable HTTP server",
                "associated_tools": gateway_tool_ids,
                "associated_resources": gateway_resource_ids,
                "associated_prompts": gateway_prompt_ids,
            },
            "visibility": vis,
        }
        if vis_team_id:
            payload["team_id"] = vis_team_id
        resp = admin_api.post("/servers", data=payload)
        assert resp.status in (200, 201), f"Failed to create {vis} server: {resp.status} {resp.text()}"
        srv = resp.json()
        servers[vis] = {"id": srv["id"], "name": name, "visibility": vis, "team_id": vis_team_id}
        logger.info("Created %s server: %s (id=%s)", vis, name, srv["id"])

    yield servers

    for srv in servers.values():
        with suppress(Exception):
            admin_api.delete(f"/servers/{srv['id']}")


@pytest.fixture(scope="module")
def test_users(admin_api: APIRequestContext, playwright: Playwright, rbac_team: dict) -> Generator[dict[str, dict[str, Any]], None, None]:
    """Create 4 test users with different RBAC roles and API tokens."""
    team_id = rbac_team["id"]
    uid = uuid.uuid4().hex[:8]

    users: dict[str, dict[str, Any]] = {}

    # Platform admin (global scope, no team needed for admin bypass)
    users["admin"] = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-admin-{uid}@test.com",
        is_admin=True,
        rbac_role="platform_admin",
    )

    # Team admin
    users["team_admin"] = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-tadmin-{uid}@test.com",
        team_id=team_id,
        rbac_role="team_admin",
    )

    # Developer
    users["developer"] = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-dev-{uid}@test.com",
        team_id=team_id,
        rbac_role="developer",
    )

    # Viewer
    users["viewer"] = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-viewer-{uid}@test.com",
        team_id=team_id,
        rbac_role="viewer",
    )

    yield users

    for user_info in users.values():
        _cleanup_user(admin_api, user_info)


@pytest.fixture(scope="module")
def outsider_user(admin_api: APIRequestContext, playwright: Playwright) -> Generator[dict[str, Any], None, None]:
    """A user with NO team membership — should only see public resources."""
    uid = uuid.uuid4().hex[:8]
    user = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-outsider-{uid}@test.com",
    )
    yield user
    _cleanup_user(admin_api, user)


@pytest.fixture(scope="module")
def scoped_token_read_only(admin_api: APIRequestContext, playwright: Playwright) -> Generator[dict[str, Any], None, None]:
    """A token with only tools.read permission (servers.use auto-injected at generation)."""
    uid = uuid.uuid4().hex[:8]
    user = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-scoped-ro-{uid}@test.com",
        is_admin=True,
        rbac_role="platform_admin",
        token_scope={"permissions": ["tools.read"]},
    )
    yield user
    _cleanup_user(admin_api, user)


@pytest.fixture(scope="module")
def scoped_token_read_execute(admin_api: APIRequestContext, playwright: Playwright) -> Generator[dict[str, Any], None, None]:
    """A token with tools.read + tools.execute permissions (servers.use auto-injected at generation)."""
    uid = uuid.uuid4().hex[:8]
    user = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-scoped-rw-{uid}@test.com",
        is_admin=True,
        rbac_role="platform_admin",
        token_scope={"permissions": ["tools.read", "tools.execute"]},
    )
    yield user
    _cleanup_user(admin_api, user)


@pytest.fixture(scope="module")
def token_lifecycle_user(admin_api: APIRequestContext, playwright: Playwright) -> Generator[dict[str, Any], None, None]:
    """An admin user whose first token survives the whole token-lifecycle class.

    Tests that do not destroy the token share this one. Tests that revoke or
    restrict a token mint their own against the same user.
    """
    uid = uuid.uuid4().hex[:8]
    user = _create_user_with_token(
        admin_api,
        playwright,
        f"{RBAC_PREFIX}-tokenlc-{uid}@test.com",
        is_admin=True,
        rbac_role="platform_admin",
    )
    yield user
    _cleanup_user(admin_api, user)


# ---------------------------------------------------------------------------
# MCP protocol helpers
# ---------------------------------------------------------------------------
_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _run_async(coro):
    """Run an async coroutine from sync code that already has an event loop (Playwright)."""
    return _thread_pool.submit(asyncio.run, coro).result()


def _mcp_client_url(server_url: str = BASE_URL) -> str:
    return f"{server_url}/mcp/" if not server_url.endswith(("/mcp", "/mcp/")) else server_url.rstrip("/") + "/"


def _unwrap_exception_group(exc: BaseException) -> list[BaseException]:
    """Flatten a possibly-nested ``ExceptionGroup`` into its leaf exceptions.

    The MCP SDK runs client calls inside anyio ``TaskGroup``s at both the
    session and transport layers. A single underlying error (an ``McpError``,
    an ``httpx.HTTPStatusError``) can arrive wrapped in one or more
    ``ExceptionGroup`` layers depending on how many task groups were open on
    the call stack when it surfaced -- for example ``initialize()`` alone
    wraps once, while ``initialize()`` followed by ``call_tool()`` on the same
    session wraps twice. Callers that need to inspect the real error must
    unwrap to an unknown, not a fixed, depth.
    """
    if isinstance(exc, ExceptionGroup):
        leaves: list[BaseException] = []
        for sub in exc.exceptions:
            leaves.extend(_unwrap_exception_group(sub))
        return leaves
    return [exc]


# Transport-layer failures an MCP call can raise. The tuple lists these errors only.
# Catching bare Exception would swallow the AssertionErrors below and the test could
# never fail (#6839). ExceptionGroup is included because the SDK's ClientSession runs
# call_tool() inside an anyio TaskGroup, which wraps a single McpError on the way out.
_TRANSPORT_ERRORS = (McpError, httpx.HTTPError, RuntimeError, TimeoutError, ExceptionGroup)

# Every RBAC denial in mcpgateway/middleware/rbac.py raises 403. A 401 means
# authentication failed before RBAC ran, so it is not evidence of a denial.
_DENIED_STATUSES = (403,)


def _assert_denied_for_rbac(call: Callable[[], Any], context: str) -> None:
    """Run an MCP call and assert the gateway denied it for an RBAC reason.

    The gateway denies in either of two shapes. It answers the JSON-RPC call with
    ``isError`` set, or it fails the call at the transport. Each shape gets its own
    assertion, and each assertion checks the denial reason. A bare ``isError`` check
    would also pass for an unrelated error, so it cannot detect an RBAC regression.

    The assertions live in the ``except`` and ``else`` bodies. Neither body is covered
    by the ``try``, so this structure cannot swallow an ``AssertionError``.

    Args:
        call: Zero-argument callable that performs the MCP tool call.
        context: Short label for the call, used in the printed output.

    Raises:
        AssertionError: If the call succeeded, or failed for another reason.
    """
    try:
        result = call()
    except _TRANSPORT_ERRORS as exc:
        leaves = _unwrap_exception_group(exc)
        denied_by_status = any(getattr(getattr(leaf, "response", None), "status_code", None) in _DENIED_STATUSES for leaf in leaves)
        denied_by_text = any("access denied" in str(leaf).lower() for leaf in leaves)
        assert denied_by_status or denied_by_text, f"expected an access denial for {context}, got: {leaves!r}"
        print(f"    -> Outsider {context} rejected at the transport (expected): {leaves[0]}")
    else:
        assert result.isError, f"Outsider {context} should be denied, got: {result}"
        detail = result.content[0].text.lower()
        assert "access denied" in detail, f"expected an access denial for {context}, got: {result.content[0].text}"
        print(f"    -> Outsider {context} denied (expected): {result.content[0].text}")


@asynccontextmanager
async def _mcp_session(server_url: str, access_token: str | None = None) -> AsyncIterator[ClientSession]:
    """Open an initialized MCP client session over Streamable HTTP."""
    url = _mcp_client_url(server_url)
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else None
    timeout = timedelta(seconds=_CLIENT_TIMEOUT)
    async with streamablehttp_client(url, headers=headers, timeout=timeout, sse_read_timeout=timeout) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream, read_timeout_seconds=timeout) as session:
            await session.initialize()
            yield session


async def _async_mcp_tools_list(access_token: str, server_url: str = BASE_URL) -> list:
    async with _mcp_session(server_url, access_token) as session:
        return (await session.list_tools()).tools


async def _async_mcp_resources_list(access_token: str, server_url: str = BASE_URL) -> list:
    async with _mcp_session(server_url, access_token) as session:
        return (await session.list_resources()).resources


async def _async_mcp_prompts_list(access_token: str, server_url: str = BASE_URL) -> list:
    async with _mcp_session(server_url, access_token) as session:
        return (await session.list_prompts()).prompts


async def _async_mcp_tool_call(access_token: str, tool_name: str, arguments: dict[str, Any] | None = None, server_url: str = BASE_URL):
    async with _mcp_session(server_url, access_token) as session:
        return await session.call_tool(tool_name, arguments or {})


async def _async_mcp_initialize(access_token: str, server_url: str = BASE_URL) -> bool:
    async with _mcp_session(server_url, access_token) as _session:
        return True


async def _async_mcp_connect(url: str, access_token: str | None = None) -> bool:
    async with _mcp_session(url, access_token) as _session:
        return True


def _mcp_tools_list(access_token: str, server_url: str = BASE_URL) -> list:
    return _run_async(_async_mcp_tools_list(access_token, server_url))


def _mcp_tools_list_after_publisher_sync(access_token: str, server_url: str = BASE_URL) -> list:
    """Retry allow-path discovery while new server config converges.

    Deny-path checks intentionally bypass this helper so stale configuration
    cannot delay or mask authorization failures.
    """
    deadline = time.monotonic() + _PER_SERVER_ACCESS_SYNC_DEADLINE_SECONDS
    while True:
        try:
            return _mcp_tools_list(access_token, server_url=server_url)
        except (httpx.HTTPError, McpError, RuntimeError, TimeoutError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(_PER_SERVER_ACCESS_RETRY_DELAY_SECONDS)


def _mcp_resources_list(access_token: str, server_url: str = BASE_URL) -> list:
    return _run_async(_async_mcp_resources_list(access_token, server_url))


def _mcp_prompts_list(access_token: str, server_url: str = BASE_URL) -> list:
    return _run_async(_async_mcp_prompts_list(access_token, server_url))


def _mcp_tool_call(access_token: str, tool_name: str, arguments: dict[str, Any] | None = None, server_url: str = BASE_URL):
    return _run_async(_async_mcp_tool_call(access_token, tool_name, arguments, server_url))


def _mcp_initialize_only(access_token: str, server_url: str = BASE_URL) -> bool:
    return _run_async(_async_mcp_initialize(access_token, server_url))


# ---------------------------------------------------------------------------
# Test: REST API server visibility
# ---------------------------------------------------------------------------
class TestServerVisibilityViaAPI:
    """Verify server visibility via REST API before MCP protocol tests."""

    def test_admin_sees_public_and_team_via_http(self, admin_api: APIRequestContext, visibility_servers: dict) -> None:
        """Admin via HTTP sees public + team servers and their own private servers.

        ``admin_api`` carries a JWT with ``is_admin=true`` and ``teams=null``.
        ``get_scoped_resource_access_context`` keeps the requester email on the
        admin-bypass path so the service layer can owner-match (issue #4694,
        commit 8c186c5e0): the listing returns public rows, team rows, and the
        caller's own private rows — never another user's private rows. The
        fixture's private server is created by this same admin, so it appears
        via owner matching. The earlier revision of this test asserted the
        pre-#4694 collapse-to-anonymous semantics and failed once owner
        matching landed.
        """
        resp = admin_api.get("/servers")
        assert resp.status == 200
        server_ids = {s["id"] for s in resp.json()}
        assert visibility_servers["public"]["id"] in server_ids, "Admin should see public server"
        assert visibility_servers["team"]["id"] in server_ids, "Admin should see team server"
        assert visibility_servers["private"]["id"] in server_ids, "Admin should see their own private server via owner matching (issue #4694)"
        print("    -> Admin sees public + team servers and own private via owner matching")

    def test_team_member_sees_public_and_team(self, test_users: dict, playwright: Playwright, visibility_servers: dict) -> None:
        token = test_users["developer"]["access_token"]
        ctx = _api_context(playwright, token)
        try:
            resp = ctx.get("/servers")
            assert resp.status == 200
            server_ids = {s["id"] for s in resp.json()}
            assert visibility_servers["public"]["id"] in server_ids, "Developer should see public server"
            assert visibility_servers["team"]["id"] in server_ids, "Developer should see team server"
        finally:
            ctx.dispose()
        print("    -> Developer sees public + team servers")

    def test_viewer_sees_public_and_team(self, test_users: dict, playwright: Playwright, visibility_servers: dict) -> None:
        token = test_users["viewer"]["access_token"]
        ctx = _api_context(playwright, token)
        try:
            resp = ctx.get("/servers")
            assert resp.status == 200
            server_ids = {s["id"] for s in resp.json()}
            assert visibility_servers["public"]["id"] in server_ids, "Viewer should see public server"
            assert visibility_servers["team"]["id"] in server_ids, "Viewer should see team server"
        finally:
            ctx.dispose()
        print("    -> Viewer sees public + team servers")

    def test_outsider_sees_only_public(self, outsider_user: dict, playwright: Playwright, visibility_servers: dict) -> None:
        token = outsider_user["access_token"]
        ctx = _api_context(playwright, token)
        try:
            resp = ctx.get("/servers")
            assert resp.status == 200
            server_ids = {s["id"] for s in resp.json()}
            assert visibility_servers["public"]["id"] in server_ids, "Outsider should see public server"
            assert visibility_servers["team"]["id"] not in server_ids, "Outsider should NOT see team server"
            assert visibility_servers["private"]["id"] not in server_ids, "Outsider should NOT see private server"
        finally:
            ctx.dispose()
        print("    -> Outsider sees only public server")

    def test_team_admin_sees_public_and_team(self, test_users: dict, playwright: Playwright, visibility_servers: dict) -> None:
        token = test_users["team_admin"]["access_token"]
        ctx = _api_context(playwright, token)
        try:
            resp = ctx.get("/servers")
            assert resp.status == 200
            server_ids = {s["id"] for s in resp.json()}
            assert visibility_servers["public"]["id"] in server_ids, "Team admin should see public server"
            assert visibility_servers["team"]["id"] in server_ids, "Team admin should see team server"
        finally:
            ctx.dispose()
        print("    -> Team admin sees public + team servers")


# ---------------------------------------------------------------------------
# Test: MCP tools/list visibility by role
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestMcpToolsVisibilityByRole:
    """MCP tools/list returns role-appropriate tools for each user."""

    def test_admin_sees_all_tools(self, test_users: dict, visibility_servers: dict) -> None:
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        tool_names = [t.name for t in tools]
        assert len(tools) > 0, "Admin should see at least one tool"
        # Admin should see tools from all servers including existing public ones
        print(f"    -> Admin sees {len(tools)} tools: {tool_names[:10]}...")

    def test_developer_sees_public_and_team_tools(self, test_users: dict) -> None:
        tools = _mcp_tools_list(test_users["developer"]["access_token"])
        assert len(tools) > 0, "Developer should see at least public tools"
        tool_names = [t.name for t in tools]
        # Developer should see mcp-rbac-streamable-http-gw-* (public Streamable HTTP) tools
        has_public_tools = any("mcp-rbac-streamable-http-gw-" in n for n in tool_names)
        assert has_public_tools, f"Developer should see public streamable HTTP gateway tools, got: {tool_names}"
        print(f"    -> Developer sees {len(tools)} tools")

    def test_viewer_sees_public_and_team_tools(self, test_users: dict) -> None:
        tools = _mcp_tools_list(test_users["viewer"]["access_token"])
        assert len(tools) > 0, "Viewer should see at least public tools"
        tool_names = [t.name for t in tools]
        has_public_tools = any("mcp-rbac-streamable-http-gw-" in n for n in tool_names)
        assert has_public_tools, f"Viewer should see public streamable HTTP gateway tools, got: {tool_names}"
        print(f"    -> Viewer sees {len(tools)} tools")

    def test_outsider_sees_only_public_tools(self, outsider_user: dict) -> None:
        tools = _mcp_tools_list(outsider_user["access_token"])
        tool_names = [t.name for t in tools]
        # Outsider should see public tools (mcp-rbac-streamable-http-gw-*) but not team-only
        has_public_tools = any("mcp-rbac-streamable-http-gw-" in n for n in tool_names)
        assert has_public_tools, f"Outsider should see public streamable HTTP gateway tools, got: {tool_names}"
        print(f"    -> Outsider sees {len(tools)} public tools")

    def test_team_admin_sees_public_and_team_tools(self, test_users: dict) -> None:
        tools = _mcp_tools_list(test_users["team_admin"]["access_token"])
        assert len(tools) > 0, "Team admin should see at least public tools"
        print(f"    -> Team admin sees {len(tools)} tools")


# ---------------------------------------------------------------------------
# Test: MCP resources + prompts visibility by role
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestMcpResourcesPromptsByRole:
    """MCP resources/list + prompts/list follow same visibility rules."""

    def test_admin_resources(self, test_users: dict) -> None:
        resources = _mcp_resources_list(test_users["admin"]["access_token"])
        print(f"    -> Admin sees {len(resources)} resources")

    def test_admin_prompts(self, test_users: dict) -> None:
        prompts = _mcp_prompts_list(test_users["admin"]["access_token"])
        print(f"    -> Admin sees {len(prompts)} prompts")

    def test_developer_resources_and_prompts(self, test_users: dict) -> None:
        resources = _mcp_resources_list(test_users["developer"]["access_token"])
        prompts = _mcp_prompts_list(test_users["developer"]["access_token"])
        print(f"    -> Developer sees {len(resources)} resources, {len(prompts)} prompts")

    def test_outsider_resources_and_prompts(self, outsider_user: dict) -> None:
        resources = _mcp_resources_list(outsider_user["access_token"])
        prompts = _mcp_prompts_list(outsider_user["access_token"])
        print(f"    -> Outsider sees {len(resources)} resources, {len(prompts)} prompts")


# ---------------------------------------------------------------------------
# Test: MCP tools/call enforcement by role
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestMcpToolCallByRole:
    """Tool execution enforcement through MCP protocol.

    Since #3687 the default /mcp endpoint uses check_any_team=True for API
    tokens, so team-scoped roles (developer, viewer, team_admin) that hold
    tools.execute in ANY team can execute tools on the default endpoint.
    Only users with NO team membership (outsider) are denied.
    """

    def test_admin_calls_tool_success(self, test_users: dict) -> None:
        result = _mcp_tool_call(test_users["admin"]["access_token"], "mcp-rbac-streamable-http-gw-get-system-time", {"timezone": "UTC"})
        assert not result.isError, f"Admin tool call should succeed: {result}"
        text = result.content[0].text
        assert len(text) > 0
        print(f"    -> Admin call mcp-rbac-streamable-http-gw-get-system-time = {text}")

    def test_developer_can_execute_on_default_endpoint(self, test_users: dict) -> None:
        """Developer has team-scoped tools.execute; check_any_team=True allows it on /mcp."""
        result = _mcp_tool_call(test_users["developer"]["access_token"], "mcp-rbac-streamable-http-gw-get-system-time", {"timezone": "UTC"})
        assert not result.isError, f"Developer tool call should succeed (check_any_team): {result}"
        print(f"    -> Developer call succeeded: {result.content[0].text}")

    def test_team_admin_can_execute_on_default_endpoint(self, test_users: dict) -> None:
        """Team admin has team-scoped tools.execute; check_any_team=True allows it on /mcp."""
        result = _mcp_tool_call(test_users["team_admin"]["access_token"], "mcp-rbac-streamable-http-gw-get-system-time", {"timezone": "UTC"})
        assert not result.isError, f"Team admin tool call should succeed (check_any_team): {result}"
        print(f"    -> Team admin call succeeded: {result.content[0].text}")

    def test_outsider_denied_tools_execute(self, outsider_user: dict) -> None:
        """Outsider has no team membership, so no tools.execute anywhere — denied."""
        _assert_denied_for_rbac(
            lambda: _mcp_tool_call(outsider_user["access_token"], f"{STREAMABLE_HTTP_GATEWAY_NAME}-get-system-time", {"timezone": "UTC"}),
            "tools.execute",
        )

    def test_outsider_calls_nonexistent_tool_error(self, outsider_user: dict) -> None:
        """An outsider calling an unknown tool is denied by RBAC, not by name resolution.

        The outsider holds no team membership, so RBAC denies the call before the
        gateway resolves the tool name. ``isError`` alone would stay true for a plain
        name-resolution failure, so the helper asserts the denial reason instead.
        """
        _assert_denied_for_rbac(
            lambda: _mcp_tool_call(outsider_user["access_token"], "nonexistent-tool-xyz-rbac"),
            "nonexistent tool call",
        )

    def test_viewer_can_execute_on_default_endpoint(self, test_users: dict) -> None:
        """Viewer has team-scoped tools.execute; check_any_team=True allows it on /mcp."""
        result = _mcp_tool_call(test_users["viewer"]["access_token"], "mcp-rbac-streamable-http-gw-get-system-time", {"timezone": "UTC"})
        assert not result.isError, f"Viewer tool call should succeed (check_any_team): {result}"
        print(f"    -> Viewer call succeeded: {result.content[0].text}")


# ---------------------------------------------------------------------------
# Test: Scoped token permissions via MCP
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestMcpScopedTokenPermissions:
    """Token scope enforcement through MCP protocol.

    The MCP endpoint (/servers/{id}/mcp) requires ``servers.use`` at the HTTP
    middleware layer *before* any JSON-RPC processing occurs. Token generation
    auto-injects ``servers.use`` when MCP-method permissions (``tools.*``,
    ``resources.*``, ``prompts.*``) are present, so tokens with these
    permissions can reach the transport layer without explicitly including it.

    Therefore:
    - A token with ``["tools.read"]`` gets ``servers.use`` auto-injected and can initialize.
    - A token with ``["tools.read", "tools.execute"]`` likewise succeeds at transport level.
    - A token with ``["servers.use", "tools.read"]`` can list tools but not call them.
    - A token with ``["servers.use", "tools.read", "tools.execute"]`` can do both.
    """

    def test_tools_read_only_token_can_initialize(self, scoped_token_read_only: dict) -> None:
        """Token with tools.read gets servers.use auto-injected and can reach MCP endpoint."""
        assert _mcp_initialize_only(scoped_token_read_only["access_token"])
        print("    -> tools.read-only token initialized (servers.use auto-injected)")

    def test_read_execute_token_can_initialize(self, scoped_token_read_execute: dict) -> None:
        """Token with tools.read+execute gets servers.use auto-injected and can reach MCP endpoint."""
        assert _mcp_initialize_only(scoped_token_read_execute["access_token"])
        print("    -> tools.read+execute token initialized (servers.use auto-injected)")

    def test_unscoped_admin_token_can_call_tools(self, test_users: dict) -> None:
        """Admin token without custom scope (empty permissions = pass-through) can call tools."""
        result = _mcp_tool_call(test_users["admin"]["access_token"], "mcp-rbac-streamable-http-gw-get-system-time", {"timezone": "UTC"})
        assert not result.isError, f"Unscoped admin token should succeed: {result}"
        text = result.content[0].text
        assert len(text) > 0
        print(f"    -> Unscoped admin token call = {text}")


# ---------------------------------------------------------------------------
# Test: Streamable HTTP transport
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestMcpStreamableHttpTransport:
    """Streamable HTTP transport works end-to-end through MCP protocol."""

    def test_streamable_http_tools_discoverable(self, test_users: dict, streamable_http_gateway: dict) -> None:
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        # Streamable HTTP tools should have a prefix from the gateway
        print(f"    -> {len(tools)} total tools visible to admin (Streamable HTTP gateway id={streamable_http_gateway['id']})")
        assert len(tools) > 0, "Should discover at least one tool via Streamable HTTP"

    def test_streamable_http_get_system_time(self, test_users: dict, streamable_http_gateway: dict) -> None:
        """Call a Streamable HTTP-sourced tool: the tool name may have gateway prefix."""
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        # Find a get-system-time tool
        time_tools = [t.name for t in tools if "get-system-time" in t.name]
        assert len(time_tools) > 0, f"Expected at least one get-system-time tool, got: {[t.name for t in tools]}"
        # Call the first one found
        result = _mcp_tool_call(test_users["admin"]["access_token"], time_tools[0], {"timezone": "UTC"})
        assert not result.isError, f"Streamable HTTP get-system-time failed: {result}"
        print(f"    -> Streamable HTTP {time_tools[0]} = {result.content[0].text}")

    def test_streamable_http_convert_time(self, test_users: dict) -> None:
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        convert_tools = [t.name for t in tools if "convert-time" in t.name]
        assert len(convert_tools) > 0, "Expected at least one convert-time tool"
        result = _mcp_tool_call(
            test_users["admin"]["access_token"],
            convert_tools[0],
            {"time": "2025-06-01T10:00:00Z", "source_timezone": "UTC", "target_timezone": "Europe/London"},
        )
        assert not result.isError, f"Streamable HTTP convert-time failed: {result}"
        print(f"    -> Streamable HTTP {convert_tools[0]}: OK")

    def test_streamable_http_resources_discoverable(self, test_users: dict) -> None:
        resources = _mcp_resources_list(test_users["admin"]["access_token"])
        print(f"    -> Admin sees {len(resources)} resources (incl. Streamable HTTP)")

    def test_streamable_http_prompts_discoverable(self, test_users: dict) -> None:
        prompts = _mcp_prompts_list(test_users["admin"]["access_token"])
        print(f"    -> Admin sees {len(prompts)} prompts (incl. Streamable HTTP)")


# ---------------------------------------------------------------------------
# Test: Per-server MCP endpoint
# ---------------------------------------------------------------------------
class TestMcpPerServerEndpoint:
    """Test /servers/{UUID}/mcp scoped access."""

    def test_public_token_accesses_public_server(self, outsider_user: dict, visibility_servers: dict) -> None:
        """Outsider can access the public server's per-server MCP endpoint."""
        server_id = visibility_servers["public"]["id"]
        server_url = f"{BASE_URL}/servers/{server_id}"
        tools = _mcp_tools_list_after_publisher_sync(outsider_user["access_token"], server_url=server_url)
        # May see only that server's tools
        print(f"    -> Outsider via /servers/{server_id}/mcp: {len(tools)} tools")
        assert tools, "public server should advertise its associated tools, not an empty list"

    def test_team_member_accesses_team_server(self, test_users: dict, visibility_servers: dict) -> None:
        """Developer can access the team server's per-server endpoint."""
        server_id = visibility_servers["team"]["id"]
        server_url = f"{BASE_URL}/servers/{server_id}"
        tools = _mcp_tools_list_after_publisher_sync(test_users["developer"]["access_token"], server_url=server_url)
        print(f"    -> Developer via /servers/{server_id}/mcp: {len(tools)} tools")
        assert tools, "team server should advertise its associated tools, not an empty list"

    def test_outsider_denied_team_server(self, outsider_user: dict, visibility_servers: dict) -> None:
        """Outsider cannot access team server's per-server endpoint."""
        server_id = visibility_servers["team"]["id"]
        server_url = f"{BASE_URL}/servers/{server_id}"
        with pytest.raises(Exception) as excinfo:
            _mcp_initialize_only(outsider_user["access_token"], server_url=server_url)
        print(f"    -> Outsider denied team server: {excinfo.value}")

    def test_outsider_denied_private_server(self, outsider_user: dict, visibility_servers: dict) -> None:
        """Outsider cannot access private server's per-server endpoint."""
        server_id = visibility_servers["private"]["id"]
        server_url = f"{BASE_URL}/servers/{server_id}"
        with pytest.raises(Exception) as excinfo:
            _mcp_initialize_only(outsider_user["access_token"], server_url=server_url)
        print(f"    -> Outsider denied private server: {excinfo.value}")


# ---------------------------------------------------------------------------
# Test: Deny paths (security invariants)
# ---------------------------------------------------------------------------
class TestDenyPaths:
    """Security invariant tests — ensure auth failures are handled correctly."""

    def test_no_token_fails(self) -> None:
        """MCP initialize with no auth token should fail."""
        with pytest.raises(Exception) as excinfo:
            _run_async(_async_mcp_connect(_mcp_client_url()))
        print(f"    -> No token: failure (expected): {excinfo.value}")

    def test_garbage_token_fails(self) -> None:
        """MCP initialize with garbage token should fail."""
        with pytest.raises(Exception) as excinfo:
            _run_async(_async_mcp_connect(_mcp_client_url(), access_token="this-is-not-a-valid-token"))
        print(f"    -> Garbage token: failure (expected): {excinfo.value}")

    def test_wrong_secret_token_fails(self) -> None:
        """MCP with token signed by wrong secret should fail."""
        bad_token = make_test_jwt(
            "admin@example.com",
            is_admin=True,
            teams=None,
            secret="completely-wrong-secret-key-12345",  # pragma: allowlist secret
        )

        with pytest.raises(Exception) as excinfo:
            _run_async(_async_mcp_connect(_mcp_client_url(), access_token=bad_token))
        print(f"    -> Wrong secret: failure (expected): {excinfo.value}")

    def test_revoked_token_fails(self, admin_api: APIRequestContext, playwright: Playwright) -> None:
        """Token created then revoked should fail MCP operations."""
        uid = uuid.uuid4().hex[:8]
        email = f"{RBAC_PREFIX}-revoke-{uid}@test.com"
        user = _create_user_with_token(admin_api, playwright, email, is_admin=True, rbac_role="platform_admin")
        access_token = user["access_token"]
        token_id = user["token_id"]

        # Verify the token works first
        tools_before = _mcp_tools_list(access_token)
        assert len(tools_before) > 0, "Token should work before revocation"

        # Revoke the token
        revoke_resp = admin_api.delete(f"/tokens/admin/{token_id}")
        assert revoke_resp.status == 204, f"Failed to revoke token: {revoke_resp.status}"

        # Small delay for revocation to propagate
        time.sleep(1)

        # Try to use the revoked token
        with pytest.raises(Exception) as excinfo:
            _mcp_tools_list(access_token)
        print(f"    -> Revoked token rejected (expected): {excinfo.value}")

        _cleanup_user(admin_api, user)

    def test_cross_team_isolation(self, outsider_user: dict, playwright: Playwright, visibility_servers: dict) -> None:
        """User outside team A cannot see team A's resources (cross-team isolation).

        Uses the outsider_user fixture (no team membership) to verify that
        team-scoped and private servers are not visible to non-members.
        """
        ctx = _api_context(playwright, outsider_user["access_token"])
        try:
            resp = ctx.get("/servers")
            assert resp.status == 200
            server_ids = {s["id"] for s in resp.json()}
            assert visibility_servers["team"]["id"] not in server_ids, "Outsider should NOT see team-scoped server"
            assert visibility_servers["private"]["id"] not in server_ids, "Outsider should NOT see private server"
            assert visibility_servers["public"]["id"] in server_ids, "Outsider should see public server"
        finally:
            ctx.dispose()

        print("    -> Cross-team isolation verified: outsider denied team/private resources")

    def test_invalid_bearer_prefix_fails(self) -> None:
        """Token without proper Bearer prefix handling."""
        with pytest.raises(Exception) as excinfo:
            _run_async(_async_mcp_connect(_mcp_client_url(), access_token="not-bearer-prefixed-garbage"))
        print(f"    -> Invalid token: failure (expected): {excinfo.value}")


# ---------------------------------------------------------------------------
# Test: API token lifecycle
# ---------------------------------------------------------------------------
class TestTokenLifecycle:
    """Create, list, authenticate, revoke, and scope-restrict an API token.

    Issue #6523. Token revocation already has a deny-path test. Everything
    before revocation was fixture infrastructure until this class. A silent
    break in the token catalog would leave the RBAC suite green.
    """

    def test_create_token_returns_access_token_and_id(self, token_lifecycle_user: dict, admin_api: APIRequestContext, playwright: Playwright) -> None:
        """POST /tokens returns a non-empty access_token and a token id.

        The POST runs inline rather than through ``_mint_token`` so the raw
        ``TokenCreateResponse`` body is asserted, not the helper's extraction.
        """
        user_jwt = _make_jwt(token_lifecycle_user["email"], is_admin=True, teams=None)
        ctx = _api_context(playwright, user_jwt)
        token_id = None
        try:
            name = f"{RBAC_PREFIX}-token-{uuid.uuid4().hex[:8]}"
            resp = ctx.post("/tokens", data={"name": name, "expires_in_days": 1})
            assert resp.status in (200, 201), f"POST /tokens failed: {resp.status} {resp.text()}"

            payload = resp.json()
            token_obj = payload.get("token", {})
            token_id = token_obj.get("id")
            assert "access_token" in payload, f"TokenCreateResponse must carry access_token, got {sorted(payload)}"
            assert "token" in payload, f"TokenCreateResponse must carry a token object, got {sorted(payload)}"
            assert isinstance(payload["access_token"], str), f"access_token must be a string, got {type(payload['access_token'])}"
            assert payload["access_token"], "access_token must not be empty"
            assert token_id, f"token object must carry an id, got {sorted(token_obj)}"
            assert token_obj["name"] == name, f"Name mismatch: {token_obj['name']} != {name}"
            assert isinstance(payload.get("warnings", []), list), "warnings must be a list when present"
            print(f"    -> Minted token {token_id} ({len(payload['access_token'])} chars, warnings={payload.get('warnings')})")
        finally:
            ctx.dispose()
            if token_id:
                with suppress(Exception):
                    admin_api.delete(f"/tokens/admin/{token_id}")

    def test_created_token_in_list(self, token_lifecycle_user: dict, playwright: Playwright) -> None:
        """GET /tokens lists the caller's token by id and name.

        ``/tokens`` blocks the ``api_token`` auth method outright
        (``mcpgateway/routers/tokens.py`` ``_require_authenticated_session`` —
        Management Plane isolation against token-chaining). List with a fresh
        session-style JWT for the same user, not the minted access_token.
        """
        user_jwt = _make_jwt(token_lifecycle_user["email"], is_admin=True, teams=None)
        ctx = _api_context(playwright, user_jwt)
        try:
            resp = ctx.get("/tokens")
            assert resp.status == 200, f"GET /tokens failed: {resp.status} {resp.text()}"
            payload = resp.json()
            assert "tokens" in payload, f"TokenListResponse must carry a 'tokens' key, got {sorted(payload)}"
            by_id = {token["id"]: token for token in payload["tokens"]}
            assert token_lifecycle_user["token_id"] in by_id, f"Created token missing from catalog. Listed ids: {sorted(by_id)}"
            listed = by_id[token_lifecycle_user["token_id"]]
            assert listed["name"] == token_lifecycle_user["token_name"], f"Name mismatch: {listed['name']} != {token_lifecycle_user['token_name']}"
            print(f"    -> Catalog lists {listed['name']} (total={payload['total']})")
        finally:
            ctx.dispose()

    def test_token_authenticates_rest_endpoint(self, token_lifecycle_user: dict, playwright: Playwright) -> None:
        """The minted token authenticates a REST endpoint."""
        ctx = _api_context(playwright, token_lifecycle_user["access_token"])
        try:
            resp = ctx.get("/tools")
            assert resp.status == 200, f"GET /tools with a valid token must return 200: {resp.status} {resp.text()}"
            print(f"    -> REST auth accepted on GET /tools: {resp.status}")
        finally:
            ctx.dispose()

    def test_token_authenticates_mcp_endpoint(self, token_lifecycle_user: dict) -> None:
        """The minted token opens an MCP session."""
        assert _mcp_initialize_only(token_lifecycle_user["access_token"]), "MCP initialize must succeed with a valid token"
        print("    -> MCP initialize accepted the minted token")

    def test_expires_at_reflects_expires_in_days(self, token_lifecycle_user: dict, admin_api: APIRequestContext, playwright: Playwright) -> None:
        """A one-day token expires about 24 hours from now.

        List with a fresh session-style JWT, not the minted access_token —
        see ``test_created_token_in_list`` for why ``/tokens`` rejects it.
        """
        minted = _mint_token(playwright, token_lifecycle_user["email"], is_admin=True, expires_in_days=1)
        user_jwt = _make_jwt(token_lifecycle_user["email"], is_admin=True, teams=None)
        ctx = _api_context(playwright, user_jwt)
        try:
            resp = ctx.get("/tokens")
            assert resp.status == 200, f"GET /tokens failed: {resp.status} {resp.text()}"
            by_id = {token["id"]: token for token in resp.json()["tokens"]}
            assert minted["token_id"] in by_id, f"Minted token missing from catalog. Listed ids: {sorted(by_id)}"
            raw = by_id[minted["token_id"]]["expires_at"]
            assert raw, "expires_in_days=1 must produce a non-null expires_at"

            expires_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            expected = datetime.now(timezone.utc) + timedelta(days=1)
            drift = abs((expires_at - expected).total_seconds())
            assert drift <= 120, f"expires_at {expires_at.isoformat()} drifts {drift:.0f}s from now+24h"
            print(f"    -> expires_at {expires_at.isoformat()} ({drift:.0f}s drift)")
        finally:
            ctx.dispose()
            with suppress(Exception):
                admin_api.delete(f"/tokens/admin/{minted['token_id']}")

    def test_revoke_token_denies_rest(self, token_lifecycle_user: dict, admin_api: APIRequestContext, playwright: Playwright) -> None:
        """A revoked token is rejected on the REST API."""
        minted = _mint_token(playwright, token_lifecycle_user["email"], is_admin=True)
        ctx = _api_context(playwright, minted["access_token"])
        try:
            before = ctx.get("/tools")
            assert before.status == 200, f"Token must work before revocation: {before.status} {before.text()}"

            revoke = admin_api.delete(f"/tokens/admin/{minted['token_id']}")
            assert revoke.status == 204, f"Revoke must return 204: {revoke.status} {revoke.text()}"
            time.sleep(_REVOCATION_PROPAGATION_SECONDS)

            after = ctx.get("/tools")
            assert after.status == 401, f"Revoked token must be rejected with 401, got {after.status}: {after.text()}"
            print(f"    -> Revoked token rejected on REST: {after.status}")
        finally:
            ctx.dispose()
            with suppress(Exception):
                admin_api.delete(f"/tokens/admin/{minted['token_id']}")

    def test_revoke_token_denies_mcp(self, token_lifecycle_user: dict, admin_api: APIRequestContext, playwright: Playwright) -> None:
        """A revoked token cannot open an MCP session."""
        minted = _mint_token(playwright, token_lifecycle_user["email"], is_admin=True)
        try:
            assert _mcp_initialize_only(minted["access_token"]), "Token must work before revocation"

            revoke = admin_api.delete(f"/tokens/admin/{minted['token_id']}")
            assert revoke.status == 204, f"Revoke must return 204: {revoke.status} {revoke.text()}"
            time.sleep(_REVOCATION_PROPAGATION_SECONDS)

            # A revoked token fails the JWT auth dependency before any MCP method
            # dispatch, so the SDK surfaces it as a raw httpx.HTTPStatusError from
            # the initialize POST -- wrapped in one or more ExceptionGroup layers
            # because the SDK runs that POST inside anyio TaskGroups (see
            # _unwrap_exception_group). Narrowed to these two types and to status
            # 401 so an unrelated transport failure (a restart, a timeout) cannot
            # read as "revocation confirmed".
            with pytest.raises((httpx.HTTPStatusError, ExceptionGroup)) as excinfo:
                _mcp_initialize_only(minted["access_token"])
            status_errors = [e for e in _unwrap_exception_group(excinfo.value) if isinstance(e, httpx.HTTPStatusError)]
            assert status_errors and status_errors[0].response.status_code == 401, f"expected a 401 from the revoked token, got: {excinfo.value!r}"
            print(f"    -> Revoked token rejected on MCP (expected): {status_errors[0]}")
        finally:
            with suppress(Exception):
                admin_api.delete(f"/tokens/admin/{minted['token_id']}")

    def test_scoped_token_denied_tool_execute(self, token_lifecycle_user: dict, admin_api: APIRequestContext, playwright: Playwright, streamable_http_gateway: dict) -> None:
        """A token scoped to tools.read cannot execute a tool.

        Token generation auto-injects ``servers.use`` for MCP-method
        permissions, so the token reaches the transport. ``token_scope_grants``
        then denies ``tools.execute`` at the JSON-RPC layer.
        """
        minted = _mint_token(
            playwright,
            token_lifecycle_user["email"],
            is_admin=True,
            scope={"permissions": ["tools.read"]},
        )
        try:
            tools = _mcp_tools_list(minted["access_token"])
            assert tools, "tools.read must still list tools"
            assert any(t.name == f"{STREAMABLE_HTTP_GATEWAY_NAME}-get-system-time" for t in tools), f"target tool missing from tools/list: {[t.name for t in tools]}"

            # The except clause lists transport errors only. Catching bare Exception
            # here would swallow the AssertionError below and the test could never fail.
            # ExceptionGroup is included because the SDK's ClientSession runs call_tool()
            # inside an anyio TaskGroup, which wraps a single McpError in an ExceptionGroup
            # on the way out. This is still safe: the assert below sits outside this try,
            # so widening the tuple here cannot swallow it.
            #
            # The inner assert checks *why* the call failed, not just that it did: an
            # unrelated transport hiccup (a restart, a timeout) would otherwise also
            # land in this except and print as "(expected)". "Access denied" is
            # _ACCESS_DENIED_MSG in mcpgateway/middleware/rbac.py, the fixed message
            # _ensure_rpc_permission() raises via JSONRPCError(-32003, ...) on a
            # token_scope_grants() denial -- the one thing this except is meant to catch.
            # _unwrap_exception_group handles the nesting depth varying by call shape
            # (a preceding tools/list on the same session adds a task-group layer).
            result = None
            try:
                result = _mcp_tool_call(minted["access_token"], f"{STREAMABLE_HTTP_GATEWAY_NAME}-get-system-time", {"timezone": "UTC"})
            except (McpError, httpx.HTTPError, RuntimeError, TimeoutError, ExceptionGroup) as exc:
                leaves = _unwrap_exception_group(exc)
                assert any("access denied" in str(leaf).lower() for leaf in leaves), f"expected an access-denial error, got: {leaves!r}"
                print(f"    -> Scoped token denied execute at the transport (expected): {leaves[0]}")

            if result is not None:
                assert result.isError, f"tools.read-only token must be denied tools.execute, got: {result}"
                print(f"    -> Scoped token denied execute (expected): {result.content[0].text}")
        finally:
            with suppress(Exception):
                admin_api.delete(f"/tokens/admin/{minted['token_id']}")


# ---------------------------------------------------------------------------
# Test: Cross-transport consistency
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestCrossTransportConsistency:
    """Same tool produces consistent results across different Streamable HTTP gateways."""

    def test_get_system_time_both_transports(self, test_users: dict) -> None:
        """Multiple gateway instances return valid timestamps for get-system-time."""
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        time_tools = [t.name for t in tools if "get-system-time" in t.name]
        assert len(time_tools) >= 1, f"Expected at least 1 get-system-time tool, got: {time_tools}"

        for tool_name in time_tools[:2]:  # Test up to 2 variants
            result = _mcp_tool_call(test_users["admin"]["access_token"], tool_name, {"timezone": "UTC"})
            assert not result.isError, f"{tool_name} failed: {result}"
            text = result.content[0].text
            assert len(text) > 0, f"{tool_name} returned empty text"
            print(f"    -> {tool_name} = {text}")

    def test_convert_time_both_transports(self, test_users: dict) -> None:
        """Both transports return valid results for convert-time."""
        tools = _mcp_tools_list(test_users["admin"]["access_token"])
        convert_tools = [t.name for t in tools if "convert-time" in t.name]
        assert len(convert_tools) >= 1, f"Expected at least 1 convert-time tool, got: {convert_tools}"

        for tool_name in convert_tools[:2]:
            result = _mcp_tool_call(
                test_users["admin"]["access_token"],
                tool_name,
                {"time": "2025-01-15T12:00:00Z", "source_timezone": "UTC", "target_timezone": "America/New_York"},
            )
            assert not result.isError, f"{tool_name} failed: {result}"
            text = result.content[0].text
            assert len(text) > 0, f"{tool_name} returned empty text"
            print(f"    -> {tool_name} = {text}")


# ---------------------------------------------------------------------------
# Virtual server lifecycle (#6519)
# ---------------------------------------------------------------------------
LIFECYCLE_PREFIX = "e2e-lifecycle"
# Distinct from _PER_SERVER_ACCESS_SYNC_DEADLINE_SECONDS above: that one retries
# only on exceptions, this one also retries while the catalog contents converge.
_LIFECYCLE_CONVERGENCE_DEADLINE = float(os.getenv("MCP_E2E_CONVERGENCE_DEADLINE", "30.0"))
_LIFECYCLE_MAX_PAGES = 50


def _json_or_fail(resp: APIResponse, call: str) -> Any:
    """Decode a JSON body, or fail with the status and body.

    Args:
        resp: Response to decode.
        call: Endpoint description for the failure message.

    Returns:
        The decoded JSON body.

    Raises:
        AssertionError: The body is not JSON.
    """
    try:
        return resp.json()
    except Exception as exc:  # pylint: disable=broad-except
        raise AssertionError(f"{call}: response is not JSON (HTTP {resp.status}): {resp.text()[:500]}") from exc


def _list_all_servers(admin_api: APIRequestContext) -> list[dict[str, Any]]:
    """Return every visible server. Follow the cursor to the last page.

    ``GET /servers`` applies a default page size. An unpaginated read drops a
    new server on a busy stack.

    Args:
        admin_api: Authenticated admin API context.

    Returns:
        All server records the caller can see.
    """
    servers: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(_LIFECYCLE_MAX_PAGES):
        params: dict[str, Any] = {"include_pagination": "true"}
        if cursor:
            params["cursor"] = cursor
        resp = admin_api.get("/servers", params=params)
        assert resp.status == 200, f"GET /servers returned {resp.status}: {resp.text()[:500]}"
        body = _json_or_fail(resp, "GET /servers")
        if isinstance(body, list):
            return body
        servers.extend(body.get("servers") or [])
        cursor = body.get("nextCursor")
        if not cursor:
            break
    return servers


def _audience_excludes_model(tool: dict[str, Any]) -> bool:
    """Report whether a REST tool record hides the tool from the model.

    Apply the audience rule to the REST payload. Do not call the production
    filter: it reads this process's settings, which differ from the gateway's.
    Import the extension key only, so the two cannot drift apart.

    Args:
        tool: Tool record from the REST API.

    Returns:
        True when the tool declares an audience without ``model``.
    """
    metadata = tool.get("extensionMetadata") or tool.get("extension_metadata") or {}
    ui = metadata.get(MCP_UI_EXTENSION) if isinstance(metadata, dict) else None
    if not isinstance(ui, dict):
        return False
    audience = ui.get("visibility", ui.get("audience"))
    if audience is None:
        return False
    if isinstance(audience, str):
        audience = [audience]
    return "model" not in audience


def _names_when_ready(probe: Any, expected: set[str]) -> set[str]:
    """Poll ``probe`` until it returns ``expected``, or the deadline expires.

    Retry only while the catalog converges. A successful response with the
    wrong contents is not readiness.

    Args:
        probe: Callable that returns the observed names.
        expected: The names to converge on.

    Returns:
        The last observed names.
    """
    deadline = time.monotonic() + _LIFECYCLE_CONVERGENCE_DEADLINE
    observed: set[str] = set()
    while True:
        try:
            observed = probe()
            if observed == expected:
                return observed
        except (httpx.HTTPError, McpError, RuntimeError, TimeoutError):
            if time.monotonic() >= deadline:
                raise
        if time.monotonic() >= deadline:
            return observed
        time.sleep(_PER_SERVER_ACCESS_RETRY_DELAY_SECONDS)


def _server_mcp_base(server_id: str) -> str:
    """Return the MCP base URL for a virtual server.

    Args:
        server_id: Virtual server id.

    Returns:
        The base URL that the MCP helpers extend with ``/mcp/``.
    """
    return f"{BASE_URL}/servers/{server_id}"


class _OwnedObjects:
    """Ids one test created. Teardown deletes them.

    Membership is explicit. Teardown never selects an object by name prefix.
    """

    def __init__(self) -> None:
        """Create empty id registries."""
        self.server_ids: list[str] = []
        self.resource_ids: list[str] = []


def _register_id(registry: list[str], resp: APIResponse) -> None:
    """Record a created id before the test asserts the response contract.

    Parse failures stay silent here. The test raises its own assertion, and
    a usable id must still reach teardown.

    Args:
        registry: List that collects ids for deletion.
        resp: Creation response.
    """
    with suppress(Exception):
        body = resp.json()
        if isinstance(body, dict) and body.get("id"):
            registry.append(body["id"])


def _delete_owned(admin_api: APIRequestContext, path: str, object_id: str) -> str | None:
    """Delete one owned object. Report an unexpected outcome.

    Args:
        admin_api: Authenticated admin API context.
        path: Collection path, for example ``/servers``.
        object_id: Id to delete.

    Returns:
        None when the object is gone. Otherwise a failure description.
    """
    try:
        resp = admin_api.delete(f"{path}/{object_id}")
    except Exception as exc:  # pylint: disable=broad-except
        return f"DELETE {path}/{object_id} raised {type(exc).__name__}: {exc}"
    if resp.status in (200, 204, 404):
        return None
    return f"DELETE {path}/{object_id} returned {resp.status}: {resp.text()[:200]}"


@pytest.fixture(scope="module")
def admin_token() -> str:
    """Return an un-narrowed platform-admin JWT.

    The admin bypass needs ``is_admin=true`` and ``teams=null`` together. The
    post-delete 404 depends on it: RBAC checks ``servers.use`` before server
    existence, so a narrowed token gets 403.

    Returns:
        A signed admin JWT.
    """
    return _make_jwt("admin@example.com", is_admin=True, teams=None)


@pytest.fixture(scope="module")
def lifecycle_tools(admin_api: APIRequestContext, streamable_http_gateway: dict) -> list[dict[str, Any]]:
    """Return the gateway's enabled tools. Assert they are model-facing.

    Args:
        admin_api: Authenticated admin API context.
        streamable_http_gateway: The suite's registered gateway.

    Returns:
        Enabled tool records for that gateway.
    """
    gateway_id = streamable_http_gateway["id"]
    deadline = time.monotonic() + _PER_SERVER_ACCESS_SYNC_DEADLINE_SECONDS
    tools: list[dict[str, Any]] = []
    # Keep why the last poll returned nothing. A 401 or a 500 otherwise reads
    # as an empty catalog, and the timeout names the wrong repair.
    last_failure = ""
    while True:
        try:
            resp = admin_api.get("/tools")
            if resp.status == 200:
                catalog = resp.json()
                tools = [tool for tool in catalog if tool.get("gatewayId") == gateway_id and tool.get("enabled", True)]
            else:
                last_failure = f"last GET /tools returned HTTP {resp.status}: {resp.text()[:200]}"
        except Exception as exc:  # pylint: disable=broad-except
            last_failure = f"last GET /tools raised {type(exc).__name__}: {exc}"
        if tools or time.monotonic() >= deadline:
            break
        time.sleep(_PER_SERVER_ACCESS_RETRY_DELAY_SECONDS)

    detail = f"\n{last_failure}" if last_failure else ""
    assert tools, f"Gateway {STREAMABLE_HTTP_GATEWAY_NAME!r} (id={gateway_id}) reported no enabled tools within {_PER_SERVER_ACCESS_SYNC_DEADLINE_SECONDS:.0f}s.{detail}"

    hidden = sorted(tool.get("name", "?") for tool in tools if _audience_excludes_model(tool))
    assert not hidden, f"Tools {hidden} declare an audience without 'model'. The gateway omits them from tools/list, but REST still reports them."
    return tools


@pytest.fixture
def owned_objects(admin_api: APIRequestContext) -> Generator[_OwnedObjects, None, None]:
    """Track objects one test creates. Delete them all.

    Delete servers before resources, so no association outlives its parent.
    Attempt every deletion. Collect the failures. Fail teardown once.

    Args:
        admin_api: Authenticated admin API context.

    Yields:
        The registry the factories write to.
    """
    owned = _OwnedObjects()
    yield owned

    failures: list[str] = []
    for server_id in owned.server_ids:
        failure = _delete_owned(admin_api, "/servers", server_id)
        if failure:
            failures.append(failure)
    for resource_id in owned.resource_ids:
        failure = _delete_owned(admin_api, "/resources", resource_id)
        if failure:
            failures.append(failure)

    if failures:
        pytest.fail("Cleanup did not remove every owned object:\n  " + "\n  ".join(failures))


@pytest.fixture
def create_server(admin_api: APIRequestContext, owned_objects: _OwnedObjects) -> Any:
    """Return a factory that creates throwaway virtual servers.

    The factory returns the raw response. The creation test asserts the status
    and body itself.

    Args:
        admin_api: Authenticated admin API context.
        owned_objects: Registry that receives created ids.

    Returns:
        A callable that creates a virtual server.
    """

    def _create(*, tool_ids: list[str] | None = None, resource_ids: list[str] | None = None, name: str | None = None, visibility: str = "public") -> APIResponse:
        payload: dict[str, Any] = {
            "server": {
                "name": name or f"{LIFECYCLE_PREFIX}-srv-{uuid.uuid4().hex[:8]}",
                "description": "Virtual server lifecycle E2E fixture",
                "associated_tools": list(tool_ids or []),
                "associated_resources": list(resource_ids or []),
            },
            "visibility": visibility,
        }
        resp = admin_api.post("/servers", data=payload)
        _register_id(owned_objects.server_ids, resp)
        return resp

    return _create


@pytest.fixture
def create_resource(admin_api: APIRequestContext, owned_objects: _OwnedObjects) -> Any:
    """Return a factory that creates throwaway resources.

    The factory never sets ``uri_template``. ``list_server_resources`` filters
    ``uri_template IS NULL``, so a template resource disappears from the
    virtual server's catalog while REST still reports the association.

    Args:
        admin_api: Authenticated admin API context.
        owned_objects: Registry that receives created ids.

    Returns:
        A callable that creates a resource.
    """

    def _create(*, visibility: str = "public") -> APIResponse:
        uid = uuid.uuid4().hex[:8]
        payload: dict[str, Any] = {
            "resource": {
                "uri": f"test://{LIFECYCLE_PREFIX}/{uid}",
                "name": f"{LIFECYCLE_PREFIX}-res-{uid}",
                "description": "Virtual server lifecycle E2E fixture",
                "mimeType": "text/plain",
                "content": f"lifecycle fixture {uid}",
            },
            "visibility": visibility,
        }
        resp = admin_api.post("/resources", data=payload)
        _register_id(owned_objects.resource_ids, resp)
        return resp

    return _create


class TestVirtualServerLifecycle:
    """Create a virtual server, reach its catalog over MCP, then delete it."""

    def test_create_server_returns_id_and_name(self, create_server: Any, lifecycle_tools: list[dict[str, Any]]) -> None:
        """Creation returns 201 and echoes the requested identity and associations.

        Args:
            create_server: Factory that returns the raw creation response.
            lifecycle_tools: The gateway's enabled tools.
        """
        expected_ids = {tool["id"] for tool in lifecycle_tools}
        expected_names = {tool["name"] for tool in lifecycle_tools}

        name = f"{LIFECYCLE_PREFIX}-create-check"
        resp = create_server(tool_ids=sorted(expected_ids), name=name)

        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server = _json_or_fail(resp, "POST /servers")

        assert server.get("id"), f"created server has no id: {server}"
        assert server["name"] == name
        # The request sends tool ids. The response splits them: ids in
        # associatedToolIds, names in associatedTools.
        assert set(server["associatedToolIds"]) == expected_ids
        assert set(server["associatedTools"]) == expected_names

    def test_created_server_in_list(self, admin_api: APIRequestContext, create_server: Any, lifecycle_tools: list[dict[str, Any]]) -> None:
        """The list and the detail endpoint both report a created server.

        Args:
            admin_api: Authenticated admin API context.
            create_server: Factory that returns the raw creation response.
            lifecycle_tools: The gateway's enabled tools.
        """
        resp = create_server(tool_ids=[tool["id"] for tool in lifecycle_tools])
        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server_id = _json_or_fail(resp, "POST /servers")["id"]

        listed = {entry["id"] for entry in _list_all_servers(admin_api)}
        assert server_id in listed, f"server {server_id} is absent from GET /servers ({len(listed)} servers listed)"

        detail = admin_api.get(f"/servers/{server_id}")
        assert detail.status == 200, f"GET /servers/{server_id} returned {detail.status}: {detail.text()[:500]}"
        assert _json_or_fail(detail, f"GET /servers/{server_id}")["id"] == server_id

    def test_associated_tools_reachable_via_mcp(self, admin_api: APIRequestContext, create_server: Any, lifecycle_tools: list[dict[str, Any]], admin_token: str) -> None:
        """The per-server REST records and the MCP catalog both report the associated tools.

        Args:
            admin_api: Authenticated admin API context.
            create_server: Factory that returns the raw creation response.
            lifecycle_tools: The gateway's enabled tools.
            admin_token: Un-narrowed platform-admin JWT.
        """
        # Both expectations come from the gateway catalog. Deriving one view
        # from the other lets a correlated REST and MCP defect pass.
        assert len(lifecycle_tools) >= 2, "scoping check needs at least two tools on the gateway"

        # Hold one tool back. A server that served the global catalog instead of
        # its own would surface the held-back tool, and every assertion below
        # would otherwise pass on a stack whose whole catalog is this gateway's.
        held_back = lifecycle_tools[0]["name"]
        associated = lifecycle_tools[1:]
        expected_ids = {tool["id"] for tool in associated}
        expected_names = {tool["name"] for tool in associated}

        resp = create_server(tool_ids=sorted(expected_ids))
        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server_id = _json_or_fail(resp, "POST /servers")["id"]

        rest = admin_api.get(f"/servers/{server_id}/tools")
        assert rest.status == 200, f"GET /servers/{server_id}/tools returned {rest.status}: {rest.text()[:500]}"
        rest_tools = _json_or_fail(rest, f"GET /servers/{server_id}/tools")

        rest_ids = {tool["id"] for tool in rest_tools}
        rest_names = {tool["name"] for tool in rest_tools}
        assert rest_ids == expected_ids, f"per-server REST tool ids mismatch: missing={sorted(expected_ids - rest_ids)} unexpected={sorted(rest_ids - expected_ids)}"
        assert rest_names == expected_names, f"per-server REST tool names mismatch: missing={sorted(expected_names - rest_names)} unexpected={sorted(rest_names - expected_names)}"

        assert held_back not in rest_names, f"held-back tool {held_back} appears in the per-server REST listing"

        observed = _names_when_ready(lambda: {tool.name for tool in _mcp_tools_list(admin_token, server_url=_server_mcp_base(server_id))}, expected_names)
        assert observed == expected_names, f"MCP tools/list mismatch: missing={sorted(expected_names - observed)} unexpected={sorted(observed - expected_names)}"
        assert held_back not in observed, f"held-back tool {held_back} leaked into the scoped MCP catalog"

    def test_associated_resources_reachable_via_mcp(self, admin_api: APIRequestContext, create_server: Any, create_resource: Any, admin_token: str) -> None:
        """The per-server REST records and the MCP catalog both report the associated resource.

        Args:
            admin_api: Authenticated admin API context.
            create_server: Factory that returns the raw creation response.
            create_resource: Factory that returns the raw resource response.
            admin_token: Un-narrowed platform-admin JWT.
        """
        resource_resp = create_resource()
        assert resource_resp.status in (200, 201), f"POST /resources returned {resource_resp.status}: {resource_resp.text()[:500]}"
        resource = _json_or_fail(resource_resp, "POST /resources")

        # A second resource stays unassociated. Without it the assertions below
        # pass even when the endpoint serves the global catalog, because the
        # stack carries no other resources and the two sets coincide.
        unassociated_resp = create_resource()
        assert unassociated_resp.status in (200, 201), f"POST /resources returned {unassociated_resp.status}: {unassociated_resp.text()[:500]}"
        unassociated_uri = _json_or_fail(unassociated_resp, "POST /resources")["uri"]

        # The id and the URI both come from the creation response, so each view
        # is checked against the resource as created.
        expected_id = str(resource["id"])
        expected_uris = {resource["uri"]}

        resp = create_server(resource_ids=[expected_id])
        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server_id = _json_or_fail(resp, "POST /servers")["id"]

        rest = admin_api.get(f"/servers/{server_id}/resources")
        assert rest.status == 200, f"GET /servers/{server_id}/resources returned {rest.status}: {rest.text()[:500]}"
        rest_resources = _json_or_fail(rest, f"GET /servers/{server_id}/resources")

        rest_ids = {str(entry["id"]) for entry in rest_resources}
        rest_uris = {entry["uri"] for entry in rest_resources}
        assert rest_ids == {expected_id}, f"per-server REST resource ids mismatch: got {sorted(rest_ids)}, expected {[expected_id]}"
        assert rest_uris == expected_uris, f"per-server REST resource uris mismatch: got {sorted(rest_uris)}, expected {sorted(expected_uris)}"

        assert unassociated_uri not in rest_uris, f"unassociated resource {unassociated_uri} appears in the per-server REST listing"

        # MCP exposes resources by URI. The protocol carries no id.
        observed = _names_when_ready(lambda: {str(resource_record.uri) for resource_record in _mcp_resources_list(admin_token, server_url=_server_mcp_base(server_id))}, expected_uris)
        assert observed == expected_uris, f"MCP resources/list mismatch: missing={sorted(expected_uris - observed)} unexpected={sorted(observed - expected_uris)}"
        assert unassociated_uri not in observed, f"unassociated resource {unassociated_uri} leaked into the scoped MCP catalog"

    def test_delete_removes_from_list(self, admin_api: APIRequestContext, create_server: Any, lifecycle_tools: list[dict[str, Any]]) -> None:
        """Deletion removes the server from the list and from the detail endpoint.

        Args:
            admin_api: Authenticated admin API context.
            create_server: Factory that returns the raw creation response.
            lifecycle_tools: The gateway's enabled tools.
        """
        resp = create_server(tool_ids=[tool["id"] for tool in lifecycle_tools])
        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server_id = _json_or_fail(resp, "POST /servers")["id"]

        assert server_id in {entry["id"] for entry in _list_all_servers(admin_api)}, "server is absent from GET /servers before deletion"

        deleted = admin_api.delete(f"/servers/{server_id}")
        assert deleted.status == 200, f"DELETE /servers/{server_id} returned {deleted.status}: {deleted.text()[:500]}"
        assert _json_or_fail(deleted, f"DELETE /servers/{server_id}")["status"] == "success"

        assert server_id not in {entry["id"] for entry in _list_all_servers(admin_api)}, "server is still present in GET /servers after deletion"

        detail = admin_api.get(f"/servers/{server_id}")
        assert detail.status == 404, f"GET /servers/{server_id} returned {detail.status} after deletion. Expected 404."

    def test_deleted_server_denies_narrowed_token_before_existence(
        self,
        admin_api: APIRequestContext,
        playwright: Playwright,
        create_server: Any,
        lifecycle_tools: list[dict[str, Any]],
    ) -> None:
        """A narrowed token is refused before the gateway checks server existence.

        The RBAC check for ``servers.use`` runs ahead of ``_validate_server_id``,
        so a caller without that permission never learns whether the server
        exists. This pins the order that the admin-only 404 above depends on.

        Args:
            admin_api: Authenticated admin API context.
            playwright: Playwright entrypoint fixture.
            create_server: Factory that returns the raw creation response.
            lifecycle_tools: The gateway's enabled tools.
        """
        user = _create_user_with_token(admin_api, playwright, f"{LIFECYCLE_PREFIX}-deny-{uuid.uuid4().hex[:8]}@test.com")
        try:
            resp = create_server(tool_ids=[tool["id"] for tool in lifecycle_tools])
            assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
            server_id = _json_or_fail(resp, "POST /servers")["id"]

            deleted = admin_api.delete(f"/servers/{server_id}")
            assert deleted.status == 200, f"DELETE /servers/{server_id} returned {deleted.status}: {deleted.text()[:500]}"

            with httpx.Client(timeout=10.0) as client:
                probe = client.post(
                    f"{_server_mcp_base(server_id)}/mcp/",
                    headers={
                        "Authorization": f"Bearer {user['access_token']}",
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                    json=build_initialize(1),
                )

            assert probe.status_code == 403, f"narrowed token against a deleted server returned {probe.status_code}. Expected 403 from the servers.use check, not the 404 an admin sees: {probe.text[:300]}"
        finally:
            _cleanup_user(admin_api, user)

    def test_mcp_endpoint_gone_after_delete(self, admin_api: APIRequestContext, create_server: Any, lifecycle_tools: list[dict[str, Any]], admin_token: str) -> None:
        """The per-server MCP endpoint stops serving after deletion.

        The gateway checks server existence with an uncached lookup, after the
        delete commits. The 404 is immediate, so this check never retries. The
        status applies to the admin identity and the Python transport: RBAC
        checks ``servers.use`` first, so a narrowed token gets 403.

        Args:
            admin_api: Authenticated admin API context.
            create_server: Factory that returns the raw creation response.
            lifecycle_tools: The gateway's enabled tools.
            admin_token: Un-narrowed platform-admin JWT.
        """
        expected_names = {tool["name"] for tool in lifecycle_tools}
        resp = create_server(tool_ids=[tool["id"] for tool in lifecycle_tools])
        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server_id = _json_or_fail(resp, "POST /servers")["id"]

        observed = _names_when_ready(lambda: {tool.name for tool in _mcp_tools_list(admin_token, server_url=_server_mcp_base(server_id))}, expected_names)
        assert observed == expected_names, f"MCP endpoint does not serve the expected tools before deletion: {sorted(observed)}"

        deleted = admin_api.delete(f"/servers/{server_id}")
        assert deleted.status == 200, f"DELETE /servers/{server_id} returned {deleted.status}: {deleted.text()[:500]}"

        # A timeout or a connection error fails the test. An unreachable
        # gateway must not read as a removed endpoint.
        with httpx.Client(timeout=10.0) as client:
            probe = client.post(
                f"{_server_mcp_base(server_id)}/mcp/",
                headers={
                    "Authorization": f"Bearer {admin_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json=build_initialize(1),
            )

        assert probe.status_code == 404, f"initialize against the deleted server returned {probe.status_code}. Expected 404: {probe.text[:500]}"


# ---------------------------------------------------------------------------
# User lifecycle (#6520)
# ---------------------------------------------------------------------------
USER_PREFIX = "e2e-user"
# Special-use TLDs such as .local and .invalid are rejected by email-validator,
# so a test domain must be a normal one.
USER_DOMAIN = "test.com"
USER_PASSWORD = "E2eUser!9xQw2@Kp5z"  # pragma: allowlist secret


def _user_email() -> str:
    """Return a fresh test user address.

    Returns:
        An address in the suite's reserved namespace.
    """
    return f"{USER_PREFIX}-{uuid.uuid4().hex[:8]}@{USER_DOMAIN}"


def _list_all_users(admin_api: APIRequestContext) -> list[dict[str, Any]]:
    """Return every visible user.

    ``limit=0`` asks for the whole set, which the endpoint documents as "0 means
    all (no limit)". The default caps at ``pagination_default_page_size`` and
    this endpoint never emits ``nextCursor``, so a default read drops users
    with no signal that the list is short.

    Args:
        admin_api: Authenticated admin API context.

    Returns:
        All user records the caller can see.
    """
    resp = admin_api.get("/auth/email/admin/users", params={"limit": 0})
    assert resp.status == 200, f"GET /auth/email/admin/users returned {resp.status}: {resp.text()[:500]}"
    body = _json_or_fail(resp, "GET /auth/email/admin/users")
    assert isinstance(body, list), f"GET /auth/email/admin/users returned {type(body).__name__}, expected a list; the paginated shape appears only with include_pagination"
    return body


def _user_role_tuples(admin_api: APIRequestContext, email: str) -> set[tuple[str, str, str, str]]:
    """Return one user's role assignments as comparable tuples.

    Args:
        admin_api: Authenticated admin API context.
        email: Address to query.

    Returns:
        ``(user_email, role_id, scope, scope_id)`` for each assignment.
    """
    resp = admin_api.get(f"/rbac/users/{email}/roles")
    assert resp.status == 200, f"GET /rbac/users/{email}/roles returned {resp.status}: {resp.text()[:500]}"
    assignments = _json_or_fail(resp, f"GET /rbac/users/{email}/roles")
    # Every assignment must belong to the user queried. Without this the
    # control-user check below is vacuous: no user can hold a tuple that
    # carries a different user's address.
    owners = {assignment.get("user_email") for assignment in assignments}
    assert owners <= {email}, f"GET /rbac/users/{email}/roles returned assignments for {sorted(owners - {email})}"
    return {(assignment["user_email"], assignment["role_id"], assignment.get("scope"), assignment.get("scope_id")) for assignment in assignments}


class _OwnedUsers:
    """Accounts this test created, and the assignments made to them.

    Membership is explicit. A failed creation never registers ownership: a 409
    means the account already existed, and deleting it would destroy an account
    the test did not create.
    """

    def __init__(self) -> None:
        """Initialise empty registries."""
        self.emails: list[str] = []
        self.role_assignments: list[tuple[str, str, str]] = []
        self.team_memberships: list[tuple[str, str]] = []


@pytest.fixture
def owned_users(admin_api: APIRequestContext) -> Generator[_OwnedUsers, None, None]:
    """Track accounts one test creates, delete them, and prove they are gone.

    Deleting a user also removes that user's role assignments and team
    memberships, so no separate revocation step runs here. Teardown verifies
    the removals rather than assuming them, and reports every failure together.

    Only a test that requested the module-scoped team can record a membership,
    and a module-scoped fixture outlives every function-scoped teardown, so the
    team is still present when the verification below runs. A team that had
    already gone would answer 404, which is not evidence that a membership was
    cleaned up, so the check treats only a readable member list as proof.

    Args:
        admin_api: Authenticated admin API context.

    Yields:
        The registry the factory writes to.
    """
    owned = _OwnedUsers()
    yield owned

    failures: list[str] = []

    for email in owned.emails:
        try:
            resp = admin_api.delete(f"/auth/email/admin/users/{email}")
        except Exception as exc:  # pylint: disable=broad-except
            failures.append(f"DELETE /auth/email/admin/users/{email} raised {type(exc).__name__}: {exc}")
            continue
        # 404 covers the account test_delete_user_removes_from_list removed.
        if resp.status not in (200, 204, 404):
            failures.append(f"DELETE /auth/email/admin/users/{email} returned {resp.status}: {resp.text()[:200]}")

    if owned.emails:
        with suppress(Exception):
            remaining = {user.get("email") for user in _list_all_users(admin_api)}
            leaked = sorted(set(owned.emails) & remaining)
            if leaked:
                failures.append(f"users still present after cleanup: {leaked}")

    for email, role_id, scope_id in owned.role_assignments:
        with suppress(Exception):
            if (email, role_id, "team", scope_id) in _user_role_tuples(admin_api, email):
                failures.append(f"role assignment {role_id} on {email} survived cleanup")

    for email, team_id in owned.team_memberships:
        with suppress(Exception):
            members = admin_api.get(f"/teams/{team_id}/members")
            # A missing team proves nothing about the membership, so only a
            # readable member list counts as verification.
            if members.status == 200 and email in {member.get("user_email") for member in members.json()}:
                failures.append(f"team membership for {email} on {team_id} survived cleanup")

    if failures:
        pytest.fail("User cleanup did not complete:\n  " + "\n  ".join(failures))


@pytest.fixture
def create_user(admin_api: APIRequestContext, owned_users: _OwnedUsers) -> Any:
    """Return a factory that creates throwaway accounts.

    The factory generates the address, so it hands back the request inputs
    alongside the response. Tests assert against what was sent rather than
    against what the reply echoes.

    Args:
        admin_api: Authenticated admin API context.
        owned_users: Registry that receives created addresses.

    Returns:
        A callable returning ``(email, payload, response)``.
    """

    def _create(*, email: str | None = None, full_name: str = "E2E User", is_admin: bool = False, is_active: bool = True) -> tuple[str, dict[str, Any], APIResponse]:
        address = email or _user_email()
        payload: dict[str, Any] = {
            "email": address,
            "password": USER_PASSWORD,
            "full_name": full_name,
            "is_admin": is_admin,
            "is_active": is_active,
        }
        resp = admin_api.post("/auth/email/admin/users", data=payload)
        # Register on the status alone, before reading the body: the address is
        # already known, so a malformed response cannot leak a created account.
        if resp.status in (200, 201) and address not in owned_users.emails:
            owned_users.emails.append(address)
        return address, payload, resp

    return _create


class TestUserLifecycle:
    """Admin creates a user, assigns an RBAC role, then deletes the user."""

    def test_create_user_returns_expected_fields(self, create_user: Any) -> None:
        """Creation returns 201 and echoes the requested account.

        Args:
            create_user: Factory returning ``(email, payload, response)``.
        """
        email, payload, resp = create_user(full_name="Lifecycle Create Check")

        assert resp.status == 201, f"POST /auth/email/admin/users returned {resp.status}: {resp.text()[:500]}"
        user = _json_or_fail(resp, "POST /auth/email/admin/users")

        # Expectations come from the request, never from the response echo.
        assert user["email"] == email
        assert user["full_name"] == payload["full_name"]
        assert user["is_active"] is True
        assert user["is_admin"] is False

    def test_created_user_in_list(self, admin_api: APIRequestContext, create_user: Any) -> None:
        """Created accounts appear in the listing.

        Several accounts are created so the assertion covers more than a single
        row, and the read asks for the whole set rather than the capped default.

        Args:
            admin_api: Authenticated admin API context.
            create_user: Factory returning ``(email, payload, response)``.
        """
        created: list[str] = []
        for _ in range(3):
            email, _payload, resp = create_user()
            assert resp.status == 201, f"POST /auth/email/admin/users returned {resp.status}: {resp.text()[:500]}"
            created.append(email)

        listed = {user.get("email") for user in _list_all_users(admin_api)}
        missing = sorted(set(created) - listed)
        assert not missing, f"created users absent from GET /auth/email/admin/users: {missing}"

    def test_assign_rbac_role_to_user(self, admin_api: APIRequestContext, create_user: Any, owned_users: _OwnedUsers, rbac_team: dict) -> None:
        """A team-scoped role reaches the target user and no one else.

        Team membership is set up here because the role is team-scoped. Managing
        membership is #6522 and is not under test.

        Args:
            admin_api: Authenticated admin API context.
            create_user: Factory returning ``(email, payload, response)``.
            owned_users: Registry recording the assignment for cleanup checks.
            rbac_team: The team the role is scoped to.
        """
        team_id = rbac_team["id"]
        role_id = _resolve_role_id(admin_api, "developer")

        target, _payload, resp = create_user()
        assert resp.status == 201, f"POST /auth/email/admin/users returned {resp.status}: {resp.text()[:500]}"
        control, _control_payload, control_resp = create_user()
        assert control_resp.status == 201, f"POST /auth/email/admin/users returned {control_resp.status}: {control_resp.text()[:500]}"

        member = admin_api.post(f"/teams/{team_id}/members", data={"email": target, "role": "member"})
        assert member.status in (200, 201), f"POST /teams/{team_id}/members returned {member.status}: {member.text()[:500]}"
        owned_users.team_memberships.append((target, team_id))

        expected = (target, role_id, "team", team_id)
        assert expected not in _user_role_tuples(admin_api, target), f"{target} already holds {role_id} on {team_id} before assignment"

        assigned = admin_api.post(f"/rbac/users/{target}/roles", data={"role_id": role_id, "scope": "team", "scope_id": team_id})
        assert assigned.status in (200, 201), f"POST /rbac/users/{target}/roles returned {assigned.status}: {assigned.text()[:500]}"
        owned_users.role_assignments.append((target, role_id, team_id))

        body = _json_or_fail(assigned, f"POST /rbac/users/{target}/roles")
        assert body["user_email"] == target
        assert body["role_id"] == role_id
        assert body.get("scope") == "team"
        assert body.get("scope_id") == team_id

        assert expected in _user_role_tuples(admin_api, target), f"{target} does not hold {role_id} on {team_id} after assignment"
        assert (control, role_id, "team", team_id) not in _user_role_tuples(admin_api, control), f"control user {control} holds an assignment it was never given"

    def test_duplicate_create_returns_409(self, create_user: Any) -> None:
        """Creating the same address twice is refused.

        The second call reuses the address the first call registered, so it adds
        no second ownership entry.

        Args:
            create_user: Factory returning ``(email, payload, response)``.
        """
        email, _payload, first = create_user()
        assert first.status == 201, f"POST /auth/email/admin/users returned {first.status}: {first.text()[:500]}"

        _email, _payload2, duplicate = create_user(email=email)
        assert duplicate.status == 409, f"duplicate POST returned {duplicate.status}, expected 409: {duplicate.text()[:500]}"

    def test_delete_user_removes_from_list(self, admin_api: APIRequestContext, create_user: Any) -> None:
        """Deletion removes the account from the listing.

        Args:
            admin_api: Authenticated admin API context.
            create_user: Factory returning ``(email, payload, response)``.
        """
        email, _payload, resp = create_user()
        assert resp.status == 201, f"POST /auth/email/admin/users returned {resp.status}: {resp.text()[:500]}"

        assert email in {user.get("email") for user in _list_all_users(admin_api)}, f"{email} is absent from the listing before deletion"

        deleted = admin_api.delete(f"/auth/email/admin/users/{email}")
        assert deleted.status in (200, 204), f"DELETE /auth/email/admin/users/{email} returned {deleted.status}: {deleted.text()[:500]}"

        assert email not in {user.get("email") for user in _list_all_users(admin_api)}, f"{email} is still present in the listing after deletion"


# ---------------------------------------------------------------------------
# Test: Cross-replica consistency
# ---------------------------------------------------------------------------
class TestCrossReplicaConsistency:
    """Writes through Nginx are visible across the three default gateway replicas.

    Ten independent reads have a roughly 99.9949% probability of reaching at
    least two replicas when Nginx distributes requests uniformly.
    """

    N_READS = 10

    def test_tool_visible_across_replicas(self, admin_api: APIRequestContext, streamable_http_gateway: dict[str, Any]) -> None:
        """Every replica probe sees at least one synchronized tool for the new gateway."""
        gateway_id = streamable_http_gateway["id"]

        for read_index in range(1, self.N_READS + 1):
            tools = _get_gateway_tools(admin_api, gateway_id, f"tool-visible-{uuid.uuid4().hex}", read_index)
            assert tools, f"Replica read {read_index} did not return tools for gateway {gateway_id}"
            assert all(tool.get("gatewayId") == gateway_id for tool in tools), f"Replica read {read_index} returned a tool for another gateway"

    def test_token_authenticates_across_replicas(self, playwright: Playwright, cross_replica_user: dict[str, Any], streamable_http_gateway: dict[str, Any]) -> None:
        """A token minted through Nginx authenticates every subsequent replica probe."""
        gateway_id = streamable_http_gateway["id"]
        user_api = _api_context(playwright, cross_replica_user["access_token"])
        try:
            for read_index in range(1, self.N_READS + 1):
                response = user_api.get(_replica_tools_path(gateway_id, f"token-auth-{uuid.uuid4().hex}"))
                _assert_replica_response(response, read_index)
        finally:
            user_api.dispose()

    def test_user_visible_across_replicas(self, admin_api: APIRequestContext, cross_replica_user: dict[str, Any]) -> None:
        """A user created through Nginx appears in every subsequent admin listing."""
        email = cross_replica_user["email"]

        for read_index in range(1, self.N_READS + 1):
            response = admin_api.get(f"/auth/email/admin/users?limit=0&replica_probe=user-visible-{uuid.uuid4().hex}")
            users = _assert_replica_response(response, read_index)
            assert any(user.get("email") == email for user in users), f"Replica read {read_index} did not return user {email}"

    def test_gateway_tools_consistent_across_replicas(self, admin_api: APIRequestContext, streamable_http_gateway: dict[str, Any]) -> None:
        """Every replica returns the same stable tool catalog and gateway ID."""
        gateway_id = streamable_http_gateway["id"]
        expected_tool_ids = streamable_http_gateway["tool_ids"]
        assert expected_tool_ids, "Gateway fixture did not capture a stable, non-empty tool catalog"

        for read_index in range(1, self.N_READS + 1):
            tools = _get_gateway_tools(admin_api, gateway_id, f"catalog-consistency-{uuid.uuid4().hex}", read_index)
            assert all(tool.get("gatewayId") == gateway_id for tool in tools), f"Replica read {read_index} returned a tool for another gateway"
            actual_tool_ids = frozenset(str(tool["id"]) for tool in tools)
            assert actual_tool_ids == expected_tool_ids, f"Replica read {read_index} returned tool IDs {sorted(actual_tool_ids)}, expected {sorted(expected_tool_ids)}"
            assert len(tools) == len(expected_tool_ids), f"Replica read {read_index} returned duplicate tools for gateway {gateway_id}"


# ---------------------------------------------------------------------------
# Team lifecycle
# ---------------------------------------------------------------------------

TEAM_PREFIX = "e2e-team"

# Two teams per page over five teams forces at least three pages.
_TEAM_PAGE_SIZE = 2
_TEAM_PAGE_COUNT = 5


def _team_name(run_prefix: str | None = None) -> str:
    """Return a fresh team name inside the suite's namespace.

    Args:
        run_prefix: Prefix that isolates one test's teams. Defaults to the
            suite prefix.

    Returns:
        A name no other run reuses.
    """
    return f"{run_prefix or TEAM_PREFIX}-{uuid.uuid4().hex[:8]}"


def _team_pages(admin_api: APIRequestContext, search_query: str, limit: int | None = None) -> list[list[dict[str, Any]]]:
    """Return each page of the teams matching ``search_query``, in order.

    ``GET /teams/`` applies a default page size, so an unpaginated read drops
    teams on a busy stack. The traversal rejects a repeated cursor, which would
    otherwise loop until the page budget runs out.

    Args:
        admin_api: Authenticated admin API context.
        search_query: Substring the gateway matches on name, slug, or description.
        limit: Page size. Defaults to the gateway's own default.

    Returns:
        One list of team records per page.

    Raises:
        AssertionError: A page failed, a cursor repeated, or the pages ran past
            the budget.
    """
    pages: list[list[dict[str, Any]]] = []
    seen_cursors: set[str] = set()
    cursor: str | None = None

    for _ in range(_LIFECYCLE_MAX_PAGES):
        params: dict[str, Any] = {"include_pagination": "true", "search_query": search_query}
        if limit is not None:
            params["limit"] = limit
        if cursor:
            params["cursor"] = cursor

        resp = admin_api.get("/teams/", params=params)
        assert resp.status == 200, f"GET /teams/ returned {resp.status}: {resp.text()[:500]}"
        body = _json_or_fail(resp, "GET /teams/")
        pages.append(body.get("teams") or [])

        cursor = body.get("nextCursor")
        if not cursor:
            return pages
        assert cursor not in seen_cursors, f"GET /teams/ repeated cursor {cursor!r}; the traversal does not advance"
        seen_cursors.add(cursor)

    raise AssertionError(f"GET /teams/ did not finish within {_LIFECYCLE_MAX_PAGES} pages for search_query={search_query!r}")


def _teams_matching(admin_api: APIRequestContext, search_query: str) -> list[dict[str, Any]]:
    """Return every team matching ``search_query`` across all pages.

    Args:
        admin_api: Authenticated admin API context.
        search_query: Substring the gateway matches on name, slug, or description.

    Returns:
        Every matching team record.
    """
    return [team for page in _team_pages(admin_api, search_query) for team in page]


def _team_by_id(teams: list[dict[str, Any]], team_id: str) -> dict[str, Any] | None:
    """Return one team record from a listing.

    Args:
        teams: Records from ``GET /teams/``.
        team_id: Id to find.

    Returns:
        The matching record, or ``None``.
    """
    return next((team for team in teams if team.get("id") == team_id), None)


def _member(members: list[dict[str, Any]], email: str) -> dict[str, Any] | None:
    """Return one member record from a team member list.

    Args:
        members: Records from ``GET /teams/{id}/members``.
        email: Address to find.

    Returns:
        The matching record, or ``None``.
    """
    return next((member for member in members if member.get("user_email") == email), None)


def _team_members(admin_api: APIRequestContext, team_id: str) -> list[dict[str, Any]]:
    """Return one team's members.

    Args:
        admin_api: Authenticated admin API context.
        team_id: Team to read.

    Returns:
        The member records.
    """
    resp = admin_api.get(f"/teams/{team_id}/members")
    assert resp.status == 200, f"GET /teams/{team_id}/members returned {resp.status}: {resp.text()[:500]}"
    return _json_or_fail(resp, f"GET /teams/{team_id}/members")


def _created_team(create_team: Any, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a team, and fail unless the gateway accepted it.

    Args:
        create_team: Factory returning ``(payload, response, body)``.
        **kwargs: Forwarded to the factory.

    Returns:
        The request payload and the created team.
    """
    payload, resp, team = create_team(**kwargs)
    assert resp.status == 201, f"POST /teams/ returned {resp.status}: {resp.text()[:500]}"
    return payload, team


class _OwnedTeams:
    """Teams this test created.

    A team is registered only after a successful create returns a usable id, so
    teardown never deletes a team the test did not make.
    """

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self.ids: list[str] = []


@pytest.fixture
def owned_teams(admin_api: APIRequestContext, owned_users: _OwnedUsers) -> Generator[_OwnedTeams, None, None]:
    """Track teams one test creates, delete them, and prove they are gone.

    This fixture requests ``owned_users`` to order the two teardowns. Pytest
    finalises in reverse setup order, so ``owned_users`` is set up first and
    runs last, and every team is deleted before the accounts that belong to it.

    Teardown continues past a failure. One unreachable team must not strand the
    rest, so transport errors and unexpected statuses are collected and reported
    together at the end.

    Args:
        admin_api: Authenticated admin API context.
        owned_users: Account registry this teardown must precede.

    Yields:
        The registry the factory writes to.
    """
    del owned_users  # Requested for teardown order only.

    owned = _OwnedTeams()
    yield owned

    failures: list[str] = []

    for team_id in reversed(owned.ids):
        try:
            resp = admin_api.delete(f"/teams/{team_id}")
        except Exception as exc:  # pylint: disable=broad-except
            failures.append(f"DELETE /teams/{team_id} raised {type(exc).__name__}: {exc}")
            continue
        # 404 covers a team the test deleted itself. A 403 is unexpected here:
        # no test drops the creator's own membership, so one signals a real
        # authorization change and must fail.
        if resp.status not in (200, 204, 404):
            failures.append(f"DELETE /teams/{team_id} returned {resp.status}: {resp.text()[:200]}")

    if owned.ids:
        try:
            remaining = {team.get("id") for team in _teams_matching(admin_api, TEAM_PREFIX)}
        except Exception as exc:  # pylint: disable=broad-except
            failures.append(f"listing teams after cleanup raised {type(exc).__name__}: {exc}")
        else:
            leaked = sorted(set(owned.ids) & remaining)
            if leaked:
                failures.append(f"teams still present after cleanup: {leaked}")

    if failures:
        pytest.fail("Team cleanup did not complete:\n  " + "\n  ".join(failures))


@pytest.fixture
def create_team(admin_api: APIRequestContext, owned_teams: _OwnedTeams) -> Any:
    """Return a factory that creates throwaway teams.

    The factory registers the new id before it returns, so a later failed
    assertion still leaves the team tracked for teardown. It hands back the
    request inputs, so tests assert against what was sent.

    Args:
        admin_api: Authenticated admin API context.
        owned_teams: Registry that receives created ids.

    Returns:
        A callable returning ``(payload, response, body)``.
    """

    def _create(*, name: str | None = None, visibility: str = "private", description: str = "E2E team lifecycle") -> tuple[dict[str, Any], APIResponse, Any]:
        payload: dict[str, Any] = {"name": name or _team_name(), "visibility": visibility, "description": description}
        resp = admin_api.post("/teams/", data=payload)

        body: Any = None
        if resp.status in (200, 201):
            body = _json_or_fail(resp, "POST /teams/")
            team_id = body.get("id") if isinstance(body, dict) else None
            assert team_id, f"POST /teams/ returned {resp.status} without a usable id: {resp.text()[:500]}"
            if team_id not in owned_teams.ids:
                owned_teams.ids.append(team_id)

        return payload, resp, body

    return _create


class TestTeamLifecycle:
    """Admin creates a team, manages its members, then deletes the team."""

    def test_create_team_returns_expected_fields(self, create_team: Any) -> None:
        """Creation returns 201 and echoes the requested team.

        Args:
            create_team: Factory returning ``(payload, response, body)``.
        """
        payload, resp, team = create_team(visibility="private")

        assert resp.status == 201, f"POST /teams/ returned {resp.status}: {resp.text()[:500]}"
        # Expectations come from the request, never from the response echo.
        assert team["id"], "POST /teams/ returned an empty id"
        assert team["name"] == payload["name"]
        assert team["visibility"] == payload["visibility"]

    def test_create_team_makes_creator_an_owner(self, admin_api: APIRequestContext, create_team: Any) -> None:
        """The caller holds an active owner membership on a team it created.

        Args:
            admin_api: Authenticated admin API context.
            create_team: Factory returning ``(payload, response, body)``.
        """
        _payload, team = _created_team(create_team)

        owner = _member(_team_members(admin_api, team["id"]), ADMIN_EMAIL)
        assert owner is not None, f"{ADMIN_EMAIL} holds no membership on the team it created"
        assert owner["role"] == "owner", f"creator holds role {owner['role']!r}, expected 'owner'"
        assert owner["is_active"] is True, "creator's owner membership is not active"

    def test_team_appears_in_listing_and_detail(self, admin_api: APIRequestContext, create_team: Any) -> None:
        """A created team is visible in the listing and in its detail record.

        The listing read follows the cursor. A first-page-only read would miss
        the team on a stack that already holds a full page.

        Args:
            admin_api: Authenticated admin API context.
            create_team: Factory returning ``(payload, response, body)``.
        """
        payload, team = _created_team(create_team)

        listed = _team_by_id(_teams_matching(admin_api, payload["name"]), team["id"])
        assert listed is not None, f"team {team['id']} is absent from GET /teams/"

        detail = admin_api.get(f"/teams/{team['id']}")
        assert detail.status == 200, f"GET /teams/{team['id']} returned {detail.status}: {detail.text()[:500]}"
        body = _json_or_fail(detail, f"GET /teams/{team['id']}")

        assert body["name"] == payload["name"]
        assert body["visibility"] == payload["visibility"]
        assert body["slug"] == listed["slug"], "detail and listing disagree on the slug"

    def test_add_team_member(self, admin_api: APIRequestContext, create_team: Any, create_user: Any) -> None:
        """Adding a member returns 201 and the member list confirms it.

        The POST response is validated first. The member list is then read back
        so the record is confirmed independently of that echo.

        Args:
            admin_api: Authenticated admin API context.
            create_team: Factory returning ``(payload, response, body)``.
            create_user: Factory returning ``(email, payload, response)``.
        """
        _payload, team = _created_team(create_team)
        team_id = team["id"]

        email, _user_payload, created = create_user()
        assert created.status == 201, f"POST /auth/email/admin/users returned {created.status}: {created.text()[:500]}"

        added = admin_api.post(f"/teams/{team_id}/members", data={"email": email, "role": "member"})
        assert added.status == 201, f"POST /teams/{team_id}/members returned {added.status}: {added.text()[:500]}"

        added_body = _json_or_fail(added, f"POST /teams/{team_id}/members")
        assert added_body["user_email"] == email
        assert added_body["team_id"] == team_id
        assert added_body["role"] == "member"

        member = _member(_team_members(admin_api, team_id), email)
        assert member is not None, f"{email} is absent from the member list after POST returned 201"
        assert member["user_email"] == email
        assert member["team_id"] == team_id
        assert member["role"] == "member"
        assert member["is_active"] is True

    def test_remove_team_member(self, admin_api: APIRequestContext, create_team: Any, create_user: Any) -> None:
        """Removing a member leaves the creator's ownership intact.

        Args:
            admin_api: Authenticated admin API context.
            create_team: Factory returning ``(payload, response, body)``.
            create_user: Factory returning ``(email, payload, response)``.
        """
        _payload, team = _created_team(create_team)
        team_id = team["id"]

        email, _user_payload, created = create_user()
        assert created.status == 201, f"POST /auth/email/admin/users returned {created.status}: {created.text()[:500]}"

        added = admin_api.post(f"/teams/{team_id}/members", data={"email": email, "role": "member"})
        assert added.status == 201, f"POST /teams/{team_id}/members returned {added.status}: {added.text()[:500]}"
        assert _member(_team_members(admin_api, team_id), email) is not None, f"{email} is absent before removal"

        removed = admin_api.delete(f"/teams/{team_id}/members/{email}")
        assert removed.status == 200, f"DELETE /teams/{team_id}/members/{email} returned {removed.status}: {removed.text()[:500]}"

        members = _team_members(admin_api, team_id)
        assert _member(members, email) is None, f"{email} is still a member after removal"

        # Removing a member must not touch the creator. A lost owner membership
        # would also block the teardown delete.
        owner = _member(members, ADMIN_EMAIL)
        assert owner is not None, "the creator's membership disappeared when another member was removed"
        assert owner["role"] == "owner", f"creator holds role {owner['role']!r} after the removal, expected 'owner'"
        assert owner["is_active"] is True, "creator's owner membership is inactive after the removal"

    def test_team_pagination_is_consistent(self, admin_api: APIRequestContext, create_team: Any) -> None:
        """Paging a known set of teams returns each one exactly once.

        The run prefix isolates this test's teams, so the assertion does not
        depend on the gateway's total team count.

        Args:
            admin_api: Authenticated admin API context.
            create_team: Factory returning ``(payload, response, body)``.
        """
        run_prefix = f"{TEAM_PREFIX}-page-{uuid.uuid4().hex[:8]}"
        created: set[str] = set()
        for _ in range(_TEAM_PAGE_COUNT):
            _payload, team = _created_team(create_team, name=_team_name(run_prefix))
            created.add(team["id"])

        pages = _team_pages(admin_api, run_prefix, limit=_TEAM_PAGE_SIZE)

        assert len(pages) > 1, f"{_TEAM_PAGE_COUNT} teams at limit={_TEAM_PAGE_SIZE} returned {len(pages)} page(s); the traversal never paged"

        seen: list[str] = [team["id"] for page in pages for team in page]
        duplicates = sorted({team_id for team_id in seen if seen.count(team_id) > 1})
        assert not duplicates, f"teams returned on more than one page: {duplicates}"
        assert set(seen) == created, f"paging returned {sorted(set(seen))}, expected {sorted(created)}"

    def test_deleted_team_disappears(self, admin_api: APIRequestContext, create_team: Any) -> None:
        """Deletion removes the team from the listing and from detail reads.

        The gateway deletes a team softly, so the row survives in the database.
        These assertions cover the REST contract, which reports the team as
        gone.

        Args:
            admin_api: Authenticated admin API context.
            create_team: Factory returning ``(payload, response, body)``.
        """
        payload, team = _created_team(create_team)
        team_id = team["id"]

        assert _team_by_id(_teams_matching(admin_api, payload["name"]), team_id) is not None, f"team {team_id} is absent from the listing before deletion"

        deleted = admin_api.delete(f"/teams/{team_id}")
        assert deleted.status == 200, f"DELETE /teams/{team_id} returned {deleted.status}: {deleted.text()[:500]}"

        assert _team_by_id(_teams_matching(admin_api, payload["name"]), team_id) is None, f"team {team_id} is still listed after deletion"

        detail = admin_api.get(f"/teams/{team_id}")
        assert detail.status == 404, f"GET /teams/{team_id} returned {detail.status} after deletion, expected 404: {detail.text()[:500]}"

    def test_delete_nonexistent_team_returns_404(self, admin_api: APIRequestContext) -> None:
        """Deleting an unused team id is refused.

        The id is well formed, so the 404 reports a missing team rather than a
        rejected path.

        Args:
            admin_api: Authenticated admin API context.
        """
        unused = uuid.uuid4().hex

        resp = admin_api.delete(f"/teams/{unused}")
        assert resp.status == 404, f"DELETE /teams/{unused} returned {resp.status}, expected 404: {resp.text()[:500]}"
