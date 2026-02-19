# -*- coding: utf-8 -*-
"""Streamable HTTP protocol header compliance checks."""

# Third-Party
import pytest


@pytest.mark.mcp20251125
@pytest.mark.mcp_core
@pytest.mark.mcp_transport_core
@pytest.mark.mcp_required
def test_streamable_http_accepts_latest_protocol_header(rpc_call, ensure_not_auth_error):
    response = rpc_call("ping", request_id="ping-latest")
    ensure_not_auth_error(response)

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "ping-latest"
    assert payload["result"] == {}


@pytest.mark.mcp20251125
@pytest.mark.mcp_core
@pytest.mark.mcp_transport_core
@pytest.mark.mcp_required
def test_streamable_http_rejects_unsupported_protocol_header(
    rpc_call,
    mcp_compliance_headers,
    ensure_not_auth_error,
):
    bad_headers = dict(mcp_compliance_headers)
    bad_headers["MCP-Protocol-Version"] = "1999-01-01"
    response = rpc_call("ping", request_id="ping-bad-version", headers=bad_headers)
    ensure_not_auth_error(response)

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "Bad Request"
    assert "Unsupported protocol version: 1999-01-01" in payload["message"]
