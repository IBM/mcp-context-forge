# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a/test_virtual_server_interfaces_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box checks that a virtual server publishes A2A interfaces through ``/v1/virtual-servers`` (#7028).

The gateway runs as a subprocess with a private SQLite DB and real HTTP requests.
Authentication, RBAC, token scoping, and visibility run exactly as in production.
"""

# Standard
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import uuid

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]

ADMIN_EMAIL = "admin@example.com"
STRANGER_EMAIL = "stranger@example.com"
BINDING = "http://127.0.0.1:9/a2a"
OTHER_BINDING = "http://127.0.0.1:9/a2a-v2"


def _free_port():
    """Return an ephemeral loopback port."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    """Start an authenticated gateway; yield its base URL and signing key."""
    tmp_path = tmp_path_factory.mktemp("server-interfaces-gateway")
    port = _free_port()
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
        "PLATFORM_ADMIN_EMAIL": ADMIN_EMAIL,
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
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()[-5000:]
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-5000:]}")
            yield base, signing_key
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _call(gateway, method, path, json=None, *, email=ADMIN_EMAIL, token=True, **token_options):
    """Send a request with a JSON body."""
    base, key = gateway
    headers = make_auth_headers(make_test_jwt(email, secret=key, algorithm="HS256", **token_options)) if token else {}
    with httpx.Client(base_url=base, headers=headers, timeout=30, trust_env=False) as client:
        return client.request(method, path, json=json)


def _admin(**options):
    """Token options of a platform admin."""
    return {"is_admin": True, "teams": None, **options}


def _create(gateway, interfaces=None, **body):
    """Create a virtual server as admin and return the response."""
    server = {"name": f"iface-{uuid.uuid4().hex[:8]}", "description": "interfaces e2e"}
    if interfaces is not None:
        server["interfaces"] = interfaces
    return _call(gateway, "POST", "/v1/virtual-servers", {"server": server, **body}, **_admin())


def _interface(binding=BINDING, **overrides):
    """Build one interface entry."""
    return {"protocol": "a2a", "binding": binding, "version": "1.0", "tenant": "team-a", **overrides}


def _by_binding(interfaces):
    """Index interfaces by binding."""
    return {item["binding"]: item for item in interfaces}


def test_create_publishes_interfaces_and_get_reads_them_back(gateway):
    """A created server returns its interfaces, and a later GET returns the same rows."""
    created = _create(gateway, [_interface()])
    assert created.status_code == 201, created.text
    body = created.json()
    assert len(body["interfaces"]) == 1
    published = body["interfaces"][0]
    assert (published["protocol"], published["binding"], published["version"], published["tenant"], published["enabled"]) == ("a2a", BINDING, "1.0", "team-a", True)
    assert published["server_id"] == body["id"] and published["id"]

    fetched = _call(gateway, "GET", f"/v1/virtual-servers/{body['id']}", **_admin())
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["interfaces"] == body["interfaces"]


def test_server_without_interfaces_lists_none(gateway):
    """A server created without interfaces returns an empty list."""
    created = _create(gateway)
    assert created.status_code == 201, created.text
    assert created.json()["interfaces"] == []


def test_update_without_interfaces_keeps_the_stored_ones(gateway):
    """An update that omits interfaces leaves the stored rows, and their ids, unchanged."""
    server = _create(gateway, [_interface()]).json()

    updated = _call(gateway, "PUT", f"/v1/virtual-servers/{server['id']}", {"description": "renamed"}, **_admin())

    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "renamed"
    assert updated.json()["interfaces"] == server["interfaces"]


def test_update_with_a_matching_pair_changes_the_row_in_place(gateway):
    """The same protocol and binding keep the row id while the other fields change."""
    server = _create(gateway, [_interface()]).json()
    original = server["interfaces"][0]

    updated = _call(gateway, "PUT", f"/v1/virtual-servers/{server['id']}", {"interfaces": [_interface(version="2.0", tenant="team-b", enabled=False)]}, **_admin())

    assert updated.status_code == 200, updated.text
    (row,) = updated.json()["interfaces"]
    assert row["id"] == original["id"]
    assert (row["version"], row["tenant"], row["enabled"]) == ("2.0", "team-b", False)


def test_update_replaces_the_list_and_an_empty_list_clears_it(gateway):
    """A new list adds and removes rows. An empty list removes them all."""
    server = _create(gateway, [_interface()]).json()

    replaced = _call(gateway, "PUT", f"/v1/virtual-servers/{server['id']}", {"interfaces": [_interface(OTHER_BINDING)]}, **_admin())
    assert replaced.status_code == 200, replaced.text
    assert list(_by_binding(replaced.json()["interfaces"])) == [OTHER_BINDING]

    cleared = _call(gateway, "PUT", f"/v1/virtual-servers/{server['id']}", {"interfaces": []}, **_admin())
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["interfaces"] == []
    assert _call(gateway, "GET", f"/v1/virtual-servers/{server['id']}", **_admin()).json()["interfaces"] == []


@pytest.mark.parametrize(
    "interfaces",
    [
        [_interface(), _interface()],
        [_interface("JSONRPC")],
        [_interface("http://169.254.169.254/latest/meta-data")],
        [_interface("ftp://agent.example.com/a2a")],
        [{"protocol": "", "binding": BINDING}],
    ],
    ids=["duplicate-pair", "not-a-url", "metadata-address", "disallowed-scheme", "empty-protocol"],
)
def test_invalid_interfaces_are_rejected_on_create_and_update(gateway, interfaces):
    """A bad interface list gets 422 and changes nothing."""
    created = _create(gateway, interfaces)
    assert created.status_code == 422, created.text

    server = _create(gateway, [_interface()]).json()
    updated = _call(gateway, "PUT", f"/v1/virtual-servers/{server['id']}", {"interfaces": interfaces}, **_admin())
    assert updated.status_code == 422, updated.text
    assert _call(gateway, "GET", f"/v1/virtual-servers/{server['id']}", **_admin()).json()["interfaces"] == server["interfaces"]


def test_create_without_a_token_returns_401_and_creates_nothing(gateway):
    """An unauthenticated create is refused."""
    response = _call(gateway, "POST", "/v1/virtual-servers", {"server": {"name": "no-token", "interfaces": [_interface()]}}, token=False)
    assert response.status_code == 401


def test_create_without_servers_create_returns_403_and_creates_nothing(gateway):
    """A token scoped to another permission cannot publish interfaces."""
    name = f"no-permission-{uuid.uuid4().hex[:8]}"
    response = _call(gateway, "POST", "/v1/virtual-servers", {"server": {"name": name, "interfaces": [_interface()]}}, **_admin(scopes={"permissions": ["servers.read"]}))

    assert response.status_code == 403
    listed = _call(gateway, "GET", "/v1/virtual-servers", **_admin()).json()
    assert name not in {item["name"] for item in (listed["items"] if isinstance(listed, dict) else listed)}


def test_update_without_servers_update_returns_403_and_keeps_interfaces(gateway):
    """A token without servers.update cannot change the published interfaces."""
    server = _create(gateway, [_interface()]).json()

    response = _call(gateway, "PUT", f"/v1/virtual-servers/{server['id']}", {"interfaces": []}, **_admin(scopes={"permissions": ["servers.read"]}))

    assert response.status_code == 403
    assert _call(gateway, "GET", f"/v1/virtual-servers/{server['id']}", **_admin()).json()["interfaces"] == server["interfaces"]


def test_other_users_private_server_interfaces_cannot_be_changed(gateway):
    """A non-admin user outside the owner's team cannot see or update a private server."""
    server = _create(gateway, [_interface()], visibility="private").json()

    response = _call(gateway, "PUT", f"/v1/virtual-servers/{server['id']}", {"interfaces": []}, email=STRANGER_EMAIL, is_admin=False, teams=["other-team"])

    assert response.status_code in (403, 404)
    assert _call(gateway, "GET", f"/v1/virtual-servers/{server['id']}", **_admin()).json()["interfaces"] == server["interfaces"]
