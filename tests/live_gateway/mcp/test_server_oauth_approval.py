# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_server_oauth_approval.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Check virtual-server issuer authorization against an isolated running gateway.
"""

# Standard
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import secrets
import sqlite3
import ssl
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

# Third-Party
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import httpx
import jwt
import pytest

# Local
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.e2e.test_candidate_credential_handshake import isolated_gateway

pytestmark = pytest.mark.e2e


@contextmanager
def _issuer_and_upstream(tmp_path: Path):
    """Provide a trusted test CA, JWT issuer, and harmless per-user OAuth upstream."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    ca_file = tmp_path / "issuer-ca.pem"
    key_file = tmp_path / "issuer-key.pem"
    ca_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public_jwk.update(kid="test-issuer", alg="RS256", use="sig")
    upstream_token = secrets.token_urlsafe(48)
    calls = []
    state = {"issuer": "", "calls": calls, "key": key, "ca_file": str(ca_file), "methods": []}

    class Handler(BaseHTTPRequestHandler):
        """Serve OIDC discovery, keys, and an OAuth-protected MCP tool."""

        def reply(self, status, payload):
            """Return a bounded JSON response."""
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            """Expose issuer metadata and the generated public verification key."""
            if self.path.endswith("openid-configuration") or self.path.endswith("oauth-authorization-server"):
                self.reply(200, {"issuer": state["issuer"], "jwks_uri": state["issuer"] + "/jwks"})
            elif self.path == "/jwks":
                self.reply(200, {"keys": [public_jwk]})
            else:
                self.reply(404, {})

        def do_POST(self):  # noqa: N802
            """Issue the admin upstream token or execute the harmless MCP tool."""
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/token":
                self.reply(200, {"access_token": upstream_token, "token_type": "Bearer", "expires_in": 3600})
                return
            if self.headers.get("Authorization") != f"Bearer {upstream_token}":
                state["methods"].append("unauthorized")
                self.reply(401, {"error": "invalid_token"})
                return
            message = json.loads(body)
            method = message.get("method")
            state["methods"].append(method)
            if method == "notifications/initialized":
                self.reply(202, {})
                return
            if method == "server/discover":
                self.reply(404, {})
                return
            if method == "initialize":
                result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "approval-test", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "account_echo", "description": "Return a harmless account label", "inputSchema": {"type": "object"}}]}
            elif method == "tools/call":
                calls.append({"used_admin_token": True})
                result = {"content": [{"type": "text", "text": "admin-upstream-account"}], "isError": False}
            else:
                result = {}
            self.reply(200, {"jsonrpc": "2.0", "id": message.get("id"), "result": result})

        def log_message(self, _format, *args):
            """Keep token material out of test output."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(str(ca_file), str(key_file))
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    state["issuer"] = f"https://127.0.0.1:{server.server_address[1]}"
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.fixture
def oauth_gateway(tmp_path):
    """Start an isolated gateway with UI routes and a locally trusted HTTPS issuer."""
    with _issuer_and_upstream(tmp_path) as issuer:
        request = SimpleNamespace(
            param={"MCPGATEWAY_UI_ENABLED": "true", "MCP_REQUIRE_AUTH": "false", "SSL_CERT_FILE": issuer["ca_file"], "HTTPX_TRUST_ENV": "true", "ENVIRONMENT": "development", "SECURE_COOKIES": "false"}
        )
        for gateway in isolated_gateway.__wrapped__(tmp_path, request):
            yield (*gateway, issuer, tmp_path / "gateway.db")


def _body(response: httpx.Response):
    """Read a JSON-RPC envelope from a JSON or SSE response."""
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return json.loads(next(line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")))


def _mcp(client, server_id, token, method, params, before_dispatch=None):
    """Authenticate an MCP session before sending a test method."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    path = f"/servers/{server_id}/mcp"
    response = client.post(
        path,
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "approval-test", "version": "1"}}},
    )
    if response.status_code != 200:
        return response
    session = response.headers.get("mcp-session-id")
    if session:
        headers["Mcp-Session-Id"] = session
    client.post(path, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    if before_dispatch:
        before_dispatch()
    return client.post(path, headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": method, "params": params})


def test_live_server_oauth_authorization_and_reapproval(oauth_gateway):
    """Reject attacker issuers and require approval before using an administrator's stored upstream token."""
    client, _admin_token, base_url, signing_key, issuer, db_file = oauth_gateway
    client.follow_redirects = True
    created = client.post(
        "/auth/email/admin/users",
        json={"email": "ordinary@example.com", "password": secrets.token_urlsafe(40), "full_name": "Ordinary User", "is_admin": False, "is_active": True, "password_change_required": False},
    )
    assert created.status_code == 201, created.text
    team = client.post("/teams", json={"name": "oauth-test-team", "visibility": "private"})
    assert team.status_code in (200, 201), team.text
    team_id = team.json()["id"]
    membership = client.post(f"/teams/{team_id}/members", json={"email": "ordinary@example.com", "role": "member"})
    assert membership.status_code in (200, 201), membership.text
    roles = client.get("/rbac/roles").json()
    role_id = next(role["id"] for role in roles if role["name"] == "developer")
    assignment = client.post("/rbac/users/ordinary@example.com/roles", json={"role_id": role_id, "scope": "team", "scope_id": team_id})
    assert assignment.status_code in (200, 201), assignment.text
    ordinary = make_test_jwt("ordinary@example.com", teams=[team_id], secret=signing_key, algorithm="HS256", include_email_claim=True)
    ordinary_headers = {"Authorization": f"Bearer {ordinary}"}
    normal = client.post("/servers", headers=ordinary_headers, json={"server": {"name": "ordinary-server"}, "team_id": team_id, "visibility": "team"})
    assert normal.status_code == 201, normal.text
    ordinary_id = normal.json()["id"]
    config = {"authorization_servers": [issuer["issuer"]], "resource": "approval-test-resource"}
    for fields in ({"oauth_enabled": True, "oauth_config": config}, {"oauth_enabled": False}, {"oauth_config": None}, {"oauth_config": {}}):
        denied = client.post("/servers", headers=ordinary_headers, json={"server": {"name": "attack-server", **fields}, "team_id": team_id})
        assert denied.status_code == 403, denied.text
        denied = client.put(f"/servers/{ordinary_id}", headers=ordinary_headers, json=fields)
        assert denied.status_code == 403, denied.text
    for path in ("/admin/servers", f"/admin/servers/{ordinary_id}/edit"):
        denied = client.post(path, headers=ordinary_headers, data={"name": "attack-server", "team_id": team_id, "oauth_enabled": "on", "oauth_authorization_server": issuer["issuer"]})
        assert denied.status_code == 403, denied.text
    for teams in ([], [team_id]):
        narrowed = make_test_jwt("admin@example.com", is_admin=True, teams=teams, secret=signing_key, algorithm="HS256")
        headers = {"Authorization": f"Bearer {narrowed}"}
        denied = client.post("/servers", headers=headers, json={"server": {"name": "narrowed-admin", "oauth_enabled": True, "oauth_config": config}})
        assert denied.status_code == 403, denied.text
        denied = client.put(f"/servers/{ordinary_id}", headers=headers, json={"oauth_config": config})
        assert denied.status_code == 403, denied.text
    spoofed = client.put(f"/servers/{ordinary_id}", headers=ordinary_headers, json={"oauth_config_approved": True, "oauth_config_generation": "attacker-generation"})
    assert spoofed.status_code == 200, spoofed.text
    assert spoofed.json()["oauthConfigApproved"] is False

    gateway = client.post(
        "/gateways",
        json={
            "name": "approval-upstream",
            "url": issuer["issuer"] + "/mcp",
            "transport": "STREAMABLEHTTP",
            "visibility": "public",
            "auth_type": "oauth",
            "oauth_config": {
                "grant_type": "authorization_code",
                "client_id": "approval-client",
                "authorization_url": issuer["issuer"] + "/authorize",
                "token_url": issuer["issuer"] + "/token",
                "redirect_uri": base_url + "/oauth/callback",
            },
        },
    )
    assert gateway.status_code in (200, 201, 202), gateway.text
    gateway_data = gateway.json()
    gateway_id = gateway_data.get("id") or gateway_data["gateway"]["id"]
    authorization = client.get(f"/oauth/authorize/{gateway_id}", params={"popup": "true"}, follow_redirects=False)
    assert authorization.status_code in (302, 307), authorization.text
    state = parse_qs(urlparse(authorization.headers["location"]).query)["state"][0]
    callback = client.get("/oauth/callback", params={"code": "test-consent", "state": state})
    assert callback.status_code == 200 and '"status": "success"' in callback.text, callback.text
    refresh = client.post(f"/oauth/fetch-tools/{gateway_id}")
    assert refresh.status_code == 200, refresh.text
    tools = client.get("/tools").json()
    candidates = [tool for tool in tools if tool.get("gatewayId") == gateway_id or tool.get("gateway_id") == gateway_id]
    assert candidates, {"methods": issuer["methods"], "refresh": refresh.json(), "tools": [{"name": tool.get("name"), "gateway": tool.get("gatewayId") or tool.get("gateway_id")} for tool in tools]}
    tool = candidates[0]
    trusted = client.post("/servers", json={"server": {"name": "trusted-server", "oauth_enabled": True, "oauth_config": config, "associated_tools": [tool["id"]]}, "visibility": "public"})
    assert trusted.status_code == 201, trusted.text
    server_id = trusted.json()["id"]

    def edit_metadata_without_changing_oauth():
        """Submit the pre-filled administrator form and preserve the stored trust generation."""
        before = client.get(f"/servers/{server_id}").json()
        with sqlite3.connect(db_file) as db:
            generation = db.execute("SELECT oauth_config_generation FROM servers WHERE id = ?", (server_id,)).fetchone()[0]
        response = client.post(
            f"/admin/servers/{server_id}/edit",
            data={
                "name": "trusted-server",
                "description": "metadata only",
                "visibility": "public",
                "oauth_controls": "1",
                "associatedTools": [tool["id"]],
                "oauth_enabled": "on",
                "oauth_authorization_server": issuer["issuer"],
                "oauth_scopes": "",
                "oauth_token_endpoint": "",
                "oauth_audience": "",
            },
        )
        assert response.status_code == 200, response.text
        after = client.get(f"/servers/{server_id}").json()
        assert after["oauthConfig"] == before["oauthConfig"]
        assert after["oauthConfigApproved"] is before["oauthConfigApproved"]
        with sqlite3.connect(db_file) as db:
            assert db.execute("SELECT oauth_config_generation FROM servers WHERE id = ?", (server_id,)).fetchone()[0] == generation

    edit_metadata_without_changing_oauth()
    forged = jwt.encode(
        {"iss": issuer["issuer"], "sub": "admin@example.com", "email": "admin@example.com", "aud": "approval-test-resource", "exp": now_timestamp() + 600},
        issuer["key"],
        algorithm="RS256",
        headers={"kid": "test-issuer"},
    )

    # Migration state preserves the issuer but removes every existing approval.
    with sqlite3.connect(db_file) as db:
        db.execute("UPDATE servers SET oauth_config_approved = 0, oauth_config_generation = NULL WHERE id = ?", (server_id,))
    edit_metadata_without_changing_oauth()
    with httpx.Client(base_url=base_url, follow_redirects=True) as anonymous:
        denied = anonymous.post(f"/servers/{server_id}/mcp", headers={"Accept": "application/json, text/event-stream"}, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert denied.status_code == 401, denied.text
    denied = _mcp(client, server_id, forged, "tools/call", {"name": tool["name"], "arguments": {}})
    assert denied.status_code == 503, denied.text
    assert issuer["calls"] == []
    metadata = client.get(f"/.well-known/oauth-protected-resource/servers/{server_id}/mcp")
    assert metadata.status_code in (404, 503), metadata.text
    assert issuer["issuer"] not in metadata.text
    pending = client.get(f"/servers/{server_id}").json()
    read_only = make_test_jwt("admin@example.com", is_admin=True, teams=None, scopes={"permissions": ["servers.read"]}, secret=signing_key, algorithm="HS256")
    denied = client.post(f"/servers/{server_id}/oauth/approve", headers={"Authorization": f"Bearer {read_only}"}, json={"version": pending["version"]})
    assert denied.status_code == 403, denied.text
    with httpx.Client(base_url=base_url) as anonymous:
        denied = anonymous.post(f"/servers/{server_id}/oauth/approve", json={"version": pending["version"]})
        assert denied.status_code == 401, denied.text
    for path, kwargs in (
        (f"/servers/{server_id}/oauth/approve", {"json": {"version": pending["version"]}}),
        (f"/admin/servers/{server_id}/oauth/approve", {"data": {"version": str(pending["version"])}}),
    ):
        denied = client.post(path, headers=ordinary_headers, **kwargs)
        assert denied.status_code == 403, denied.text
    approved = client.post(f"/servers/{server_id}/oauth/approve", json={"version": pending["version"]})
    assert approved.status_code == 200, approved.text
    metadata = client.get(f"/.well-known/oauth-protected-resource/servers/{server_id}/mcp")
    assert metadata.status_code == 200, metadata.text
    assert metadata.json()["authorization_servers"] == [issuer["issuer"]]
    stale = client.post(f"/servers/{server_id}/oauth/approve", json={"version": pending["version"]})
    assert stale.status_code == 409, stale.text
    permitted = _mcp(client, server_id, forged, "tools/call", {"name": tool["name"], "arguments": {}}, before_dispatch=edit_metadata_without_changing_oauth)
    assert permitted.status_code == 200, permitted.text
    assert "admin-upstream-account" in json.dumps(_body(permitted)), permitted.text
    assert issuer["calls"] == [{"used_admin_token": True}]
    denied = _mcp(client, ordinary_id, forged, "logging/setLevel", {"level": "debug"})
    assert denied.status_code in (401, 403), denied.text
    assert issuer["calls"] == [{"used_admin_token": True}]


def now_timestamp():
    """Return current UTC seconds for short-lived test tokens."""
    return int(datetime.now(timezone.utc).timestamp())
