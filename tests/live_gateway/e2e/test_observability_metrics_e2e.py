# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_observability_metrics_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box observability metrics checks against an isolated gateway subprocess.

The gateway uses a temporary SQLite database and accepts only this test's
traffic. No existing gateway, Redis instance, or credentials are used.
"""

from __future__ import annotations

# Standard
from collections.abc import Callable, Generator
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]
_OBSERVABILITY_WINDOW_HOURS = 1
_OBSERVABILITY_INTERVAL_MINUTES = 5


def _build_initialize(request_id: int = 1) -> dict[str, object]:
    """Build an MCP initialize request.

    Args:
        request_id: JSON-RPC request identifier.

    Returns:
        An MCP initialize request payload.
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "observability-metrics-test", "version": "1.0.0"},
        },
    }


def _wait_for_gateway(process: subprocess.Popen[bytes], client: httpx.Client, log_path: Path) -> None:
    """Wait until an isolated gateway becomes healthy.

    Args:
        process: Gateway subprocess.
        client: Client for the isolated gateway.
        log_path: Gateway log path for startup failures.
    """
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        assert process.poll() is None, log_path.read_text(encoding="utf-8")[-5000:]
        try:
            if client.get("/health").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    pytest.fail(f"Gateway startup timed out: {log_path.read_text(encoding='utf-8')[-5000:]}")


def _platform_viewer_client(admin_client: httpx.Client, base_url: str) -> httpx.Client:
    """Create a platform viewer and return its authenticated client.

    Args:
        admin_client: Administrator client for user creation and role checks.
        base_url: Isolated gateway base URL.

    Returns:
        A client authenticated with the platform viewer's session token.
    """
    email = f"observability-viewer-{uuid.uuid4().hex[:8]}@test.com"
    password = f"Aa1!{secrets.token_urlsafe(24)}"
    created = admin_client.post(
        "/auth/email/admin/users",
        json={
            "email": email,
            "password": password,
            "full_name": "Observability Metrics Viewer",
            "is_admin": False,
            "is_active": True,
            "password_change_required": False,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_admin"] is False

    roles = admin_client.get("/rbac/roles")
    assert roles.status_code == 200, roles.text
    platform_viewer_id = next(role["id"] for role in roles.json() if role.get("name") == "platform_viewer")

    assignments = admin_client.get(f"/rbac/users/{email}/roles")
    assert assignments.status_code == 200, assignments.text
    assert any(assignment["role_id"] == platform_viewer_id and assignment.get("scope") == "global" for assignment in assignments.json())

    login = httpx.post(
        f"{base_url}/auth/email/login",
        json={"email": email, "password": password},
        timeout=15,
        trust_env=False,
    )
    assert login.status_code == 200, login.text
    login_payload = login.json()
    assert login_payload["user"]["is_admin"] is False
    return httpx.Client(base_url=base_url, headers=make_auth_headers(login_payload["access_token"]), timeout=15, trust_env=False)


@pytest.fixture(name="isolated_observability_gateway")
def _isolated_observability_gateway(tmp_path: Path, unused_tcp_port_factory: Callable[[], int]) -> Generator[httpx.Client, None, None]:
    """Start an observable gateway with a private SQLite database.

    Args:
        tmp_path: Temporary directory owned by pytest.
        unused_tcp_port_factory: Factory that selects an available TCP port.

    Yields:
        A client authenticated as a global platform viewer.
    """
    port = unused_tcp_port_factory()
    base_url = f"http://127.0.0.1:{port}"
    signing_key = secrets.token_urlsafe(48)
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), *[str(Path(path).resolve()) for path in os.getenv("PYTHONPATH", "").split(os.pathsep) if path]]),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "AUTH_REQUIRED": "true",
        "MCP_REQUIRE_AUTH": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        "PLUGINS_ENABLED": "false",
        "OBSERVABILITY_ENABLED": "true",
        "LOG_LEVEL": "ERROR",
        "PYTHONUNBUFFERED": "1",
    }
    admin_token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    log_path = tmp_path / "gateway.log"
    with log_path.open("w") as log_file:
        with subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp_path,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        ) as process:
            try:
                with httpx.Client(base_url=base_url, headers=make_auth_headers(admin_token), timeout=15, trust_env=False) as admin_client:
                    _wait_for_gateway(process, admin_client, log_path)
                    with _platform_viewer_client(admin_client, base_url) as viewer_client:
                        yield viewer_client
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _observability_timeseries_totals(client: httpx.Client) -> tuple[int, int, int]:
    """Return total, successful, and failed traces from the metrics endpoint.

    Args:
        client: Client authenticated as a global metrics reader.

    Returns:
        The three trace totals across the query window.
    """
    response = client.get(
        "/v1/observability/metrics/timeseries",
        params={"hours": _OBSERVABILITY_WINDOW_HOURS, "interval_minutes": _OBSERVABILITY_INTERVAL_MINUTES},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    series_names = ("buckets", "values", "success_count", "error_count")
    assert set(payload) == set(series_names)
    assert len({len(payload[name]) for name in series_names}) == 1
    assert all(isinstance(bucket, str) for bucket in payload["buckets"])
    assert all(isinstance(value, int) for name in series_names[1:] for value in payload[name])
    assert all(success + error <= total for total, success, error in zip(payload["values"], payload["success_count"], payload["error_count"], strict=True))
    return sum(payload["values"]), sum(payload["success_count"]), sum(payload["error_count"])


def test_observability_timeseries_status_counts(isolated_observability_gateway: httpx.Client) -> None:
    """A platform viewer sees exact counts from its isolated gateway."""
    client = isolated_observability_gateway
    mcp_headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "mcp-protocol-version": "2025-03-26",
    }
    before = _observability_timeseries_totals(client)

    successful = client.post("/mcp/", headers=mcp_headers, json=_build_initialize())
    assert successful.status_code == 200, successful.text

    failed = client.post(f"/servers/{uuid.uuid4()}/mcp", headers=mcp_headers, json=_build_initialize())
    assert failed.status_code == 403, failed.text

    after = _observability_timeseries_totals(client)
    assert tuple(current - previous for current, previous in zip(after, before, strict=True)) == (2, 1, 1)
