# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_task_routes.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Client-facing A2A task and push notification config routes (issue #6702).
"""

# Standard
import base64
from datetime import datetime, timedelta, timezone
import json
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import A2AAgent, A2APushNotificationConfig, A2ATask, Base
from mcpgateway.main import _decode_a2a_page_token, _encode_a2a_page_token, app, get_current_user_with_permissions, get_db
from mcpgateway.services.a2a_service import A2AAgentService

BASE = "/v1/a2a/agent-1/tasks"
HEADERS = {"Authorization": "Bearer test-token"}
CONFIG = {"id": "cfg-1", "a2a_agent_id": "agent-1", "task_id": "t1", "webhook_url": "https://example.com/hook", "events": None, "enabled": True}


@pytest.fixture
def service():
    """Patch the module-level A2A service."""
    with patch("mcpgateway.main.a2a_service") as svc:
        svc.get_task = AsyncMock(return_value={"id": "t1"})
        svc.cancel_task = AsyncMock(return_value={"id": "t1", "status": {"state": "canceled"}})
        svc.check_agent_manage_access = AsyncMock(return_value=True)
        svc.list_tasks_page = MagicMock(return_value=[])
        svc.has_push_config = MagicMock(return_value=False)
        svc.find_push_config = MagicMock(return_value=CONFIG)
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


def _raw_token(payload) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


class TestPageToken:
    """pageToken round trip and validation."""

    def test_round_trip(self):
        """An encoded cursor decodes to itself."""
        ts = datetime(2026, 1, 2, 3, 4, 5, 678, tzinfo=timezone.utc)
        assert _decode_a2a_page_token(_encode_a2a_page_token(ts, "row-1")) == (ts, "row-1")

    def test_missing_token_is_none(self):
        """No token starts at the first page."""
        assert _decode_a2a_page_token(None) is None

    @pytest.mark.parametrize(
        "token",
        [
            "not-base64!!",
            "e30=",
            _raw_token({"o": 1e309}),
            _raw_token({"o": 2**64}),
            _raw_token({"u": 5, "i": "x"}),
            _raw_token({"u": "2026-01-01T00:00:00", "i": 7}),
            _raw_token({"u": "2026-01-01T00:00:00", "i": ""}),
            _raw_token({"u": "2026-01-01T00:00:00", "i": "x" * 37}),
            _raw_token({"u": "not-a-date", "i": "x"}),
            _raw_token([1, 2]),
        ],
    )
    def test_invalid_token_rejected(self, token):
        """Malformed tokens raise 400."""
        with pytest.raises(Exception) as exc:
            _decode_a2a_page_token(token)
        assert getattr(exc.value, "status_code", None) == 400


class TestTasks:
    """List, get and cancel."""

    def test_list_paginates(self, service, client):
        """A full extra row yields a nextPageToken built from the last returned row."""
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        service.list_tasks_page.return_value = [({"id": f"t{i}"}, ts, f"r{i}") for i in range(3)]
        body = client.get(BASE, params={"pageSize": 2}, headers=HEADERS).json()
        assert [t["id"] for t in body["tasks"]] == ["t0", "t1"]
        assert _decode_a2a_page_token(body["nextPageToken"]) == (ts, "r1")
        assert service.list_tasks_page.call_args.kwargs["limit"] == 3

    def test_list_last_page_has_empty_token(self, service, client):
        """The last page returns an empty nextPageToken and passes the cursor to the service."""
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        service.list_tasks_page.return_value = [({"id": "t0"}, ts, "r0")]
        body = client.get(BASE, params={"pageSize": 2, "pageToken": _encode_a2a_page_token(ts, "r9")}, headers=HEADERS).json()
        assert body == {"tasks": [{"id": "t0"}], "nextPageToken": ""}
        assert service.list_tasks_page.call_args.kwargs["after"] == (ts, "r9")

    def test_list_bad_state_422(self, service, client):
        """An unknown state filter is rejected."""
        assert client.get(BASE, params={"state": "bogus"}, headers=HEADERS).status_code == 422

    def test_agent_not_manageable_404(self, service, client):
        """List, get and cancel return 404 when the caller cannot manage the agent."""
        service.check_agent_manage_access.return_value = False
        assert client.get(BASE, headers=HEADERS).status_code == 404
        assert client.get(f"{BASE}/t1", headers=HEADERS).status_code == 404
        assert client.post(f"{BASE}/t1/cancel", headers=HEADERS).status_code == 404
        service.cancel_task.assert_not_called()

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

    def test_service_disabled_404(self, client):
        """A disabled A2A service returns the typed a2a_disabled 404."""
        with patch("mcpgateway.main.a2a_service", None):
            response = client.get(BASE, headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["detail"]["error"] == "a2a_disabled"


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

    def test_create_existing_returns_200(self, service, client):
        """Re-registering an existing webhook URL returns 200, not 201."""
        service.has_push_config.return_value = True
        resp = client.post(self.URL, json={"webhook_url": "https://example.com/hook"}, headers=HEADERS)
        assert resp.status_code == 200

    def test_get_and_missing(self, service, client):
        """GET by ID returns the config, or 404 for an unknown ID."""
        assert client.get(f"{self.URL}/cfg-1", headers=HEADERS).json()["id"] == "cfg-1"
        service.find_push_config.return_value = None
        assert client.get(f"{self.URL}/nope", headers=HEADERS).status_code == 404

    def test_delete(self, service, client):
        """DELETE removes the config."""
        assert client.delete(f"{self.URL}/cfg-1", headers=HEADERS).json() == {"deleted": True}
        service.delete_push_config.assert_called_once_with(service.delete_push_config.call_args.args[0], "cfg-1", agent_id="agent-1", task_id="t1")

    def test_delete_other_task_config_404(self, service, client):
        """A config ID that does not belong to the path task cannot be deleted."""
        service.delete_push_config.return_value = False
        assert client.delete(f"{self.URL}/other", headers=HEADERS).status_code == 404

    def test_hidden_task_blocks_all_operations(self, service, client):
        """Every config operation returns 404 when the task is not visible."""
        service.get_task.return_value = None
        assert client.get(self.URL, headers=HEADERS).status_code == 404
        assert client.get(f"{self.URL}/cfg-1", headers=HEADERS).status_code == 404
        assert client.delete(f"{self.URL}/cfg-1", headers=HEADERS).status_code == 404
        service.delete_push_config.assert_not_called()

    def test_writes_blocked_for_non_owner(self, service, client):
        """Config create and delete return 404 when the caller does not manage the agent."""
        service.check_agent_manage_access.return_value = False
        assert client.post(self.URL, json={"webhook_url": "https://example.com/hook"}, headers=HEADERS).status_code == 404
        assert client.delete(f"{self.URL}/cfg-1", headers=HEADERS).status_code == 404
        service.create_push_config.assert_not_called()
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


OWNER = "owner@example.com"
OTHER = "other@example.com"


@pytest.fixture
def real_db():
    """In-memory SQLite database with one team agent, its task, and a webhook config."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    db.add(A2AAgent(id="agent-1", name="a", slug="a", endpoint_url="https://agent.example.com", owner_email=OWNER, visibility="public", team_id="team-1"))
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(5):
        db.add(A2ATask(id=f"row-{i}", a2a_agent_id="agent-1", task_id=f"t{i}", state="working", payload={"history": ["secret"]}, updated_at=base))
    db.add(A2APushNotificationConfig(id="cfg-1", a2a_agent_id="agent-1", task_id="t0", webhook_url="https://example.com/hook"))
    db.commit()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield db
    app.dependency_overrides.clear()
    db.close()


def _as(email: str, teams, is_admin: bool = False) -> TestClient:
    app.dependency_overrides[get_current_user_with_permissions] = lambda: {"sub": email, "email": email, "is_admin": is_admin, "teams": teams}
    return TestClient(app)


@pytest.fixture(autouse=False)
def allow_rbac():
    """Grant every RBAC permission so the tests exercise ownership and visibility only."""
    with patch("mcpgateway.middleware.rbac.PermissionService.check_permission", new=AsyncMock(return_value=True)):
        yield


@pytest.mark.usefixtures("real_db", "allow_rbac")
class TestOwnershipDenyPaths:
    """Real-DB deny paths: only the agent owner may read tasks or manage webhooks."""

    URL = f"{BASE}/t0/pushNotificationConfigs"

    def test_owner_allowed(self):
        """The agent owner lists, reads and cancels tasks."""
        c = _as(OWNER, ["team-1"])
        assert len(c.get(BASE, headers=HEADERS).json()["tasks"]) == 5
        assert c.get(f"{BASE}/t0", headers=HEADERS).status_code == 200
        assert c.post(f"{BASE}/t0/cancel", headers=HEADERS).json()["status"]["state"] == "canceled"

    def test_list_omits_history(self):
        """List summaries omit history while a single GET includes it."""
        c = _as(OWNER, ["team-1"])
        assert "history" not in c.get(BASE, headers=HEADERS).json()["tasks"][0]
        assert c.get(f"{BASE}/t1", headers=HEADERS).json()["history"] == ["secret"]

    @pytest.mark.parametrize("teams", [[], ["team-1"]])
    def test_non_owner_cannot_read_or_cancel(self, teams):
        """A caller who sees the public agent but does not own it gets 404, including with a public-only token."""
        c = _as(OTHER, teams)
        assert c.get(BASE, headers=HEADERS).status_code == 404
        assert c.get(f"{BASE}/t0", headers=HEADERS).status_code == 404
        assert c.post(f"{BASE}/t0/cancel", headers=HEADERS).status_code == 404

    def test_non_owner_cannot_write_configs(self, real_db):
        """A non-owner cannot create, overwrite, list, or delete webhook configs."""
        c = _as(OTHER, [])
        assert c.post(self.URL, json={"webhook_url": "https://example.com/hook", "auth_token": "x"}, headers=HEADERS).status_code == 404
        assert c.get(self.URL, headers=HEADERS).status_code == 404
        assert c.delete(f"{self.URL}/cfg-1", headers=HEADERS).status_code == 404
        cfg = real_db.query(A2APushNotificationConfig).filter_by(id="cfg-1").one()
        assert cfg.auth_token is None

    def test_owner_config_lifecycle(self):
        """The owner creates (201), updates (200), reads, and deletes a config."""
        c = _as(OWNER, ["team-1"])
        first = c.post(self.URL, json={"webhook_url": "https://example.com/new"}, headers=HEADERS)
        assert first.status_code == 201
        assert c.post(self.URL, json={"webhook_url": "https://example.com/new", "enabled": False}, headers=HEADERS).status_code == 200
        cfg_id = first.json()["id"]
        assert c.get(f"{self.URL}/{cfg_id}", headers=HEADERS).json()["webhook_url"] == "https://example.com/new"
        assert c.delete(f"{self.URL}/{cfg_id}", headers=HEADERS).json() == {"deleted": True}
        assert c.get(f"{self.URL}/{cfg_id}", headers=HEADERS).status_code == 404

    def test_config_of_other_task_not_reachable(self):
        """A config ID scoped to task t0 is not readable or deletable under task t1."""
        c = _as(OWNER, ["team-1"])
        other = f"{BASE}/t1/pushNotificationConfigs/cfg-1"
        assert c.get(other, headers=HEADERS).status_code == 404
        assert c.delete(other, headers=HEADERS).status_code == 404


@pytest.mark.usefixtures("real_db", "allow_rbac")
class TestKeysetPagination:
    """Rows sharing an updated_at page without gaps or duplicates."""

    def test_full_walk_has_no_gaps_or_duplicates(self):
        """Walking pages of two over five tied rows returns each task exactly once."""
        c = _as(OWNER, ["team-1"])
        seen, token = [], None
        for _ in range(5):
            params = {"pageSize": 2, **({"pageToken": token} if token else {})}
            body = c.get(BASE, params=params, headers=HEADERS).json()
            seen += [t["id"] for t in body["tasks"]]
            token = body["nextPageToken"]
            if not token:
                break
        assert sorted(seen) == [f"t{i}" for i in range(5)]
        assert len(seen) == len(set(seen))

    def test_cancel_between_pages_does_not_skip(self):
        """Updating a task that was already returned does not shift later pages."""
        c = _as(OWNER, ["team-1"])
        first = c.get(BASE, params={"pageSize": 2}, headers=HEADERS).json()
        assert c.post(f"{BASE}/{first['tasks'][0]['id']}/cancel", headers=HEADERS).status_code == 200
        rest = c.get(BASE, params={"pageSize": 10, "pageToken": first["nextPageToken"]}, headers=HEADERS).json()
        assert len(first["tasks"]) + len(rest["tasks"]) == 5


class TestManageAccess:
    """check_agent_manage_access on the service."""

    @pytest.mark.asyncio
    async def test_unknown_agent_denied(self, real_db):
        """A missing agent is denied."""
        assert not await A2AAgentService().check_agent_manage_access(real_db, "nope", OWNER, ["team-1"])

    @pytest.mark.asyncio
    async def test_owner_allowed_other_denied(self, real_db):
        """The owner passes and a different user fails."""
        svc = A2AAgentService()
        assert await svc.check_agent_manage_access(real_db, "agent-1", OWNER, ["team-1"])
        assert not await svc.check_agent_manage_access(real_db, "agent-1", OTHER, ["team-1"])

    @pytest.mark.asyncio
    async def test_anonymous_requires_admin_bypass(self, real_db):
        """Without an email, only admin bypass (token_teams None) passes."""
        svc = A2AAgentService()
        assert await svc.check_agent_manage_access(real_db, "agent-1", None, None)
        assert not await svc.check_agent_manage_access(real_db, "agent-1", None, [])
