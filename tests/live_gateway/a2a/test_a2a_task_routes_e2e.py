# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_a2a_task_routes_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks for the client-facing ``/v1/a2a/{agent_id}/tasks`` routes.

The gateway runs as a subprocess with a private SQLite DB. The test registers an
agent over HTTP, seeds task rows directly (tasks are normally written by the
invoke path), and drives list, get, cancel, and push config CRUD as the owner
and as a second user.
"""

# Standard
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
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


@pytest.fixture(scope="module")
def task_gateway(tmp_path_factory):
    """Start a gateway with one public agent and seeded tasks; yield (admin client, other-user client, agent id)."""
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

                stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
                with sqlite3.connect(db_path) as conn:
                    for i in range(TASK_COUNT):
                        conn.execute(
                            "INSERT INTO a2a_tasks (id, a2a_agent_id, task_id, state, payload, created_at, updated_at) VALUES (?, ?, ?, 'working', '{\"history\": [\"private\"]}', ?, ?)",
                            (f"row-{i}", agent_id, f"task-{i}", stamp, stamp),
                        )
                yield admin, other, agent_id
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
