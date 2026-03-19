# -*- coding: utf-8 -*-
"""Tasks capability checks (optional feature lane)."""

# Third-Party
import pytest


@pytest.mark.mcp20251125
@pytest.mark.mcp_tasks
@pytest.mark.mcp_optional
def test_initialize_capabilities_do_not_advertise_tasks_by_default(
    rpc_call,
    ensure_not_auth_error,
    initialize_request,
):
    response = rpc_call("initialize", request_id="init-tasks-cap", params=initialize_request)
    ensure_not_auth_error(response)

    assert response.status_code == 200
    payload = response.json()
    assert "result" in payload
    capabilities = payload["result"]["capabilities"]
    assert "tasks" not in capabilities


@pytest.mark.mcp20251125
@pytest.mark.mcp_tasks
@pytest.mark.mcp_optional
@pytest.mark.parametrize(
    ("method", "params"),
    (
        ("tasks/list", {}),
        ("tasks/get", {"id": "task-1"}),
        ("tasks/result", {"id": "task-1"}),
        ("tasks/cancel", {"id": "task-1"}),
    ),
)
def test_task_methods_return_method_not_found_when_not_advertised(
    method,
    params,
    rpc_call,
    ensure_not_auth_error,
):
    response = rpc_call(method, request_id=f"{method}-unsupported", params=params)
    ensure_not_auth_error(response)

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == f"{method}-unsupported"
    assert payload["error"]["code"] in (-32601, -32602)
