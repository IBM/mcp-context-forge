# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_mcp_protocol_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

End-to-end MCP protocol tests via the official ``mcp`` SDK client (``ClientSession`` over Streamable HTTP).

Exercises tools, resources, prompts, and raw transport behavior against a live
ContextForge instance, replacing the older ``mcp-cli`` + ``mcpgateway.wrapper``
subprocess suite with a single in-pytest async client. No external CLI
binaries required.

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
    make test-mcp-protocol-e2e
    pytest tests/e2e/test_mcp_protocol_e2e.py -v -s
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from datetime import timedelta
import json
import os
import subprocess
import sys
from typing import Any
import uuid

# Third-Party
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError
from mcp.types import InitializeResult
import pytest

# Local
from ..helpers.mcp_test_helpers import (
    ADMIN_EMAIL,
    BASE_URL,
    build_initialize,
    JWT_SECRET,
    skip_no_gateway,
    skip_no_rust_mcp_gateway,
    TOKEN_EXPIRY,
)

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
