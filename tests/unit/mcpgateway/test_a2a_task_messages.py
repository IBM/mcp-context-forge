# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_task_messages.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Follow-up message route for existing A2A tasks (issue #6703).
"""

# Standard
from unittest.mock import AsyncMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.main import app, get_current_user_with_permissions
from mcpgateway.middleware.token_scoping import _PERMISSION_PATTERNS

BASE = "/v1/a2a/agent-1/tasks"
HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture
def service():
    """Patch the module-level A2A service."""
    with patch("mcpgateway.main.a2a_service") as svc:
        svc.check_agent_manage_access = AsyncMock(return_value=True)
        yield svc


@pytest.fixture
def client():
    """Test client authenticated as an admin."""
    app.dependency_overrides[get_current_user_with_permissions] = lambda: {"sub": "a@example.com", "email": "a@example.com", "is_admin": True, "teams": None}
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestTaskMessages:
    """Follow-up messages to an existing task."""

    URL = f"{BASE}/t1/messages"

    @pytest.fixture(autouse=True)
    def continue_task(self, service):
        """Stub the service continuation."""
        service.continue_task = AsyncMock(return_value={"result": {"id": "t1"}})
        return service.continue_task

    def test_text_shorthand_becomes_text_part(self, continue_task, client):
        """A ``text`` body is expanded to a single text part and bound to the path IDs."""
        resp = client.post(self.URL, json={"text": "yes, proceed"}, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"result": {"id": "t1"}}
        args = continue_task.call_args.args
        assert args[1:] == ("agent-1", "t1", {"parts": [{"text": "yes, proceed"}]})

    def test_message_passthrough(self, continue_task, client):
        """A ``message`` body reaches the service as sent."""
        message = {"role": "ROLE_USER", "parts": [{"text": "hi"}]}
        client.post(self.URL, json={"message": message}, headers=HEADERS)
        assert continue_task.call_args.args[3] == message

    def test_non_owner_gets_404_and_service_is_not_called(self, service, continue_task, client):
        """A caller who cannot manage the agent is denied before any task lookup or agent call."""
        service.check_agent_manage_access.return_value = False
        resp = client.post(self.URL, json={"text": "x"}, headers=HEADERS)
        assert resp.status_code == 404
        continue_task.assert_not_called()

    def test_success_writes_an_audit_entry_with_ids_only(self, client):
        """A follow-up is audited by agent and task ID, never by message content."""
        with patch("mcpgateway.main._audit_a2a_task_action") as audit:
            client.post(self.URL, json={"text": "secret-answer"}, headers=HEADERS)
        assert audit.call_args.args[2:] == ("continue_a2a_task", "agent-1", "t1")
        assert "secret-answer" not in str(audit.call_args)

    def test_failed_follow_up_is_not_audited(self, continue_task, client):
        """A rejected follow-up leaves no audit entry."""
        # First-Party
        from mcpgateway.services.a2a_service import A2ATaskStateError

        continue_task.side_effect = A2ATaskStateError("done")
        with patch("mcpgateway.main._audit_a2a_task_action") as audit:
            assert client.post(self.URL, json={"text": "x"}, headers=HEADERS).status_code == 409
        audit.assert_not_called()

    @pytest.mark.parametrize(
        "body",
        [
            {"message": {"parts": [{"text": "x"}], "unexpected": 1}},
            {"message": {"parts": [{"text": "x"}] * 51}},
            {"message": {"parts": [{"text": "x" * 65537}]}},
            {"text": "x" * 65537},
        ],
    )
    def test_oversized_or_unknown_message_fields_422(self, continue_task, client, body):
        """Unknown message fields, too many parts and oversized text are rejected before the service."""
        assert client.post(self.URL, json=body, headers=HEADERS).status_code == 422
        continue_task.assert_not_called()

    @pytest.mark.parametrize("body", [{}, {"text": "a", "message": {"parts": [{"text": "b"}]}}, {"message": {"parts": []}}, {"message": {}}, {"text": ""}])
    def test_invalid_body_422(self, continue_task, client, body):
        """Zero or two payloads, or a message without parts, return 422."""
        assert client.post(self.URL, json=body, headers=HEADERS).status_code == 422
        continue_task.assert_not_called()

    @pytest.mark.parametrize(
        "error, status",
        [("A2AAgentNotFoundError", 404), ("A2ATaskStateError", 409), ("A2AAgentError", 400)],
    )
    def test_error_mapping(self, continue_task, client, error, status):
        """Unknown task is 404, terminal task is 409, other agent errors are 400."""
        # First-Party
        from mcpgateway.services import a2a_service

        continue_task.side_effect = getattr(a2a_service, error)("boom")
        resp = client.post(self.URL, json={"text": "x"}, headers=HEADERS)
        assert resp.status_code == status
        assert resp.json()["detail"] == "boom"


def test_token_scope_maps_messages_to_invoke():
    """The follow-up route requires a2a.invoke under token scoping."""
    assert next(p for m, rx, p in _PERMISSION_PATTERNS if m == "POST" and rx.match("/a2a/a/tasks/t/messages")) == "a2a.invoke"
