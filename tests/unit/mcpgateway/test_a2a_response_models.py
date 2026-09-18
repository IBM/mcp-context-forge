# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_response_models.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Typed response models for the A2A invocation routes (issue #6699).

Two things are checked here:

* The three invocation routes declare named response models, and the generated
  OpenAPI document points at those components instead of an anonymous object, so
  a generated client gets a type rather than an unknown blob.
* The models are non-pruning and non-injecting. These routes forward whatever JSON
  document the target agent produced, so declaring envelope keys must not add nulls
  for keys the agent omitted, drop keys the model never heard of, or reject a payload
  that drifts from the A2A spec.
"""

# Standard
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

# Third-Party
from fastapi import status
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.main import app, get_current_user_with_permissions
from mcpgateway.schemas import A2AInvokeResponse, A2AJsonRpcResponse

# The versioned path each invocation route is published under, and the component it must
# reference. The legacy unversioned shims mount the same route objects, so they inherit
# the model without appearing in the generated spec.
TYPED_A2A_OPERATIONS: Dict[str, type] = {
    "/v1/a2a/{agent_name}/invoke": A2AInvokeResponse,
    "/v1/a2a/invoke": A2AInvokeResponse,
    "/v1/a2a/{agent_name}/jsonrpc": A2AJsonRpcResponse,
}


V1_TASK_RESPONSE: Dict[str, Any] = {
    "jsonrpc": "2.0",
    "result": {
        "id": "task-456",
        "contextId": "ctx-789",
        "status": {"state": "TASK_STATE_WORKING", "message": "Processing..."},
    },
    "id": 1,
}

LEGACY_TASK_RESPONSE: Dict[str, Any] = {
    "jsonrpc": "2.0",
    "result": {
        "kind": "task",
        "id": "task-123",
        "status": {
            "kind": "task-status",
            "state": "input-required",
            "message": {"kind": "message", "role": "agent", "parts": [{"kind": "text", "text": "Which file?"}]},
        },
    },
    "id": "req-9",
}


@pytest.fixture
def mock_a2a_service():
    """Patch the module-level A2A service used by the invocation routes."""
    with patch("mcpgateway.main.a2a_service") as service:
        yield service


@pytest.fixture
def mock_auth():
    """Bypass the permission dependency with an admin identity."""

    def _admin():
        """Return an admin principal so a2a.invoke is granted."""
        return {"sub": "test-user@example.com", "email": "test-user@example.com", "is_admin": True, "teams": None}

    app.dependency_overrides[get_current_user_with_permissions] = _admin
    yield _admin
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    """Bearer headers for the mocked authentication path."""
    return {"Authorization": "Bearer test-token"}


class TestRoutesDeclareNamedModels:
    """The response models the A2A invocation routes publish."""

    def test_openapi_references_components_not_anonymous_objects(self):
        """Every invocation route answers with a $ref to its model, not an anonymous object.

        This is what turns ``unknown`` in a generated client into a named type.
        """
        spec = app.openapi()
        invocation_paths = {path for path in spec["paths"] if path.startswith("/v1/a2a/") and (path.endswith("/invoke") or path.endswith("/jsonrpc"))}
        assert invocation_paths == set(TYPED_A2A_OPERATIONS), f"invocation routes changed: {sorted(invocation_paths)}"
        for path, model in TYPED_A2A_OPERATIONS.items():
            schema = spec["paths"][path]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
            assert schema == {"$ref": f"#/components/schemas/{model.__name__}"}, f"{path} still publishes {schema}"

    def test_component_documents_envelope_and_allows_extras(self):
        """The published component names the JSON-RPC keys and keeps unknown ones.

        ``additionalProperties`` is what lets an agent-specific key survive, and the
        property descriptions are the contract the generated client renders.
        """
        spec = app.openapi()
        for model_name in ("A2AInvokeResponse", "A2AJsonRpcResponse"):
            component = spec["components"]["schemas"][model_name]
            assert set(component["properties"]) == {"jsonrpc", "result", "error", "id"}
            assert component["additionalProperties"] is True
            for description in component["properties"].values():
                assert description.get("description")


class TestInvokePassthrough:
    """POST /a2a/{agent_name}/invoke and POST /a2a/invoke forward the agent document."""

    @pytest.mark.parametrize(
        "payload",
        [
            V1_TASK_RESPONSE,
            LEGACY_TASK_RESPONSE,
            {"error": "upstream unavailable"},
            {"result": None},
            {"id": "abc", "result": [1, 2], "jsonrpc": 2.0, "error": {"code": -32603, "message": "x", "data": [None, True]}},
            {"text": "hello", "confidence": 0.9},
            {},
        ],
        ids=["v1-task", "legacy-task", "gateway-error", "null-result", "spec-drift", "non-jsonrpc", "empty"],
    )
    def test_body_survives_serialization(self, mock_a2a_service, mock_auth, auth_headers, payload):
        """Unknown keys, null values and non-standard types reach the client unchanged.

        Args:
            mock_a2a_service: Patched A2A service returning the test payload.
            mock_auth: Admin principal override.
            auth_headers: Bearer headers for the route.
            payload: The document the mocked agent returns.
        """
        mock_a2a_service.invoke_agent = AsyncMock(return_value=payload)
        client = TestClient(app)

        response = client.post("/a2a/agent-1/invoke", json={"parameters": {"query": "hello"}}, headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload

    def test_by_id_route_forwards_agent_keys(self, mock_a2a_service, mock_auth, auth_headers):
        """The agent-id route keeps keys the model has never seen, including nested nulls.

        Args:
            mock_a2a_service: Patched A2A service.
            mock_auth: Admin principal override.
            auth_headers: Bearer headers for the route.
        """
        payload = {"agentCustom": {"keep": None}, "result": {"taskId": "t-1"}}
        mock_a2a_service.invoke_agent = AsyncMock(return_value=payload)
        client = TestClient(app)

        response = client.post("/a2a/invoke", json={"agent_id": "06f3c1f0-0000-4000-8000-000000000000", "parameters": {}}, headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload


class TestJsonRpcPassthrough:
    """POST /a2a/{agent_name}/jsonrpc keeps a JSON-RPC envelope."""

    def test_agent_envelope_returned_unchanged(self, mock_a2a_service, mock_auth, auth_headers):
        """A response that already carries jsonrpc is forwarded as-is.

        Args:
            mock_a2a_service: Patched A2A service.
            mock_auth: Admin principal override.
            auth_headers: Bearer headers for the route.
        """
        mock_a2a_service.invoke_agent = AsyncMock(return_value=LEGACY_TASK_RESPONSE)
        client = TestClient(app)

        response = client.post("/a2a/agent-1/jsonrpc", json={"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": "req-9"}, headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == LEGACY_TASK_RESPONSE

    def test_result_wrapped_with_request_id(self, mock_a2a_service, mock_auth, auth_headers):
        """A bare agent result is wrapped, keeping the request id alongside it.

        Args:
            mock_a2a_service: Patched A2A service.
            mock_auth: Admin principal override.
            auth_headers: Bearer headers for the route.
        """
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"taskId": "t7", "status": {"state": "TASK_STATE_COMPLETED"}})
        client = TestClient(app)

        response = client.post("/a2a/agent-1/jsonrpc", json={"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": 5}, headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"jsonrpc": "2.0", "result": {"taskId": "t7", "status": {"state": "TASK_STATE_COMPLETED"}}, "id": 5}

    def test_notification_omits_id(self, mock_a2a_service, mock_auth, auth_headers):
        """A notification gets no id key, not an id set to null.

        Args:
            mock_a2a_service: Patched A2A service.
            mock_auth: Admin principal override.
            auth_headers: Bearer headers for the route.
        """
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"taskId": "t8"})
        client = TestClient(app)

        response = client.post("/a2a/agent-1/jsonrpc", json={"jsonrpc": "2.0", "method": "SendMessage", "params": {}}, headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"jsonrpc": "2.0", "result": {"taskId": "t8"}}
