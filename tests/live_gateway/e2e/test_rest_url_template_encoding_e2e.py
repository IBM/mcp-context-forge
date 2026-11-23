# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Location: ./tests/live_gateway/e2e/test_rest_url_template_encoding_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box check that REST tool URL template values stay inside their template
slot.

Starts a private gateway subprocess, registers a REST tool whose URL holds an
``{id}`` placeholder and points at a local recording HTTP server, then calls
the tool over the virtual server's MCP transport:

- An ordinary value reaches the template path unchanged.
- Reserved characters (``#``, ``?``) arrive percent-encoded inside the same
  path segment.
- A value with a dot segment or a prior percent-encoded sequence returns an
  MCP error result, and the upstream receives no request.
"""

from __future__ import annotations

# Standard
import contextlib
from http.server import ThreadingHTTPServer
import threading

# Third-Party
import pytest

# First-Party
from tests.live_gateway.e2e.test_rest_non_json_output_schema_e2e import _RecordingHandler, isolated_gateway  # noqa: F401  pylint: disable=unused-import
from tests.live_gateway.plugins._helpers import create_virtual_server, initialize_session, mcp_headers

pytestmark = pytest.mark.e2e


class _TemplateHandler(_RecordingHandler):
    """Record the request path of each template tool call."""

    requests: list = []
    body = b"{}"


@contextlib.contextmanager
def _call_template_tool(client, token, value, *, tool_name):
    """Register a REST tool with an ``{id}`` URL template, then call it via MCP.

    Cleanup (deleting the server/tool, stopping the upstream) always runs on
    exit, including when the caller's assertions raise.

    Args:
        client: Authenticated client for the isolated gateway.
        token: Bearer token for the gateway's MCP transport.
        value: Value passed as the ``id`` argument.
        tool_name: Unique tool name for this scenario.

    Yields:
        The decoded MCP ``result`` of the ``tools/call`` request.
    """
    _TemplateHandler.requests.clear()
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _TemplateHandler)
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    tool_id = None
    server_id = None
    try:
        response = client.post(
            "/tools",
            json={
                "tool": {
                    "name": tool_name,
                    "description": "URL template encoding probe",
                    "integration_type": "REST",
                    "url": f"http://127.0.0.1:{upstream.server_port}/v1/users/{{id}}/public",
                    "request_type": "GET",
                    "visibility": "public",
                    "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                    "auth_type": "bearer",
                    "auth_token": "fake-backend-token",  # pragma: allowlist secret
                },
                "team_id": None,
            },
        )
        assert response.status_code == 200, response.text
        tool = response.json()
        tool_id = tool["id"]

        server_id = create_virtual_server(client, name=f"{tool_name}_server", tool_ids=[tool_id])
        session_id = initialize_session(client, server_id=server_id, token=token)

        call_response = client.post(
            f"/servers/{server_id}/mcp/",
            headers=mcp_headers(token, session_id=session_id),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool["name"], "arguments": {"id": value}}},
        )
        assert call_response.status_code == 200, call_response.text
        payload = call_response.json()
        assert "result" in payload, payload
        yield payload["result"]
    finally:
        try:
            if server_id:
                client.delete(f"/servers/{server_id}")
            if tool_id:
                client.delete(f"/tools/{tool_id}")
        finally:
            upstream.shutdown()
            upstream.server_close()
            worker.join(timeout=5)


def test_ordinary_value_reaches_template_path(isolated_gateway):  # noqa: F811
    """An ordinary value fills the template slot unchanged."""
    client, token = isolated_gateway
    with _call_template_tool(client, token, "42", tool_name="rest_template_ordinary_probe") as result:
        assert result.get("isError") is not True, result
        assert _TemplateHandler.requests == [("GET", "/v1/users/42/public")]


@pytest.mark.parametrize(
    ("value", "expected_path"),
    [
        ("42#", "/v1/users/42%23/public"),
        ("42?role=admin", "/v1/users/42%3Frole%3Dadmin/public"),
    ],
)
def test_reserved_chars_stay_in_template_path(isolated_gateway, value, expected_path):  # noqa: F811
    """Reserved characters arrive percent-encoded inside the template path."""
    client, token = isolated_gateway
    with _call_template_tool(client, token, value, tool_name="rest_template_reserved_probe") as result:
        assert result.get("isError") is not True, result
        assert _TemplateHandler.requests == [("GET", expected_path)]


@pytest.mark.parametrize("value", ["../../admin/keys#", "42%2F43"])
def test_unsafe_value_is_rejected_without_upstream_call(isolated_gateway, value):  # noqa: F811
    """A dot-segment or pre-encoded value returns an error and sends no upstream request."""
    client, token = isolated_gateway
    with _call_template_tool(client, token, value, tool_name="rest_template_unsafe_probe") as result:
        assert result["isError"] is True
        assert _TemplateHandler.requests == []
