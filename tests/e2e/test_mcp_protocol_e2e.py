# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_mcp_protocol_e2e.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end MCP protocol tests via the FastMCP ``Client``.

Exercises tools, resources, prompts, and raw transport behavior against a live
ContextForge instance, replacing the older ``mcp-cli`` + ``mcpgateway.wrapper``
subprocess suite with a single in-pytest async client. No external CLI
binaries required.

Requirements:
    - Gateway running (default: http://localhost:8080 via docker-compose)
    - Upstreams ``fast_time_server`` + ``fast_test_server`` registered
      (provided by the default compose stack)
    - Environment variables (or defaults):
        MCP_CLI_BASE_URL       Gateway URL (default: http://localhost:8080)
        JWT_SECRET_KEY         JWT signing secret
        PLATFORM_ADMIN_EMAIL   Admin email (default: admin@example.com)

Usage:
    make test-mcp-protocol-e2e
    pytest tests/e2e/test_mcp_protocol_e2e.py -v -s
"""

# Future
from __future__ import annotations

# Standard
import json
import os
import subprocess
import sys

# Third-Party
import httpx
import pytest
from fastmcp.client import Client
from fastmcp.client.auth import BearerAuth
from mcp.shared.exceptions import McpError

# Local
from .helpers.mcp_test_helpers import (
    ADMIN_EMAIL,
    BASE_URL,
    JWT_SECRET,
    TOKEN_EXPIRY,
    build_initialize,
    skip_no_gateway,
    skip_no_rust_mcp_gateway,
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


@pytest.fixture
async def client(jwt_token: str, mcp_url: str):
    async with Client(
        mcp_url,
        auth=BearerAuth(jwt_token),
        init_timeout=_CLIENT_TIMEOUT,
        timeout=_CLIENT_TIMEOUT,
    ) as connected:
        yield connected


# ---------------------------------------------------------------------------
# Connectivity / lifecycle
# ---------------------------------------------------------------------------
class TestConnectivity:

    async def test_ping(self, client: Client) -> None:
        """Ping roundtrips via the live gateway session."""
        await client.ping()
        print("    -> ping OK")

    async def test_initialize_reports_server_info(self, client: Client) -> None:
        """Initialize exposes protocolVersion, capabilities, and serverInfo."""
        init = client.initialize_result
        assert init.protocolVersion, f"missing protocolVersion: {init}"
        assert init.capabilities, f"missing capabilities: {init}"
        assert init.serverInfo, f"missing serverInfo: {init}"
        print(f"    -> Protocol: {init.protocolVersion}, Server: {init.serverInfo.name} v{init.serverInfo.version}")

    async def test_server_capabilities_include_core_surfaces(self, client: Client) -> None:
        """Gateway advertises tools, resources, and prompts capabilities."""
        caps = client.initialize_result.capabilities
        assert caps.tools is not None, f"tools capability missing: {caps}"
        assert caps.resources is not None, f"resources capability missing: {caps}"
        assert caps.prompts is not None, f"prompts capability missing: {caps}"
        advertised = [k for k in ("tools", "resources", "prompts", "logging", "completions") if getattr(caps, k, None) is not None]
        print(f"    -> Capabilities: {advertised}")

    async def test_multiple_calls_in_one_session(self, client: Client) -> None:
        """A single session supports interleaved tools/resources/prompts calls."""
        tools = await client.list_tools()
        resources = await client.list_resources()
        prompts = await client.list_prompts()
        assert tools, "tools empty"
        # resources / prompts may legitimately be empty depending on upstreams
        print(f"    -> tools={len(tools)} resources={len(resources)} prompts={len(prompts)}")


# ---------------------------------------------------------------------------
# Discovery — tools / resources / prompts
# ---------------------------------------------------------------------------
class TestTools:

    async def test_tools_list_nonempty(self, client: Client) -> None:
        tools = await client.list_tools()
        assert len(tools) > 0, "no tools registered on gateway"
        print(f"    -> {len(tools)} tools: {[t.name for t in tools][:10]}")

    async def test_tools_have_required_fields(self, client: Client) -> None:
        tools = await client.list_tools()
        for tool in tools:
            assert tool.name, f"tool missing name: {tool}"
            assert tool.description, f"tool {tool.name} missing description"
            assert tool.inputSchema is not None, f"tool {tool.name} missing inputSchema"
        print(f"    -> all {len(tools)} tools have name/description/inputSchema")

    async def test_tools_include_gateway_prefixed(self, client: Client) -> None:
        """Federated tools surface under a hyphenated ``<server>-<tool>`` name."""
        tools = await client.list_tools()
        prefixed = [t.name for t in tools if "-" in t.name]
        assert prefixed, f"expected gateway-prefixed tools, got: {[t.name for t in tools]}"
        print(f"    -> {len(prefixed)} gateway-prefixed tools present")

    async def test_tool_input_schemas_are_json_schema_objects(self, client: Client) -> None:
        for tool in await client.list_tools():
            schema = tool.inputSchema
            if schema:
                assert schema.get("type") == "object", f"tool {tool.name} inputSchema not type=object: {schema}"
        print("    -> all tool inputSchemas validated as type=object")


class TestDiscovery:

    async def test_resources_list(self, client: Client) -> None:
        resources = await client.list_resources()
        print(f"    -> {len(resources)} resources")

    async def test_resources_read_roundtrip(self, client: Client) -> None:
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
        resources = await client.list_resources()
        if not resources:
            pytest.skip("No resources registered on gateway — nothing to read")
        last_error: McpError | None = None
        for target in resources:
            try:
                contents = await client.read_resource(str(target.uri))
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

    async def test_prompts_list(self, client: Client) -> None:
        prompts = await client.list_prompts()
        print(f"    -> {len(prompts)} prompts")

    async def test_prompt_get_renders(self, client: Client) -> None:
        """Render any advertised prompt via prompts/get.

        Prefers a prompt with no required arguments to avoid hard-coding
        fixture names. Skips cleanly when no suitable prompt is registered.
        """
        prompts = await client.list_prompts()
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
    (fast_time_server, fast_test_server) which may be transiently unavailable.
    """

    async def test_get_system_time(self, client: Client) -> None:
        result = await client.call_tool_mcp(name="fast-time-get-system-time", arguments={"timezone": "UTC"})
        assert result.isError is False, f"get-system-time returned error (upstream may be down): {result.content}"
        assert result.content and result.content[0].type == "text"
        text = result.content[0].text
        assert text
        print(f"    -> get-system-time(UTC) = {text}")

    async def test_echo(self, client: Client) -> None:
        test_message = "hello-from-mcp-protocol-e2e"
        result = await client.call_tool_mcp(name="fast-test-echo", arguments={"message": test_message})
        assert result.isError is False, f"echo returned error (upstream may be down): {result.content}"
        text = result.content[0].text
        assert test_message in text, f"echo did not return message: {text}"
        print(f"    -> echo('{test_message}') = {text}")

    async def test_convert_time(self, client: Client) -> None:
        result = await client.call_tool_mcp(
            name="fast-time-convert-time",
            arguments={"time": "2025-01-15T12:00:00Z", "source_timezone": "UTC", "target_timezone": "America/New_York"},
        )
        assert result.isError is False, f"convert-time returned error (upstream may be down): {result.content}"
        assert result.content[0].type == "text"
        print(f"    -> convert-time(UTC->NY) = {result.content[0].text}")

    async def test_get_stats(self, client: Client) -> None:
        result = await client.call_tool_mcp(name="fast-test-get-stats", arguments={})
        assert result.isError is False, f"get-stats returned error (upstream may be down): {result.content}"
        print(f"    -> get-stats = {result.content[0].text[:120]}")

    async def test_schema_error_preserves_payload(self, client: Client) -> None:
        """End-to-end regression guard for ContextForge #4202.

        Drives the full MCP-federation path — FastMCP client -> gateway ->
        federated Rust fast_test_server -> gateway ingress validator ->
        gateway egress handler -> back to the client. The upstream
        ``fast-test-schema-error`` tool declares an ``outputSchema`` of
        ``{"required": ["recognitionId"], ...}`` and always returns
        ``isError=true`` with the verbatim user text "You cannot send
        more than 200 points". Every validator in the chain must honour
        the spec's "error responses do not require structured content"
        rule and leave the payload untouched.

        Assertion guards specifically against the pre-fix symptom: a
        payload substituted with a JSON validation-error dict containing
        ``"validator"`` or ``"required"`` keys.

        Issue: https://github.com/IBM/mcp-context-forge/issues/4202
        MCP spec: 2025-11-25 "Error Handling".
        """
        tool = await self._require_declared_output_schema(client, "fast-test-schema-error")
        assert tool is not None
        result = await client.call_tool_mcp(name="fast-test-schema-error", arguments={})
        assert result.isError is True, f"expected isError=true, got: {result}"
        text = result.content[0].text if result.content else ""
        assert "200 points" in text, f"expected original error text preserved, got: {text!r}"
        assert '"validator"' not in text and '"required"' not in text, f"error payload appears to have been replaced by a validation error (regression of #4202): {text!r}"
        print(f"    -> schema_error isError=true preserved: {text}")

    async def test_schema_success_validates_payload(self, client: Client) -> None:
        """End-to-end positive control for the #4202 fix.

        Proves validation *still runs and succeeds* for legitimate
        responses — catching any over-broad fix that accidentally
        disables the success path. The upstream
        ``fast-test-schema-success`` fixture declares the same
        ``outputSchema`` as ``schema_error`` but returns
        ``isError=false`` with ``{"recognitionId": "rec-123", ...}``,
        which satisfies the schema. Also verifies that
        ``structuredContent`` propagates to the downstream client on
        successful validation.
        """
        tool = await self._require_declared_output_schema(client, "fast-test-schema-success")
        assert tool is not None
        result = await client.call_tool_mcp(name="fast-test-schema-success", arguments={})
        assert result.isError is False, f"expected success, got: {result}"
        payload = json.loads(result.content[0].text)
        assert payload.get("recognitionId") == "rec-123", f"unexpected payload: {payload}"
        structured = result.structuredContent
        assert structured is not None, f"expected structured content on successful validation: {result}"
        assert structured.get("recognitionId") == "rec-123", f"unexpected structured content: {structured}"
        print(f"    -> schema_success validated: {payload}")

    async def test_nonexistent_tool(self, client: Client) -> None:
        """Calling a nonexistent tool surfaces an error, via either path."""
        try:
            result = await client.call_tool_mcp(name="nonexistent-tool-xyz", arguments={})
        except McpError as exc:
            print(f"    -> McpError (expected): {exc}")
            return
        assert result.isError is True, f"expected error for non-existent tool: {result}"
        print(f"    -> isError=True (expected): {result.content[0].text[:100] if result.content else ''}")

    @staticmethod
    async def _require_declared_output_schema(client: Client, tool_name: str):
        """Preflight: assert ``tool_name`` is advertised with a non-empty outputSchema.

        Without this guard, a stale fast_test_server image or an incomplete
        federation sync would cause the actual ``tools/call`` tests to
        fail with a misleading assertion. Fails fast with an actionable
        message.
        """
        tools = await client.list_tools()
        match = next((t for t in tools if t.name == tool_name), None)
        assert match is not None, (
            f"Tool {tool_name!r} is not registered in the gateway. " f"Rebuild the fast_test_server image and restart docker-compose so " f"register_fast_test picks up the new schema fixtures."
        )
        schema = match.outputSchema
        assert schema, (
            f"Tool {tool_name!r} has no outputSchema declared in the gateway: {match}. " "Check that the upstream tool declares an output_schema and that the gateway sync completed successfully."
        )
        return match


# ---------------------------------------------------------------------------
# Raw HTTP / transport parity — exercises paths the high-level client hides
# ---------------------------------------------------------------------------
class TestRawJsonRpc:
    """Direct JSON-RPC probes for behavior the high-level FastMCP client hides."""

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
