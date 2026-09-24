# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_rest_non_json_output_schema_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box check for a REST tool that declares an outputSchema and returns a
non-JSON (truncated) body against a running gateway.

Registers a REST tool pointing at a local HTTP server that serves an invalid,
truncated JSON body, calls it over the gateway's public ``/mcp`` transport,
and asserts the parse-error message reaches the caller instead of a generic
output-validation failure.
"""

from __future__ import annotations

# Standard
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

# Keep in sync with tests/live_gateway/plugins/_helpers.py.
MCP_PROTOCOL_VERSION = "2025-11-25"

# Invalid, truncated JSON: an unterminated string inside a "results" array.
_TRUNCATED_BODY = ('{"results": ["' + "x" * 6000).encode()


class _TruncatedJSONHandler(BaseHTTPRequestHandler):
    """Serve a truncated JSON body for the schema-tool parse-error probe."""

    def do_GET(self):
        """Return 200 with an invalid, truncated JSON body."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(_TRUNCATED_BODY)

    def log_message(self, format, *args):
        """Keep the fixture HTTP server quiet."""


def _mcp_headers(token: str, *, session_id: str | None = None) -> dict[str, str]:
    """Build MCP JSON-RPC headers for a bearer token.

    Args:
        token: Bearer token to send.
        session_id: Optional MCP session identifier to attach.

    Returns:
        Standard MCP streamable-HTTP headers.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    return headers


def test_non_json_body_with_output_schema_reports_parse_error():
    """A truncated JSON body on a schema tool surfaces a parse error, not a validation error."""
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _TruncatedJSONHandler)
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    tool_id = None
    try:
        with httpx.Client(base_url=BASE_URL, headers=make_auth_headers(token), timeout=15, verify=False) as client:
            response = client.post(
                "/tools",
                json={
                    "tool": {
                        "name": "rest_non_json_output_schema_probe",
                        "description": "Non-JSON body probe for outputSchema tools",
                        "integrationType": "REST",
                        "url": f"http://127.0.0.1:{upstream.server_port}/probe",
                        "requestType": "GET",
                        "visibility": "public",
                        "outputSchema": {
                            "type": "object",
                            "properties": {"results": {"type": "array"}},
                            "required": ["results"],
                        },
                    },
                    "team_id": None,
                },
            )
            assert response.status_code == 200, response.text
            tool = response.json()
            tool_id = tool["id"]
            tool_name = tool["name"]

            init_response = client.post(
                "/mcp/",
                headers=_mcp_headers(token),
                json={
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "rest-non-json-output-schema-e2e", "version": "1.0.0"},
                    },
                },
            )
            assert init_response.status_code == 200, init_response.text
            session_id = init_response.headers.get("mcp-session-id")

            call_response = client.post(
                "/mcp/",
                headers=_mcp_headers(token, session_id=session_id),
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": {}},
                },
            )
            assert call_response.status_code == 200, call_response.text
            payload = call_response.json()
            assert "result" in payload, payload
            result = payload["result"]

            assert result["isError"] is True
            text = "\n".join(block.get("text", "") for block in result.get("content", []) if isinstance(block, dict) and block.get("type") == "text")
            assert "Response body is not valid JSON" in text
            assert "Output validation error" not in call_response.text
    finally:
        try:
            if tool_id:
                with httpx.Client(base_url=BASE_URL, headers=make_auth_headers(token), timeout=15, verify=False) as client:
                    client.delete(f"/tools/{tool_id}")
        finally:
            upstream.shutdown()
            upstream.server_close()
            worker.join(timeout=5)
