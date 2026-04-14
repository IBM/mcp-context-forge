# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_mcp_cli_protocol.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end MCP protocol tests using mcp-cli against a live ContextForge instance.

These tests exercise the MCP protocol through IBM's mcp-cli client, validating that
ContextForge correctly serves tools, resources, prompts, and server info over the
stdio transport (via mcpgateway.wrapper). No LLM provider or API key is required —
all tested commands operate purely at the MCP protocol level.

Requirements:
    - mcp-cli installed: pip install "mcp-cli[cli]"
    - ContextForge running (default: http://localhost:8080 via docker-compose)
    - Environment variables (or defaults):
        MCP_CLI_BASE_URL: Gateway URL (default: http://localhost:8080)
        JWT_SECRET_KEY: JWT signing secret (default: my-test-key-but-now-longer-than-32-bytes)
        PLATFORM_ADMIN_EMAIL: Admin email (default: admin@example.com)

Usage:
    # Run all mcp-cli protocol tests against docker-compose stack
    make test-mcp-cli

    # Run directly with pytest
    pytest tests/e2e/test_mcp_cli_protocol.py -v -s

    # Override gateway URL
    MCP_CLI_BASE_URL=http://localhost:4444 pytest tests/e2e/test_mcp_cli_protocol.py -v -s
"""

# Future
from __future__ import annotations

# Standard
import json
import os
from pathlib import Path
import subprocess
import sys

# Third-Party
import httpx
import pytest

# Local
from .mcp_test_helpers import (
    ADMIN_EMAIL,
    BASE_URL,
)
from .mcp_test_helpers import (
    JWT_SECRET,
)
from .mcp_test_helpers import (
    skip_no_gateway,
    skip_no_mcp_cli,
    TOKEN_EXPIRY,
    WRAPPER_PYTHON,
)
from .mcp_test_helpers import build_initialize as _build_initialize
from .mcp_test_helpers import extract_json_from_output as _extract_json_from_output
from .mcp_test_helpers import run_mcp_cli as _run_mcp_cli
from .mcp_test_helpers import send_jsonrpc_via_wrapper as _send_jsonrpc_via_wrapper

pytestmark = [pytest.mark.e2e, skip_no_mcp_cli, skip_no_gateway]


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
def config_file(jwt_token: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    config = {
        "mcpServers": {
            "contextforge": {
                "command": WRAPPER_PYTHON,
                "args": ["-m", "mcpgateway.wrapper"],
                "env": {
                    "MCP_AUTH": f"Bearer {jwt_token}",
                    "MCP_SERVER_URL": BASE_URL,
                    "MCP_TOOL_CALL_TIMEOUT": "30",
                },
            }
        }
    }
    tmp_dir = tmp_path_factory.mktemp("mcp_cli_test")
    config_path = tmp_dir / "server_config.json"
    config_path.write_text(json.dumps(config, indent=2))
    print(f"  server_config.json -> {config_path}")
    print(f"  Gateway URL: {BASE_URL}")
    print("  Transport: stdio via mcpgateway.wrapper")
    return config_path


# Helpers _run_mcp_cli, _extract_json_from_output, _send_jsonrpc_via_wrapper,
# and _build_initialize are imported from .mcp_test_helpers above.


# ---------------------------------------------------------------------------
# MCP Protocol Lifecycle Tests (via mcp-cli)
# ---------------------------------------------------------------------------
class TestMcpCliConnectivity:

    def test_ping(self, config_file: Path) -> None:
        """mcp-cli ping: verify server connectivity."""
        result = _run_mcp_cli(config_file, "ping")
        assert result.returncode == 0, f"ping failed: {result.stderr}"
        assert "Connected" in result.stdout, f"Expected 'Connected' in: {result.stdout}"
        print("    -> Server responded: Connected")

    def test_servers_list(self, config_file: Path) -> None:
        """mcp-cli servers: retrieve server info table."""
        result = _run_mcp_cli(config_file, "servers")
        assert result.returncode == 0, f"servers failed: {result.stderr}"
        assert "contextforge" in result.stdout
        assert "Connected" in result.stdout
        # Extract tool count from output
        for line in result.stdout.splitlines():
            if "contextforge" in line:
                print(f"    -> {line.strip()}")
                break


# ---------------------------------------------------------------------------
# MCP tools/list Tests (via mcp-cli)
# ---------------------------------------------------------------------------
class TestMcpCliTools:

    def test_tools_list_raw(self, config_file: Path) -> None:
        """mcp-cli tools --raw: returns valid JSON array."""
        result = _run_mcp_cli(config_file, "tools", "--raw")
        assert result.returncode == 0, f"tools --raw failed: {result.stderr}"
        tools = _extract_json_from_output(result.stdout)
        assert isinstance(tools, list)
        assert len(tools) > 0, "No tools returned from gateway"
        print(f"    -> {len(tools)} tools discovered: {[t['name'] for t in tools]}")

    def test_tools_list_has_required_fields(self, config_file: Path) -> None:
        """mcp-cli tools --raw: each tool has name, description, parameters."""
        result = _run_mcp_cli(config_file, "tools", "--raw")
        assert result.returncode == 0
        tools = _extract_json_from_output(result.stdout)
        for tool in tools:
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool, f"Tool missing 'description': {tool}"
            assert "parameters" in tool, f"Tool missing 'parameters': {tool}"
        print(f"    -> All {len(tools)} tools have required fields (name, description, parameters)")

    def test_tools_list_table_format(self, config_file: Path) -> None:
        """mcp-cli tools --all: renders formatted table."""
        result = _run_mcp_cli(config_file, "tools", "--all")
        assert result.returncode == 0, f"tools --all failed: {result.stderr}"
        assert "Available Tools" in result.stdout or "Tool" in result.stdout
        print("    -> Table rendered with 'Available Tools' header")

    def test_tools_include_gateway_tools(self, config_file: Path) -> None:
        """mcp-cli tools: gateway-prefixed tools are discoverable."""
        result = _run_mcp_cli(config_file, "tools", "--raw")
        assert result.returncode == 0
        tools = _extract_json_from_output(result.stdout)
        tool_names = [t["name"] for t in tools]
        has_prefixed = any("-" in name for name in tool_names)
        assert has_prefixed, f"Expected gateway-prefixed tools, got: {tool_names}"
        prefixed = [n for n in tool_names if "-" in n]
        print(f"    -> {len(prefixed)} gateway-prefixed tools found")

    def test_tools_schema_types(self, config_file: Path) -> None:
        """mcp-cli tools: tool parameters are valid JSON Schema objects."""
        result = _run_mcp_cli(config_file, "tools", "--raw")
        assert result.returncode == 0
        tools = _extract_json_from_output(result.stdout)
        for tool in tools:
            params = tool.get("parameters", {})
            if params:
                assert "type" in params, f"Tool {tool['name']} parameters missing 'type'"
                assert params["type"] == "object", f"Tool {tool['name']} parameters type is not 'object'"
        print("    -> All tool parameters validated as type=object JSON Schema")


# ---------------------------------------------------------------------------
# MCP resources/list Tests (via mcp-cli)
# ---------------------------------------------------------------------------
class TestMcpCliResources:

    def test_resources_list(self, config_file: Path) -> None:
        """mcp-cli resources: resources/list executes without error."""
        result = _run_mcp_cli(config_file, "resources")
        assert result.returncode == 0, f"resources failed: {result.stderr}"
        print("    -> resources/list OK")


# ---------------------------------------------------------------------------
# MCP prompts/list Tests (via mcp-cli)
# ---------------------------------------------------------------------------
class TestMcpCliPrompts:

    def test_prompts_list(self, config_file: Path) -> None:
        """mcp-cli prompts: prompts/list executes without error."""
        result = _run_mcp_cli(config_file, "prompts")
        assert result.returncode == 0, f"prompts failed: {result.stderr}"
        print("    -> prompts/list OK")


# ---------------------------------------------------------------------------
# MCP JSON-RPC protocol via mcpgateway.wrapper stdio
# ---------------------------------------------------------------------------
@pytest.mark.flaky(reruns=1, reruns_delay=2)
class TestMcpStdioProtocol:
    """Raw MCP JSON-RPC protocol tests via mcpgateway.wrapper.

    Bypasses mcp-cli to exercise the full MCP protocol directly, covering
    operations mcp-cli doesn't support without an LLM (tools/call, etc).

    Marked flaky(reruns=1) because these hit live upstream MCP servers
    (fast_time_server, fast_test_server) which may be transiently unavailable.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, jwt_token: str) -> None:
        self.env = {
            **os.environ,
            "MCP_AUTH": f"Bearer {jwt_token}",
            "MCP_SERVER_URL": BASE_URL,
            "MCP_TOOL_CALL_TIMEOUT": "30",
        }

    def test_initialize(self) -> None:
        """JSON-RPC initialize: returns protocol version, capabilities, server info."""
        responses = _send_jsonrpc_via_wrapper(self.env, [_build_initialize()])
        assert len(responses) >= 1, "No responses received"
        init_resp = next((r for r in responses if r.get("id") == 1), None)
        assert init_resp is not None, f"No init response: {responses}"
        result = init_resp["result"]
        assert "protocolVersion" in result
        assert "capabilities" in result
        assert "serverInfo" in result
        print(f"    -> Protocol: {result['protocolVersion']}, Server: {result['serverInfo']['name']} v{result['serverInfo'].get('version', '?')}")

    def test_tools_list_jsonrpc(self) -> None:
        """JSON-RPC tools/list: returns tool definitions with inputSchema."""
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        tools_resp = next((r for r in responses if r.get("id") == 2), None)
        assert tools_resp is not None, f"No tools/list response: {responses}"
        tools = tools_resp["result"]["tools"]
        assert isinstance(tools, list) and len(tools) > 0
        for tool in tools:
            assert "name" in tool
            assert "inputSchema" in tool
        print(f"    -> {len(tools)} tools: {[t['name'] for t in tools]}")

    def test_tools_call_get_system_time(self) -> None:
        """JSON-RPC tools/call fast-time-get-system-time: returns UTC timestamp."""
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fast-time-get-system-time", "arguments": {"timezone": "UTC"}}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        call_resp = next((r for r in responses if r.get("id") == 2), None)
        assert call_resp is not None, f"No tools/call response: {responses}"
        result = call_resp["result"]
        assert not result.get("isError", False), f"get-system-time returned error (upstream may be down): {result.get('content', [{}])[0].get('text', '')}"
        assert "content" in result
        assert len(result["content"]) > 0
        assert result["content"][0]["type"] == "text"
        text = result["content"][0]["text"]
        assert len(text) > 0
        print(f"    -> get-system-time(UTC) = {text}")

    def test_tools_call_echo(self) -> None:
        """JSON-RPC tools/call fast-test-echo: echoes message back."""
        test_message = "hello-from-mcp-cli-test"
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fast-test-echo", "arguments": {"message": test_message}}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        call_resp = next((r for r in responses if r.get("id") == 2), None)
        assert call_resp is not None
        result = call_resp["result"]
        assert not result.get("isError", False), f"Echo tool returned error (upstream may be down): {result['content'][0]['text']}"
        text = result["content"][0]["text"]
        assert test_message in text, f"Echo did not return message: {text}"
        print(f"    -> echo('{test_message}') = {text}")

    def test_tools_call_convert_time(self) -> None:
        """JSON-RPC tools/call fast-time-convert-time: UTC -> America/New_York."""
        messages = [
            _build_initialize(1),
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "fast-time-convert-time", "arguments": {"time": "2025-01-15T12:00:00Z", "source_timezone": "UTC", "target_timezone": "America/New_York"}},
            },
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        call_resp = next((r for r in responses if r.get("id") == 2), None)
        assert call_resp is not None
        result = call_resp["result"]
        assert not result.get("isError", False), f"convert-time returned error (upstream may be down): {result.get('content', [{}])[0].get('text', '')}"
        text = result["content"][0]["text"]
        assert result["content"][0]["type"] == "text"
        print(f"    -> convert-time(UTC->NY) = {text}")

    def test_tools_call_get_stats(self) -> None:
        """JSON-RPC tools/call fast-test-get-stats: returns server statistics."""
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fast-test-get-stats", "arguments": {}}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        call_resp = next((r for r in responses if r.get("id") == 2), None)
        assert call_resp is not None
        assert "result" in call_resp
        result = call_resp["result"]
        assert not result.get("isError", False), f"get-stats returned error (upstream may be down): {result.get('content', [{}])[0].get('text', '')}"
        text = result["content"][0]["text"]
        print(f"    -> get-stats = {text[:120]}")

    def _require_declared_output_schema(self, tool_name: str) -> dict:
        """Preflight guard: assert the gateway advertises ``tool_name`` with a non-empty outputSchema.

        Without this guard, a stale fast_test_server image, an uncompleted
        federation sync, or a gateway-side tool validation rejection (such
        as the unsafe-character filter that caused a ``schema_error``
        description with ``;`` to be silently dropped during PR development)
        would cause the actual ``tools/call`` tests below to fail with a
        misleading assertion. This helper hits ``tools/list`` through the
        same stdio wrapper the tests use, confirms both the tool name and
        the declared schema are present, and fails fast with an actionable
        message pointing the operator at the image rebuild.

        MCP spec reference: 2025-11-25 "Output Schema" — tools with a
        declared output schema must expose it via ``tools/list``.
        """
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        list_resp = next((r for r in responses if r.get("id") == 2), None)
        assert list_resp is not None, f"No tools/list response: {responses}"
        tools = list_resp.get("result", {}).get("tools", [])
        match = next((t for t in tools if t.get("name") == tool_name), None)
        assert match is not None, (
            f"Tool {tool_name!r} is not registered in the gateway. " f"Rebuild the fast_test_server image and restart docker-compose so " f"register_fast_test picks up the new schema fixtures."
        )
        schema = match.get("outputSchema") or match.get("output_schema")
        assert schema, (
            f"Tool {tool_name!r} has no outputSchema declared in the gateway: {match}. " f"Check that the upstream tool declares an output_schema and that " f"the gateway sync completed successfully."
        )
        return schema

    def test_tools_call_schema_error_preserves_payload(self) -> None:
        """End-to-end regression guard for ContextForge #4202.

        Issue: https://github.com/IBM/mcp-context-forge/issues/4202

        Drives the full MCP-federation path through the stdio wrapper →
        gateway (server-side SDK) → federated Rust ``fast_test_server`` →
        gateway ingress validator → gateway egress handler → back to the
        stdio client. The upstream ``fast-test-schema-error`` tool declares
        an ``outputSchema`` of ``{"required": ["recognitionId"], ...}`` and
        always returns ``isError=true`` with the verbatim user text
        "You cannot send more than 200 points". Every validator in the
        chain — MCP Python client SDK, gateway's own
        ``_extract_and_validate_structured_content`` (ingress fix), and
        the MCP Python server SDK at the gateway's egress (via the
        ``types.CallToolResult`` short-circuit) — must honour the spec's
        "error responses do not require structured content" rule and leave
        the payload untouched.

        The assertion additionally guards against the specific pre-fix
        symptom: a payload substituted with a JSON validation-error dict
        containing ``"validator"`` or ``"required"`` keys. Seeing those
        strings in the returned text indicates a regression of the ingress
        fix, the egress fix, or both.

        MCP spec references:
        - 2025-11-25 "Error Handling":
          https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling
        - 2025-11-25 "Output Schema":
          https://modelcontextprotocol.io/specification/2025-11-25/server/tools#output-schema

        Related:
        - Ingress unit guards:
          ``tests/unit/mcpgateway/services/test_tool_service_coverage.py::TestExtractAndValidateErrorResponses``
        - Egress unit guards (local + pooled branches):
          ``tests/unit/mcpgateway/transports/test_streamablehttp_transport.py::test_call_tool_preserves_is_error_for_egress``
          and ``::test_call_tool_session_affinity_forwarded_preserves_is_error``
        - Non-MCP path coverage gap (REST/OpenAPI/A2A):
          https://github.com/IBM/mcp-context-forge/issues/4207
        """
        self._require_declared_output_schema("fast-test-schema-error")
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fast-test-schema-error", "arguments": {}}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        call_resp = next((r for r in responses if r.get("id") == 2), None)
        assert call_resp is not None, f"No response for id=2: {responses}"
        assert "result" in call_resp, f"Expected result envelope: {call_resp}"
        result = call_resp["result"]
        assert result.get("isError") is True, f"Expected isError=true, got: {result}"
        text = result.get("content", [{}])[0].get("text", "")
        # The original error text must be preserved — not replaced by a schema
        # validation error payload (which would contain keys like 'validator'
        # or 'required').
        assert "200 points" in text, f"Expected original error text to be preserved, got: {text!r}"
        assert '"validator"' not in text and '"required"' not in text, f"Error payload appears to have been replaced by a validation error (regression of #4202): {text!r}"
        print(f"    -> schema_error isError=true preserved: {text}")

    def test_tools_call_schema_success_validates_payload(self) -> None:
        """End-to-end positive control for the #4202 fix.

        While ``test_tools_call_schema_error_preserves_payload`` proves the
        gateway *skips* validation for error responses, this test proves
        that validation *still runs and succeeds* for legitimate responses —
        catching any over-broad fix that accidentally disables the success
        path. The upstream ``fast-test-schema-success`` Rust fixture
        declares the same ``outputSchema`` as ``schema_error`` but returns
        ``isError=false`` with ``{"recognitionId": "rec-123", "message":
        "ok"}``, which satisfies the schema. Assertions:

        1. ``isError`` is absent/false.
        2. The text content round-trips through JSON.
        3. The MCP SDK's server-side validator at the gateway's egress
           propagates ``structuredContent`` to the downstream client —
           proving the egress handler's success branch still returns the
           ``(unstructured, structured)`` tuple so the SDK validates.

        Without this positive control, a future refactor that simply drops
        the validator everywhere would pass
        ``test_tools_call_schema_error_preserves_payload`` (no validation
        runs, error text is preserved) while silently breaking
        ``outputSchema`` enforcement.

        MCP spec reference: 2025-11-25 "Output Schema":
        https://modelcontextprotocol.io/specification/2025-11-25/server/tools#output-schema

        Related:
        - Negative counterpart (#4202 skip):
          ``test_tools_call_schema_error_preserves_payload``
        - Structured-content attachment by the ingress validator:
          ``tests/unit/mcpgateway/services/test_tool_service_coverage.py::TestExtractAndValidateErrorResponses::test_validate_success_response_normally``
        """
        self._require_declared_output_schema("fast-test-schema-success")
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fast-test-schema-success", "arguments": {}}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        call_resp = next((r for r in responses if r.get("id") == 2), None)
        assert call_resp is not None, f"No response for id=2: {responses}"
        assert "result" in call_resp, f"Expected result envelope: {call_resp}"
        result = call_resp["result"]
        assert not result.get("isError", False), f"Expected success, got: {result}"
        text = result.get("content", [{}])[0].get("text", "")
        payload = json.loads(text)
        assert payload.get("recognitionId") == "rec-123", f"Unexpected payload: {payload}"
        # When validation succeeds the gateway attaches structured_content
        # alongside the original text content.
        structured = result.get("structuredContent") or result.get("structured_content")
        assert structured is not None, f"Expected structured content on successful validation: {result}"
        assert structured.get("recognitionId") == "rec-123", f"Unexpected structured content: {structured}"
        print(f"    -> schema_success validated: {payload}")

    def test_tools_call_nonexistent_tool(self) -> None:
        """JSON-RPC tools/call nonexistent-tool-xyz: returns error response."""
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "nonexistent-tool-xyz", "arguments": {}}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        call_resp = next((r for r in responses if r.get("id") == 2), None)
        assert call_resp is not None
        has_error = "error" in call_resp or ("result" in call_resp and call_resp["result"].get("isError", False))
        assert has_error, f"Expected error for non-existent tool: {call_resp}"
        if "error" in call_resp:
            print(f"    -> Error (expected): {call_resp['error'].get('message', call_resp['error'])}")
        else:
            print(f"    -> isError=True (expected): {call_resp['result'].get('content', [{}])[0].get('text', '')[:100]}")

    def test_resources_list_jsonrpc(self) -> None:
        """JSON-RPC resources/list: returns resource array."""
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "resources/list", "params": {}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        res_resp = next((r for r in responses if r.get("id") == 2), None)
        assert res_resp is not None
        resources = res_resp["result"]["resources"]
        assert "resources" in res_resp["result"]
        print(f"    -> {len(resources)} resources")

    def test_prompts_list_jsonrpc(self) -> None:
        """JSON-RPC prompts/list: returns prompt array."""
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "prompts/list", "params": {}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        prompts_resp = next((r for r in responses if r.get("id") == 2), None)
        assert prompts_resp is not None
        prompts = prompts_resp["result"]["prompts"]
        assert "prompts" in prompts_resp["result"]
        print(f"    -> {len(prompts)} prompts")

    def test_multiple_concurrent_requests(self) -> None:
        """JSON-RPC: 5 requests in one session all get responses."""
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
            {"jsonrpc": "2.0", "id": 4, "method": "prompts/list", "params": {}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "fast-time-get-system-time", "arguments": {"timezone": "UTC"}}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages, timeout=30, settle_seconds=5.0)
        response_ids = {r.get("id") for r in responses}
        for expected_id in [1, 2, 3, 4, 5]:
            assert expected_id in response_ids, f"Missing response for id={expected_id}, got: {response_ids}"
        print(f"    -> All 5 responses received (ids: {sorted(response_ids)})")

    def test_invalid_method(self) -> None:
        """JSON-RPC nonexistent/method: returns error."""
        messages = [
            _build_initialize(1),
            {"jsonrpc": "2.0", "id": 2, "method": "nonexistent/method", "params": {}},
        ]
        responses = _send_jsonrpc_via_wrapper(self.env, messages)
        err_resp = next((r for r in responses if r.get("id") == 2), None)
        assert err_resp is not None
        assert "error" in err_resp, f"Expected error for invalid method: {err_resp}"
        print(f"    -> Error (expected): {err_resp['error'].get('message', err_resp['error'])}")


# ---------------------------------------------------------------------------
# Protocol Coverage
# ---------------------------------------------------------------------------
class TestMcpProtocolCoverage:

    def test_all_discovery_methods(self, config_file: Path) -> None:
        """mcp-cli: all 3 discovery methods (tools, resources, prompts) work."""
        for cmd in ["tools", "resources", "prompts"]:
            result = _run_mcp_cli(config_file, cmd)
            assert result.returncode == 0, f"{cmd} failed: {result.stderr}"
            print(f"    -> {cmd}: OK")

    def test_server_capabilities(self, jwt_token: str) -> None:
        """JSON-RPC initialize: server reports tools, resources, prompts capabilities."""
        env = {**os.environ, "MCP_AUTH": f"Bearer {jwt_token}", "MCP_SERVER_URL": BASE_URL, "MCP_TOOL_CALL_TIMEOUT": "30"}
        responses = _send_jsonrpc_via_wrapper(env, [_build_initialize()])
        init_resp = next((r for r in responses if r.get("id") == 1), None)
        assert init_resp is not None
        caps = init_resp["result"]["capabilities"]
        assert "tools" in caps, f"Missing 'tools' capability: {caps}"
        assert "resources" in caps, f"Missing 'resources' capability: {caps}"
        assert "prompts" in caps, f"Missing 'prompts' capability: {caps}"
        cap_names = sorted(caps.keys())
        print(f"    -> Server capabilities: {cap_names}")


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
            init_response = client.post(f"{BASE_URL}/mcp/", headers=initialize_headers, json=_build_initialize())
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
