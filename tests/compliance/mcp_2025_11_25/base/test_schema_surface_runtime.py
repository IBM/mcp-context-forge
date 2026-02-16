# -*- coding: utf-8 -*-
"""Schema-surface runtime checks for MCP 2025-11-25 methods."""

# Standard
from pathlib import Path
from typing import Any, Dict

# Third-Party
import pytest
import yaml


def _manifest_methods() -> list[str]:
    manifest_path = Path(__file__).resolve().parents[1] / "manifest" / "schema_methods.yaml"
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    assert manifest["protocol_version"] == "2025-11-25"
    return list(manifest["methods"])


ALL_METHODS = _manifest_methods()
REQUEST_METHODS = [method for method in ALL_METHODS if not method.startswith("notifications/")]
NOTIFICATION_METHODS = [method for method in ALL_METHODS if method.startswith("notifications/")]


REQUEST_SAMPLE_PARAMS: Dict[str, Any] = {
    "initialize": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "mcp-compliance-suite", "version": "1.0.0"},
    },
    "ping": None,
    "completion/complete": {
        "ref": {"type": "ref/prompt", "name": "mcp-compliance-probe-prompt"},
        "argument": {"name": "query", "value": "hello"},
    },
    "logging/setLevel": {"level": "info"},
    "prompts/list": {},
    "prompts/get": {"name": "mcp-compliance-probe-prompt", "arguments": {}},
    "resources/list": {},
    "resources/templates/list": {},
    "resources/read": {"uri": "file:///tmp/mcp-compliance-probe-resource"},
    "resources/subscribe": {"uri": "file:///tmp/mcp-compliance-probe-resource"},
    "resources/unsubscribe": {"uri": "file:///tmp/mcp-compliance-probe-resource"},
    "tools/list": {},
    "tools/call": {"name": "mcp-compliance-probe-tool", "arguments": {}},
    "roots/list": {},
    "sampling/createMessage": {"messages": [], "maxTokens": 32},
    "elicitation/create": {
        "message": "Provide input for compliance probe",
        "requestedSchema": {"type": "object", "properties": {}, "required": []},
    },
    "tasks/list": {},
    "tasks/get": {"id": "task-compliance-probe"},
    "tasks/result": {"id": "task-compliance-probe"},
    "tasks/cancel": {"id": "task-compliance-probe"},
}

NOTIFICATION_SAMPLE_PARAMS: Dict[str, Any] = {
    "notifications/initialized": {},
    "notifications/cancelled": {"requestId": "req-compliance-probe", "reason": "test-cancel"},
    "notifications/progress": {"progressToken": "token-compliance-probe", "progress": 1, "total": 10, "message": "in-progress"},
    "notifications/message": {"level": "info", "logger": "mcp-compliance", "data": {"message": "probe"}},
    "notifications/resources/updated": {"uri": "file:///tmp/mcp-compliance-probe-resource"},
    "notifications/resources/list_changed": {},
    "notifications/prompts/list_changed": {},
    "notifications/tools/list_changed": {},
    "notifications/roots/list_changed": {},
    "notifications/elicitation/complete": {"id": "elicitation-compliance-probe", "response": {"action": "cancel"}},
    "notifications/tasks/status": {"taskId": "task-compliance-probe", "status": "running"},
}


@pytest.mark.mcp20251125
def test_schema_request_method_samples_cover_all_request_methods():
    assert set(REQUEST_METHODS) == set(REQUEST_SAMPLE_PARAMS)


@pytest.mark.mcp20251125
def test_schema_notification_method_samples_cover_all_notification_methods():
    assert set(NOTIFICATION_METHODS) == set(NOTIFICATION_SAMPLE_PARAMS)


@pytest.mark.mcp20251125
@pytest.mark.parametrize("method", REQUEST_METHODS)
def test_all_schema_request_methods_return_jsonrpc_envelope(
    method: str,
    rpc_call,
    ensure_not_auth_error,
):
    request_id = f"surface-{method}"
    response = rpc_call(method, request_id=request_id, params=REQUEST_SAMPLE_PARAMS[method])
    ensure_not_auth_error(response)

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == request_id
    assert ("result" in payload) ^ ("error" in payload)
    if "error" in payload:
        assert isinstance(payload["error"].get("code"), int)
        assert isinstance(payload["error"].get("message"), str)


@pytest.mark.mcp20251125
@pytest.mark.parametrize("method", NOTIFICATION_METHODS)
def test_all_schema_notification_methods_are_accepted(
    method: str,
    compliance_client,
    mcp_compliance_headers,
    mcp_compliance_rpc_path,
    ensure_not_auth_error,
):
    response = compliance_client.post(
        mcp_compliance_rpc_path,
        headers=mcp_compliance_headers,
        json={"jsonrpc": "2.0", "method": method, "params": NOTIFICATION_SAMPLE_PARAMS[method]},
    )
    ensure_not_auth_error(response)
    assert response.status_code == 202
