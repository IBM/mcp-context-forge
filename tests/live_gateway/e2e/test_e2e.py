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
from collections.abc import AsyncIterator
import concurrent.futures
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
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
from playwright.sync_api import APIRequestContext, Playwright

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


# ---------------------------------------------------------------------------
# JWT helper (for admin bootstrap only — all test users use POST /tokens)
# ---------------------------------------------------------------------------
def _make_jwt(email: str, is_admin: bool = False, teams=None) -> str:
    return make_test_jwt(email, is_admin=is_admin, teams=teams, secret=_JWT_SECRET)


def _api_context(playwright: Playwright, token: str) -> APIRequestContext:
    return make_playwright_api_context(playwright, BASE_URL, token)


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

    Returns dict with: email, access_token, token_id, team_id, role.
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

    # 4. Create API token via POST /tokens (as the user, using admin JWT that impersonates)
    # We use a JWT for this user to create a self-owned token
    user_jwt = _make_jwt(email, is_admin=is_admin, teams=[team_id] if team_id else None)
    user_ctx = _api_context(playwright, user_jwt)
    token_name = f"{RBAC_PREFIX}-token-{uuid.uuid4().hex[:8]}"
    token_data: dict[str, Any] = {
        "name": token_name,
        "expires_in_days": 1,
    }
    if team_id:
        token_data["team_id"] = team_id
    if token_scope:
        token_data["scope"] = token_scope

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

    return {
        "email": email,
        "access_token": access_token,
        "token_id": token_id,
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
    """Register fast_time_server via Streamable HTTP transport and wait for tool sync."""
    streamable_http_url = "http://fast_time_server:9080/mcp"

    # Delete any pre-existing gateway with same name or same URL
    with suppress(Exception):
        gateways = admin_api.get("/gateways").json()
        for gw in gateways:
            if gw.get("name") == STREAMABLE_HTTP_GATEWAY_NAME or gw.get("url") == streamable_http_url:
                admin_api.delete(f"/gateways/{gw['id']}")

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

    # Poll for tool sync (up to 30s)
    for i in range(30):
        time.sleep(1)
        try:
            tools = admin_api.get("/tools").json()
            gateway_tools = [t for t in tools if t.get("gatewayId") == gw_id]
            if gateway_tools:
                logger.info("Streamable HTTP gateway synced: %d tools", len(gateway_tools))
                break
        except Exception:
            pass
    else:
        logger.warning("Streamable HTTP gateway tool sync timed out, continuing anyway")

    yield {"id": gw_id, "name": STREAMABLE_HTTP_GATEWAY_NAME}

    with suppress(Exception):
        admin_api.delete(f"/gateways/{gw_id}")


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


# ---------------------------------------------------------------------------
# MCP protocol helpers
# ---------------------------------------------------------------------------
_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _run_async(coro):
    """Run an async coroutine from sync code that already has an event loop (Playwright)."""
    return _thread_pool.submit(asyncio.run, coro).result()


def _mcp_client_url(server_url: str = BASE_URL) -> str:
    return f"{server_url}/mcp/" if not server_url.endswith(("/mcp", "/mcp/")) else server_url.rstrip("/") + "/"


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
        try:
            result = _mcp_tool_call(outsider_user["access_token"], "mcp-rbac-streamable-http-gw-get-system-time", {"timezone": "UTC"})
            assert result.isError, f"Outsider should be denied tools.execute, got: {result}"
        except Exception:
            pass  # McpError or connection error — both valid denials
        print("    -> Outsider denied tools.execute (expected)")

    def test_outsider_calls_nonexistent_tool_error(self, outsider_user: dict) -> None:
        try:
            result = _mcp_tool_call(outsider_user["access_token"], "nonexistent-tool-xyz-rbac")
            assert result.isError, f"Nonexistent tool should return error, got: {result}"
        except Exception:
            pass  # McpError — expected for outsider with no permissions
        print("    -> Outsider nonexistent tool: error (expected)")

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
