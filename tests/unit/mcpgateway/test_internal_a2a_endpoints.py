# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the /_internal/a2a/* endpoints in mcpgateway/main.py.

Coverage strategy
-----------------
1. **Untrusted-request 403 gate** — all endpoints must reject non-runtime
   callers with HTTP 403.  The trust check lives in a single helper,
   ``_is_trusted_internal_mcp_runtime_request``, which is patched to
   ``False`` so we exercise every endpoint without standing up auth
   infrastructure.

2. **Happy-path / service delegation** — a representative subset of
   endpoints is tested with the trust gate patched to ``True`` and the
   downstream service calls mocked, verifying that the HTTP response code
   and body are correct.

3. **Not-found / missing-field** — selected endpoints verify the 404 and
   400 paths.
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.validation.jsonrpc import JSONRPCError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TRUST_PATH = "mcpgateway.main._is_trusted_internal_mcp_runtime_request"

# Endpoints that take an empty JSON body for the untrusted-403 check.
_SIMPLE_ENDPOINTS: list[str] = [
    "/_internal/a2a/invoke/authz",
    "/_internal/a2a/list/authz",
    "/_internal/a2a/get/authz",
    "/_internal/a2a/tasks/get",
    "/_internal/a2a/tasks/list",
    "/_internal/a2a/tasks/cancel",
    "/_internal/a2a/push/create",
    "/_internal/a2a/push/get",
    "/_internal/a2a/push/list",
    "/_internal/a2a/push/delete",
    "/_internal/a2a/events/flush",
    "/_internal/a2a/events/replay",
]

# Path-templated endpoints for the untrusted-403 check.
_AGENT_ENDPOINTS: list[str] = [
    "/_internal/a2a/agents/my-agent/resolve",
    "/_internal/a2a/agents/my-agent/card",
]

# Authenticate delegates to handle_internal_mcp_authenticate which raises
# HTTPException(403), so we include it separately.
_AUTHENTICATE_ENDPOINT = "/_internal/a2a/authenticate"


@pytest.fixture()
def client(app_with_temp_db):
    """Return a synchronous TestClient for the FastAPI app.

    Intentionally does NOT use the context-manager form so that the
    lifespan is not triggered.  This matches the pattern used in
    test_main.py and avoids the StreamableHTTPSessionManager
    "can only be called once" error that occurs when the module-scoped
    ``app_with_temp_db`` lifespan is re-entered across parameterized
    tests.
    """
    return TestClient(app_with_temp_db, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1.  Every endpoint returns 403 when the trust gate is False
# ---------------------------------------------------------------------------


class TestUntrustedRequestsReturn403:
    """All /_internal/a2a/* endpoints must return 403 when untrusted."""

    @patch(_TRUST_PATH, return_value=False)
    def test_authenticate_untrusted(self, _mock, client):
        resp = client.post(_AUTHENTICATE_ENDPOINT, json={})
        assert resp.status_code == 403

    @pytest.mark.parametrize("url", _SIMPLE_ENDPOINTS)
    @patch(_TRUST_PATH, return_value=False)
    def test_simple_endpoint_untrusted(self, _mock, url, client):
        resp = client.post(url, json={})
        assert resp.status_code == 403

    @pytest.mark.parametrize("url", _AGENT_ENDPOINTS)
    @patch(_TRUST_PATH, return_value=False)
    def test_agent_endpoint_untrusted(self, _mock, url, client):
        resp = client.post(url, json={})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 2.  Happy-path tests (trust gate = True, service mocked)
# ---------------------------------------------------------------------------


class TestTasksGetTrusted:
    """tasks/get returns 200 + task dict when a matching task exists."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_task")
    def test_returns_task(self, mock_get_task, _mock_trust, client):
        mock_get_task.return_value = {"task_id": "t1", "state": "completed"}
        resp = client.post("/_internal/a2a/tasks/get", json={"task_id": "t1"})
        assert resp.status_code == 200
        assert resp.json()["task_id"] == "t1"

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_task")
    def test_missing_task_id_returns_400(self, _mock_get_task, _mock_trust, client):
        resp = client.post("/_internal/a2a/tasks/get", json={})
        assert resp.status_code == 400

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_task")
    def test_task_not_found_returns_404(self, mock_get_task, _mock_trust, client):
        mock_get_task.return_value = None
        resp = client.post("/_internal/a2a/tasks/get", json={"task_id": "missing"})
        assert resp.status_code == 404


class TestInternalA2AAuthzTrusted:
    """Trusted authz routes should preserve the MCP authz behavior contract."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._authorize_internal_mcp_request", new_callable=AsyncMock)
    def test_get_authz_returns_204_on_success(self, mock_authorize, _mock_trust, client):
        resp = client.post("/_internal/a2a/get/authz", json={})
        assert resp.status_code == 204
        mock_authorize.assert_awaited_once()

    @patch(_TRUST_PATH, return_value=True)
    @patch(
        "mcpgateway.main._authorize_internal_mcp_request",
        new_callable=AsyncMock,
        side_effect=JSONRPCError(-32003, "Access denied", {"method": "a2a/get"}),
    )
    def test_list_authz_maps_jsonrpc_error_to_403(self, _mock_authorize, _mock_trust, client):
        resp = client.post("/_internal/a2a/list/authz", json={})
        assert resp.status_code == 403
        assert resp.json()["message"] == "Access denied"


class TestTasksListTrusted:
    """tasks/list returns 200 + tasks array."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.list_tasks")
    def test_returns_tasks(self, mock_list_tasks, _mock_trust, client):
        mock_list_tasks.return_value = [{"task_id": "t1"}]
        resp = client.post("/_internal/a2a/tasks/list", json={})
        assert resp.status_code == 200
        assert resp.json()["tasks"] == [{"task_id": "t1"}]


class TestTasksCancelTrusted:
    """tasks/cancel returns 200 when task found, 404 when not."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.cancel_task")
    def test_cancels_task(self, mock_cancel, _mock_trust, client):
        mock_cancel.return_value = {"task_id": "t1", "state": "canceled"}
        resp = client.post("/_internal/a2a/tasks/cancel", json={"task_id": "t1"})
        assert resp.status_code == 200
        assert resp.json()["state"] == "canceled"

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.cancel_task")
    def test_missing_task_id_returns_400(self, _mock_cancel, _mock_trust, client):
        resp = client.post("/_internal/a2a/tasks/cancel", json={})
        assert resp.status_code == 400

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.cancel_task")
    def test_task_not_found_returns_404(self, mock_cancel, _mock_trust, client):
        mock_cancel.return_value = None
        resp = client.post("/_internal/a2a/tasks/cancel", json={"task_id": "missing"})
        assert resp.status_code == 404


class TestPushCreateTrusted:
    """push/create returns 200 with config, 400 when required fields missing."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.create_push_config")
    def test_creates_config(self, mock_create, _mock_trust, client):
        mock_create.return_value = {"id": "cfg1"}
        resp = client.post(
            "/_internal/a2a/push/create",
            json={"a2a_agent_id": "agent1", "task_id": "t1", "webhook_url": "https://example.com/webhook"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "cfg1"

    @patch(_TRUST_PATH, return_value=True)
    def test_missing_required_fields_returns_400(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/push/create", json={"a2a_agent_id": "agent1"})
        assert resp.status_code == 400


class TestPushGetTrusted:
    """push/get returns 200 + config when found, 404 when not."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_push_config")
    def test_returns_config(self, mock_get, _mock_trust, client):
        mock_get.return_value = {"id": "cfg1", "task_id": "t1"}
        resp = client.post("/_internal/a2a/push/get", json={"task_id": "t1"})
        assert resp.status_code == 200
        assert resp.json()["task_id"] == "t1"

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_push_config")
    def test_config_not_found_returns_404(self, mock_get, _mock_trust, client):
        mock_get.return_value = None
        resp = client.post("/_internal/a2a/push/get", json={"task_id": "t1"})
        assert resp.status_code == 404

    @patch(_TRUST_PATH, return_value=True)
    def test_missing_task_id_returns_400(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/push/get", json={})
        assert resp.status_code == 400


class TestPushListTrusted:
    """push/list returns 200 + configs array."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.list_push_configs")
    def test_returns_configs(self, mock_list, _mock_trust, client):
        mock_list.return_value = [{"id": "cfg1"}, {"id": "cfg2"}]
        resp = client.post("/_internal/a2a/push/list", json={})
        assert resp.status_code == 200
        assert len(resp.json()["configs"]) == 2


class TestPushDeleteTrusted:
    """push/delete returns 200 when deleted, 404 when not found, 400 if id missing."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.delete_push_config")
    def test_deletes_config(self, mock_delete, _mock_trust, client):
        mock_delete.return_value = True
        resp = client.post("/_internal/a2a/push/delete", json={"config_id": "cfg1"})
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.delete_push_config")
    def test_config_not_found_returns_404(self, mock_delete, _mock_trust, client):
        mock_delete.return_value = False
        resp = client.post("/_internal/a2a/push/delete", json={"config_id": "missing"})
        assert resp.status_code == 404

    @patch(_TRUST_PATH, return_value=True)
    def test_missing_config_id_returns_400(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/push/delete", json={})
        assert resp.status_code == 400


class TestEventsFlushTrusted:
    """events/flush returns 200 + count."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.flush_events")
    def test_flushes_events(self, mock_flush, _mock_trust, client):
        mock_flush.return_value = 3
        resp = client.post("/_internal/a2a/events/flush", json={"events": [{"seq": 1}, {"seq": 2}, {"seq": 3}]})
        assert resp.status_code == 200
        assert resp.json()["count"] == 3

    @patch(_TRUST_PATH, return_value=True)
    def test_empty_events_returns_zero_count(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/events/flush", json={"events": []})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestEventsReplayTrusted:
    """events/replay returns 200 + events array, 400 when task_id missing."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.replay_events")
    def test_replays_events(self, mock_replay, _mock_trust, client):
        mock_replay.return_value = [{"seq": 1, "data": "x"}]
        resp = client.post("/_internal/a2a/events/replay", json={"task_id": "t1", "after_sequence": 0})
        assert resp.status_code == 200
        assert resp.json()["events"] == [{"seq": 1, "data": "x"}]

    @patch(_TRUST_PATH, return_value=True)
    def test_missing_task_id_returns_400(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/events/replay", json={})
        assert resp.status_code == 400


class TestAgentResolveTrusted:
    """agents/{name}/resolve returns 200 when agent found, 404 when not."""

    @patch(_TRUST_PATH, return_value=True)
    @patch(
        "mcpgateway.main._build_internal_mcp_forwarded_user",
        return_value={"email": "user@example.com", "teams": ["team-a"], "is_admin": False},
    )
    @patch("mcpgateway.db.A2AAgent")
    def test_agent_not_found_returns_404(self, _mock_db_agent, _mock_user, _mock_trust, client):
        """When the DB has no match and server service also finds nothing, expect 404."""
        with patch("mcpgateway.main.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_session_local.return_value = mock_db

            with patch("mcpgateway.services.a2a_server_service.A2AServerService.resolve_server_agent", return_value=None):
                resp = client.post("/_internal/a2a/agents/nonexistent/resolve", json={})

        assert resp.status_code == 404

    @patch(_TRUST_PATH, return_value=True)
    @patch(
        "mcpgateway.main._build_internal_mcp_forwarded_user",
        return_value={"email": "user@example.com", "teams": ["team-a"], "is_admin": False},
    )
    def test_agent_found_in_db_returns_200(self, _mock_user, _mock_trust, client):
        """When a DB agent is found it is returned as JSON with 200."""
        mock_agent = MagicMock()
        mock_agent.id = "agent-id-1"
        mock_agent.name = "my-agent"
        mock_agent.endpoint_url = "https://agent.example.com"
        mock_agent.agent_type = "generic"
        mock_agent.protocol_version = "1.0"
        mock_agent.auth_type = None
        mock_agent.auth_value = None
        mock_agent.auth_query_params = None
        mock_agent.visibility = "public"
        mock_agent.owner_email = None
        mock_agent.team_id = None
        mock_agent.enabled = True

        with patch("mcpgateway.main.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = mock_agent
            mock_session_local.return_value = mock_db

            resp = client.post("/_internal/a2a/agents/my-agent/resolve", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "my-agent"
        assert data["agent_type"] == "generic"

    @patch(_TRUST_PATH, return_value=True)
    @patch(
        "mcpgateway.main._build_internal_mcp_forwarded_user",
        return_value={"email": "intruder@example.com", "teams": ["team-b"], "is_admin": False},
    )
    def test_private_agent_outside_scope_returns_404(self, _mock_user, _mock_trust, client):
        mock_agent = MagicMock()
        mock_agent.id = "agent-id-2"
        mock_agent.name = "private-agent"
        mock_agent.endpoint_url = "https://agent.example.com/private"
        mock_agent.agent_type = "generic"
        mock_agent.protocol_version = "1.0"
        mock_agent.auth_type = None
        mock_agent.auth_value = None
        mock_agent.auth_query_params = None
        mock_agent.visibility = "private"
        mock_agent.owner_email = "owner@example.com"
        mock_agent.team_id = "team-a"
        mock_agent.enabled = True

        with patch("mcpgateway.main.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = mock_agent
            mock_session_local.return_value = mock_db

            resp = client.post("/_internal/a2a/agents/private-agent/resolve", json={})

        assert resp.status_code == 404


class TestAgentCardTrusted:
    """agents/{name}/card returns 200 when agent card found, 404 when not."""

    @patch(_TRUST_PATH, return_value=True)
    @patch(
        "mcpgateway.main._build_internal_mcp_forwarded_user",
        return_value={"email": "user@example.com", "teams": ["team-a"], "is_admin": False},
    )
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_agent_card")
    @patch("mcpgateway.services.a2a_server_service.A2AServerService.get_server_agent_card")
    def test_card_not_found_returns_404(self, mock_server_card, mock_card, _mock_user, _mock_trust, client):
        mock_card.return_value = None
        mock_server_card.return_value = None
        resp = client.post("/_internal/a2a/agents/unknown-agent/card", json={})
        assert resp.status_code == 404

    @patch(_TRUST_PATH, return_value=True)
    @patch(
        "mcpgateway.main._build_internal_mcp_forwarded_user",
        return_value={"email": "user@example.com", "teams": ["team-a"], "is_admin": False},
    )
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_agent_card")
    @patch("mcpgateway.main.SessionLocal")
    def test_card_found_returns_200(self, mock_session_local, mock_card, _mock_user, _mock_trust, client):
        mock_card.return_value = {"name": "my-agent", "url": "https://agent.example.com"}
        mock_agent = MagicMock()
        mock_agent.visibility = "public"
        mock_agent.owner_email = None
        mock_agent.team_id = None
        mock_agent.enabled = True
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent
        mock_session_local.return_value = mock_db
        resp = client.post("/_internal/a2a/agents/my-agent/card", json={})
        assert resp.status_code == 200
        assert resp.json()["name"] == "my-agent"
