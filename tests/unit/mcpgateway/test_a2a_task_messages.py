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
from mcpgateway.middleware import token_scoping

BASE = "/v1/a2a/agent-1/tasks"
HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture
def service():
    """Patch the module-level A2A service."""
    with patch("mcpgateway.main.a2a_service") as svc:
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
    table = next(v for v in vars(token_scoping).values() if isinstance(v, list) and v and isinstance(v[0], tuple) and len(v[0]) == 3 and hasattr(v[0][1], "match"))
    assert next(p for m, rx, p in table if m == "POST" and rx.match("/a2a/a/tasks/t/messages")) == "a2a.invoke"


def test_service_disabled_503(client):
    """A disabled A2A service returns 503."""
    with patch("mcpgateway.main.a2a_service", None):
        assert client.post(f"{BASE}/t1/messages", json={"text": "x"}, headers=HEADERS).status_code == 503
