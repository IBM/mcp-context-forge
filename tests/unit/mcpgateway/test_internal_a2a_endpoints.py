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
from mcpgateway.main import _get_internal_a2a_scope_context
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
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_task")
    def test_returns_task(self, mock_get_task, _mock_scope, _mock_trust, client):
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
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_task")
    def test_task_not_found_returns_404(self, mock_get_task, _mock_scope, _mock_trust, client):
        mock_get_task.return_value = None
        resp = client.post("/_internal/a2a/tasks/get", json={"task_id": "missing"})
        assert resp.status_code == 404

    @patch(_TRUST_PATH, return_value=True)
    def test_invalid_agent_id_returns_400(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/tasks/get", json={"task_id": "t1", "agent_id": 123})
        assert resp.status_code == 400


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


class TestInternalA2AScopeContext:
    @patch("mcpgateway.main._build_internal_mcp_forwarded_user", return_value={"email": "admin@test.com"})
    @patch("mcpgateway.main._get_rpc_filter_context", return_value=("admin@test.com", None, True))
    def test_admin_with_null_teams_keeps_bypass(self, _mock_scope, _mock_user):
        assert _get_internal_a2a_scope_context(MagicMock()) == ("admin@test.com", None)

    @patch("mcpgateway.main._build_internal_mcp_forwarded_user", return_value={"email": "user@test.com"})
    @patch("mcpgateway.main._get_rpc_filter_context", return_value=("user@test.com", None, False))
    def test_non_admin_with_null_teams_becomes_public_only(self, _mock_scope, _mock_user):
        assert _get_internal_a2a_scope_context(MagicMock()) == ("user@test.com", [])


class TestTasksListTrusted:
    """tasks/list returns 200 + tasks array."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService.list_tasks")
    def test_returns_tasks(self, mock_list_tasks, _mock_scope, _mock_trust, client):
        mock_list_tasks.return_value = [{"task_id": "t1"}]
        resp = client.post("/_internal/a2a/tasks/list", json={})
        assert resp.status_code == 200
        assert resp.json()["tasks"] == [{"task_id": "t1"}]

    @patch(_TRUST_PATH, return_value=True)
    def test_invalid_agent_id_returns_400(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/tasks/list", json={"agent_id": 123})
        assert resp.status_code == 400

    @patch(_TRUST_PATH, return_value=True)
    def test_invalid_state_returns_400(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/tasks/list", json={"state": 123})
        assert resp.status_code == 400


class TestTasksCancelTrusted:
    """tasks/cancel returns 200 when task found, 404 when not."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService.cancel_task")
    def test_cancels_task(self, mock_cancel, _mock_scope, _mock_trust, client):
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
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService.cancel_task")
    def test_task_not_found_returns_404(self, mock_cancel, _mock_scope, _mock_trust, client):
        mock_cancel.return_value = None
        resp = client.post("/_internal/a2a/tasks/cancel", json={"task_id": "missing"})
        assert resp.status_code == 404

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.main.SessionLocal")
    @patch("mcpgateway.services.a2a_service.A2AAgentService.cancel_task")
    def test_scope_context_passed_through(self, mock_cancel, mock_session_cls, mock_scope, _mock_trust, client):
        """Verify that _get_internal_a2a_scope_context output is forwarded to cancel_task."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_cancel.return_value = {"task_id": "t1", "state": "canceled"}
        resp = client.post("/_internal/a2a/tasks/cancel", json={"task_id": "t1"})
        assert resp.status_code == 200
        # Verify scope context was passed through to the service method.
        _, kwargs = mock_cancel.call_args
        assert kwargs.get("user_email") == "user@test.com"
        assert kwargs.get("token_teams") == ["team-a"]

    @patch(_TRUST_PATH, return_value=True)
    def test_invalid_agent_id_returns_400(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/tasks/cancel", json={"task_id": "t1", "agent_id": 123})
        assert resp.status_code == 400


class TestPushCreateTrusted:
    """push/create returns 200 with config, 400 when required fields missing."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.create_push_config")
    def test_creates_config(self, mock_create, _mock_access, _mock_scope, _mock_trust, client):
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

    @patch(_TRUST_PATH, return_value=True)
    def test_invalid_schema_returns_400(self, _mock_trust, client):
        resp = client.post(
            "/_internal/a2a/push/create",
            json={"a2a_agent_id": "agent1", "task_id": "t1", "webhook_url": "not-a-url"},
        )
        assert resp.status_code == 400
        assert "invalid push config" in resp.json()["error"]

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=False)
    def test_hidden_agent_returns_404(self, _mock_access, _mock_scope, _mock_trust, client):
        resp = client.post(
            "/_internal/a2a/push/create",
            json={"a2a_agent_id": "agent1", "task_id": "t1", "webhook_url": "https://example.com/webhook"},
        )
        assert resp.status_code == 404


class TestPushGetTrusted:
    """push/get returns 200 + config when found, 404 when not."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_push_config")
    def test_returns_config(self, mock_get, _mock_access, _mock_scope, _mock_trust, client):
        mock_get.return_value = {"id": "cfg1", "task_id": "t1", "a2a_agent_id": "agent1"}
        resp = client.post("/_internal/a2a/push/get", json={"task_id": "t1"})
        assert resp.status_code == 200
        assert resp.json()["task_id"] == "t1"

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_push_config")
    def test_config_not_found_returns_404(self, mock_get, _mock_scope, _mock_trust, client):
        mock_get.return_value = None
        resp = client.post("/_internal/a2a/push/get", json={"task_id": "t1"})
        assert resp.status_code == 404

    @patch(_TRUST_PATH, return_value=True)
    def test_missing_task_id_returns_400(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/push/get", json={})
        assert resp.status_code == 400

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=False)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_push_config")
    def test_hidden_config_returns_404(self, mock_get, _mock_access, _mock_scope, _mock_trust, client):
        mock_get.return_value = {"id": "cfg1", "task_id": "t1", "a2a_agent_id": "agent1"}
        resp = client.post("/_internal/a2a/push/get", json={"task_id": "t1"})
        assert resp.status_code == 404


class TestPushListTrusted:
    """push/list returns 200 + configs array.

    The internal endpoint uses ``list_push_configs_for_dispatch`` (not
    ``list_push_configs``) so the Rust sidecar receives decrypted
    ``auth_token`` values for webhook dispatch.
    """

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.list_push_configs_for_dispatch")
    def test_returns_configs(self, mock_list, _mock_access, _mock_scope, _mock_trust, client):
        mock_list.return_value = [
            {"id": "cfg1", "a2a_agent_id": "agent1", "auth_token": "plaintext-1"},  # pragma: allowlist secret
            {"id": "cfg2", "a2a_agent_id": "agent1", "auth_token": None},
        ]
        resp = client.post("/_internal/a2a/push/list", json={})
        assert resp.status_code == 200
        configs = resp.json()["configs"]
        assert len(configs) == 2
        # The dispatch listing must pass decrypted tokens through to Rust.
        assert configs[0]["auth_token"] == "plaintext-1"

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService.list_push_configs_for_dispatch")
    def test_forwards_scope_context_to_service(self, mock_list, _mock_scope, _mock_trust, client):
        """Visibility is now enforced in SQL inside the service.

        The endpoint must forward ``user_email``/``token_teams`` to the
        dispatch listing method; the prior Python-side post-filter
        (``_check_agent_access_by_id`` loop) has been removed in favour of
        an ``IN (visible_agent_ids)`` clause pushed into the query.
        """
        mock_list.return_value = [
            {"id": "cfg1", "a2a_agent_id": "agent1", "auth_token": None},
        ]
        resp = client.post("/_internal/a2a/push/list", json={"agent_id": "agent1"})
        assert resp.status_code == 200
        configs = resp.json()["configs"]
        assert configs == [{"id": "cfg1", "a2a_agent_id": "agent1", "auth_token": None}]
        _, kwargs = mock_list.call_args
        assert kwargs["user_email"] == "user@test.com"
        assert kwargs["token_teams"] == ["team-a"]
        assert kwargs["agent_id"] == "agent1"


class TestPushDeleteTrusted:
    """push/delete returns 200 when deleted, 404 when not found, 400 if id missing."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.delete_push_config")
    def test_deletes_config(self, mock_delete, _mock_access, _mock_scope, _mock_trust, client):
        mock_delete.return_value = True
        resp = client.post("/_internal/a2a/push/delete", json={"config_id": "cfg1"})
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.delete_push_config")
    def test_config_not_found_returns_404(self, mock_delete, _mock_access, _mock_scope, _mock_trust, client):
        mock_delete.return_value = False
        resp = client.post("/_internal/a2a/push/delete", json={"config_id": "missing"})
        assert resp.status_code == 404

    @patch(_TRUST_PATH, return_value=True)
    def test_missing_config_id_returns_400(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/push/delete", json={})
        assert resp.status_code == 400

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.main.SessionLocal")
    def test_hidden_config_returns_404(self, mock_session_local, _mock_scope, _mock_trust, client):
        mock_cfg = MagicMock()
        mock_cfg.a2a_agent_id = "agent1"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_cfg
        mock_session_local.return_value = mock_db

        with patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=False):
            resp = client.post("/_internal/a2a/push/delete", json={"config_id": "cfg1"})
        assert resp.status_code == 404


class TestEventsFlushTrusted:
    """events/flush returns 200 + count."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("admin@test.com", None))
    @patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.flush_events")
    def test_flushes_events(self, mock_flush, _mock_access, _mock_scope, _mock_trust, client):
        mock_flush.return_value = 3
        # events without task_id skip the visibility check (nothing to look up)
        resp = client.post("/_internal/a2a/events/flush", json={"events": [{"seq": 1}, {"seq": 2}, {"seq": 3}]})
        assert resp.status_code == 200
        assert resp.json()["count"] == 3

    @patch(_TRUST_PATH, return_value=True)
    def test_empty_events_returns_zero_count(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/events/flush", json={"events": []})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team1"]))
    @patch("mcpgateway.main.SessionLocal")
    def test_rejects_events_for_inaccessible_agents(self, mock_session_cls, _mock_scope, _mock_trust, client):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        # Simulate a task row that maps to an agent the caller cannot access.
        mock_task = MagicMock()
        mock_task.task_id = "t1"
        mock_task.a2a_agent_id = "agent-123"
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_task]

        with patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=False):
            resp = client.post("/_internal/a2a/events/flush", json={"events": [{"task_id": "t1", "seq": 1}]})
        assert resp.status_code == 403
        assert "access denied" in resp.json()["error"]

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team1"]))
    @patch("mcpgateway.main.SessionLocal")
    @patch("mcpgateway.services.a2a_service.A2AAgentService.flush_events")
    def test_flushes_events_for_accessible_task_agents(self, mock_flush, mock_session_cls, _mock_scope, _mock_trust, client):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_task = MagicMock()
        mock_task.task_id = "t1"
        mock_task.a2a_agent_id = "agent-123"
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_task]
        mock_flush.return_value = 1

        with patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=True):
            resp = client.post("/_internal/a2a/events/flush", json={"events": [{"task_id": "t1", "seq": 1}]})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team1"]))
    @patch("mcpgateway.main.SessionLocal")
    def test_rejects_events_for_unknown_task_ids(self, mock_session_cls, _mock_scope, _mock_trust, client):
        """Unknown task_ids must 400 — previously they bypassed visibility entirely."""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        # No matching rows — task_id is unknown.
        mock_db.query.return_value.filter.return_value.all.return_value = []

        resp = client.post("/_internal/a2a/events/flush", json={"events": [{"task_id": "nonexistent", "seq": 1}]})
        assert resp.status_code == 400
        body = resp.json()
        assert body["unknown_task_ids"] == ["nonexistent"]


class TestEventsReplayTrusted:
    """events/replay returns 200 + events array, 400 when task_id missing."""

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("admin@test.com", None))
    @patch("mcpgateway.main.SessionLocal")
    @patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=True)
    @patch("mcpgateway.services.a2a_service.A2AAgentService.replay_events")
    def test_replays_events(self, mock_replay, _mock_access, mock_session_cls, _mock_scope, _mock_trust, client):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_task = MagicMock()
        mock_task.a2a_agent_id = "agent-1"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task
        mock_replay.return_value = [{"seq": 1, "data": "x"}]
        resp = client.post("/_internal/a2a/events/replay", json={"task_id": "t1", "after_sequence": 0})
        assert resp.status_code == 200
        assert resp.json()["events"] == [{"seq": 1, "data": "x"}]

    @patch(_TRUST_PATH, return_value=True)
    def test_missing_task_id_returns_400(self, _mock_trust, client):
        resp = client.post("/_internal/a2a/events/replay", json={})
        assert resp.status_code == 400

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team1"]))
    @patch("mcpgateway.main.SessionLocal")
    def test_rejects_replay_for_inaccessible_task(self, mock_session_cls, _mock_scope, _mock_trust, client):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_task = MagicMock()
        mock_task.a2a_agent_id = "agent-123"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        with patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=False):
            resp = client.post("/_internal/a2a/events/replay", json={"task_id": "t1", "after_sequence": 0})
        assert resp.status_code == 404

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team1"]))
    @patch("mcpgateway.main.SessionLocal")
    def test_rejects_replay_for_missing_task(self, mock_session_cls, _mock_scope, _mock_trust, client):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = client.post("/_internal/a2a/events/replay", json={"task_id": "nonexistent", "after_sequence": 0})
        assert resp.status_code == 404


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

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@example.com", ["team-a"]))
    def test_server_agent_fallback_returns_200(self, _mock_scope, _mock_trust, client):
        with patch("mcpgateway.main.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_session_local.return_value = mock_db

            with patch(
                "mcpgateway.services.a2a_server_service.A2AServerService.resolve_server_agent",
                return_value={"name": "server-agent", "endpoint_url": "https://server.example.com"},
            ):
                resp = client.post("/_internal/a2a/agents/server-agent/resolve", json={})

        assert resp.status_code == 200
        assert resp.json()["name"] == "server-agent"

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@example.com", ["team-a"]))
    def test_resolve_returns_encrypted_auth_fields(self, _mock_scope, _mock_trust, client):
        mock_agent = MagicMock()
        mock_agent.id = "agent-id-1"
        mock_agent.name = "my-agent"
        mock_agent.endpoint_url = "https://agent.example.com"
        mock_agent.agent_type = "generic"
        mock_agent.protocol_version = "1.0"
        mock_agent.auth_type = "api_key"
        mock_agent.auth_value = "enc-auth"
        mock_agent.auth_query_params = {"k": "enc-param"}
        mock_agent.enabled = True

        with patch("mcpgateway.main.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = mock_agent
            mock_session_local.return_value = mock_db

            with patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access", return_value=True):
                resp = client.post("/_internal/a2a/agents/my-agent/resolve", json={})

        assert resp.status_code == 200
        assert resp.json()["auth_value_encrypted"] == "enc-auth"
        assert resp.json()["auth_query_params_encrypted"] == {"k": "enc-param"}


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

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@example.com", ["team-a"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_agent_card", return_value=None)
    @patch("mcpgateway.services.a2a_server_service.A2AServerService.get_server_agent_card")
    @patch("mcpgateway.main.SessionLocal")
    def test_card_server_fallback_returns_200(self, mock_session_local, mock_server_card, _mock_card, _mock_scope, _mock_trust, client):
        mock_agent = MagicMock()
        mock_agent.enabled = True
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent
        mock_session_local.return_value = mock_db
        mock_server_card.return_value = {"name": "server-agent", "url": "https://server.example.com"}

        with patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access", return_value=False):
            resp = client.post("/_internal/a2a/agents/server-agent/card", json={})

        assert resp.status_code == 200
        assert resp.json()["name"] == "server-agent"


class TestInternalA2AExceptionHandling:
    def _broken_db(self):
        mock_db = MagicMock()
        mock_db.rollback.side_effect = RuntimeError("rollback failed")
        mock_db.invalidate = MagicMock()
        mock_db.close = MagicMock()
        return mock_db

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main.SessionLocal")
    @patch("mcpgateway.main._authorize_internal_mcp_request", new_callable=AsyncMock, side_effect=RuntimeError("boom"))
    def test_authz_rollback_failure_invalidates(self, _mock_authz, mock_session_local, _mock_trust, client):
        mock_db = self._broken_db()
        mock_session_local.return_value = mock_db

        resp = client.post("/_internal/a2a/get/authz", json={})

        assert resp.status_code == 500
        mock_db.rollback.assert_called_once()
        mock_db.invalidate.assert_called_once()

    @pytest.mark.parametrize(
        ("url", "body", "patch_target", "setup"),
        [
            (
                "/_internal/a2a/tasks/get",
                {"task_id": "t1"},
                "mcpgateway.services.a2a_service.A2AAgentService.get_task",
                lambda mock_db: None,
            ),
            (
                "/_internal/a2a/tasks/list",
                {},
                "mcpgateway.services.a2a_service.A2AAgentService.list_tasks",
                lambda mock_db: None,
            ),
            (
                "/_internal/a2a/tasks/cancel",
                {"task_id": "t1"},
                "mcpgateway.services.a2a_service.A2AAgentService.cancel_task",
                lambda mock_db: None,
            ),
            (
                "/_internal/a2a/push/create",
                {"a2a_agent_id": "agent1", "task_id": "t1", "webhook_url": "https://example.com/webhook"},
                "mcpgateway.services.a2a_service.A2AAgentService.create_push_config",
                lambda mock_db: None,
            ),
            (
                "/_internal/a2a/push/get",
                {"task_id": "t1"},
                "mcpgateway.services.a2a_service.A2AAgentService.get_push_config",
                lambda mock_db: None,
            ),
            (
                "/_internal/a2a/push/list",
                {},
                "mcpgateway.services.a2a_service.A2AAgentService.list_push_configs_for_dispatch",
                lambda mock_db: None,
            ),
            (
                "/_internal/a2a/push/delete",
                {"config_id": "cfg1"},
                "mcpgateway.services.a2a_service.A2AAgentService.delete_push_config",
                lambda mock_db: mock_db.query.return_value.filter.return_value.first.return_value.__setattr__("a2a_agent_id", "agent1"),
            ),
            (
                "/_internal/a2a/events/flush",
                {"events": [{"seq": 1}]},
                "mcpgateway.services.a2a_service.A2AAgentService.flush_events",
                lambda mock_db: None,
            ),
            (
                "/_internal/a2a/events/replay",
                {"task_id": "t1"},
                "mcpgateway.services.a2a_service.A2AAgentService.replay_events",
                lambda mock_db: mock_db.query.return_value.filter.return_value.first.return_value.__setattr__("a2a_agent_id", "agent1"),
            ),
        ],
    )
    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.main.SessionLocal")
    def test_endpoint_rollback_failure_invalidates(self, mock_session_local, _mock_scope, _mock_trust, url, body, patch_target, setup, client):
        mock_db = self._broken_db()
        mock_session_local.return_value = mock_db
        setup(mock_db)

        with patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access_by_id", return_value=True):
            with patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access", return_value=True):
                with patch(patch_target, side_effect=RuntimeError("boom")):
                    resp = client.post(url, json=body)

        assert resp.status_code == 500
        mock_db.rollback.assert_called_once()
        mock_db.invalidate.assert_called_once()

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.main.SessionLocal")
    def test_resolve_rollback_failure_invalidates(self, mock_session_local, _mock_scope, _mock_trust, client):
        mock_db = self._broken_db()
        mock_agent = MagicMock()
        mock_agent.enabled = True
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent
        mock_session_local.return_value = mock_db

        with patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access", side_effect=RuntimeError("boom")):
            resp = client.post("/_internal/a2a/agents/my-agent/resolve", json={})

        assert resp.status_code == 500
        mock_db.rollback.assert_called_once()
        mock_db.invalidate.assert_called_once()

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-a"]))
    @patch("mcpgateway.main.SessionLocal")
    def test_card_rollback_failure_invalidates(self, mock_session_local, _mock_scope, _mock_trust, client):
        mock_db = self._broken_db()
        mock_agent = MagicMock()
        mock_agent.enabled = True
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent
        mock_session_local.return_value = mock_db

        with patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access", return_value=True):
            with patch("mcpgateway.services.a2a_service.A2AAgentService.get_agent_card", side_effect=RuntimeError("boom")):
                resp = client.post("/_internal/a2a/agents/my-agent/card", json={})

        assert resp.status_code == 500
        mock_db.rollback.assert_called_once()
        mock_db.invalidate.assert_called_once()


# ---------------------------------------------------------------------------
# 4.  Deny-path regression tests (CLAUDE.md security-sensitive-change policy)
# ---------------------------------------------------------------------------
#
# These cover the three deny scenarios that CLAUDE.md requires for
# security-sensitive changes: insufficient permissions (RBAC), wrong team
# (token-scoping), and feature disabled.


class TestInternalA2ADenyPaths:
    """Deny-path regressions for /_internal/a2a/* endpoints."""

    # --- RBAC: insufficient permissions ---------------------------------

    @patch(_TRUST_PATH, return_value=True)
    @patch(
        "mcpgateway.main._authorize_internal_mcp_request",
        new_callable=AsyncMock,
        side_effect=JSONRPCError(-32003, "Access denied", {"method": "a2a/invoke", "permission": "a2a.invoke"}),
    )
    def test_invoke_authz_rbac_denied_returns_403(self, _mock_authorize, _mock_trust, client):
        """Missing a2a.invoke permission must return 403 with a structured error."""
        resp = client.post("/_internal/a2a/invoke/authz", json={})
        assert resp.status_code == 403
        body = resp.json()
        assert body["message"] == "Access denied"
        assert body["code"] == -32003

    @patch(_TRUST_PATH, return_value=True)
    @patch(
        "mcpgateway.main._authorize_internal_mcp_request",
        new_callable=AsyncMock,
        side_effect=JSONRPCError(-32003, "Access denied", {"method": "a2a/get", "permission": "a2a.read"}),
    )
    def test_get_authz_rbac_denied_returns_403(self, _mock_authorize, _mock_trust, client):
        """Missing a2a.read permission must return 403."""
        resp = client.post("/_internal/a2a/get/authz", json={})
        assert resp.status_code == 403
        assert resp.json()["code"] == -32003

    # --- Token scoping: wrong team --------------------------------------

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-other"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService.get_task")
    def test_tasks_get_wrong_team_returns_404(self, mock_get_task, _mock_scope, _mock_trust, client):
        """A caller scoped to team-other must not see a task owned by team-a.

        The service's visibility filter (driven by user_email/token_teams)
        returns ``None`` for resources outside the caller's scope; the
        endpoint surfaces that as a 404 — enumeration-resistant and
        indistinguishable from "not found".
        """
        mock_get_task.return_value = None
        resp = client.post("/_internal/a2a/tasks/get", json={"task_id": "t1"})
        assert resp.status_code == 404
        _, kwargs = mock_get_task.call_args
        assert kwargs.get("user_email") == "user@test.com"
        assert kwargs.get("token_teams") == ["team-other"]

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-other"]))
    @patch("mcpgateway.main.SessionLocal")
    def test_agent_resolve_wrong_team_returns_404(self, mock_session_local, _mock_scope, _mock_trust, client):
        """Wrong team on /agents/{name}/resolve must return 404 (not 403).

        The scope context narrows visibility via ``_check_agent_access``.
        When that check returns False the endpoint responds 404 — same shape
        as "agent not found" — so callers cannot enumerate agents they
        cannot see.
        """
        mock_db = MagicMock()
        mock_agent = MagicMock()
        mock_agent.enabled = True
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent
        mock_session_local.return_value = mock_db

        with patch("mcpgateway.services.a2a_service.A2AAgentService._check_agent_access", return_value=False):
            with patch("mcpgateway.services.a2a_server_service.A2AServerService.resolve_server_agent", return_value=None):
                resp = client.post("/_internal/a2a/agents/team-a-agent/resolve", json={})

        assert resp.status_code == 404

    @patch(_TRUST_PATH, return_value=True)
    @patch("mcpgateway.main._get_internal_a2a_scope_context", return_value=("user@test.com", ["team-other"]))
    @patch("mcpgateway.services.a2a_service.A2AAgentService.cancel_task")
    def test_tasks_cancel_wrong_team_returns_404(self, mock_cancel, _mock_scope, _mock_trust, client):
        """Cancel on a cross-team task must 404, and scope must be forwarded."""
        mock_cancel.return_value = None
        resp = client.post("/_internal/a2a/tasks/cancel", json={"task_id": "t1"})
        assert resp.status_code == 404
        _, kwargs = mock_cancel.call_args
        assert kwargs.get("token_teams") == ["team-other"]

    # --- Feature disabled -----------------------------------------------

    @pytest.mark.parametrize("url", _SIMPLE_ENDPOINTS + [_AUTHENTICATE_ENDPOINT])
    def test_endpoints_reject_when_a2a_disabled(self, url, client, monkeypatch):
        """With MCPGATEWAY_A2A_ENABLED=False, internal A2A endpoints must refuse.

        The feature-flag check is wired into
        ``_is_trusted_internal_mcp_runtime_request`` for ``/_internal/a2a/*``
        paths: even a request with valid sidecar headers is treated as
        untrusted when the feature is off (defense-in-depth — a legitimate
        sidecar should not be running in that configuration).
        """
        monkeypatch.setattr("mcpgateway.main.settings.mcpgateway_a2a_enabled", False)
        # Provide the sidecar headers so the only thing that can cause
        # rejection is the feature-flag branch.
        headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-mcp-runtime-auth": "stub",  # pragma: allowlist secret
        }
        with patch("mcpgateway.main._has_valid_internal_mcp_runtime_auth_header", return_value=True):
            resp = client.post(url, json={}, headers=headers)
        assert resp.status_code == 403

    @pytest.mark.parametrize("url", _AGENT_ENDPOINTS)
    def test_agent_endpoints_reject_when_a2a_disabled(self, url, client, monkeypatch):
        monkeypatch.setattr("mcpgateway.main.settings.mcpgateway_a2a_enabled", False)
        headers = {
            "x-contextforge-mcp-runtime": "rust",
            "x-contextforge-mcp-runtime-auth": "stub",  # pragma: allowlist secret
        }
        with patch("mcpgateway.main._has_valid_internal_mcp_runtime_auth_header", return_value=True):
            resp = client.post(url, json={}, headers=headers)
        assert resp.status_code == 403

    def test_mcp_runtime_endpoints_still_trusted_when_a2a_disabled(self, client, monkeypatch):
        """Disabling A2A must NOT block ``/_internal/mcp/*`` trust.

        The feature-flag gate in ``_is_trusted_internal_mcp_runtime_request``
        narrows to ``path.startswith("/_internal/a2a/")``.  A future
        refactor that hoists the A2A flag check up one level would
        silently disable all internal MCP dispatch whenever A2A is off —
        a significant availability regression for A2A-disabled
        deployments.  This test pins the path-scoped behavior.
        """
        # First-Party
        from starlette.requests import Request

        monkeypatch.setattr("mcpgateway.main.settings.mcpgateway_a2a_enabled", False)

        # Synthesize a request scope whose URL path is /_internal/mcp/...
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/_internal/mcp/authenticate",
            "raw_path": b"/_internal/mcp/authenticate",
            "query_string": b"",
            "headers": [
                (b"x-contextforge-mcp-runtime", b"rust"),
                (b"x-contextforge-mcp-runtime-auth", b"stub"),
            ],
            "client": ("127.0.0.1", 12345),
        }
        request = Request(scope)

        # First-Party
        from mcpgateway.main import _is_trusted_internal_mcp_runtime_request

        with patch("mcpgateway.main._has_valid_internal_mcp_runtime_auth_header", return_value=True):
            assert _is_trusted_internal_mcp_runtime_request(request) is True

        # And the equivalent /_internal/a2a/ path with the same headers
        # MUST still be rejected (the feature flag narrows correctly).
        a2a_scope = {**scope, "path": "/_internal/a2a/authenticate", "raw_path": b"/_internal/a2a/authenticate"}
        with patch("mcpgateway.main._has_valid_internal_mcp_runtime_auth_header", return_value=True):
            assert _is_trusted_internal_mcp_runtime_request(Request(a2a_scope)) is False
