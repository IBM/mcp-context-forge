# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_task_routes_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks for the client-facing ``/v1/a2a/{agent_id}/tasks`` routes.

The gateway runs as a subprocess with a private SQLite DB. The test registers an
agent over HTTP, seeds task rows directly (tasks are normally written by the
invoke path), and drives list, get, cancel, push config CRUD, and follow-up
messages as the owner and as other users. A stub JSON-RPC agent answers follow-ups.
"""

# Standard
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_COUNT = 3
WEBHOOK = {"webhook_url": "https://example.com/hook", "auth_token": "webhook-secret"}  # pragma: allowlist secret


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class _StubAgent(BaseHTTPRequestHandler):
    """Answer every JSON-RPC POST with a completed task that echoes the follow-up's task ID."""

    received = []

    def do_POST(self):  # noqa: N802
        """Record the request and reply with a completed task."""
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        _StubAgent.received.append(body)
        message = body.get("params", {}).get("message", {})
        result = {"id": message.get("taskId"), "contextId": message.get("contextId"), "status": {"state": "completed"}}
        payload = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        """Silence request logging."""


class _Gateway(tuple):
    """The ``(admin, other, agent_id)`` triple, plus the clients and IDs the follow-up tests need."""

    db_path = None
    invoker = None
    reader = None
    stub_agent_id = None


@pytest.fixture(scope="module")
def stub_agent():
    """Serve a stub A2A agent; yield its URL."""
    server = HTTPServer(("127.0.0.1", _free_port()), _StubAgent)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/invoke"
    server.shutdown()


@pytest.fixture(scope="module")
def task_gateway(tmp_path_factory, stub_agent):
    """Start a gateway with public agents and seeded tasks; yield (admin client, other-user client, agent id)."""
    tmp_path = tmp_path_factory.mktemp("a2a-task-gateway")
    port = _free_port()
    signing_key = secrets.token_urlsafe(48)
    db_path = tmp_path / "gateway.db"
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), *[str(Path(path).resolve()) for path in os.getenv("PYTHONPATH", "").split(os.pathsep) if path]]),
        "DATABASE_URL": f"sqlite:///{db_path}",
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "AUTH_REQUIRED": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "true",
        "SSRF_ALLOW_LOCALHOST": "true",
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
    }
    admin_token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    other_token = make_test_jwt("other@example.com", is_admin=False, teams=[], secret=signing_key, algorithm="HS256")
    invoker_token = make_test_jwt("invoker@example.com", is_admin=False, teams=[], scopes={"permissions": ["a2a.invoke"]}, secret=signing_key, algorithm="HS256")
    reader_token = make_test_jwt("reader@example.com", is_admin=False, teams=[], scopes={"permissions": ["a2a.read"]}, secret=signing_key, algorithm="HS256")
    log_path = tmp_path / "gateway.log"
    with log_path.open("w") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            with (
                httpx.Client(base_url=base_url, headers=make_auth_headers(admin_token), timeout=15, trust_env=False) as admin,
                httpx.Client(base_url=base_url, headers=make_auth_headers(other_token), timeout=15, trust_env=False) as other,
                httpx.Client(base_url=base_url, headers=make_auth_headers(invoker_token), timeout=15, trust_env=False) as invoker,
                httpx.Client(base_url=base_url, headers=make_auth_headers(reader_token), timeout=15, trust_env=False) as reader,
            ):
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()[-5000:]
                    try:
                        if admin.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-5000:]}")

                agent = {"name": "task-e2e", "description": "Task routes e2e", "endpoint_url": "http://127.0.0.1:9/invoke", "agent_type": "generic", "protocol_version": "1.0"}
                created = admin.post("/a2a", json={"agent": agent, "visibility": "public"})
                assert created.status_code in (200, 201), created.text
                agent_id = created.json()["id"]

                stub = {**agent, "name": "task-stub", "endpoint_url": stub_agent}
                created_stub = admin.post("/a2a", json={"agent": stub, "visibility": "public"})
                assert created_stub.status_code in (200, 201), created_stub.text
                stub_agent_id = created_stub.json()["id"]

                role = admin.post("/rbac/roles", json={"name": "a2a-tester", "description": "Invoke A2A agents", "scope": "global", "permissions": ["a2a.read", "a2a.invoke"]})
                assert role.status_code == 200, role.text
                for email in ("invoker@example.com", "reader@example.com"):
                    user = {"email": email, "password": f"Aa1!{secrets.token_urlsafe(24)}", "full_name": email, "is_admin": False}
                    assert admin.post("/auth/email/admin/users", json=user).status_code == 201
                    granted = admin.post(f"/rbac/users/{email}/roles", json={"role_id": role.json()["id"], "scope": "global"})
                    assert granted.status_code == 200, granted.text

                stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
                with sqlite3.connect(db_path) as conn:
                    for i in range(TASK_COUNT):
                        conn.execute(
                            "INSERT INTO a2a_tasks (id, a2a_agent_id, task_id, state, payload, created_at, updated_at) VALUES (?, ?, ?, 'working', '{\"history\": [\"private\"]}', ?, ?)",
                            (f"row-{i}", agent_id, f"task-{i}", stamp, stamp),
                        )
                    for row_id, task_id, state in (("stub-row-0", "ask-1", "input-required"), ("stub-row-1", "ask-2", "input-required"), ("stub-row-2", "ask-3", "input-required"), ("stub-row-3", "done-1", "completed")):
                        conn.execute(
                            "INSERT INTO a2a_tasks (id, a2a_agent_id, task_id, state, context_id, payload, created_at, updated_at) VALUES (?, ?, ?, ?, 'ctx-1', NULL, ?, ?)",
                            (row_id, stub_agent_id, task_id, state, stamp, stamp),
                        )
                gateway = _Gateway((admin, other, agent_id))
                gateway.db_path, gateway.invoker, gateway.reader, gateway.stub_agent_id = db_path, invoker, reader, stub_agent_id
                yield gateway
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_list_paginates_without_history(task_gateway):
    """Pages of two cover all tasks once and omit history."""
    admin, _other, agent_id = task_gateway
    seen, token = [], None
    for _ in range(TASK_COUNT):
        params = {"pageSize": 2, **({"pageToken": token} if token else {})}
        response = admin.get(f"/v1/a2a/{agent_id}/tasks", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert all("history" not in task for task in body["tasks"])
        seen += [task["id"] for task in body["tasks"]]
        token = body["nextPageToken"]
        if not token:
            break
    assert sorted(seen) == [f"task-{i}" for i in range(TASK_COUNT)]


def test_bad_page_token_is_400(task_gateway):
    """A malformed pageToken returns 400, not 500."""
    admin, _other, agent_id = task_gateway
    assert admin.get(f"/v1/a2a/{agent_id}/tasks", params={"pageToken": "!!"}).status_code == 400


def test_get_includes_history_and_cancel(task_gateway):
    """GET returns history; cancel moves the task to canceled."""
    admin, _other, agent_id = task_gateway
    assert admin.get(f"/v1/a2a/{agent_id}/tasks/task-0").json()["history"] == ["private"]
    canceled = admin.post(f"/v1/a2a/{agent_id}/tasks/task-0/cancel")
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"]["state"] == "canceled"


def test_push_config_crud(task_gateway):
    """Create returns 201, re-register returns 200, and delete removes the config."""
    admin, _other, agent_id = task_gateway
    url = f"/v1/a2a/{agent_id}/tasks/task-1/pushNotificationConfigs"
    first = admin.post(url, json=WEBHOOK)
    assert first.status_code == 201, first.text
    assert "auth_token" not in first.json()
    assert admin.post(url, json=WEBHOOK).status_code == 200
    config_id = first.json()["id"]
    assert admin.get(f"{url}/{config_id}").json()["id"] == config_id
    assert admin.delete(f"{url}/{config_id}").json() == {"deleted": True}
    assert admin.get(f"{url}/{config_id}").status_code == 404


def test_second_user_is_denied_everywhere(task_gateway):
    """A user who does not own the agent cannot read, cancel, or register webhooks."""
    admin, other, agent_id = task_gateway
    base = f"/v1/a2a/{agent_id}/tasks"
    config_url = f"{base}/task-2/pushNotificationConfigs"
    denied = {401, 403, 404}
    assert other.get(base).status_code in denied
    assert other.get(f"{base}/task-2").status_code in denied
    assert other.post(f"{base}/task-2/cancel").status_code in denied
    assert other.post(config_url, json=WEBHOOK).status_code in denied
    assert admin.get(config_url).json() == {"configs": []}
    assert admin.get(f"{base}/task-2").json()["status"]["state"] == "working"


def _messages_url(agent_id, task_id):
    """Return the follow-up message route."""
    return f"/v1/a2a/{agent_id}/tasks/{task_id}/messages"


def _event_payloads(db_path, task_id):
    """Return the stored task_continued payloads for a task."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT payload FROM a2a_task_events WHERE task_id = ? AND event_type = 'task_continued'", (task_id,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def test_owner_continues_an_input_required_task(task_gateway):
    """A follow-up reaches the agent bound to the stored task, updates the task, and logs a redacted event."""
    admin = task_gateway[0]
    stub_agent_id = task_gateway.stub_agent_id
    sent = len(_StubAgent.received)
    response = admin.post(_messages_url(stub_agent_id, "ask-1"), json={"text": "my-password-is-hunter2"})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["id"] == "ask-1"
    received = _StubAgent.received[sent]["params"]["message"]
    assert received["taskId"] == "ask-1" and received["contextId"] == "ctx-1"
    assert admin.get(f"/v1/a2a/{stub_agent_id}/tasks/ask-1").json()["status"]["state"] == "completed"
    [event] = _event_payloads(task_gateway.db_path, "ask-1")
    assert event["previous_state"] == "input-required" and event["state"] == "completed"
    assert event["parts"] == [{"kind": "text", "length": 22}]
    assert "hunter2" not in json.dumps(event)


def test_terminal_task_returns_409(task_gateway):
    """A completed task does not accept follow-ups."""
    sent = len(_StubAgent.received)
    response = task_gateway[0].post(_messages_url(task_gateway.stub_agent_id, "done-1"), json={"text": "more"})
    assert response.status_code == 409, response.text
    assert len(_StubAgent.received) == sent


def test_unknown_task_returns_404(task_gateway):
    """An unknown task returns 404 and never reaches the agent."""
    sent = len(_StubAgent.received)
    assert task_gateway[0].post(_messages_url(task_gateway.stub_agent_id, "missing"), json={"text": "x"}).status_code == 404
    assert len(_StubAgent.received) == sent


def test_mismatching_identity_fields_return_400(task_gateway):
    """A message that names another task or context is rejected."""
    admin = task_gateway[0]
    url = _messages_url(task_gateway.stub_agent_id, "ask-2")
    assert admin.post(url, json={"message": {"taskId": "other", "parts": [{"text": "x"}]}}).status_code == 400
    assert admin.post(url, json={"message": {"contextId": "other", "parts": [{"text": "x"}]}}).status_code == 400
    assert admin.post(url, json={"message": {"role": "agent", "parts": [{"text": "x"}]}}).status_code == 400


def test_follow_up_without_credentials_is_401(task_gateway):
    """A request without a token is rejected and never reaches the agent."""
    sent = len(_StubAgent.received)
    with httpx.Client(base_url=str(task_gateway[0].base_url), timeout=15, trust_env=False) as anonymous:
        assert anonymous.post(_messages_url(task_gateway.stub_agent_id, "ask-3"), json={"text": "x"}).status_code == 401
    assert len(_StubAgent.received) == sent


def test_follow_up_without_invoke_permission_is_403(task_gateway):
    """A token limited to a2a.read cannot send a follow-up."""
    sent = len(_StubAgent.received)
    assert task_gateway.reader.post(_messages_url(task_gateway.stub_agent_id, "ask-3"), json={"text": "x"}).status_code == 403
    assert len(_StubAgent.received) == sent


def test_invoker_who_does_not_own_the_agent_gets_404(task_gateway):
    """A caller with a2a.invoke who can see a public agent still cannot continue another user's task."""
    admin, invoker = task_gateway[0], task_gateway.invoker
    sent = len(_StubAgent.received)
    url = _messages_url(task_gateway.stub_agent_id, "ask-3")
    assert invoker.get(f"/v1/a2a/{task_gateway.stub_agent_id}/tasks/ask-3").status_code in (403, 404)
    assert invoker.post(url, json={"text": "hijack"}).status_code == 404
    assert len(_StubAgent.received) == sent
    assert admin.get(f"/v1/a2a/{task_gateway.stub_agent_id}/tasks/ask-3").json()["status"]["state"] == "input-required"
