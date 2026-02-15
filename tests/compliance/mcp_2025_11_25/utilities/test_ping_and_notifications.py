# -*- coding: utf-8 -*-
"""Utility method checks (ping and notifications)."""

# Third-Party
import pytest


@pytest.mark.mcp20251125
@pytest.mark.mcp_core
@pytest.mark.mcp_utilities
@pytest.mark.mcp_required
def test_ping_returns_empty_object_result(rpc_call, ensure_not_auth_error):
    response = rpc_call("ping", request_id="ping-utility")
    ensure_not_auth_error(response)

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "ping-utility"
    assert payload["result"] == {}


@pytest.mark.mcp20251125
@pytest.mark.mcp_core
@pytest.mark.mcp_utilities
@pytest.mark.mcp_required
@pytest.mark.parametrize(
    ("method", "params"),
    (
        ("notifications/initialized", {}),
        ("notifications/cancelled", {"requestId": "req-123", "reason": "user-requested"}),
    ),
)
def test_notifications_are_accepted_with_202(
    method,
    params,
    compliance_client,
    mcp_compliance_headers,
    mcp_compliance_rpc_path,
    ensure_not_auth_error,
):
    response = compliance_client.post(
        mcp_compliance_rpc_path,
        headers=mcp_compliance_headers,
        json={"jsonrpc": "2.0", "method": method, "params": params},
    )
    ensure_not_auth_error(response)
    assert response.status_code == 202
