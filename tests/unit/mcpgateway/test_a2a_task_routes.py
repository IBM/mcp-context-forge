# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_task_routes.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Client-facing A2A task and push notification config routes (issue #6702).
"""

# Standard
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.main import _decode_a2a_page_token, _encode_a2a_page_token, app, get_current_user_with_permissions

BASE = "/v1/a2a/agent-1/tasks"
HEADERS = {"Authorization": "Bearer test-token"}
CONFIG = {"id": "cfg-1", "a2a_agent_id": "agent-1", "task_id": "t1", "webhook_url": "https://example.com/hook", "events": None, "enabled": True}


@pytest.fixture
def service():
    """Patch the module-level A2A service."""
    with patch("mcpgateway.main.a2a_service") as svc:
        svc.get_task = AsyncMock(return_value={"id": "t1"})
        svc.cancel_task = AsyncMock(return_value={"id": "t1", "status": {"state": "canceled"}})
        svc.list_tasks = MagicMock(return_value=[])
        svc.list_push_configs = MagicMock(return_value=[CONFIG])
        svc.create_push_config = MagicMock(return_value=CONFIG)
        svc.delete_push_config = MagicMock(return_value=True)
        yield svc


@pytest.fixture
def client():
    """Test client authenticated as an admin."""
    app.dependency_overrides[get_current_user_with_permissions] = lambda: {"sub": "a@example.com", "email": "a@example.com", "is_admin": True, "teams": None}
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestPageToken:
    """pageToken round trip."""

    def test_round_trip(self):
        """An encoded offset decodes to itself."""
        assert _decode_a2a_page_token(_encode_a2a_page_token(150)) == 150

    def test_missing_token_is_zero(self):
        """No token starts at the first page."""
        assert _decode_a2a_page_token(None) == 0

    @pytest.mark.parametrize("token", ["not-base64!!", "e30=", _encode_a2a_page_token(-1)])
    def test_invalid_token_rejected(self, token):
        """Malformed or negative tokens raise 400."""
        with pytest.raises(Exception) as exc:
            _decode_a2a_page_token(token)
        assert getattr(exc.value, "status_code", None) == 400


class TestTasks:
    """List, get and cancel."""

    def test_list_paginates(self, service, client):
        """A full extra row yields a nextPageToken that resumes at the next offset."""
        service.list_tasks.return_value = [{"id": f"t{i}"} for i in range(3)]
        body = client.get(BASE, params={"pageSize": 2}, headers=HEADERS).json()
        assert [t["id"] for t in body["tasks"]] == ["t0", "t1"]
        assert _decode_a2a_page_token(body["nextPageToken"]) == 2
        assert service.list_tasks.call_args.kwargs["limit"] == 3

    def test_list_last_page_has_empty_token(self, service, client):
        """The last page returns an empty nextPageToken."""
        service.list_tasks.return_value = [{"id": "t0"}]
        body = client.get(BASE, params={"pageSize": 2, "pageToken": _encode_a2a_page_token(4)}, headers=HEADERS).json()
        assert body == {"tasks": [{"id": "t0"}], "nextPageToken": ""}
        assert service.list_tasks.call_args.kwargs["offset"] == 4

    def test_list_bad_token_400(self, service, client):
        """An invalid pageToken returns 400."""
        assert client.get(BASE, params={"pageToken": "!!"}, headers=HEADERS).status_code == 400

    def test_get_found(self, service, client):
        """GET returns the task."""
        assert client.get(f"{BASE}/t1", headers=HEADERS).json() == {"id": "t1"}

    def test_get_not_visible_404(self, service, client):
        """A task hidden by visibility scoping returns 404."""
        service.get_task.return_value = None
        assert client.get(f"{BASE}/t1", headers=HEADERS).status_code == 404

    def test_cancel(self, service, client):
        """POST cancel returns the canceled task."""
        assert client.post(f"{BASE}/t1/cancel", headers=HEADERS).json()["status"]["state"] == "canceled"

    def test_cancel_not_visible_404(self, service, client):
        """Cancel of a hidden task returns 404."""
        service.cancel_task.return_value = None
        assert client.post(f"{BASE}/t1/cancel", headers=HEADERS).status_code == 404

    def test_service_disabled_503(self, client):
        """A disabled A2A service returns 503."""
        with patch("mcpgateway.main.a2a_service", None):
            assert client.get(BASE, headers=HEADERS).status_code == 503


class TestPushConfigs:
    """Push notification config CRUD."""

    URL = f"{BASE}/t1/pushNotificationConfigs"

    def test_create_takes_ids_from_path(self, service, client):
        """Agent and task IDs come from the path, never the body."""
        resp = client.post(self.URL, json={"webhook_url": "https://example.com/hook", "a2a_agent_id": "evil", "task_id": "evil"}, headers=HEADERS)
        assert resp.status_code == 201
        data = service.create_push_config.call_args.args[1]
        assert data["a2a_agent_id"] == "agent-1" and data["task_id"] == "t1"

    def test_create_rejects_ssrf_url(self, service, client):
        """A webhook URL pointing at metadata endpoints is rejected."""
        assert client.post(self.URL, json={"webhook_url": "http://169.254.169.254/x"}, headers=HEADERS).status_code == 422

    def test_create_hidden_task_404(self, service, client):
        """Creating a config for an invisible task returns 404 and writes nothing."""
        service.get_task.return_value = None
        assert client.post(self.URL, json={"webhook_url": "https://example.com/hook"}, headers=HEADERS).status_code == 404
        service.create_push_config.assert_not_called()

    def test_list(self, service, client):
        """GET lists configs."""
        assert client.get(self.URL, headers=HEADERS).json() == {"configs": [CONFIG]}

    def test_get_and_missing(self, service, client):
        """GET by ID returns the config, or 404 for an unknown ID."""
        assert client.get(f"{self.URL}/cfg-1", headers=HEADERS).json()["id"] == "cfg-1"
        assert client.get(f"{self.URL}/nope", headers=HEADERS).status_code == 404

    def test_delete(self, service, client):
        """DELETE removes the config."""
        assert client.delete(f"{self.URL}/cfg-1", headers=HEADERS).json() == {"deleted": True}
        service.delete_push_config.assert_called_once_with(service.delete_push_config.call_args.args[0], "cfg-1")

    def test_delete_other_task_config_404(self, service, client):
        """A config ID that does not belong to the path task cannot be deleted."""
        assert client.delete(f"{self.URL}/other", headers=HEADERS).status_code == 404
        service.delete_push_config.assert_not_called()

    def test_hidden_task_blocks_all_operations(self, service, client):
        """Every config operation returns 404 when the task is not visible."""
        service.get_task.return_value = None
        assert client.get(self.URL, headers=HEADERS).status_code == 404
        assert client.get(f"{self.URL}/cfg-1", headers=HEADERS).status_code == 404
        assert client.delete(f"{self.URL}/cfg-1", headers=HEADERS).status_code == 404
        service.delete_push_config.assert_not_called()


class TestTokenScopeMapping:
    """Token-scoping permission mapping for the new routes."""

    def test_mapping(self):
        """Reads map to a2a.read, cancel to a2a.invoke, config writes to a2a.update."""
        # First-Party
        from mcpgateway.middleware import token_scoping

        table = next(v for v in vars(token_scoping).values() if isinstance(v, list) and v and isinstance(v[0], tuple) and len(v[0]) == 3 and hasattr(v[0][1], "match"))

        def perm(method: str, path: str) -> Optional[str]:
            return next((p for m, rx, p in table if m == method and rx.match(path)), None)

        assert perm("GET", "/a2a/a/tasks/t") == "a2a.read"
        assert perm("POST", "/a2a/a/tasks/t/cancel") == "a2a.invoke"
        assert perm("POST", "/a2a/a/tasks/t/pushNotificationConfigs") == "a2a.update"
        assert perm("DELETE", "/a2a/a/tasks/t/pushNotificationConfigs/c") == "a2a.update"
