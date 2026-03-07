# Copyright (c) 2025 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for A2A Server Router (mcpgateway/routers/a2a_server_router.py).

Tests JSON-RPC dispatch, REST endpoints, agent card discovery, server
discovery routes, and security deny-path scenarios using FastAPI's TestClient
with mocked service and auth layers.
"""

# Standard
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

# First-Party
import mcpgateway.routers.a2a_server_router as router_mod
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.routers.a2a_server_router import router
from mcpgateway.services.a2a_errors import A2AAgentError, A2AAgentNotFoundError, A2AAgentUpstreamError
from mcpgateway.services.a2a_server_service import A2AServerNotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_USER = {"email": "user@test.com", "sub": "user-1", "is_admin": True, "teams": None, "db": MagicMock()}
_DENIED_USER = {"email": "denied@test.com", "sub": "user-denied", "is_admin": False, "teams": ["team-1"], "db": MagicMock()}
_INVOKE_CONTEXT = ("user-1", "user@test.com", ["team-1"])


def _register_a2a_exception_handlers(app: FastAPI) -> None:
    """Register A2A exception handlers matching main.py's global handlers."""

    @app.exception_handler(A2AAgentNotFoundError)
    async def _not_found(_request: Request, exc: A2AAgentNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))

    @app.exception_handler(A2AAgentUpstreamError)
    async def _upstream(_request: Request, exc: A2AAgentUpstreamError):
        raise HTTPException(status_code=502, detail=str(exc))

    @app.exception_handler(A2AAgentError)
    async def _error(_request: Request, exc: A2AAgentError):
        raise HTTPException(status_code=400, detail=str(exc))


def _make_mock_service():
    """Return a fully-mocked A2AServerService."""
    svc = MagicMock()
    svc.send_message = AsyncMock(return_value={"result": {"id": "task-abc", "state": "SUBMITTED"}})
    svc.get_task = AsyncMock(return_value={"result": {"id": "task-abc", "state": "WORKING"}})
    svc.cancel_task = AsyncMock(return_value={"result": {"id": "task-abc", "state": "CANCELED"}})
    svc.list_tasks = AsyncMock(return_value={"result": [{"id": "task-1"}, {"id": "task-2"}]})
    svc.get_agent_card = AsyncMock(return_value={"name": "Test Agent", "description": "A test agent card"})
    svc.list_a2a_servers = MagicMock(return_value=[{"id": "srv-1", "name": "Server A"}])
    return svc


@contextmanager
def _patched_client(mock_service):
    """Context manager that injects a mock service into the router module.

    Yields a TestClient and restores the originals on exit so tests
    that need a custom side_effect can build a one-off client cleanly.
    """
    orig_service = router_mod._service
    orig_ctx = router_mod._get_invoke_context
    router_mod._service = mock_service
    router_mod._get_invoke_context = lambda request, user: _INVOKE_CONTEXT

    app = FastAPI()
    _register_a2a_exception_handlers(app)
    app.include_router(router, prefix="/servers")
    app.dependency_overrides[get_current_user_with_permissions] = lambda: _FAKE_USER
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        router_mod._service = orig_service
        router_mod._get_invoke_context = orig_ctx


@contextmanager
def _patched_client_denied(mock_service, mock_perm_svc):
    """Context manager for deny-path tests where permission is refused.

    Sets ``MockPermissionService.check_permission`` to return ``False`` and
    injects ``_DENIED_USER`` (non-admin) so the ``@require_permission``
    decorator returns 403.

    Args:
        mock_service: Mocked A2AServerService instance.
        mock_perm_svc: The ``MockPermissionService`` class from the conftest
            fixture, used to flip the permission outcome.
    """
    mock_perm_svc.check_permission = AsyncMock(return_value=False)

    orig_service = router_mod._service
    orig_ctx = router_mod._get_invoke_context
    router_mod._service = mock_service
    router_mod._get_invoke_context = lambda request, user: _INVOKE_CONTEXT

    app = FastAPI()
    _register_a2a_exception_handlers(app)
    app.include_router(router, prefix="/servers")
    app.dependency_overrides[get_current_user_with_permissions] = lambda: _DENIED_USER
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        router_mod._service = orig_service
        router_mod._get_invoke_context = orig_ctx
        mock_perm_svc.check_permission = AsyncMock(return_value=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_service():
    return _make_mock_service()


@pytest.fixture
def client(mock_service):
    """TestClient with all dependencies mocked.

    Monkey-patches the module-level ``_service`` and ``_get_invoke_context``
    so the router uses our mocks at request time.
    """
    with _patched_client(mock_service) as c:
        yield c


# ---------------------------------------------------------------------------
# JSON-RPC Dispatch Tests
# ---------------------------------------------------------------------------


class TestJsonRpcDispatch:
    """Tests for POST /{server_id}/a2a JSON-RPC dispatcher."""

    def test_jsonrpc_send_message(self, client, mock_service):
        resp = client.post(
            "/servers/srv-1/a2a",
            json={"jsonrpc": "2.0", "method": "SendMessage", "params": {"message": {"role": "user"}}, "id": "req-1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "req-1"
        assert data["result"]["id"] == "task-abc"
        mock_service.send_message.assert_awaited_once()

    def test_jsonrpc_get_task(self, client, mock_service):
        resp = client.post(
            "/servers/srv-1/a2a",
            json={"jsonrpc": "2.0", "method": "GetTask", "params": {"taskId": "task-xyz"}, "id": "req-2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["id"] == "task-abc"
        mock_service.get_task.assert_awaited_once()
        # Verify taskId was extracted correctly.
        call_args = mock_service.get_task.call_args
        assert call_args[0][2] == "task-xyz"  # positional: db, server_id, task_id

    def test_jsonrpc_cancel_task(self, client, mock_service):
        resp = client.post(
            "/servers/srv-1/a2a",
            json={"jsonrpc": "2.0", "method": "CancelTask", "params": {"taskId": "task-cancel"}, "id": "req-3"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["state"] == "CANCELED"
        mock_service.cancel_task.assert_awaited_once()

    def test_jsonrpc_list_tasks(self, client, mock_service):
        resp = client.post(
            "/servers/srv-1/a2a",
            json={"jsonrpc": "2.0", "method": "ListTasks", "params": {}, "id": "req-4"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["result"], list)
        mock_service.list_tasks.assert_awaited_once()

    def test_jsonrpc_get_agent_card(self, client, mock_service):
        resp = client.post(
            "/servers/srv-1/a2a",
            json={"jsonrpc": "2.0", "method": "GetAgentCard", "params": {}, "id": "req-5"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["name"] == "Test Agent"
        mock_service.get_agent_card.assert_awaited_once()

    def test_jsonrpc_method_not_found(self, client):
        resp = client.post(
            "/servers/srv-1/a2a",
            json={"jsonrpc": "2.0", "method": "NonExistentMethod", "params": {}, "id": "req-6"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32601
        assert "Method not found" in data["error"]["message"]
        assert data["id"] == "req-6"

    def test_jsonrpc_invalid_params_type(self, client):
        """params as a list instead of dict should return -32600 (W10 fix)."""
        resp = client.post(
            "/servers/srv-1/a2a",
            json={"jsonrpc": "2.0", "method": "SendMessage", "params": ["bad", "params"], "id": "req-7"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32600
        assert "params must be an object" in data["error"]["message"]
        assert data["id"] == "req-7"

    def test_jsonrpc_server_not_found(self):
        svc = _make_mock_service()
        svc.send_message = AsyncMock(side_effect=A2AServerNotFoundError("Server 'srv-x' not found"))
        with _patched_client(svc) as c:
            resp = c.post(
                "/servers/srv-x/a2a",
                json={"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": "req-8"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32602
        assert "srv-x" in data["error"]["message"]
        assert data["id"] == "req-8"

    def test_jsonrpc_upstream_error(self):
        svc = _make_mock_service()
        svc.send_message = AsyncMock(side_effect=A2AAgentUpstreamError("Upstream 500"))
        with _patched_client(svc) as c:
            resp = c.post(
                "/servers/srv-1/a2a",
                json={"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": "req-9"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32603
        assert "Upstream" in data["error"]["message"]

    def test_jsonrpc_generic_error(self):
        svc = _make_mock_service()
        svc.send_message = AsyncMock(side_effect=A2AAgentError("Something went wrong"))
        with _patched_client(svc) as c:
            resp = c.post(
                "/servers/srv-1/a2a",
                json={"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": "req-10"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32600
        assert "Something went wrong" in data["error"]["message"]

    def test_jsonrpc_version_mismatch(self, client):
        """jsonrpc field set to something other than '2.0' should return -32600."""
        resp = client.post(
            "/servers/srv-1/a2a",
            json={"jsonrpc": "1.0", "method": "SendMessage", "params": {}, "id": "req-ver"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32600
        assert "2.0" in data["error"]["message"]
        assert data["id"] == "req-ver"

    def test_jsonrpc_version_missing(self, client):
        """Missing jsonrpc field should return -32600."""
        resp = client.post(
            "/servers/srv-1/a2a",
            json={"method": "SendMessage", "params": {}, "id": "req-nover"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32600
        assert "2.0" in data["error"]["message"]
        assert data["id"] == "req-nover"


# ---------------------------------------------------------------------------
# REST Endpoint Tests
# ---------------------------------------------------------------------------


class TestRestEndpoints:
    """Tests for REST-style A2A endpoints."""

    def test_send_message_success(self, client, mock_service):
        resp = client.post(
            "/servers/srv-1/a2a/message:send",
            json={"message": {"role": "user", "parts": [{"text": "hello"}]}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["id"] == "task-abc"
        mock_service.send_message.assert_awaited_once()

    def test_send_message_server_not_found(self):
        svc = _make_mock_service()
        svc.send_message = AsyncMock(side_effect=A2AServerNotFoundError("Server 'missing' not found"))
        with _patched_client(svc) as c:
            resp = c.post("/servers/missing/a2a/message:send", json={})
        assert resp.status_code == 404

    def test_get_task_success(self, client, mock_service):
        resp = client.get("/servers/srv-1/a2a/tasks/task-xyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["id"] == "task-abc"
        mock_service.get_task.assert_awaited_once()

    def test_list_tasks_with_query_params(self, client, mock_service):
        resp = client.get("/servers/srv-1/a2a/tasks?state=WORKING&session_id=sess-1&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["result"], list)
        mock_service.list_tasks.assert_awaited_once()
        # Verify the query params were assembled into the params dict.
        call_args = mock_service.list_tasks.call_args
        params = call_args[0][2]  # positional: db, server_id, params
        assert params["state"] == "WORKING"
        assert params["sessionId"] == "sess-1"
        assert params["limit"] == 10

    def test_cancel_task_success(self, client, mock_service):
        resp = client.post("/servers/srv-1/a2a/tasks/task-xyz:cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["state"] == "CANCELED"
        mock_service.cancel_task.assert_awaited_once()

    def test_stream_message_success(self):
        """POST /{server_id}/a2a/message:stream should stream SSE events."""
        svc = _make_mock_service()

        async def _fake_stream(*args, **kwargs):
            async def _gen():
                yield b"event: message\ndata: {}\n\n"
            return _gen()

        svc.stream_message = AsyncMock(side_effect=_fake_stream)
        with _patched_client(svc) as c:
            resp = c.post(
                "/servers/srv-1/a2a/message:stream",
                json={"message": {"role": "user", "parts": [{"text": "hi"}]}},
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


# ---------------------------------------------------------------------------
# Agent Card Tests
# ---------------------------------------------------------------------------


class TestAgentCard:
    """Tests for agent card discovery endpoints."""

    def test_get_agent_card(self, client, mock_service):
        resp = client.get("/servers/srv-1/a2a/v1/card")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Agent"
        mock_service.get_agent_card.assert_awaited_once()

    def test_well_known_agent_card(self, client, mock_service):
        resp = client.get("/servers/srv-1/.well-known/agent-card.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Agent"
        mock_service.get_agent_card.assert_awaited_once()

    def test_agent_card_server_not_found(self):
        svc = _make_mock_service()
        svc.get_agent_card = AsyncMock(side_effect=A2AServerNotFoundError("Server 'missing' not found"))
        with _patched_client(svc) as c:
            resp = c.get("/servers/missing/a2a/v1/card")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Discovery Test
# ---------------------------------------------------------------------------


class TestDiscovery:
    """Tests for A2A server discovery endpoint."""

    def test_list_a2a_servers(self, client, mock_service):
        resp = client.get("/servers/a2a/discover")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "Server A"
        mock_service.list_a2a_servers.assert_called_once()


# ---------------------------------------------------------------------------
# Security Deny-Path Tests
# ---------------------------------------------------------------------------


class TestDenyPaths:
    """Security deny-path regression tests: verify 403 when permission is denied.

    Each test sets ``MockPermissionService.check_permission`` to ``False`` and
    uses a non-admin user to confirm that every protected endpoint correctly
    returns HTTP 403.
    """

    def test_jsonrpc_dispatch_denied(self, mock_service, mock_permission_service):
        """POST /{server_id}/a2a must return 403 when permission is denied."""
        with _patched_client_denied(mock_service, mock_permission_service) as c:
            resp = c.post(
                "/servers/srv-1/a2a",
                json={"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": "deny-1"},
            )
        assert resp.status_code == 403

    def test_send_message_denied(self, mock_service, mock_permission_service):
        """POST /{server_id}/a2a/message:send must return 403 when permission is denied."""
        with _patched_client_denied(mock_service, mock_permission_service) as c:
            resp = c.post(
                "/servers/srv-1/a2a/message:send",
                json={"message": {"role": "user", "parts": [{"text": "hello"}]}},
            )
        assert resp.status_code == 403

    def test_get_agent_card_denied(self, mock_service, mock_permission_service):
        """GET /{server_id}/a2a/v1/card must return 403 when permission is denied."""
        with _patched_client_denied(mock_service, mock_permission_service) as c:
            resp = c.get("/servers/srv-1/a2a/v1/card")
        assert resp.status_code == 403

    def test_list_a2a_servers_denied(self, mock_service, mock_permission_service):
        """GET /a2a/discover must return 403 when permission is denied."""
        with _patched_client_denied(mock_service, mock_permission_service) as c:
            resp = c.get("/servers/a2a/discover")
        assert resp.status_code == 403

    def test_stream_message_denied(self, mock_service, mock_permission_service):
        """POST /{server_id}/a2a/message:stream must return 403 when permission is denied."""
        with _patched_client_denied(mock_service, mock_permission_service) as c:
            resp = c.post("/servers/srv-1/a2a/message:stream", json={})
        assert resp.status_code == 403

    def test_get_task_denied(self, mock_service, mock_permission_service):
        """GET /{server_id}/a2a/tasks/{task_id} must return 403 when permission is denied."""
        with _patched_client_denied(mock_service, mock_permission_service) as c:
            resp = c.get("/servers/srv-1/a2a/tasks/task-xyz")
        assert resp.status_code == 403

    def test_list_tasks_denied(self, mock_service, mock_permission_service):
        """GET /{server_id}/a2a/tasks must return 403 when permission is denied."""
        with _patched_client_denied(mock_service, mock_permission_service) as c:
            resp = c.get("/servers/srv-1/a2a/tasks")
        assert resp.status_code == 403

    def test_cancel_task_denied(self, mock_service, mock_permission_service):
        """POST /{server_id}/a2a/tasks/{task_id}:cancel must return 403 when permission is denied."""
        with _patched_client_denied(mock_service, mock_permission_service) as c:
            resp = c.post("/servers/srv-1/a2a/tasks/task-xyz:cancel")
        assert resp.status_code == 403

    def test_well_known_card_denied(self, mock_service, mock_permission_service):
        """GET /{server_id}/.well-known/agent-card.json must return 403 when permission is denied."""
        with _patched_client_denied(mock_service, mock_permission_service) as c:
            resp = c.get("/servers/srv-1/.well-known/agent-card.json")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Server Visibility Tests
# ---------------------------------------------------------------------------


class TestServerVisibility:
    """Verify that team-scoped servers are not accessible to unauthorized users."""

    def test_server_visibility_denied(self):
        """A user without matching team should get a 404 from a team-scoped server."""
        svc = _make_mock_service()
        svc.send_message = AsyncMock(side_effect=A2AServerNotFoundError("Server 'srv-team' not found"))
        with _patched_client(svc) as c:
            resp = c.post(
                "/servers/srv-team/a2a/message:send",
                json={"message": {"role": "user", "parts": [{"text": "hello"}]}},
            )
        assert resp.status_code == 404
